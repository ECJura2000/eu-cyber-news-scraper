"""Anonymous, publisher-scoped Danish ministry news adapters.

The public POST helper reuses HttpClient's robots policy, TLS transport, pacing,
concurrency and byte limit. Only the published read-only listing operations are
allowed; it never follows POST redirects or obtains authentication/form tokens.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx
from bs4 import BeautifulSoup

from .http import HttpClient, HttpStats, ResponseTooLargeError, _retry_delay
from .models import Article, Source

NORTH_ADAPTERS = frozenset({"north_gobasic", "north_nextjs", "north_ankiro"})
_OWNERS = {
    "dk_climate": ("kefm.dk", r"^/aktuelt/nyheder/20\d{2}/"),
    "dk_business": ("em.dk", r"^/aktuelt/nyheder/20\d{2}/"),
    "dk_nature": ("mgtp.dk", r"^/nyheder/20\d{2}/"),
    "dk_children": ("baebm.dk", r"^/nyheder/nyhedsarkiv/20\d{2}/"),
    "dk_employment": ("bm.dk", r"^/nyheder/(?:nyheder|pressemeddelelser)/20\d{2}/"),
    "dk_taxation": ("svmn.dk", r"^/aktuelt/presse-nyheder/pressemeddelelser/[^/]+"),
}
_NEXT_CATALOG = "1c188e834b904d36a2d5271a428a5147"
_GENERATOR = "GoBasic.Presentation.Controls.ListHelper, GoBasic.Presentation"


def _origin(source: Source, url: str) -> bool:
    if source.country != "DK" or source.id not in _OWNERS:
        return False
    try:
        parts = urlsplit(url)
        domain = _OWNERS[source.id][0]
        return (parts.scheme == "https" and parts.hostname in {domain, "www." + domain}
                and parts.username is None and parts.password is None and parts.port in {None, 443})
    except ValueError:
        return False


def _news_url(source: Source, url: str) -> bool:
    from .parsers import allowed_article_url

    return (_origin(source, url) and bool(re.match(_OWNERS[source.id][1], urlsplit(url).path))
            and allowed_article_url(source, url))


def _article(source: Source, title: str, url: str, raw_date: str, summary: str, via: str) -> Article:
    from .parsers import apply_publication_date, plain_text

    article = Article(source_id=source.id, country=source.country, source_name=source.name_zh,
                      institution_type=source.institution_type, language=source.language,
                      title=plain_text(title), url=url, summary=plain_text(summary), fetched_via=via,
                      published_timezone=source.timezone)
    if raw_date:
        apply_publication_date(article, raw_date, timezone_name=source.timezone,
                               languages=(source.language,), source="json-api" if via.startswith("json:")
                               else "source-selector", confidence="high")
    return article


def _gobasic_html(html: str, source: Source, base_url: str) -> list[Article]:
    from .parsers import plain_text

    soup = BeautifulSoup(html, "lxml")
    result: list[Article] = []
    seen: set[str] = set()
    for node in soup.select("div.item[data-url]"):
        heading = node.select_one(".heading")
        link = heading.select_one("a[href]") if heading else None
        if heading is None or link is None:
            continue
        url = urljoin(base_url, str(link.get("href", "")))
        if url != urljoin(base_url, str(node.get("data-url", ""))) or not _news_url(source, url):
            continue
        if url in seen:
            continue
        title = plain_text(heading.get_text(" "))
        if len(title) < 8:
            continue
        date_node = node.select_one("span.date")
        raw = date_node.get_text(" ", strip=True) if date_node else ""
        match = re.fullmatch(r"(?:Publiceret\s+)?(\d{2}-\d{2}-\d{4})", raw, re.I)
        summary = node.select_one("div.text > p")
        result.append(_article(source, title, url, match.group(1) if match else "",
                               summary.get_text(" ") if summary else "", "html:" + base_url))
        seen.add(url)
    return result


def _ankiro_html(html: str, source: Source, base_url: str) -> list[Article]:
    from .parsers import plain_text

    if source.id != "dk_employment" or not _origin(source, base_url):
        raise ValueError("Unsupported Ankiro ministry origin")
    result: list[Article] = []
    seen: set[str] = set()
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.select("li > a[href]"):
        title_node = anchor.select_one("h3.search-module__list-module__results-headline")
        if title_node is None:
            continue
        try:
            redirect = urlsplit(urljoin(base_url, str(anchor["href"])))
        except ValueError:
            continue
        if (redirect.scheme != "https" or redirect.netloc != "bm.ankiro.dk"
                or redirect.path != "/Rest/bm.dk/Redir"):
            continue
        targets = parse_qs(redirect.query).get("url", [])
        if len(targets) != 1 or not _news_url(source, targets[0]) or targets[0] in seen:
            continue
        title = plain_text(title_node.get_text(" "))
        if len(title) < 8:
            continue
        date_node = anchor.select_one("span.search-module__list-module__result-tags")
        raw = date_node.get_text(" ", strip=True) if date_node else ""
        match = re.fullmatch(r"(?:Nyhed|Pressemeddelelse)(?:\s*-\s*Ligestilling)?\s*/\s*(\d{2}-\d{2}-\d{4})", raw)
        result.append(_article(source, title, targets[0], match.group(1) if match else "", "",
                               "html:" + base_url))
        seen.add(targets[0])
    return result


def parse_north_feed(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    """Parse genuine public JSON; creation/update dates never replace publication dates."""
    if not _origin(source, source.listing_url) or not _origin(source, fetched_from):
        raise ValueError("Unsupported north ministry origin")
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid public north news JSON") from exc
    if source.parser_adapter == "north_gobasic":
        if source.id not in {"dk_climate", "dk_business", "dk_nature", "dk_children"}:
            raise ValueError("Unsupported GoBasic ministry")
        responses = data.get("responses", [data]) if isinstance(data, dict) else []
        if not isinstance(responses, list) or not responses:
            raise ValueError("Missing public GoBasic response")
        articles: dict[str, Article] = {}
        for response in responses:
            if not isinstance(response, dict) or not (response.get("success") is True
                                                     or response.get("succeeded") is True):
                raise ValueError("Public GoBasic request did not succeed")
            value = response.get("value")
            if not isinstance(value, dict) or not isinstance(value.get("page"), str):
                raise ValueError("Missing public GoBasic HTML page")
            for article in _gobasic_html(value["page"], source, source.listing_url):
                articles.setdefault(article.url, article)
        return list(articles.values())
    if source.parser_adapter != "north_nextjs" or source.id != "dk_taxation":
        raise ValueError("Unsupported north JSON adapter")
    rows = data.get("articles") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("Missing public Next.js result list")
    result: list[Article] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            parent = UUID(str(row.get("parentGId", ""))).hex
        except ValueError:
            continue
        if (parent != _NEXT_CATALOG or row.get("siteName") != "SKM" or row.get("culture") != "da-dk"
                or row.get("domainName") != "https://svmn.dk/"
                or not isinstance(row.get("types"), list)
                or "Pressemeddelelser" not in row["types"]):
            continue
        url, title = row.get("url"), row.get("title")
        if not isinstance(url, str) or not isinstance(title, str) or not _news_url(source, url):
            continue
        if url in seen or len(title.strip()) < 8:
            continue
        date = row.get("date")
        raw = date if isinstance(date, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", date,
        ) else ""
        description = row.get("description")
        result.append(_article(source, title, url, raw, description if isinstance(description, str) else "",
                               "json:" + fetched_from))
        seen.add(url)
    return result


def parse_north_listing(html: str, source: Source, base_url: str) -> list[Article]:
    if not _origin(source, base_url):
        raise ValueError("Unsupported north ministry origin")
    if source.parser_adapter == "north_ankiro":
        return _ankiro_html(html, source, base_url)
    if source.parser_adapter in {"north_gobasic", "north_nextjs"}:
        if html.lstrip().startswith(("{", "[")):
            return parse_north_feed(html, source, base_url)
        if source.parser_adapter == "north_gobasic":
            return _gobasic_html(html, source, base_url)
        # Bootstrap page timestamps describe the page shell, not news articles.
        return []
    raise ValueError("Unsupported north listing adapter")


def public_listing_request(html: str, source: Source, page: int = 1) -> tuple[str, dict[str, Any], str]:
    """Reproduce the published anonymous query, retaining its ministry filter."""
    if not _origin(source, source.listing_url) or not 1 <= page <= 3:
        raise ValueError("Unsupported public north request")
    soup = BeautifulSoup(html, "lxml")
    origin = urlsplit(source.listing_url)
    if source.parser_adapter == "north_nextjs" and source.id == "dk_taxation":
        node = soup.select_one("script#__NEXT_DATA__")
        data = json.loads(node.get_text()) if node else {}
        props = data.get("props", {}).get("pageProps", {})
        catalog = props.get("content", {}).get("page", {})
        if (catalog.get("documentType") != "newsCatalogPage" or catalog.get("url") != origin.path
                or UUID(str(catalog.get("id", ""))).hex != _NEXT_CATALOG
                or props.get("site", {}).get("theme") != "SKM" or data.get("locale") != "da-dk"):
            raise ValueError("Public Next.js ministry catalog changed")
        if page != 1:
            raise ValueError("Public Next.js API has no verified pagination contract")
        return (urlunsplit((origin.scheme, origin.netloc, "/api/indexSearch", "", "")),
                {"index": "skm-da", "parentGId": catalog["id"], "query": "*", "tags": None,
                 "types": None, "operatorForTagsAndTypes": "and", "sort": "date", "limit": 25,
                 "lang": "da"}, "application/json")
    if source.parser_adapter != "north_gobasic":
        raise ValueError("No public POST for this north adapter")
    if source.id == "dk_children":
        node = soup.select_one(".archive-search-result.dynamic-list[data-config]")
        config = json.loads(str(node["data-config"])) if node else {}
        spec = config.get("options", {}).get("specification", {})
        if (spec.get("siteSearch") is not False or "NewsPage" not in spec.get("filter", {}).get("t", [])
                or not spec.get("filter", {}).get("rf") or soup.select_one('input[name="__RequestVerificationToken"]')):
            raise ValueError("Missing anonymous, news-scoped GoBasic archive configuration")
        endpoint = config.get("options", {}).get("endpoint") or "search"
        if endpoint != "search":
            raise ValueError("Unverified GoBasic public endpoint")
        return (urlunsplit((origin.scheme, origin.netloc, "/gbapi/search/getPage", "", "")),
                {"config": config, "page": page, "userInput": {"query": "", "categorizations": []},
                 "lastGroupName": "", "rootFolders": None}, "application/json")
    if source.id not in {"dk_climate", "dk_business", "dk_nature"}:
        raise ValueError("Unsupported public GoBasic ministry")
    for node in soup.select("script:not([src])"):
        text = node.get_text()
        match = re.search(r"application\.script\.register\(\s*'itemlist'\s*,", text)
        if not match:
            continue
        config, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        if config.get("options", {}).get("generator") != _GENERATOR:
            continue
        context = json.loads(base64.b64decode(config.get("context", ""), validate=True))
        if (context.get("siteSearch") is not False
                or "NewsPage" not in context.get("filter", {}).get("t", [])
                or not (context.get("filter", {}).get("rf") or context.get("filter", {}).get("cids"))):
            continue
        path = re.sub(r"\.[^/]+$", "", origin.path).rstrip("/")
        return (urlunsplit((origin.scheme, origin.netloc, path + "/proxy.gba", origin.query, "")),
                {"control": _GENERATOR, "method": "GetPage", "path": path,
                 "query": "?" + origin.query if origin.query else "",
                 "args": {"arg0": config, "arg1": page,
                          "arg2": {"query": "", "categorizations": []}, "arg3": ""}},
                "versus/callback; charset=utf-8")
    raise ValueError("No published anonymous NewsPage query; sitewide search is not a fallback")


async def _post_public_listing(client: HttpClient, source: Source, url: str, payload: dict[str, Any],
                               content_type: str, stats: HttpStats) -> httpx.Response:
    if not client.obey_robots or not _origin(source, url):
        raise ValueError("Public north transport requires production robots enforcement")
    path = urlsplit(url).path
    if not (path.endswith("/proxy.gba") and payload.get("method") == "GetPage"
            or path == "/gbapi/search/getPage" and source.id == "dk_children"
            or path == "/api/indexSearch" and source.id == "dk_taxation"):
        raise ValueError("Only the published read-only north listing POST is allowed")
    host = urlsplit(url).hostname or ""
    await client._ensure_robots(url, stats, source.tls_intermediate_bundle, source.user_agent,
                                lambda target: _origin(source, target))
    limiter = client._host_limiters.setdefault(host, asyncio.Semaphore(client._per_host_limit))
    headers = {"Content-Type": content_type}
    if source.id == "dk_children":
        headers["gp_currentpage"] = source.listing_url
    if source.user_agent:
        headers["User-Agent"] = source.user_agent
    async with limiter:
        async with client._global_limiter:
            await client._pace(host)
            stats.request_count += 1
            async with client._client_for_bundle(source.tls_intermediate_bundle).stream(
                "POST", url, content=json.dumps(payload), headers=headers, follow_redirects=False,
            ) as response:
                stats.statuses.append(str(response.status_code))
                if response.is_redirect:
                    raise ValueError("Public north POST redirected; review required, no redirect followed")
                if response.status_code in {429, 503}:
                    delay = _retry_delay(response)
                    client._host_cooldowns[host] = max(
                        client._host_cooldowns.get(host, 0.0), time.monotonic() + delay,
                    )
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > client.max_response_bytes:
                        raise ResponseTooLargeError("Public north response exceeds production byte limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
                stats.bytes_downloaded += len(body)
                return httpx.Response(response.status_code, headers=response.headers, content=body,
                                      request=response.request)


async def fetch_north_listing(html: str, source: Source, client: HttpClient,
                             stats: HttpStats | None = None) -> dict[str, Any]:
    """Bounded public listing bootstrap for scraper dispatch; no credentials saved."""
    metrics = stats if stats is not None else HttpStats()
    responses: list[Any] = []
    digests: list[str] = []
    public_urls: list[str] = []
    truncated = False
    pages = 1 if source.parser_adapter == "north_nextjs" else min(3, max(1, source.max_pages))
    for page in range(1, pages + 1):
        url, payload, content_type = public_listing_request(html, source, page)
        response = await _post_public_listing(client, source, url, payload, content_type, metrics)
        data = response.json()
        digests.append(hashlib.sha256(response.content).hexdigest())
        public_urls.append(url)
        if source.parser_adapter == "north_nextjs":
            if not isinstance(data, list):
                raise ValueError("Public Next.js result schema changed")
            responses.extend(data)
            truncated = len(data) >= 25
            break
        if not isinstance(data, dict) or not isinstance(data.get("value"), dict):
            raise ValueError("Public GoBasic result schema changed")
        responses.append(data)
        # The genuine response carries lastPage; absence is not completeness proof.
        truncated = data["value"].get("lastPage") is not True
        if not truncated:
            break
    key = "articles" if source.parser_adapter == "north_nextjs" else "responses"
    return {"source_url": source.listing_url, key: responses, "response_sha256": digests,
            "public_urls": public_urls, "truncated": truncated}
