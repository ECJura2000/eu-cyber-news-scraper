from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .authority import annotate_authority
from .dedupe import dedupe_articles
from .http import HttpClient
from .models import Article, Source, SourceResult, SourceStatus
from .parsers import discover_feeds, enrich_from_detail, parse_feed, parse_listing
from .topics import classify_article, is_relevant


def scrape_source(
    source: Source,
    client: HttpClient,
    *,
    since: datetime,
    until: datetime,
    include_unmatched: bool = False,
    include_undated: bool = False,
    fetch_details: bool = True,
) -> SourceResult:
    started = time.monotonic()
    articles: list[Article] = []
    errors: list[str] = []
    fetched_via = ""
    pages_fetched = 0

    for feed_url in source.feed_urls:
        try:
            response = client.get(feed_url)
            parsed = parse_feed(response.content, source, feed_url)
            if parsed:
                articles.extend(parsed)
                fetched_via = "configured-feed"
                break
        except Exception as exc:  # source failure must not stop other sources
            errors.append(f"{feed_url}: {type(exc).__name__}: {exc}")

    # Feeds are often truncated to the newest 10-20 items. Sources with
    # explicit yearly/pagination rules must also traverse their archive.
    if not articles or source.yearly_listing_url or source.pagination_url:
        for listing_url in _listing_urls(source, since, until):
            try:
                response = client.get(listing_url)
                pages_fetched += 1
                listing_html = response.text
                if pages_fetched == 1 and not articles:
                    discovered = [url for url in discover_feeds(listing_html, listing_url) if url not in source.feed_urls]
                    for feed_url in discovered[:3]:
                        try:
                            feed_response = client.get(feed_url)
                            parsed = parse_feed(feed_response.content, source, feed_url)
                            if parsed:
                                articles.extend(parsed)
                                fetched_via = "discovered-feed"
                                break
                        except Exception as exc:
                            errors.append(f"{feed_url}: {type(exc).__name__}: {exc}")
                if fetched_via != "discovered-feed":
                    parsed = parse_listing(listing_html, source, listing_url)
                    articles.extend(parsed)
                    fetched_via = "feed+html-listing" if "feed" in fetched_via else "html-listing"
                    dated = [item.published_at for item in parsed if item.published_at]
                    if dated and max(dated) < since:
                        break
                else:
                    break
            except Exception as exc:
                errors.append(f"{listing_url}: {type(exc).__name__}: {exc}")

    articles = dedupe_articles(articles)
    unique_title_ratio = (
        len({item.title.casefold().strip() for item in articles}) / len(articles) if articles else 1.0
    )
    if fetch_details:
        _enrich_articles(articles, source, client, errors)

    dated = [article for article in articles if _in_range(article, since, until, include_undated)]
    for article in dated:
        classify_article(article)
        annotate_authority(article, source)
    relevant = dated if include_unmatched else [article for article in dated if is_relevant(article)]
    relevant.sort(key=lambda item: item.published_at or since, reverse=True)

    # A reachable page with zero parsed articles is not healthy: it often means
    # that a feed or HTML layout changed and must not silently pass automation.
    success = bool(articles)
    newest = max((item.published_at for item in articles if item.published_at), default=None)
    dated_count = sum(item.published_at is not None for item in articles)
    undated_ratio = (len(articles) - dated_count) / len(articles) if articles else 0.0
    warning = ""
    if not articles and not errors:
        warning = "來源可連線，但未解析出新聞；請檢查版型或發布頻率。"
    content_warning = ""
    if success and articles and not relevant:
        content_warning = "已抓到資料，但指定期間內沒有命中觀測主題。"
    if success and errors:
        fallback_warning = f"部分抓取路徑失敗，已使用備援；最近錯誤：{errors[-1]}"
        warning = f"{warning} {fallback_warning}".strip()
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
        in_range_count=len(dated),
        freshness_lag_days=round(max(0.0, (until - newest).total_seconds() / 86400), 2) if newest else 0.0,
        content_warning=content_warning,
    )
    return SourceResult(source=source, articles=relevant, status=status)


def _enrich_articles(articles: list[Article], source: Source, client: HttpClient, errors: list[str]) -> None:
    candidates = [article for article in articles if not article.published_at or len(article.summary) < 40]
    selected = candidates[: source.detail_pages]
    if not selected:
        return

    def enrich(article: Article) -> str | None:
        if _is_non_html_url(article.url):
            return None
        try:
            response = client.get(article.url)
            content_type = response.headers.get("content-type", "").casefold()
            if content_type and not any(value in content_type for value in ("html", "xhtml")):
                return None
            enrich_from_detail(article, response.text)
            return None
        except Exception as exc:
            return f"{article.url}: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=min(4, len(selected))) as executor:
        futures = [executor.submit(enrich, article) for article in selected]
        for future in as_completed(futures):
            if error := future.result():
                errors.append(error)


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
