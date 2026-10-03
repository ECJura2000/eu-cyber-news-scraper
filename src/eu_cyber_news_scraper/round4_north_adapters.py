"""Bounded first-party publication adapters; no script execution or date inference."""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .http import HttpClient, HttpStats, ResponseTooLargeError, _retry_delay
from .models import Article, Source

ROUND4_NORTH_ADAPTERS = frozenset({"cy_minister_table", "cz_public_flight", "dk_resilience_json",
                                  "dk_environment_json", "dk_foreign_ritzau", "belspo_central_press", "bmlv_publication"})
SCOPES = {
    "cy_minister_table": ("cy_education", "CY", "el", "Europe/Nicosia", "enimerosi.moec.gov.cy", "/"),
    "cz_public_flight": ("cz_interior", "CZ", "cs", "Europe/Prague", "mv.gov.cz", "/"),
    "dk_resilience_json": ("dk_resilience", "DK", "da", "Europe/Copenhagen", "mssb.dk", "/nyheder/"),
    "dk_environment_json": ("dk_environment", "DK", "da", "Europe/Copenhagen", "mim.dk", "/nyheder/pressemeddelelser"),
    "dk_foreign_ritzau": ("dk_foreign_affairs", "DK", "da", "Europe/Copenhagen", "um.dk", "/nyheder/"),
    "belspo_central_press": ("be_science_policy", "BE", "fr", "Europe/Brussels", "www.belspo.be", "/belspo/organisation/press_fr.stm"),
    "bmlv_publication": ("at_bmlv", "AT", "de", "Europe/Vienna", "www.bmlv.gv.at", "/aktuell/index.shtml"),
}
_MINISTRY = "Υπουργείο Παιδείας, Αθλητισμού και Νεολαίας"
_MIM_ROOT = "fc28d56a-dae2-477b-a2c4-34f997eb243d"
_MSSB_MODULE = "663e4c9d-383a-4692-ab61-31adb9a30fc7"


def _safe_url(url: str, host: str) -> bool:
    try:
        p = urlsplit(url)
        decoded = unquote(p.path)
        return (p.scheme == "https" and p.hostname == host and p.username is None
                and p.password is None and p.port in {None, 443} and not p.fragment
                and not any(ord(c) < 32 for c in url + decoded) and "\\" not in decoded
                and not any(piece in {".", ".."} for piece in decoded.split("/")))
    except ValueError:
        return False


def _scope(source: Source, fetched_from: str, *, api: bool = False) -> str:
    spec = SCOPES.get(source.parser_adapter)
    if spec is None or (source.id, source.country, source.language, source.timezone) != spec[:4]:
        raise ValueError("Round4 source identity/language/timezone mismatch")
    host, path = spec[4:]
    if (not _safe_url(source.listing_url, host) or urlsplit(source.listing_url).path != path
            or urlsplit(source.listing_url).query):
        raise ValueError("Round4 canonical listing scope changed")
    api_url = {"dk_resilience_json": "https://mssb.dk/umbraco/api/DynamicListSearchApi/search",
               "dk_environment_json": "https://search.mst.dk/api/News/Search",
               "dk_foreign_ritzau": "https://via.ritzau.dk/public-website-api/pressroom/2012662/releases/20/0"}.get(source.parser_adapter)
    if api:
        if fetched_from != api_url:
            raise ValueError("Round4 anonymous API scope changed")
    elif not _safe_url(fetched_from, host):
        raise ValueError("Round4 publisher origin mismatch")
    return host


