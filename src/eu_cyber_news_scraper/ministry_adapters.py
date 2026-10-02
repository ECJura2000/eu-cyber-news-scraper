"""Narrow adapters for four captured, publicly published ministry news formats."""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .models import Article, Source

MINISTRY_FEED_ADAPTERS = frozenset({"bg_justice_json", "it_defence_json"})
MINISTRY_LISTING_ADAPTERS = frozenset({"bg_defence_onclick", "bg_labour_english_dates"})
_SCOPES = {
    "bg_defence_onclick": ("bg_defence", "BG", "bg", "Europe/Sofia", "www.mod.bg"),
    "bg_labour_english_dates": ("bg_labour", "BG", "bg", "Europe/Sofia", "www.mlsp.government.bg"),
    "bg_justice_json": ("bg_justice", "BG", "bg", "Europe/Sofia", "justice.government.bg"),
    "it_defence_json": ("it_defence", "IT", "it", "Europe/Rome", "www.difesa.it"),
}
_ITALIAN_MONTHS = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
                   "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12}


def _scope(source: Source, fetched_from: str, allowed: frozenset[str]) -> str:
    if source.parser_adapter not in allowed:
        raise ValueError("Unsupported ministry adapter")
    identifier, country, language, zone, host = _SCOPES[source.parser_adapter]
    if (source.id, source.country, source.language, source.timezone) != (identifier, country, language, zone):
        raise ValueError("Ministry adapter source identity/language/timezone mismatch")
    for url in (source.listing_url, fetched_from):
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != host or parts.username or parts.password
                or parts.port not in (None, 443) or parts.fragment):
            raise ValueError("Ministry adapter requires its canonical HTTPS publisher")
        if source.parser_adapter == "bg_justice_json":
            query = parse_qs(parts.query)
            if (parts.path != "/api/content/GetNewsSQData" or query.get("blockId") != ["5"]
                    or query.get("lang") != ["bg"] or set(query) != {"count", "blockId", "lang"}
                    or len(query.get("count", [])) != 1 or not query["count"][0].isdigit()
                    or not 1 <= int(query["count"][0]) <= 100):
                raise ValueError("Justice news endpoint lacks the published ministry block scope")
        elif source.parser_adapter == "it_defence_json" and (parts.path != "/data/primopiano/elenco.json" or parts.query):
            raise ValueError("Defence feed must be the published primopiano JSON")
        elif source.parser_adapter == "bg_defence_onclick" and not re.fullmatch(r"/news(?:/\d+/1,2,3)?", parts.path):
            raise ValueError("Defence listing must be the official news route")
        elif source.parser_adapter == "bg_labour_english_dates" and (parts.path != "/novini" or parts.query):
            raise ValueError("Labour listing must be the official news route")
    return host


def _article(source: Source, host: str, title: object, route: object, fetched_from: str) -> Article | None:
    # Import at call time: parsers.py dispatches into this module.
    from .parsers import allowed_article_url, plain_text

    if not isinstance(title, str) or not isinstance(route, str):
        return None
    title = plain_text(title)
    decoded = unquote(route)
    if (len(title) < 8 or any(ord(c) < 32 for c in decoded) or "\\" in decoded
            or any(piece in {".", ".."} for piece in decoded.split("/"))):
        return None
    url = urljoin(fetched_from, route)
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != host or parts.username or parts.password
            or parts.port not in (None, 443) or parts.fragment or parts.query or not allowed_article_url(source, url)):
        return None
    path = unquote(parts.path)
    patterns = {
        "bg_defence_onclick": r"/news\d+",
        "bg_labour_english_dates": r"/(?!author/|novini$|uploads/)[^/]+",
        "bg_justice_json": r"/home/index/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
        "it_defence_json": r"/primopiano/[a-zA-Z0-9_-]+/\d+\.html",
    }
    if not re.fullmatch(patterns[source.parser_adapter], path):
        return None
    return Article(source_id=source.id, country=source.country, source_name=source.name_zh,
                   institution_type=source.institution_type, language=source.language, title=title, url=url,
                   fetched_via=f"{'json' if source.parser_adapter in MINISTRY_FEED_ADAPTERS else 'listing'}:{fetched_from}",
                   published_timezone=source.timezone)


def _date(article: Article, raw: str, source: Source, parsed: datetime | None, *, precision: str = "datetime") -> None:
    from .parsers import apply_publication_date

    if parsed is None:
        return
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(source.timezone))
    date_source = "json-api" if source.parser_adapter in MINISTRY_FEED_ADAPTERS else "source-selector"
    apply_publication_date(article, parsed.isoformat(), timezone_name=source.timezone,
                           languages=(source.language,), source=date_source, confidence="high")
    # Keep the exact publisher value as evidence, rather than the normalized intermediate timestamp.
    article.published_at_raw = raw
    article.date_precision = precision
    for candidate in article.date_candidates:
        candidate.raw_value = raw
        candidate.precision = precision


