import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.parsers import parse_datetime, parse_listing
from eu_cyber_news_scraper.scraper import scrape_source
from eu_cyber_news_scraper.sitecore_public import ENDPOINT, NEWS_TEMPLATE, fetch_listing, search_scope

AREA = "847EE87D80774A00A5F802E885A86D16"
ROOT_ID = "EA7894D09F2947BEA8949CB1ECDC2728"
SOURCE = Source(id="pt_test", country="PT", name="Test Ministry", name_zh="測試部",
                institution_type="ministry", language="pt", homepage="https://portugal.gov.pt/",
                listing_url="https://portugal.gov.pt/pt/gc25/area-de-governo/test/noticias",
                allow_domains=("portugal.gov.pt", "edge-platform.sitecorecloud.io"),
                parser_adapter="sitecore_public", detail_pages=0, timezone="Europe/Lisbon")
BOOTSTRAP = ('i.sitecoreEdgeContextId=n.env.SITECORE_EDGE_CONTEXT_ID||"public-routing-test";'
             'i.sitecoreEdgeUrl=n.env.SITECORE_EDGE_URL||"https://edge-platform.sitecorecloud.io";')


def html(areas=None, script="/_next/static/chunks/pages/_app-test.js", template=NEWS_TEMPLATE):
    fields = {"data": {"datasource": {
        "SearchResultsByTemplate": {"jsonValue": [{"fields": {"Title": {"value": template}}}]},
        "SearchResultsByAreas": {"values": [{"id": value} for value in (areas if areas is not None else [AREA])]},
        "SearchResultsRootItem": {"jsonValue": [{"id": ROOT_ID}]},
    }}}
    data = {"props": {"pageProps": {"layoutData": {"sitecore": {"route": {
        "placeholders": {"main": [{"componentName": "SearchResults", "fields": fields}]}
    }}}}}}
    return f'<script id="__NEXT_DATA__">{json.dumps(data)}</script><script src="{script}"></script>'


def row():
    return {"id": "123", "template": {"id": NEWS_TEMPLATE},
            "url": {"path": "/pt/gc25/comunicacao/noticias/test"},
            "title": {"value": "Official cybersecurity announcement"}, "fallbackTitle": {"value": "Fallback"},
            "date": {"value": "20260923T140000Z"}, "summary": {"value": "<b>NIS2</b>"},
            "areas": {"jsonValue": [{"id": AREA, "fields": {"unused": "do not retain"}}]}}


class Client:
    def __init__(self, page=None, pages=None, script=BOOTSTRAP, error=None):
        self.page = html() if page is None else page
        self.pages = pages or [{"data": {"search": {"results": [row()], "total": 1,
                               "pageInfo": {"hasNext": False, "endCursor": ""}}}}]
        self.script = script
        self.error = error
        self.urls = []
        self.query_count = 0

    async def get(self, url, *, stats=None):
        self.urls.append(url)
        if url.startswith(ENDPOINT):
            query = parse_qs(urlsplit(url).query)["query"][0]
            assert AREA[:8] in query and 'name:"areas"' in query and NEWS_TEMPLATE[:8] in query
            assert "mutation" not in query
            if self.error:
                raise RuntimeError("sensitive routing: public-routing-test")
            data = self.pages[min(self.query_count, len(self.pages)-1)]
            self.query_count += 1
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
        content = self.script if "_app-" in url else self.page
        return httpx.Response(200, text=content, request=httpx.Request("GET", url))


def fetch(client, source=SOURCE):
    return asyncio.run(fetch_listing(client.page, source, client.get, client))


def test_public_query_projection_and_exact_scope():
    client = Client()
    data = fetch(client)
    assert data["scope"] == [AREA] and not data["truncated"]
    assert "public-routing-test" not in json.dumps(data)
    assert "unused" not in json.dumps(data)
    articles = parse_listing(json.dumps(data), SOURCE, SOURCE.listing_url)
    assert len(articles) == 1 and articles[0].published_date_local == "2026-09-23"
    assert articles[0].date_confidence == "high" and articles[0].summary == "NIS2"


def test_anonymous_adapter_integrates_with_production_source_status():
    result = asyncio.run(scrape_source(SOURCE, Client(), since=datetime(2026, 9, 1, tzinfo=timezone.utc),
                         until=datetime(2026, 10, 3, tzinfo=timezone.utc), include_unmatched=True, fetch_details=False))
    assert result.status.success and result.status.raw_count == result.status.dated_count == 1
    assert result.status.fetched_via == "public-sitecore"


@pytest.mark.parametrize("page", ["<main></main>", html(areas=[]), html(template="00000000000000000000000000000000")])
def test_no_sitewide_or_missing_query_configuration_fallback(page):
    with pytest.raises(ValueError):
        search_scope(page)