def _article(source: Source, title: str, url: str, raw: str, via: str) -> Article | None:
    from .parsers import allowed_article_url, apply_publication_date, plain_text

    host = "via.ritzau.dk" if source.parser_adapter == "dk_foreign_ritzau" else SCOPES[source.parser_adapter][4]
    if not _safe_url(url, host) or not allowed_article_url(source, url):
        return None
    title = plain_text(title)
    if len(title) < 8:
        return None
    article = Article(source.id, source.country, source.name_zh, source.institution_type,
                      source.language, title, url, fetched_via=via, published_timezone=source.timezone,
                      publisher_organisation=source.id)
    if raw:
        normalized = raw
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", raw):
            try:
                normalized = datetime.fromisoformat(raw).replace(tzinfo=ZoneInfo(source.timezone)).isoformat()
            except ValueError:
                return None
        apply_publication_date(article, normalized, timezone_name=source.timezone, languages=(source.language,),
                               source="json-api" if via.startswith("json:") else "source-selector", confidence="high")
        article.published_at_raw = raw
        for candidate in article.date_candidates:
            candidate.raw_value = raw
    return article


def _flight_records(soup: BeautifulSoup) -> dict[str, Any]:
    """Decode literal Flight string chunks as JSON; never execute publisher JS."""
    chunks = []
    for script in soup.select("script"):
        text = script.get_text().strip()
        match = re.fullmatch(r"self\.__next_f\.push\((\[.*\])\);?", text, re.S)
        if not match:
            continue
        try:
            chunk = json.loads(match[1])
        except ValueError:
            continue
        if isinstance(chunk, list) and len(chunk) == 2 and chunk[0] == 1 and isinstance(chunk[1], str):
            chunks.append(chunk[1])
    records = {}
    for line in "".join(chunks).splitlines():
        key, sep, value = line.partition(":")
        if sep and re.fullmatch(r"[0-9a-f]+", key) and value.startswith(("[", "{")):
            try:
                records[key] = json.loads(value)
            except ValueError:
                continue
    return records


def _walk(node: Any, records: dict[str, Any], visited: frozenset[str] = frozenset()) -> Iterator[Any]:
    if isinstance(node, str) and re.fullmatch(r"\$[0-9a-f]+", node):
        key = node[1:]
        if key not in visited and key in records:
            yield from _walk(records[key], records, visited | {key})
    elif isinstance(node, (dict, list)):
        yield node
        for value in node.values() if isinstance(node, dict) else node:
            yield from _walk(value, records, visited)


def _cz_flight(soup: BeautifulSoup, source: Source, base_url: str) -> list[Article]:
    records = _flight_records(soup)
    visible = {urljoin(base_url, str(a["href"])): a.get_text(" ", strip=True)
               for a in soup.select("article h3 a[href]")}
    output: dict[str, Article] = {}
    for node in _walk(list(records.values()), records):
        if not (isinstance(node, list) and len(node) == 4 and node[:2] == ["$", "article"]):
            continue
        descendants = list(_walk(node[3], records))
        links = [v for v in descendants if isinstance(v, dict) and isinstance(v.get("href"), str)
                 and isinstance(v.get("children"), str)
                 and urljoin(base_url, v["href"]) in visible
                 and v["children"] == visible[urljoin(base_url, v["href"])]]
        if len(links) != 1:
            continue
        dates: list[str] = []
        for v in descendants:
            if isinstance(v, list) and len(v) == 4 and v[:2] == ["$", "span"]:
                children = v[3].get("children") if isinstance(v[3], dict) else None
                if isinstance(children, list) and len(children) == 2 and children[0] == "Publikováno: ":
                    dates.extend(d["value"] for d in _walk(children[1], records)
                                 if isinstance(d, dict) and isinstance(d.get("value"), str)
                                 and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}", d["value"]))
        if len(set(dates)) != 1:
            continue
        link = links[0]
        a = _article(source, link["children"], urljoin(base_url, link["href"]), dates[0], "html:" + base_url)
        if a:
            output.setdefault(a.url, a)
    return list(output.values())


