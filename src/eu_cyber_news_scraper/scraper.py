from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from .authority import annotate_authority
from .dedupe import dedupe_articles
from .http import HttpClient, HttpStats
from .models import Article, Source, SourceResult, SourceStatus
from .parsers import discover_feeds, enrich_from_detail, parse_feed, parse_listing
from .topics import classify_article, is_relevant


class RedirectDomainError(RuntimeError):
    pass


async def scrape_source(
    source: Source,
    client: HttpClient,
    *,
    since: datetime,
    until: datetime,
    include_unmatched: bool = False,
    include_undated: bool = False,
    fetch_details: bool = True,
    source_budget_seconds: int = 60,
    observed_at: datetime | None = None,
) -> SourceResult:
    started = time.monotonic()
    stats = HttpStats()
    budget = max(1, source_budget_seconds)
    try:
        async with asyncio.timeout(budget):
            return await _scrape_source_impl(
                source,
                client,
                since=since,
                until=until,
                include_unmatched=include_unmatched,
                include_undated=include_undated,
                fetch_details=fetch_details,
                observed_at=observed_at,
                started=started,
                stats=stats,
            )
    except TimeoutError:
        return SourceResult(
            source=source,
            articles=[],
            status=SourceStatus(
                source_id=source.id,
                source_name=source.name_zh,
                country=source.country,
                critical=source.critical,
                success=False,
                fetched_via="",
                raw_count=0,
                relevant_count=0,
                duration_seconds=round(time.monotonic() - started, 3),
                warning="來源抓取時間超過預算，未完成工作已取消。",
                error="SourceBudgetExceeded",
                fetch_status="failed",
                parse_status="not_run",
                freshness_status="unknown",
                content_status="unknown",
                request_count=stats.request_count,
                bytes_downloaded=stats.bytes_downloaded,
                retry_count=stats.retry_count,
                timeout_count=stats.timeout_count + 1,
                budget_exhausted=True,
                http_statuses=tuple(stats.statuses),
                error_code="SOURCE_BUDGET_EXCEEDED",
            ),
        )


async def _scrape_source_impl(
    source: Source,
    client: HttpClient,
    *,
    since: datetime,
    until: datetime,
    include_unmatched: bool,
    include_undated: bool,
    fetch_details: bool,
    observed_at: datetime | None,
    started: float,
    stats: HttpStats,
) -> SourceResult:
    articles: list[Article] = []
    errors: list[str] = []
    fetched_via = ""
    pages_fetched = 0
    transport_succeeded = False

    for feed_url in source.feed_urls:
        try:
            response = await _get_source_response(client, feed_url, source, stats)
            transport_succeeded = True
            parsed = parse_feed(response.content, source, feed_url)
            if parsed:
                articles.extend(parsed)
                fetched_via = "configured-feed"
                break
        except Exception as exc:  # source failure must not stop other sources
            errors.append(f"{feed_url}: {type(exc).__name__}: {exc}")

    # Feeds are often truncated. Sources with explicit archive rules must also
    # traverse their listing so historical fixed periods remain complete.
    if not articles or source.yearly_listing_url or source.pagination_url:
        for listing_url in _listing_urls(source, since, until):
            try:
                response = await _get_source_response(client, listing_url, source, stats)
                transport_succeeded = True
                pages_fetched += 1
                listing_html = response.text
                if pages_fetched == 1 and not articles and not source.card_selectors:
                    discovered = [
                        url
                        for url in discover_feeds(listing_html, listing_url)
                        if url not in source.feed_urls
                        and "/comments/" not in urlsplit(url).path.casefold()
                        and _same_allowed_host(url, source)
                    ]
                    for feed_url in discovered[:3]:
                        try:
                            feed_response = await _get_source_response(client, feed_url, source, stats)
                            transport_succeeded = True
                            parsed = parse_feed(feed_response.content, source, feed_url)
                            if parsed:
                                articles.extend(parsed)
                                fetched_via = "discovered-feed"
                                break
                        except Exception as exc:
                            errors.append(f"{feed_url}: {type(exc).__name__}: {exc}")
                parsed = parse_listing(listing_html, source, listing_url)
                articles.extend(parsed)
                fetched_via = "feed+html-listing" if "feed" in fetched_via else "html-listing"
                parsed_dates = [item.published_at for item in parsed if item.published_at]
                if parsed_dates and max(parsed_dates) < since:
                    break
            except Exception as exc:
                errors.append(f"{listing_url}: {type(exc).__name__}: {exc}")

    articles = dedupe_articles(articles)
    unique_title_ratio = (
        len({item.title.casefold().strip() for item in articles}) / len(articles) if articles else 1.0
    )
    if fetch_details:
        await _enrich_articles(articles, source, client, errors, stats)

    reference_time = observed_at or datetime.now(timezone.utc)
    future_limit = reference_time + timedelta(hours=24)
    invalid_date_count = 0
    unexplained_future_date_count = 0
    for article in articles:
        if article.published_at and article.published_at > future_limit:
            if article.date_source not in {"visible-text", "title-text"} and article.date_confidence != "low":
                unexplained_future_date_count += 1
            article.published_at = None
            article.published_date_local = ""
            article.date_confidence = "invalid"
            invalid_date_count += 1

    in_range_articles = [article for article in articles if _in_range(article, since, until, include_undated)]
    for article in in_range_articles:
        classify_article(article)
        annotate_authority(article, source)
    relevant = (
        in_range_articles
        if include_unmatched
        else [article for article in in_range_articles if is_relevant(article)]
    )
    relevant.sort(key=lambda item: item.published_at or since, reverse=True)

    success = bool(articles)
    newest = max((item.published_at for item in articles if item.published_at), default=None)
    dated_count = sum(item.published_at is not None for item in articles)
    undated_ratio = (len(articles) - dated_count) / len(articles) if articles else 0.0
    warning = ""
    if not articles and not errors:
        warning = "來源可連線，但未解析出新聞；請檢查版型或發布頻率。"
    if invalid_date_count:
        warning = f"{warning} 已忽略 {invalid_date_count} 筆不合理未來日期。".strip()
    content_warning = ""
    if success and articles and not relevant:
        content_warning = "已抓到資料，但指定期間內沒有命中觀測主題。"
    if success and errors:
        fallback_warning = f"部分抓取路徑失敗，已使用備援；最近錯誤：{errors[-1]}"
        warning = f"{warning} {fallback_warning}".strip()

    parse_status = _parse_status(transport_succeeded, success, undated_ratio, source.date_policy)
    freshness_lag = max(0.0, (until - newest).total_seconds() / 86400) if newest else 0.0
    freshness_status = "unknown" if not newest else ("stale" if freshness_lag > source.freshness_days else "fresh")
    status = SourceStatus(
        source_id=source.id,
        source_name=source.name_zh,
        country=source.country,
        critical=source.critical,
        success=success,
        fetched_via=fetched_via,
        raw_count=len(articles),
        relevant_count=len(relevant),
        duration_seconds=round(time.monotonic() - started, 3),
        newest_published_at=newest.isoformat() if newest else "",
        warning=warning,
        error=" | ".join(errors[-4:]) if not success else "",
        pages_fetched=pages_fetched,
        dated_count=dated_count,
        undated_ratio=round(undated_ratio, 4),
        unique_title_ratio=round(unique_title_ratio, 4),
        in_range_count=len(in_range_articles),
        freshness_lag_days=round(freshness_lag, 2),
        content_warning=content_warning,
        fetch_status="ok" if transport_succeeded else "failed",
        parse_status=parse_status,
        freshness_status=freshness_status,
        content_status="hits" if relevant else ("no_hits" if success else "unknown"),
        invalid_date_count=invalid_date_count,
        unexplained_future_date_count=unexplained_future_date_count,
        timeout_count=stats.timeout_count,
        request_count=stats.request_count,
        bytes_downloaded=stats.bytes_downloaded,
        retry_count=stats.retry_count,
        http_statuses=tuple(stats.statuses),
        error_code="" if success else ("PARSE_EMPTY" if transport_succeeded else "FETCH_FAILED"),
    )
    return SourceResult(source=source, articles=relevant, status=status)


