from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin, urlsplit

import dateparser
import feedparser
from bs4 import BeautifulSoup

from .models import Article, Source

DATE_SETTINGS = {
    "RETURN_AS_TIMEZONE_AWARE": True,
    "TIMEZONE": "UTC",
    "TO_TIMEZONE": "UTC",
    "PREFER_DAY_OF_MONTH": "first",
}


def parse_datetime(value: str | None, languages: Iterable[str] = ()) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]|$)", normalized):
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    parsed = dateparser.parse(value, languages=list(languages) or None, settings=DATE_SETTINGS)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plain_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(BeautifulSoup(html_module.unescape(value), "html.parser").stripped_strings)


def discover_feeds(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls = []
    for link in soup.select("link[rel~='alternate'][href]"):
        media_type = (link.get("type") or "").casefold()
        if "rss" in media_type or "atom" in media_type or "xml" in media_type:
            urls.append(urljoin(base_url, link["href"]))
    return list(dict.fromkeys(urls))


def parse_feed(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    if _looks_like_json(payload):
        return _parse_presscorner_json(payload, source, fetched_from)
    feed = feedparser.parse(payload)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Invalid feed: {feed.get('bozo_exception', 'unknown parse error')}")
    articles = []
    for entry in feed.entries:
        title = plain_text(entry.get("title"))
        url = entry.get("link") or ""
        if not title or not url or not allowed_article_url(source, url):
            continue
        raw_date = entry.get("published") or entry.get("updated") or entry.get("created")
        content = entry.get("content") or [{}]
        articles.append(
            Article(
                source_id=source.id,
                country=source.country,
                source_name=source.name_zh,
                institution_type=source.institution_type,
                language=source.language,
                title=title,
                url=url,
                published_at=parse_datetime(raw_date, _date_languages(source.language)),
                summary=plain_text(entry.get("summary") or entry.get("description") or content[0].get("value")),
                fetched_via=f"feed:{fetched_from}",
            )
        )
    return articles


def parse_listing(html: str, source: Source, base_url: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    base_node = soup.select_one("base[href]")
    document_base = urljoin(base_url, base_node["href"]) if base_node else base_url
    # Some government sites render news links outside <main> or use a very
    # shallow list.  Always include anchors as a final candidate pool; URL
    # allow/include/exclude rules below keep navigation links out.
    candidates = [
        *soup.select("article"),
        *soup.select("main li"),
        *soup.select("main a[href]"),
        *soup.select("a[href]"),
    ]
    articles = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        links = [candidate] if candidate.name == "a" else candidate.select("a[href]")
        link = next(
            (
                node
                for node in links
                if node.get("href") and allowed_article_url(source, urljoin(document_base, node["href"].strip()))
            ),
            None,
        )
        if link is None:
            continue
        url = urljoin(document_base, link["href"].strip())
        if url in seen_urls:
            continue
        link_text = plain_text(link.get_text(" "))
        context = candidate
        if candidate.name == "a":
            # Government cards commonly keep the date beside the title link.
            # Use the nearest ancestor containing date metadata, without
            # climbing far enough to mix neighbouring cards.
            for _ in range(3):
                if context.parent is None:
                    break
                context = context.parent
                if context.select_one("time") or _extract_date_text(context.get_text(" ")):
                    break
        title_node = context.select_one("h1, h2, h3, h4") if len(link_text) < 8 and context.name != "a" else None
        title = plain_text(title_node.get_text(" ") if title_node else link.get_text(" "))
        if len(title) < 8:
            continue
        time_node = context.select_one("time") if context.name != "a" else None
        date_text = ""
        if time_node:
            date_text = time_node.get("datetime") or time_node.get_text(" ")
        if not date_text:
            date_text = _extract_date_text(context.get_text(" "))
        summary_node = context.select_one("p") if context.name != "a" else None
        seen_urls.add(url)
        articles.append(
            Article(
                source_id=source.id,
                country=source.country,
                source_name=source.name_zh,
                institution_type=source.institution_type,
                language=source.language,
                title=title,
                url=url,
                published_at=parse_datetime(date_text, _date_languages(source.language)),
                summary=plain_text(summary_node.get_text(" ") if summary_node else ""),
                fetched_via=f"html:{base_url}",
            )
        )
    return articles


def _looks_like_json(payload: bytes | str) -> bool:
    prefix = payload[:100].decode("utf-8", errors="ignore") if isinstance(payload, bytes) else payload[:100]
    return prefix.lstrip().startswith("{")


def _parse_presscorner_json(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise ValueError(f"Invalid JSON feed: {exc}") from exc
    rows = data.get("docuLanguageListResources", []) if isinstance(data, dict) else []
    articles = []
    for row in rows:
        title = plain_text(row.get("title"))
        reference = str(row.get("refCode") or "")
        if not title or not reference:
            continue
        slug = reference.casefold().replace("/", "_")
        url = f"https://ec.europa.eu/commission/presscorner/detail/en/{slug}"
        if not allowed_article_url(source, url):
            continue
        articles.append(
            Article(
                source_id=source.id,
                country=source.country,
                source_name=source.name_zh,
                institution_type=source.institution_type,
                language=source.language,
                title=title,
                url=url,
                published_at=parse_datetime(row.get("eventDate"), _date_languages(source.language)),
                summary=plain_text(row.get("leadText")),
                fetched_via=f"json:{fetched_from}",
            )
        )
    return articles


def enrich_from_detail(article: Article, html: str) -> Article:
    soup = BeautifulSoup(html, "lxml")
    structured = _article_json_ld(soup)
    title = _first(
        structured.get("headline"),
        _meta(soup, "property", "og:title"),
        _meta(soup, "name", "twitter:title"),
        soup.title.string if soup.title else "",
    )
    summary = _first(
        structured.get("description"),
        _meta(soup, "property", "og:description"),
        _meta(soup, "name", "description"),
    )
    date_value = _first(
        structured.get("datePublished"),
        _meta(soup, "property", "article:published_time"),
        _meta(soup, "name", "date"),
        _time_value(soup),
        _extract_date_text(soup.get_text(" ", strip=True)),
    )
    if title and len(plain_text(title)) >= 8:
        article.title = plain_text(title)
    if summary and len(plain_text(summary)) > len(article.summary):
        article.summary = plain_text(summary)
    if parsed_date := parse_datetime(str(date_value), _date_languages(article.language)):
        article.published_at = parsed_date
    return article


def allowed_article_url(source: Source, url: str) -> bool:
    parts = urlsplit(url)
    domain = parts.netloc.casefold().split(":")[0]
    if parts.scheme not in {"http", "https"}:
        return False
    if source.allow_domains and not any(domain == allowed or domain.endswith(f".{allowed}") for allowed in source.allow_domains):
        return False
    target = f"{parts.path}?{parts.query}" if parts.query else parts.path
    if source.include_patterns and not any(re.search(pattern, target, flags=re.IGNORECASE) for pattern in source.include_patterns):
        return False
    if any(re.search(pattern, target, flags=re.IGNORECASE) for pattern in source.exclude_patterns):
        return False
    return True


def _date_languages(language: str) -> tuple[str, ...]:
    return {"en": ("en",), "fr": ("fr",), "de": ("de",)}.get(language, ())


def _extract_date_text(value: str) -> str:
    patterns = (
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}\s+[A-Za-zÀ-ÿäöüÄÖÜß]+\s+\d{4}\b",
        r"\b\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]+\s+\d{4}\b",
        r"\b(?:Publié le|Veröffentlicht am|Release Date:)\s+[^|]{6,40}",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _article_json_ld(soup: BeautifulSoup) -> dict:
    for node in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(node.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _walk_json_ld(payload):
            type_value = item.get("@type", "")
            types = type_value if isinstance(type_value, list) else [type_value]
            if any(value in {"Article", "NewsArticle", "Report", "TechArticle", "BlogPosting"} for value in types):
                return item
    return {}


def _walk_json_ld(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _walk_json_ld(item)
    elif isinstance(payload, dict):
        yield payload
        if "@graph" in payload:
            yield from _walk_json_ld(payload["@graph"])


def _meta(soup: BeautifulSoup, attr: str, value: str) -> str:
    node = soup.find("meta", attrs={attr: value})
    return node.get("content", "") if node else ""


def _time_value(soup: BeautifulSoup) -> str:
    node = soup.select_one("time[datetime], time")
    if not node:
        return ""
    return node.get("datetime") or node.get_text(" ")


def _first(*values):
    return next((value for value in values if value), "")
