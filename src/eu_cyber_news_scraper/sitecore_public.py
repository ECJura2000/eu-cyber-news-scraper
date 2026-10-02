"""Read the anonymous, ministry-scoped content used by Portugal's public frontend.

No API key or Authorization header is used. The public tenant routing value is
discovered anew, kept in memory only, and omitted from returned diagnostics.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import UUID
from weakref import WeakKeyDictionary

import httpx
from bs4 import BeautifulSoup

from .models import Source

Get = Callable[[str], Awaitable[httpx.Response]]
ENDPOINT = "https://edge-platform.sitecorecloud.io/v1/content/api/graphql/v1"
NEWS_TEMPLATE = "DC3CC8F2100446C7827CCAD36919C735"
_BOOTSTRAPS: WeakKeyDictionary[Any, dict[str, asyncio.Task[str]]] = WeakKeyDictionary()


def guid(value: str) -> str:
    return UUID(value.strip("{}")).hex.upper()


def search_scope(html: str) -> tuple[str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("script#__NEXT_DATA__")
    if node is None:
        raise ValueError("Public news page has no server-provided query configuration")
    route = json.loads(node.get_text())["props"]["pageProps"]["layoutData"]["sitecore"]["route"]

    def components(value: Any) -> Any:
        if isinstance(value, dict):
            if value.get("componentName") == "SearchResults":
                yield value
            for child in value.values():
                yield from components(child)
        elif isinstance(value, list):
            for child in value:
                yield from components(child)

    for component in components(route.get("placeholders", {})):
        data = component["fields"]["data"]["datasource"]
        templates = data["SearchResultsByTemplate"]["jsonValue"]
        if not any(guid(item["fields"]["Title"]["value"]) == NEWS_TEMPLATE for item in templates):
            continue
        areas = [guid(item["id"]) for item in data.get("SearchResultsByAreas", {}).get("values", [])]
        if areas:
            root = data["SearchResultsRootItem"]["jsonValue"][0]["id"]
            return guid(root), areas
    raise ValueError("No attributable ministry area in public news query; site-wide news is not a substitute")


async def _routing_value(script_url: str, get: Get) -> str:
    response = await get(script_url)
    response.raise_for_status()
    match = re.search(r'i\.sitecoreEdgeContextId=n\.env\.SITECORE_EDGE_CONTEXT_ID\|\|"([A-Za-z0-9_-]+)"', response.text)
    host = re.search(r'i\.sitecoreEdgeUrl=n\.env\.SITECORE_EDGE_URL\|\|"([^"]+)"', response.text)
    if not match or not host or host.group(1) != "https://edge-platform.sitecorecloud.io":
        raise ValueError("Public frontend configuration changed; review required")
    return match.group(1)


async def fetch_listing(html: str, source: Source, get: Get, client: Any) -> dict[str, Any]:
    origin = urlsplit(source.listing_url)
    if (origin.scheme != "https" or origin.hostname not in {"portugal.gov.pt", "www.portugal.gov.pt"}
            or origin.username or origin.password or origin.port not in (None, 443)):
        raise ValueError("Unsupported public frontend origin")
    root, areas = search_scope(html)
    soup = BeautifulSoup(html, "html.parser")
    scripts = [urljoin(source.listing_url, str(item["src"])) for item in soup.select("script[src]")
               if re.search(r"/_next/static/chunks/pages/_app-[^/]+\.js", str(item["src"]))]
    if len(scripts) != 1:
        raise ValueError("Missing or untrusted public frontend bootstrap")
    bootstrap = urlsplit(scripts[0])
    if (bootstrap.hostname != origin.hostname or bootstrap.scheme != "https"
            or bootstrap.username or bootstrap.password or bootstrap.port not in (None, 443)):
        raise ValueError("Missing or untrusted public frontend bootstrap")
    cache = _BOOTSTRAPS.setdefault(client, {})
    task = cache.get(scripts[0])
    if task is None:
        task = asyncio.create_task(_routing_value(scripts[0], get))
        cache[scripts[0]] = task
    try:
        routing = await asyncio.shield(task)
    except BaseException:
        if task.done() and cache.get(scripts[0]) is task:
            del cache[scripts[0]]
        raise
    results = []
    cursor = ""
    has_next = False
    digests = []
    from hashlib import sha256

    for _page in range(source.max_pages):
        filters = [f'{{name:"_path",value:"{{{str(UUID(root)).upper()}}}",operator:EQ}}',
                   '{name:"_language",value:"pt",operator:EQ}',
                   f'{{name:"_templates",value:"{{{str(UUID(NEWS_TEMPLATE)).upper()}}}",operator:EQ}}',
                   '{OR:[' + ','.join(f'{{name:"areas",value:"{{{str(UUID(area)).upper()}}}",operator:CONTAINS}}'
                                      for area in areas) + ']}']
        after = ',after:' + json.dumps(cursor) if cursor else ""
        query = ('{search(where:{AND:[' + ','.join(filters) + ']},first:50' + after
                 + ',orderBy:{name:"cardDate",direction:DESC}){total pageInfo{endCursor hasNext} results{'
                 'id template{id} url{path} title:field(name:"CardTitle"){value} '
                 'fallbackTitle:field(name:"Title"){value} date:field(name:"CardDate"){value} '
                 'summary:field(name:"CardDescription"){value} areas:field(name:"Areas"){jsonValue}}}}')
        try:
            response = await get(ENDPOINT + '?' + urlencode({'sitecoreContextId': routing, 'query': query}))
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise ValueError("Public content query schema changed")
            search = payload["data"]["search"]
        except Exception:
            # URLs in transport exceptions contain the transient routing value.
            raise ValueError("Anonymous public content query failed; no authenticated fallback") from None
        digests.append(sha256(response.content).hexdigest())
        for row in search["results"]:
            values = row.get("areas", {}).get("jsonValue") or []
            results.append({"id": row["id"], "template": row.get("template", {}).get("id"),
                            "path": row["url"]["path"],
                            "title": (row.get("title") or {}).get("value") or (row.get("fallbackTitle") or {}).get("value"),
                            "date": (row.get("date") or {}).get("value"),
                            "summary": (row.get("summary") or {}).get("value"),
                            "areas": [guid(item["id"]) for item in values]})
        page_info = search["pageInfo"]
        has_next = bool(page_info["hasNext"])
        next_cursor = page_info.get("endCursor") or ""
        if not has_next:
            break
        if not next_cursor or next_cursor == cursor:
            raise ValueError("Public content pagination did not advance")
        cursor = next_cursor
    return {"source_url": source.listing_url, "scope": areas, "articles": results,
            "truncated": has_next, "response_sha256": digests, "public_endpoint": ENDPOINT}
