from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import dateparser
import feedparser
from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import Article, Source

DATE_SETTINGS = {
    "RETURN_AS_TIMEZONE_AWARE": True,
    "TIMEZONE": "UTC",
    "TO_TIMEZONE": "UTC",
    # Every configured authority is European; numeric dates such as
    # 08-04-2026 therefore mean 8 April, not August 4.
    "DATE_ORDER": "DMY",
    "PREFER_DAY_OF_MONTH": "first",
}

DATE_SOURCE_PRIORITY = {
    "feed-published": 100,
    "json-api": 100,
    "json-ld": 90,
    "article-meta": 80,
    "time-element": 70,
    "source-selector": 60,
    "visible-text": 40,
    "title-text": 20,
}

NAVIGATION_TITLES = {
    "next",
    "next page",
    "previous",
    "previous page",
    "nächste seite",
    "vorherige seite",
    "weiter",
    "zurück",
    "page suivante",
    "page précédente",
    "wissenschaft",
}


def parse_datetime(
    value: str | None,
    languages: Iterable[str] = (),
    timezone_name: str = "UTC",
) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    normalized = re.sub(
        r"^(?:Publié le|Veröffentlicht am|Pressemitteilung vom|Release Date:)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
        r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]|$)", normalized):
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    settings = {**DATE_SETTINGS, "TIMEZONE": timezone_name}
    parsed_value = dateparser.parse(normalized, languages=list(languages) or None, settings=settings)
    if not isinstance(parsed_value, datetime):
        return None
    parsed = parsed_value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def apply_publication_date(
    article: Article,
    raw_value: str | None,
    *,
    timezone_name: str,
    languages: Iterable[str],
    source: str,
    confidence: str,
) -> bool:
    raw = str(raw_value or "").strip()
    parsed = parse_datetime(raw, languages, timezone_name)
    if not parsed:
        return False
    if article.published_at and article.published_at != parsed:
        article.date_conflict = True
    current_priority = DATE_SOURCE_PRIORITY.get(article.date_source, -1)
    candidate_priority = DATE_SOURCE_PRIORITY.get(source, 0)
    if article.published_at and current_priority > candidate_priority:
        return False
    article.published_at = parsed
    article.published_at_raw = raw
    article.published_timezone = timezone_name
    article.published_date_local = parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    article.date_precision = "datetime" if re.search(r"\d{1,2}:\d{2}|T\d{2}", raw) else "date"
    article.date_source = source
    article.date_confidence = confidence
    return True


def plain_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(BeautifulSoup(html_module.unescape(value), "html.parser").stripped_strings)