@pytest.mark.parametrize("source,page", [
    (replace(SOURCE, listing_url="https://evilportugal.gov.pt/news"), html()),
    (replace(SOURCE, listing_url="https://user@portugal.gov.pt/news"), html()),
    (replace(SOURCE, listing_url="https://portugal.gov.pt:8443/news"), html()),
    (SOURCE, html(script="https://evil.example/_next/static/chunks/pages/_app-test.js")),
    (SOURCE, html(script="http://portugal.gov.pt/_next/static/chunks/pages/_app-test.js")),
    (SOURCE, html(script="https://user@portugal.gov.pt/_next/static/chunks/pages/_app-test.js")),
    (SOURCE, html(script="https://portugal.gov.pt:8443/_next/static/chunks/pages/_app-test.js")),
    (SOURCE, html(script="/other-script.js")),
])
def test_frontend_origin_and_bootstrap_fail_closed(source, page):
    client = Client(page=page)
    with pytest.raises(ValueError):
        fetch(client, source)
    assert not client.urls


def test_changed_frontend_config_and_query_errors_are_not_authenticated():
    for client in [Client(script="changed"), Client(error=True), Client(pages=[{"errors": [{"message": "denied"}]}])]:
        with pytest.raises(ValueError) as error:
            fetch(client)
        assert "public-routing-test" not in str(error.value)


def test_bootstrap_is_shared_only_within_same_client():
    async def run():
        client = Client()
        await fetch_listing(client.page, SOURCE, client.get, client)
        await fetch_listing(client.page, SOURCE, client.get, client)
        return client
    client = asyncio.run(run())
    assert sum("_app-" in url for url in client.urls) == 1 and client.query_count == 2


def test_failed_bootstrap_can_recover_within_same_client():
    class RecoveringClient(Client):
        async def get(self, url, *, stats=None):
            if "_app-" in url and not hasattr(self, 'failed'):
                self.failed = True
                raise httpx.ConnectError('Temporary upstream failure')
            return await super().get(url, stats=stats)

    async def run():
        client = RecoveringClient()
        with pytest.raises(httpx.ConnectError):
            await fetch_listing(client.page, SOURCE, client.get, client)
        return await fetch_listing(client.page, SOURCE, client.get, client)

    assert asyncio.run(run())['articles'][0]['title'] == row()['title']['value']


def test_bounded_pagination_warns_and_repeated_cursor_fails():
    page = {"data": {"search": {"results": [row()], "total": 2,
            "pageInfo": {"hasNext": True, "endCursor": "cursor"}}}}
    data = fetch(Client(pages=[page]))
    assert data["truncated"] is True
    result = asyncio.run(scrape_source(SOURCE, Client(pages=[page]), since=datetime(2026, 9, 1, tzinfo=timezone.utc),
                         until=datetime(2026, 10, 3, tzinfo=timezone.utc), include_unmatched=True, fetch_details=False))
    assert "不完整" in result.status.warning
    with pytest.raises(ValueError, match="pagination"):
        fetch(Client(pages=[page]), replace(SOURCE, max_pages=2))
    complete = copy.deepcopy(page)
    complete["data"]["search"]["pageInfo"] = {"hasNext": False, "endCursor": ""}
    assert not fetch(Client(pages=[page, complete]), replace(SOURCE, max_pages=2))["truncated"]


@pytest.mark.parametrize("change", ["area", "template", "host"])
def test_items_from_other_ministry_or_template_or_host_are_rejected(change):
    data = fetch(Client())
    item = data["articles"][0]
    item.update({"area": {"areas": ["00000000000000000000000000000000"]},
                 "template": {"template": "00000000000000000000000000000000"},
                 "host": {"path": "https://evil.example/noticias/test"}}[change])
    assert parse_listing(json.dumps(data), SOURCE, SOURCE.listing_url) == []


def test_dates_and_listing_scope_cannot_be_guessed():
    data = fetch(Client())
    data["source_url"] = "https://portugal.gov.pt/other"
    with pytest.raises(ValueError, match="scope"):
        parse_listing(json.dumps(data), SOURCE, SOURCE.listing_url)
    data["source_url"] = SOURCE.listing_url
    data["articles"][0]["date"] = "00010101T000000Z"
    # Year 1 is a Sitecore unset-date sentinel, never a valid publication.
    with pytest.raises(ValueError, match="publication date"):
        parse_listing(json.dumps(data), SOURCE, SOURCE.listing_url)
    assert parse_datetime("20260230T000000Z") is None
    data["articles"][0]["date"] = "20260230T000000Z"
    with pytest.raises(ValueError, match="publication date"):
        parse_listing(json.dumps(data), SOURCE, SOURCE.listing_url)


@pytest.mark.parametrize("url", [
    ENDPOINT + "?sitecoreContextId=public-routing-test&query=test",
    "https://portugal.gov.pt/_next/static/chunks/pages/_app-test.js",
])
def test_public_routing_and_bootstrap_are_not_written_to_http_cache(tmp_path, url):
    from eu_cyber_news_scraper.http_cache import ResponseCache

    cache = ResponseCache(tmp_path)
    response = httpx.Response(200, text=BOOTSTRAP, headers={"etag": "test"}, request=httpx.Request("GET", url))
    cache.save(response, "test")
    assert cache.load(url, "test") is None
    assert cache.connection.execute("SELECT count(*) FROM responses").fetchone()[0] == 0
    cache.close()