async def _enrich_articles(
    articles: list[Article],
    source: Source,
    client: HttpClient,
    errors: list[str],
    stats: HttpStats,
) -> None:
    candidates = [article for article in articles if not article.published_at or len(article.summary) < 40]
    selected = [article for article in candidates[: source.detail_pages] if not _is_non_html_url(article.url)]
    if not selected:
        return

    async def enrich(article: Article) -> str | None:
        try:
            response = await _get_source_response(client, article.url, source, stats)
            content_type = response.headers.get("content-type", "").casefold()
            if content_type and not any(value in content_type for value in ("html", "xhtml")):
                return None
            enrich_from_detail(article, response.text, source)
            return None
        except Exception as exc:
            return f"{article.url}: {type(exc).__name__}: {exc}"

    for result in await asyncio.gather(*(enrich(article) for article in selected)):
        if result:
            errors.append(result)


def _parse_status(transport_succeeded: bool, success: bool, undated_ratio: float, date_policy: str) -> str:
    if not transport_succeeded:
        return "failed"
    if not success:
        return "empty"
    if date_policy == "unavailable":
        return "exception"
    if date_policy == "best_effort" and undated_ratio > 0.25:
        return "attention"
    if undated_ratio > 0.25:
        return "attention"
    return "healthy"


def _same_allowed_host(url: str, source: Source) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    allowed = source.allow_domains or (urlsplit(source.homepage).hostname or "",)
    return any(hostname == domain.casefold() or hostname.endswith(f".{domain.casefold()}") for domain in allowed)


async def _get_source_response(
    client: HttpClient,
    url: str,
    source: Source,
    stats: HttpStats,
) -> httpx.Response:
    if source.tls_intermediate_bundle:
        response = await client.get(url, stats=stats, ssl_bundle=source.tls_intermediate_bundle)
    else:
        response = await client.get(url, stats=stats)
    final_url = str(response.url)
    if not _same_allowed_host(final_url, source):
        raise RedirectDomainError(f"redirect target is outside source allow_domains: {final_url}")
    return response


def _is_non_html_url(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return path.endswith((".pdf", ".rss", ".atom", ".xml")) or path.rstrip("/").endswith("/feed")


def _in_range(article: Article, since: datetime, until: datetime, include_undated: bool) -> bool:
    if not article.published_at:
        return include_undated
    return since <= article.published_at < until


def _listing_urls(source: Source, since: datetime, until: datetime) -> list[str]:
    end_year = (until - timedelta(microseconds=1)).year
    if source.yearly_listing_url:
        bases = [source.yearly_listing_url.format(year=year) for year in range(end_year, since.year - 1, -1)]
    else:
        bases = [source.listing_url]
    urls: list[str] = []
    for base in bases:
        urls.append(base)
        if source.pagination_url:
            year = next((value for value in range(since.year, end_year + 1) if str(value) in base), end_year)
            urls.extend(
                source.pagination_url.format(page=page, year=year)
                for page in range(1, source.max_pages)
            )
    return list(dict.fromkeys(urls))