def _exact_datetime(raw: object, pattern: str, fmt: str) -> datetime | None:
    if not isinstance(raw, str) or not re.fullmatch(pattern, raw):
        return None
    try:
        return datetime.strptime(raw, fmt)
    except ValueError:
        return None


def parse_ministry_feed(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    """Parse only the ministry-scoped public JSON schemas named by this source."""
    host = _scope(source, fetched_from, MINISTRY_FEED_ADAPTERS)
    try:
        rows = json.loads(payload)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError("Invalid ministry JSON feed") from exc
    if not isinstance(rows, list):
        raise ValueError("Ministry JSON feed must contain a list")
    articles: list[Article] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if source.parser_adapter == "bg_justice_json":
            try:
                content = json.loads(row.get("jsonContent", ""))
            except (ValueError, TypeError):
                continue
            if not isinstance(content, dict) or not isinstance(content.get("title"), dict):
                continue
            route = row.get("url")
            if not isinstance(route, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", route):
                continue
            article = _article(source, host, content["title"].get("bg"), "/home/index/" + route, fetched_from)
            raw = row.get("date")
            parsed = _exact_datetime(raw, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "%Y-%m-%d %H:%M")
            precision = "datetime"
        else:
            article = _article(source, host, row.get("titolo"), row.get("url"), fetched_from)
            raw = row.get("contentitemdata")
            parsed = _exact_datetime(raw, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "%Y-%m-%dT%H:%M:%S")
            visible = row.get("sdata")
            match = re.fullmatch(r"(\d{2}) ([a-z]{3}) (\d{4})", visible) if isinstance(visible, str) else None
            # sdata is the frontend's displayed publication date; no body/title date inference.
            if parsed and (not match or (int(match[3]), _ITALIAN_MONTHS.get(match[2]), int(match[1]))
                           != (parsed.year, parsed.month, parsed.day)):
                parsed = None
            precision = "date" if parsed and not (parsed.hour or parsed.minute or parsed.second) else "datetime"
        if article is None or article.url in seen:
            continue
        _date(article, raw if isinstance(raw, str) else "", source, parsed, precision=precision)
        articles.append(article)
        seen.add(article.url)
    return articles


def parse_ministry_listing(html: str, source: Source, base_url: str) -> list[Article]:
    """Read literal published HTML fields; never evaluate onclick or other JavaScript."""
    from .parsers import parse_datetime

    host = _scope(source, base_url, MINISTRY_LISTING_ADAPTERS)
    # The defence publisher nests <p> inside <h4>; lxml moves that title out.
    soup = BeautifulSoup(html, "html.parser" if source.parser_adapter == "bg_defence_onclick" else "lxml")
    selector = "#newsContainer > div[onclick]" if source.parser_adapter == "bg_defence_onclick" else "article.post__horizontal"
    articles: list[Article] = []
    seen: set[str] = set()
    for card in soup.select(selector):
        if source.parser_adapter == "bg_defence_onclick":
            onclick = str(card.get("onclick", ""))
            match = re.fullmatch(r"\s*location\.href\s*=\s*(['\"])(/news\d+)\1\s*;?\s*", onclick)
            title_node = card.select_one("h4.card-title")
            date_node = card.select_one(".card-body > p")
            route = match[2] if match else None
            title = title_node.get_text(" ", strip=True) if title_node else ""
            raw = date_node.get_text(" ", strip=True) if date_node else ""
            parsed = _exact_datetime(raw, r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", "%d/%m/%Y %H:%M")
        else:
            link = card.select_one("h3.post__title a[href]")
            date_node = card.select_one("span.post__created-at")
            route = link.get("href") if link else None
            title = link.get_text(" ", strip=True) if link else ""
            raw = date_node.get_text(" ", strip=True) if date_node else ""
            parsed = None
            english = re.fullmatch(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{2}, \d{4}", raw)
            bulgarian = re.fullmatch(
                r"\d{1,2} (?:януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември) \d{4}", raw,
            )
            if english or bulgarian:
                parsed = parse_datetime(raw, languages=("en", "bg"), timezone_name=source.timezone)
        article = _article(source, host, title, route, base_url)
        if article is None or article.url in seen:
            continue
        _date(article, raw, source, parsed, precision="date" if source.parser_adapter == "bg_labour_english_dates" else "datetime")
        articles.append(article)
        seen.add(article.url)
    return articles
