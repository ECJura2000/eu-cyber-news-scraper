"""Manual Finnish agency and judicial aggregate adapters; never ministry aliases.

The aggregate remains the discovery source. Its official destination host is the
publisher evidence, including an explicit multi-court label for Tuomioistuimet.
Only item pubDate and OPH's node-post-date are publication dates.
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .models import Article, Source

FINLAND_LISTING_ADAPTERS = frozenset({"fi_oph_listing"})
FINLAND_FEED_ADAPTERS = frozenset({"fi_oikeus_aggregate_rss"})
FINLAND_PUBLISHERS = {
    "www.ulosottolaitos.fi": "Ulosottolaitos (National Enforcement Authority Finland)",
    "www.tuomioistuimet.fi": "Tuomioistuimet.fi (Finnish Courts; multi-court publisher portal)",
    "www.korkeinoikeus.fi": "Korkein oikeus (Supreme Court of Finland)",
    "www.oikeusrekisterikeskus.fi": "Oikeusrekisterikeskus (Legal Register Centre)",
    "www.oikeuspalveluvirasto.fi": "Oikeuspalveluvirasto (National Legal Services Authority)",
    "www.kho.fi": "Korkein hallinto-oikeus (Supreme Administrative Court of Finland)",
    "www.vakuutusoikeus.fi": "Vakuutusoikeus (Insurance Court of Finland)",
}


def _https_host(url: str) -> str:
    try:
        decoded = unquote(url)
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.username or parts.password
                or parts.port not in (None, 443) or parts.fragment
                or "\\" in decoded or any(ord(c) < 32 for c in decoded)
                or any(p in {".", ".."} for p in unquote(parts.path).split("/"))):
            return ""
        return parts.hostname or ""
    except ValueError:
        return ""


def _scope(source: Source, fetched_from: str, *, feed: bool) -> None:
    identifier = "fi_judicial_administration_portal" if feed else "fi_education_agency"
    adapter = "fi_oikeus_aggregate_rss" if feed else "fi_oph_listing"
    host = "www.oikeus.fi" if feed else "www.oph.fi"
    if (source.id, source.country, source.language, source.timezone, source.parser_adapter) != (
            identifier, "FI", "fi", "Europe/Helsinki", adapter):
        raise ValueError("Finnish adapter source identity/language/timezone mismatch")
    for url in (source.listing_url, fetched_from):
        parts = urlsplit(url)
        if _https_host(url) != host:
            raise ValueError("Finnish adapter requires the canonical official HTTPS origin")
        if feed:
            if (parts.path != "/feed/rss-feed" or
                    parse_qs(parts.query, keep_blank_values=True) != {"post_type": ["ajankohtaiset"]}):
                raise ValueError("Only the judicial news aggregate endpoint is supported")
        elif parts.path != "/fi/tiedotteet" or parts.query:
            raise ValueError("Only the Finnish Education Agency press listing is supported")


def _article(source: Source, title: str, url: str, fetched_from: str, publisher: str) -> Article:
    from .parsers import plain_text

    return Article(source_id=source.id, country=source.country, source_name=source.name_zh,
                   institution_type=source.institution_type, language=source.language,
                   title=plain_text(title), url=url, publisher_organisation=publisher,
                   discovered_by=[source.id], fetched_via=f"{'feed' if source.feed_urls else 'listing'}:{fetched_from}",
                   published_timezone=source.timezone)


def _date(article: Article, raw: str, source: Source, parsed: datetime, *, feed: bool) -> None:
    from .parsers import apply_publication_date

    apply_publication_date(article, parsed.isoformat(), timezone_name=source.timezone,
                           languages=("fi", "sv", "en"),
                           source="feed-published" if feed else "source-selector", confidence="high")
    article.published_at_raw = raw
    article.date_precision = "datetime" if feed else "date"
    for candidate in article.date_candidates:
        candidate.raw_value = raw
        candidate.precision = article.date_precision


def parse_finland_listing(html: str, source: Source, base_url: str) -> list[Article]:
    """Parse only OPH's main press cards; reject navigation and related widgets."""
    from .parsers import allowed_article_url, plain_text

    _scope(source, base_url, feed=False)
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []
    seen: set[str] = set()
    for card in soup.select("main .listing-item.node--type-news"):
        if (card.find_parent(["aside", "nav", "footer"])
                or card.find_parent(class_=re.compile(r"^(related|related-news|sidebar)$"))):
            continue
        link = card.select_one("h3.listing-title a.listing-title__link[href]")
        date_node = card.select_one(".listing-item-footer .node-post-date")
        kind = card.select_one(".listing-item-bundle")
        if link is None or date_node is None or kind is None or kind.get_text(strip=True) != "Tiedote":
            continue
        route = str(link["href"])
        url = urljoin(base_url, route)
        title = plain_text(link.get_text(" ", strip=True))
        if (_https_host(route if urlsplit(route).scheme else url) != "www.oph.fi"
                or urlsplit(url).query or not re.fullmatch(r"/fi/uutiset/20\d{2}/[^/]+", urlsplit(url).path)
                or not allowed_article_url(source, url) or len(title) < 8 or url in seen
                or any(p in {".", ".."} for p in unquote(route).split("/"))):
            continue
        raw = date_node.get_text(" ", strip=True)
        if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", raw):
            continue
        try:
            parsed = datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=ZoneInfo(source.timezone))
        except ValueError:
            continue
        article = _article(source, title, url, base_url, "Opetushallitus (Finnish National Agency for Education)")
        summary = card.select_one(".body .text-long")
        article.summary = plain_text(summary.get_text(" ", strip=True)) if summary else ""
        _date(article, raw, source, parsed, feed=False)
        articles.append(article)
        seen.add(url)
    return articles


def parse_finland_feed(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    """Retain the aggregate and exact validated publisher; never use update dates."""
    from .parsers import allowed_article_url, plain_text

    _scope(source, fetched_from, feed=True)
    # This published endpoint is UTF-8 RSS. Reject DTDs before parsing; never
    # resolve external entities or fetch XML resources.
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    if re.search(r"<!DOCTYPE", text, re.I):
        raise ValueError("Expected judicial RSS without a DTD")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("Invalid judicial RSS") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected judicial RSS without a DTD")
    articles: list[Article] = []
    seen: set[str] = set()
    for item in root.findall("channel/item"):
        url = (item.findtext("link") or "").strip()
        title = plain_text(item.findtext("title") or "")
        raw = (item.findtext("pubDate") or "").strip()
        host = _https_host(url)
        if (host not in FINLAND_PUBLISHERS or len(title) < 8 or url in seen or urlsplit(url).query
                or not re.fullmatch(r"/ajankohtaiset/[^/]+/?", urlsplit(url).path)
                or not allowed_article_url(source, url) or not raw):
            continue
        try:
            parsed = parsedate_to_datetime(raw)
        except (ValueError, TypeError, OverflowError):
            continue
        if parsed.tzinfo is None:
            continue
        article = _article(source, title, url, fetched_from, FINLAND_PUBLISHERS[host])
        article.summary = plain_text(item.findtext("description") or "")
        _date(article, raw, source, parsed, feed=True)
        articles.append(article)
        seen.add(url)
    return articles