def parse_round4_listing(html: str, source: Source, base_url: str) -> list[Article]:
    _scope(source, base_url)
    if source.parser_adapter == "dk_foreign_ritzau" and html.lstrip().startswith("{"):
        return parse_round4_feed(html, source, "https://via.ritzau.dk/public-website-api/pressroom/2012662/releases/20/0")
    if source.parser_adapter in {"dk_environment_json", "dk_resilience_json"} and html.lstrip().startswith("{"):
        endpoint = ("https://search.mst.dk/api/News/Search" if source.id == "dk_environment"
                    else "https://mssb.dk/umbraco/api/DynamicListSearchApi/search")
        return parse_round4_feed(html, source, endpoint)
    if source.parser_adapter in {"belspo_central_press", "bmlv_publication"} and html.lstrip().startswith("{"):
        bundle = json.loads(html)
        if (not isinstance(bundle, dict) or bundle.get("source_url") != source.listing_url
                or not isinstance(bundle.get("details"), list) or len(bundle["details"]) > 3):
            raise ValueError("Round4 detail bundle requires the canonical source listing")
        result: dict[str, Article] = {}
        for detail in bundle["details"]:
            if not isinstance(detail, dict) or not isinstance(detail.get("url"), str) or not isinstance(detail.get("html"), str):
                raise ValueError("Invalid Round4 detail bundle entry")
            for article in parse_round4_detail(detail["html"], source, detail["url"]):
                result.setdefault(article.url, article)
        return list(result.values())
    soup = BeautifulSoup(html, "lxml")
    if source.parser_adapter == "cz_public_flight":
        return _cz_flight(soup, source, base_url)
    if source.parser_adapter == "cy_minister_table":
        output: dict[str, Article] = {}
        for row in soup.select("tr.dxgvDataRow_DevEx"):
            cells = row.find_all("td", recursive=False)
            link = row.select_one('a.myHyperlink[href]')
            if len(cells) < 9 or link is None:
                continue
            title = cells[7].get_text(" ", strip=True)
            sender = cells[6].get_text(" ", strip=True)
            # The ministry table also contains school/department support notices.
            if sender != _MINISTRY or not re.match(r"(?:Δηλώσεις|Μήνυμα|Χαιρετισμός|Ομιλία) της Υπουργού\b", title):
                continue
            route = str(link["href"])
            raw = cells[8].get_text(" ", strip=True)  # Καταχώριση: publication registration, not event date.
            if not re.fullmatch(r"/ypp\d+", route) or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw):
                continue
            a = _article(source, title, urljoin(base_url, route), raw, "html:" + base_url)
            if a:
                output.setdefault(a.url, a)
        return list(output.values())
    if source.parser_adapter in {"dk_environment_json", "dk_resilience_json"}:
        return []  # Page-shell create/update times are not article publication dates.
    return []  # These mixed archives require attributable article detail pages.


def parse_round4_detail(html: str, source: Source, url: str) -> list[Article]:
    _scope(source, url)
    soup = BeautifulSoup(html, "lxml")
    if source.parser_adapter == "belspo_central_press":
        if not re.fullmatch(r"/belspo/organisation/press/[^/]+_fr\.stm", urlsplit(url).path):
            return []
        headings = soup.select("h1")
        about = next((h for h in soup.select("h2") if h.get_text(" ", strip=True) == "À propos de BELSPO"), None)
        contact = next((h for h in soup.select("h2") if h.get_text(" ", strip=True) == "Contact presse :"), None)
        if len(headings) != 2 or headings[0].get_text(" ", strip=True) != "COMMUNIQUÉ DE PRESSE" or about is None or contact is None:
            return []
        # Only the local press-contact block counts; footer publisher text is ignored.
        contacts = []
        for sibling in contact.next_siblings:
            if getattr(sibling, "name", None) == "h2":
                break
            if hasattr(sibling, "get_text"):
                contacts.append(sibling.get_text(" ", strip=True))
        if not re.search(r"\b[\w.+-]+@belspo\.be\b", " ".join(contacts)):
            return []
        paragraph = headings[1].find_next("p")
        match = re.match(r"BRUXELLES,\s*(\d{2}/\d{2}/\d{4})\s*-", paragraph.get_text(" ", strip=True) if paragraph else "")
        if not match:
            return []
        a = _article(source, headings[1].get_text(" ", strip=True), url, match[1], "detail:" + url)
        return [a] if a else []
    if source.parser_adapter == "bmlv_publication":
        # Legacy dc:date equals article:modified_time in the observed feed. A dateline
        # may describe the event, so accept only an explicit publication field.
        author = soup.select_one('meta[name="author"]')
        published = soup.select_one('meta[property="article:published_time"]')
        title = soup.select_one("#content > h2")
        if (urlsplit(url).path != "/cms/artikel.php" or author is None
                or author.get("content") != "Bundesministerium für Landesverteidigung"
                or published is None or title is None):
            return []
        a = _article(source, title.get_text(" ", strip=True), url, str(published.get("content", "")), "detail:" + url)
        return [a] if a and a.published_at else []
    return []


