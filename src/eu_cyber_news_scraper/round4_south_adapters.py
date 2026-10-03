"""Anonymous, publisher-bound ES SharePoint and IT Gatsby news adapters.

Only explicit publication fields are accepted. Navigation, consultation dates,
weather bulletins, modification timestamps and other publishers are excluded.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

# The existing lxml dependency has no bundled stubs; keep this untyped XML boundary local.
from lxml import etree  # type: ignore[import-untyped]

from .http import MAX_RESPONSE_BYTES, HttpClient, HttpStats
from .models import Article, Source

ES_LISTING = (
    "https://portal.mineco.gob.es/es-es/comunicacion/_api/web/lists"
    "(guid'de1040a8-90d1-4f24-9455-423894813206')/items"
    "?$select=TituloSP,FechaPublicacionSP,FechaPublicacionCalculadaSP,FileRef,PublishingPageLayout,CanalesSP"
    "&$orderby=FechaPublicacionSP%20desc&$top=30"
)
IT_LISTING = "https://www.protezionecivile.gov.it/page-data/it/page-data.json"
ROUND4_SOUTH_FEED_ADAPTERS = frozenset({"round4_es_sharepoint", "round4_it_dpc_gatsby"})
_SCOPES = {
    "round4_es_sharepoint": ("es_economy", "ES", "es", "Europe/Madrid", ES_LISTING),
    "round4_it_dpc_gatsby": ("it_civil_protection", "IT", "it", "Europe/Rome", IT_LISTING),
}
_D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
_M = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _scope(source: Source, fetched_from: str) -> str:
    expected = _SCOPES.get(source.parser_adapter)
    if expected is None or (source.id, source.country, source.language, source.timezone, source.listing_url) != expected:
        raise ValueError("Round4 source identity, language, timezone or endpoint mismatch")
    if fetched_from != expected[-1]:
        raise ValueError("Round4 feed must use its exact public ministry endpoint")
    return urlsplit(fetched_from).hostname or ""


def _origin(url: str, host: str) -> bool:
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == host and not p.username and not p.password
                and p.port in (None, 443) and not p.fragment)
    except ValueError:
        return False


def _article(source: Source, host: str, title: object, route: object, raw: object,
             *, visible_date: str | None = None) -> Article | None:
    from .parsers import allowed_article_url, apply_publication_date, plain_text

    if not all(isinstance(x, str) for x in (title, route, raw)):
        return None
    assert isinstance(title, str) and isinstance(route, str) and isinstance(raw, str)
    decoded = unquote(route)
    if (not route.startswith("/") or route.startswith("//") or "\\" in decoded
            or any(ord(c) < 32 for c in decoded) or re.search(r"%[0-9a-fA-F]{2}", decoded)
            or any(part in {".", ".."} for part in decoded.split("/"))):
        return None
    if source.id == "es_economy":
        pattern = r"/es-es/comunicacion/Paginas/(?!default\.aspx$)[^/?#]+\.aspx"
    elif source.id == "it_institutional_reforms":
        pattern = r"/it/comunicazione/notizie/[^/?#]+/"
    else:
        pattern = r"/it/(?:notizia|comunicato-stampa)/[^/?#]+/"
    if not re.fullmatch(pattern, decoded):
        return None
    url = urljoin(f"https://{host}/", route)
    if not _origin(url, host) or not allowed_article_url(source, url):
        return None
    title = " ".join(plain_text(title).replace("\u200b", "").split())
    if len(title) < 8 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", raw):
        return None
    try:
        date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    local = date.astimezone(ZoneInfo(source.timezone)).date().isoformat()
    if visible_date is not None and visible_date != local:
        return None
    article = Article(source_id=source.id, country=source.country, source_name=source.name_zh,
                      institution_type=source.institution_type, language=source.language, title=title, url=url,
                      fetched_via=f"public-api:{source.listing_url}", published_timezone=source.timezone)
    apply_publication_date(article, raw, timezone_name=source.timezone, languages=(source.language,),
                           source="source-selector", confidence="high")
    if source.id == "es_economy":
        article.date_precision = "date"
        for candidate in article.date_candidates:
            candidate.precision = "date"
    return article


def parse_round4_south_feed(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    """Parse the captured public schema; accept only complete dated ministry news."""
    host = _scope(source, fetched_from)
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if len(payload.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("Round4 payload exceeds production byte limit")
    result: list[Article] = []
    if source.id == "es_economy":
        if "<!DOCTYPE" in payload.upper() or "<!ENTITY" in payload.upper():
            raise ValueError("SharePoint feed must not define XML entities")
        try:
            root = etree.fromstring(payload.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError as exc:
            raise ValueError("Invalid ministry SharePoint XML") from exc
        if (root.tag != _ATOM + "feed" or root.get("{http://www.w3.org/XML/1998/namespace}base")
                != "https://portal.mineco.gob.es/es-es/comunicacion/_api/"):
            raise ValueError("SharePoint feed publisher scope mismatch")
        for entry in root.findall(_ATOM + "entry"):
            props = entry.find(_ATOM + "content/" + _M + "properties")
            if props is None:
                continue
            channels = props.findall(_D + "CanalesSP/" + _D + "element")
            if not any(c.findtext(_D + "WssId") == "205"
                       and c.findtext(_D + "TermGuid") == "4a14a97d-6a0d-4fd8-8375-7b54e951899d"
                       and c.findtext(_D + "Label") == "Noticias (Comunicación)" for c in channels):
                continue
            if props.findtext(_D + "PublishingPageLayout/" + _D + "Url") != (
                "https://portal.mineco.gob.es/_catalogs/masterpage/Mineco/Noticia.aspx"
            ):
                continue
            item = _article(source, host, props.findtext(_D + "TituloSP"), props.findtext(_D + "FileRef"),
                            props.findtext(_D + "FechaPublicacionSP"),
                            visible_date=props.findtext(_D + "FechaPublicacionCalculadaSP", ""))
            if item:
                result.append(item)
    else:
        try:
            data = json.loads(payload)
            if (data["componentChunkName"] != "component---src-pages-index-it-jsx" or data["path"] != "/it/"):
                raise ValueError("DPC public page identity mismatch")
            relationships = data["result"]["data"]["node"]["relationships"]
            if not isinstance(relationships, dict):
                raise ValueError("DPC homepage relationship schema changed")
            rows = [relationships.get("field_primo_piano_contenuto")]
            for key in ("field_evidenza_1", "field_evidenza_2", "field_evidenza_3"):
                value = relationships.get(key, [])
                if not isinstance(value, list):
                    raise ValueError("DPC homepage news schema changed")
                rows.extend(value)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid DPC public page schema") from exc
        for row in rows:
            if not isinstance(row, dict) or row.get("__typename") not in {"node__notizia", "node__comunicato_stampa"}:
                continue
            rel = row.get("relationships")
            if not isinstance(rel, dict):
                continue
            subdomain = rel.get("field_sottodominio", {})
            if not isinstance(subdomain, dict) or subdomain.get("name") != "Portale":
                continue
            category = "notizia" if row["__typename"] == "node__notizia" else "comunicato-stampa"
            fields = row.get("fields")
            route = fields.get("slug") if isinstance(fields, dict) else None
            if not isinstance(route, str) or not route.startswith(f"/{category}/"):
                continue
            item = _article(source, host, row.get("title"), "/it" + route, row.get("field_data"))
            if item:
                result.append(item)
    return list({item.url: item for item in result}.values())


def parse_round4_reforms_detail(html: str, source: Source, url: str) -> list[Article]:
    """Reject current undated reform news; require explicit first-party publication metadata.

    The captured page has only og:updated_time and an event date in the body.
    This parser is intentionally not registered as a runnable source until live
    articles provide a publication field. It never falls back to either date.
    """
    host = "www.riformeistituzionali.gov.it"
    if ((source.id, source.country, source.language, source.timezone)
            != ("it_institutional_reforms", "IT", "it", "Europe/Rome")
            or source.parser_adapter != "round4_it_reforms_detail" or not _origin(url, host)
            or not _origin(source.listing_url, host)
            or urlsplit(source.listing_url).path != "/it/comunicazione/notizie/"
            or not re.fullmatch(r"/it/comunicazione/notizie/[^/]+/", urlsplit(url).path)
            or urlsplit(url).query):
        raise ValueError("Reforms detail must belong to the exact ministry news scope")
    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one("h1")
    canonical = soup.select_one('meta[property="og:url"]')
    publisher = soup.select_one('meta[property="og:site_name"]')
    published = soup.select('meta[property="article:published_time"]')
    if (title is None or canonical is None or canonical.get("content") != url
            or publisher is None or publisher.get("content") != (
                "Ministro per le riforme istituzionali e la semplificazione normativa"
            ) or len(published) != 1):
        return []
    item = _article(source, host, title.get_text(" ", strip=True), urlsplit(url).path,
                    published[0].get("content"))
    return [item] if item else []


async def fetch_round4_south_feed(
    client: HttpClient, source: Source, *, stats: HttpStats | None = None,
) -> httpx.Response:
    """Use existing robots/TLS/size/retry/pacing implementation with an origin guard."""
    host = _scope(source, source.listing_url)
    if not client.obey_robots:
        raise ValueError("Round4 fetching requires robots enforcement")
    if client.min_interval <= 0 or client.max_response_bytes > MAX_RESPONSE_BYTES:
        raise ValueError("Round4 fetching requires bounded bytes and positive origin pacing")
    response = await client.get(source.listing_url, stats=stats, redirect_guard=lambda url: _origin(url, host))
    response.raise_for_status()
    _scope(source, str(response.url))
    return response