def discover_feeds(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    for link in soup.select("link[rel~='alternate'][href]"):
        media_type = _attribute(link, "type").casefold()
        if "rss" in media_type or "atom" in media_type or "xml" in media_type:
            urls.append(urljoin(base_url, _attribute(link, "href")))
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
        article = Article(
                source_id=source.id,
                country=source.country,
                source_name=source.name_zh,
                institution_type=source.institution_type,
                language=source.language,
                title=title,
                url=url,
                summary=plain_text(entry.get("summary") or entry.get("description") or content[0].get("value")),
                fetched_via=f"feed:{fetched_from}",
                published_timezone=source.timezone,
            )
        apply_publication_date(
            article,
            raw_date,
            timezone_name=source.timezone,
            languages=_date_languages(source.language),
            source="feed-published",
            confidence="high",
        )
        articles.append(article)
    return articles


def parse_listing(html: str, source: Source, base_url: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    base_node = soup.select_one("base[href]")
    document_base = urljoin(base_url, _attribute(base_node, "href")) if base_node else base_url
    # Some government sites render news links outside <main> or use a very
    # shallow list.  Always include anchors as a final candidate pool; URL
    # allow/include/exclude rules below keep navigation links out.
    candidates = (
        [node for selector in source.card_selectors for node in soup.select(selector)]
        if source.card_selectors
        else [
            *soup.select("article"),
            *soup.select("main li"),
            *soup.select("main a[href]"),
            *soup.select("a[href]"),
        ]
    )
    articles = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if candidate.name == "a":
            links = [candidate]
        elif source.link_selectors:
            links = [node for selector in source.link_selectors for node in candidate.select(selector)]
        else:
            links = candidate.select("a[href]")
        link = next(
            (
                node
                for node in links
                if _attribute(node, "href")
                and allowed_article_url(source, urljoin(document_base, _attribute(node, "href").strip()))
            ),
            None,
        )
        if link is None:
            continue
        url = urljoin(document_base, _attribute(link, "href").strip())
        canonical = _canonical_candidate_url(url)
        if canonical in seen_urls:
            continue
        link_text = plain_text(link.get_text(" "))
        context = _candidate_context(link) if candidate.name == "a" else candidate
        title_node = None
        if source.title_selectors and context.name != "a":
            title_node = next(
                (context.select_one(selector) for selector in source.title_selectors if context.select_one(selector)),
                None,
            )
        elif len(link_text) < 8 and context.name != "a":
            title_node = context.select_one("h1, h2, h3, h4")
        title = plain_text(title_node.get_text(" ") if title_node else link.get_text(" "))
        if len(title) < 8 or _looks_like_navigation_title(title):
            continue
        time_node = context.select_one("time") if context.name != "a" else None
        date_text = ""
        date_source = "visible-text"
        date_confidence = "low"
        if source.date_selectors and context.name != "a":
            date_node = next(
                (context.select_one(selector) for selector in source.date_selectors if context.select_one(selector)),
                None,
            )
            if date_node:
                date_text = _attribute(date_node, "datetime") or date_node.get_text(" ")
                date_source = "source-selector"
                date_confidence = "medium"
        if time_node:
            date_text = date_text or _attribute(time_node, "datetime") or time_node.get_text(" ")
            if date_source == "visible-text":
                date_source = "time-element"
                date_confidence = "high"
        if not date_text:
            date_text = _extract_date_text(context.get_text(" "))
        if source.summary_selectors and context.name != "a":
            summary_node = next(
                (context.select_one(selector) for selector in source.summary_selectors if context.select_one(selector)),
                None,
            )
        else:
            summary_node = context.select_one("p") if context.name != "a" else None
        seen_urls.add(canonical)
        article = Article(
                source_id=source.id,
                country=source.country,
                source_name=source.name_zh,
                institution_type=source.institution_type,
                language=source.language,
                title=title,
                url=url,
                summary=plain_text(summary_node.get_text(" ") if summary_node else ""),
                fetched_via=f"html:{base_url}",
                published_timezone=source.timezone,
            )
        apply_publication_date(
            article,
            date_text,
            timezone_name=source.timezone,
            languages=_date_languages(source.language),
            source=date_source,
            confidence=date_confidence,
        )
        articles.append(article)
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
        article = Article(
                source_id=source.id,
                country=source.country,
                source_name=source.name_zh,
                institution_type=source.institution_type,
                language=source.language,
                title=title,
                url=url,
                summary=plain_text(row.get("leadText")),
                fetched_via=f"json:{fetched_from}",
                published_timezone=source.timezone,
            )
        apply_publication_date(
            article,
            row.get("eventDate"),
            timezone_name=source.timezone,
            languages=_date_languages(source.language),
            source="json-api",
            confidence="high",
        )
        articles.append(article)
    return articles


def enrich_from_detail(article: Article, html: str, source: Source | None = None) -> Article:
    soup = BeautifulSoup(html, "lxml")
    structured = _article_json_ld(soup)
    title = _first(
        structured.get("headline"),
        _heading_value(soup),
        _meta(soup, "property", "og:title"),
        _meta(soup, "name", "twitter:title"),
        soup.title.string if soup.title else "",
    )
    summary = _first(
        structured.get("description"),
        _meta(soup, "property", "og:description"),
        _meta(soup, "name", "description"),
    )
    if title and len(plain_text(title)) >= 8:
        article.title = plain_text(title)
    if summary and len(plain_text(summary)) > len(article.summary):
        article.summary = plain_text(summary)
    adapter_date = _adapter_date_value(soup, source)
    source_date = _source_date_value(soup, source)
    generic_date_meta = "" if source and source.parser_adapter == "dpma_press_release" else _meta(soup, "name", "date")
    date_candidates = (
        ("json-ld", "high", structured.get("datePublished")),
        ("article-meta", "high", _meta(soup, "property", "article:published_time")),
        ("article-meta", "high", generic_date_meta),
        ("time-element", "high", _time_value(soup)),
        ("source-selector", "high", adapter_date or source_date),
        ("visible-text", "medium", _visible_date_value(soup)),
        ("title-text", "low", _title_date_value(soup)),
    )
    for date_source, confidence, date_value in date_candidates:
        apply_publication_date(
            article,
            str(date_value or ""),
            timezone_name=article.published_timezone or "UTC",
            languages=_date_languages(article.language),
            source=date_source,
            confidence=confidence,
        )
    return article


def _adapter_date_value(soup: BeautifulSoup, source: Source | None) -> str:
    if not source or source.parser_adapter != "dpma_press_release":
        return ""
    match = re.search(
        r"Pressemitteilung\s+vom\s+\d{1,2}\.?\s+[A-Za-zÀ-ÿäöüÄÖÜß]+\s+\d{4}",
        soup.get_text(" ", strip=True),
        flags=re.IGNORECASE,
    )
    return match.group(0) if match else ""


def _source_date_value(soup: BeautifulSoup, source: Source | None) -> str:
    if not source:
        return ""
    for selector in source.date_selectors:
        node = soup.select_one(selector)
        if node:
            return _attribute(node, "datetime") or node.get_text(" ", strip=True)
    return ""


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


def _candidate_context(link: Tag) -> Tag:
    context = link
    for parent in link.parents:
        if getattr(parent, "name", None) in {"article", "li"}:
            return parent
        classes = _attribute(parent, "class").casefold() if isinstance(parent, Tag) else ""
        if getattr(parent, "name", None) not in {"h1", "h2", "h3", "h4"} and re.search(
            r"(?:^|[-_\s])(card|item|news|teaser|result)(?:$|[-_\s])", classes
        ):
            return parent
        if getattr(parent, "name", None) in {"main", "body"}:
            break
    return context


def _looks_like_navigation_title(value: str) -> bool:
    normalized = plain_text(value).casefold().strip(" .:›»←→")
    if normalized in NAVIGATION_TITLES:
        return True
    return bool(re.fullmatch(r"(?:page|seite)\s+\d+", normalized))


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


def _article_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
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


def _walk_json_ld(payload: Any) -> Iterator[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _walk_json_ld(item)
    elif isinstance(payload, dict):
        yield payload
        if "@graph" in payload:
            yield from _walk_json_ld(payload["@graph"])


def _meta(soup: BeautifulSoup, attr: str, value: str) -> str:
    node = soup.find("meta", attrs={attr: value})
    return _attribute(node, "content") if isinstance(node, Tag) else ""


def _time_value(soup: BeautifulSoup) -> str:
    node = soup.select_one("time[datetime], time")
    if not node:
        return ""
    return _attribute(node, "datetime") or node.get_text(" ")


def _visible_date_value(soup: BeautifulSoup) -> str:
    node = soup.select_one(
        "[class*='publish' i], [class*='date' i], [id*='publish' i], [id*='date' i]"
    )
    if not node:
        return ""
    text = node.get_text(" ", strip=True)
    return _extract_date_text(text) or text


def _title_date_value(soup: BeautifulSoup) -> str:
    return _extract_date_text(soup.title.get_text(" ", strip=True)) if soup.title else ""


def _heading_value(soup: BeautifulSoup) -> str:
    node = soup.select_one("main h1, article h1, h1")
    return node.get_text(" ", strip=True) if node else ""


def _first(*values: object) -> str:
    return next((str(value) for value in values if value), "")


def _attribute(node: Tag, name: str) -> str:
    value = node.get(name, "")
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _canonical_candidate_url(value: str) -> str:
    parts = urlsplit(value)
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return f"{parts.scheme.casefold()}://{parts.netloc.casefold()}{path}"