def public_round4_request(html: str, source: Source) -> tuple[str, dict[str, Any], dict[str, str]]:
    _scope(source, source.listing_url)
    soup = BeautifulSoup(html, "lxml")
    if source.parser_adapter == "dk_resilience_json":
        node = soup.select_one("[data-js-dynamic-list-module]")
        config = json.loads(str(node.get("data-js-dynamic-list-module", "{}"))) if node else {}
        if (config.get("currentPageId") != 1632 or config.get("dynamicListModuleId") != _MSSB_MODULE
                or config.get("locale") != "da" or config.get("dynamicListGlobalPageId") is not None):
            raise ValueError("Resilience public ministry listing contract changed")
        return ("https://mssb.dk/umbraco/api/DynamicListSearchApi/search",
                {"SearchTerm": "", "currentpageid": 1632, "ModuleId": _MSSB_MODULE,
                 "GlobalPageId": None, "Culture": "da", "DateFormat": "d", "Page": "1"}, {})
    if source.parser_adapter == "dk_environment_json":
        node = soup.select_one("script#__NEXT_DATA__")
        data = json.loads(node.get_text()) if node else {}
        props = data.get("props", {}).get("pageProps", {})
        page = props.get("content", {}).get("page", {})
        sections = page.get("properties", {}).get("pageSections", [])
        overview: dict[str, Any] = next((s["content"]["properties"] for s in sections
                         if s.get("documentType") == "contentPageOverview"), {})
        root = overview.get("rootFolder", {})
        if (root.get("key") != _MIM_ROOT or root.get("url") != SCOPES[source.parser_adapter][5]
                or props.get("content", {}).get("host") != "http://mim.local:3001"
                or data.get("runtimeConfig", {}).get("NEXT_PUBLIC_SEARCH_API_URL") != "https://search.mst.dk/"):
            raise ValueError("Environment public ministry root contract changed")
        return ("https://search.mst.dk/api/News/Search",
                {"key": _MIM_ROOT, "documentTypes": ["articlePage"], "subjects": [],
                 "categories": [{"name": None}], "takeAmount": 10, "skipAmount": 0,
                 "to": None, "from": None, "direction": "descending", "UserTextInputField": ""},
                {"Hostname": "http://mim.local:3001"})
    raise ValueError("No verified anonymous POST for this source")


async def _post(client: HttpClient, source: Source, url: str, payload: dict[str, Any],
                extra_headers: dict[str, str], stats: HttpStats) -> httpx.Response:
    _scope(source, url, api=True)
    if source.id == "dk_environment":
        if (payload.get("key") != _MIM_ROOT or payload.get("documentTypes") != ["articlePage"]
                or payload.get("takeAmount") != 10 or payload.get("skipAmount") != 0
                or extra_headers != {"Hostname": "http://mim.local:3001"}):
            raise ValueError("Environment POST changed ministry root or request scope")
    elif source.id == "dk_resilience":
        if (payload.get("currentpageid") != 1632 or payload.get("ModuleId") != _MSSB_MODULE
                or payload.get("GlobalPageId") is not None or payload.get("Page") != "1" or extra_headers):
            raise ValueError("Resilience POST changed ministry root or request scope")
    else:
        raise ValueError("No public listing POST for this adapter")
    if not client.obey_robots:
        raise ValueError("Round4 transport requires production robots enforcement")
    host = urlsplit(url).hostname or ""
    def guard(target: str) -> bool:
        return _safe_url(target, host)
    await client._ensure_robots(url, stats, source.tls_intermediate_bundle, source.user_agent, guard)
    limiter = client._host_limiters.setdefault(host, asyncio.Semaphore(client._per_host_limit))
    async with limiter:
        async with client._global_limiter:
            await client._pace(host)
            stats.request_count += 1
            async with client._client_for_bundle(source.tls_intermediate_bundle).stream(
                "POST", url, content=json.dumps(payload),
                headers={"Content-Type": "application/json", "Accept": "application/json", **extra_headers},
                follow_redirects=False,
            ) as response:
                stats.statuses.append(str(response.status_code))
                if response.is_redirect:
                    raise ValueError("Round4 public POST redirected; no redirect followed")
                if response.status_code in {429, 503}:
                    client._host_cooldowns[host] = max(client._host_cooldowns.get(host, 0.0),
                                                       time.monotonic() + _retry_delay(response))
                response.raise_for_status()
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > client.max_response_bytes:
                        raise ResponseTooLargeError("Round4 listing exceeds production byte limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
                stats.bytes_downloaded += len(body)
                return httpx.Response(response.status_code, headers=response.headers, content=body,
                                      request=response.request)


def parse_round4_feed(payload: bytes | str, source: Source, fetched_from: str) -> list[Article]:
    _scope(source, fetched_from, api=True)
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Missing Round4 public listing result")
    if source.parser_adapter == "dk_foreign_ritzau":
        pressroom = data.get("pressroom", {})
        publisher = pressroom.get("publisher", {}) if isinstance(pressroom, dict) else {}
        releases = data.get("release_listing", {})
        if (publisher.get("id") != 2012662 or publisher.get("name") != "Udenrigsministeriet"
                or publisher.get("website") not in {"http://um.dk/", "https://um.dk/"}
                or pressroom.get("slug") != "udenrigsministeriet" or publisher.get("masterPressroomInUse") is not False
                or not isinstance(releases, dict) or not isinstance(releases.get("releases"), list)):
            raise ValueError("Foreign Affairs publisher-scoped pressroom identity changed")
        result: dict[str, Article] = {}
        for row in releases["releases"]:
            if not isinstance(row, dict) or not isinstance(row.get("versions"), dict):
                continue
            version = row["versions"].get("da")
            if not isinstance(version, dict) or version.get("type") not in {"Nyhed", "Pressemeddelelse"}:
                continue
            route, title, raw = version.get("url"), version.get("title"), row.get("date")
            if not isinstance(route, str) or not isinstance(title, str) or not isinstance(raw, str):
                continue
            url = urljoin("https://via.ritzau.dk/", route)
            p = urlsplit(url)
            q = parse_qs(p.query)
            if (not _safe_url(url, "via.ritzau.dk") or not re.fullmatch(r"/release/\d+/[^/]+", p.path)
                    or p.path.split("/")[2] != str(row.get("id")) or q != {"publisherId": ["2012662"], "lang": ["da"]}
                    or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", raw)):
                continue
            article = _article(source, title, url, raw, "json:" + fetched_from)
            if article and article.published_at:
                result.setdefault(article.url, article)
        return list(result.values())
    rows = data.get("items") if source.parser_adapter == "dk_resilience_json" else data.get("searchResults")
    if not isinstance(rows, list):
        raise ValueError("Round4 public listing schema changed")
    output: dict[str, Article] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("title") if source.parser_adapter == "dk_resilience_json" else row.get("header")
        route = row.get("link") if source.parser_adapter == "dk_resilience_json" else row.get("url")
        raw = row.get("date")
        if source.parser_adapter == "dk_resilience_json" and row.get("contentType") != "articlePage":
            continue
        if not isinstance(title, str) or not isinstance(route, str) or not isinstance(raw, str):
            continue
        path = urlsplit(urljoin(source.listing_url, route)).path
        prefix = "/nyheder/nyhedsarkiv/" if source.id == "dk_resilience" else "/nyheder/pressemeddelelser/"
        if not path.startswith(prefix) or not re.match(r"\d{4}-\d{2}-\d{2}(?:T|$)", raw):
            continue
        a = _article(source, title, urljoin(source.listing_url, route), raw, "json:" + fetched_from)
        if a and a.published_at:
            output.setdefault(a.url, a)
    return list(output.values())


async def fetch_round4_details(html: str, source: Source, client: HttpClient,
                               stats: HttpStats | None = None) -> list[Article]:
    """Inspect at most three archive links; mixed publishers are rejected per detail.

    This bound does not imply archive completeness. Integration must expose truncation.
    """
    host = _scope(source, source.listing_url)
    if source.parser_adapter not in {"belspo_central_press", "bmlv_publication"} or not client.obey_robots:
        raise ValueError("Unsupported Round4 detail listing or robots policy")
    metrics = stats if stats is not None else HttpStats()
    soup = BeautifulSoup(html, "lxml")
    links = []
    for link in soup.select("a[href]"):
        url = urljoin(source.listing_url, str(link["href"]))
        path = urlsplit(url).path
        admitted = (bool(re.fullmatch(r"/belspo/organisation/press/[^/]+_fr\.stm", path))
                    if source.id == "be_science_policy" else path == "/cms/artikel.php")
        if admitted and _safe_url(url, host) and url not in links:
            links.append(url)
    result: dict[str, Article] = {}
    for url in links[:3]:
        # Fail visibly on inaccessible candidates rather than silently dropping failures.
        response = await client.get(url, stats=metrics, redirect_guard=lambda target: _safe_url(target, host))
        for article in parse_round4_detail(response.text, source, str(response.url)):
            result.setdefault(article.url, article)
    return list(result.values())


async def fetch_round4_listing(html: str, source: Source, client: HttpClient,
                               stats: HttpStats | None = None) -> dict[str, Any]:
    """One bounded frontend request; callers must surface possible truncation."""
    metrics = stats if stats is not None else HttpStats()
    if source.parser_adapter == "dk_foreign_ritzau":
        _scope(source, source.listing_url)
        soup = BeautifulSoup(html, "lxml")
        widget = soup.select_one("#embedded-pressroom-releases[data-publisher]")
        script = soup.select_one('script[src="https://via.ritzau.dk/embedded/prs_embedded.js"]')
        if widget is None or widget.get("data-publisher") != "2012662" or script is None or not client.obey_robots:
            raise ValueError("Foreign Affairs official public publisher embed changed")
        base = "https://via.ritzau.dk/public-website-api/pressroom/2012662"
        publisher_response = await client.get(base, stats=metrics, redirect_guard=lambda u: _safe_url(u, "via.ritzau.dk"))
        response = await client.get(base + "/releases/20/0", stats=metrics,
                                    redirect_guard=lambda u: _safe_url(u, "via.ritzau.dk"))
        payload_text = json.dumps({"pressroom": publisher_response.json(), "release_listing": response.json()})
        parse_round4_feed(payload_text, source, base + "/releases/20/0")
        return {"payload": payload_text, "fetched_from": base + "/releases/20/0", "truncated": True}
    url, payload, headers = public_round4_request(html, source)
    response = await _post(client, source, url, payload, headers, metrics)
    return {"payload": response.text, "fetched_from": url, "truncated": True}
