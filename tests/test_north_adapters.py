"""Genuine Danish publication fixtures and bounded anonymous transport policy."""
import asyncio
import base64
import hashlib
import json
import time
from dataclasses import replace
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
from bs4 import BeautifulSoup

from eu_cyber_news_scraper import north_adapters as n
from eu_cyber_news_scraper.http import HttpClient, HttpStats, ResponseTooLargeError, RobotsDeniedError
from eu_cyber_news_scraper.models import Source

FIX = Path(__file__).parent / "fixtures"
IDS = ("dk_climate", "dk_business", "dk_nature", "dk_taxation", "dk_employment")


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


def source(i="dk_climate"):
    config = json.loads((FIX / f"ministry_{i}.provenance.json").read_text())["source_config"]
    for key, value in Source.__dataclass_fields__.items():
        if isinstance(value.default, tuple) and key in config:
            config[key] = tuple(config[key])
    return Source(**config)


def fixture(i):
    ext = "html" if i == "dk_employment" else "json"
    return (FIX / f"ministry_{i}.{ext}").read_text()


def bootstrap(i="dk_climate"):
    return (FIX / f"north_{i}_bootstrap.html").read_text()


@pytest.mark.parametrize("i", IDS)
def test_genuine_fixture_and_live_proof(i):
    s = source(i)
    text = fixture(i)
    p = json.loads((FIX / f"ministry_{i}.provenance.json").read_text())
    assert hashlib.sha256(text.encode()).hexdigest() == p["fixture_sha256"]
    articles = n.parse_north_listing(text, s, s.listing_url)
    assert len(articles) == len(p["expected"]) > 0
    for a, expected in zip(articles, p["expected"], strict=True):
        assert (a.title, a.url, a.published_date_local, a.date_confidence) == (
            expected["title"], expected["url"], expected["published_date_local"], "high")
        assert not a.date_conflict
    assert p["live_status"]["success"]
    assert p["live_status"]["raw_count"] == p["live_status"]["dated_count"] > 0
    assert not s.schedule_enabled and not s.critical
    assert type(s.detail_pages) is int and s.detail_pages == 0


@pytest.mark.parametrize("url", ["http://kefm.dk/", "https://evil.dk/", "https://user@kefm.dk/",
                                 "https://kefm.dk:444/", "https://[broken"])
def test_origin_rejects(url):
    assert not n._origin(source(), url)
    with pytest.raises(ValueError):
        n.parse_north_listing("", source(), url)


def test_origin_country_id_and_direct_html():
    assert not n._origin(replace(source(), country="FR"), source().listing_url)
    assert not n._origin(replace(source(), id="unknown"), source().listing_url)
    data = json.loads(fixture("dk_climate"))
    assert n.parse_north_listing(data["value"]["page"], source(), source().listing_url)
    assert n.parse_north_listing(bootstrap("dk_taxation"), source("dk_taxation"), source("dk_taxation").listing_url) == []
    with pytest.raises(ValueError):
        n.parse_north_listing("", replace(source(), parser_adapter="unknown"), source().listing_url)


@pytest.mark.parametrize("payload", ["not JSON", "[]", "{}", '{"responses":{}}',
                                    '{"success":false}', '{"success":true,"value":{}}',
                                    '{"responses":[null]}'])
def test_invalid_gobasic(payload):
    with pytest.raises(ValueError):
        n.parse_north_feed(payload, source(), source().listing_url)


def test_wrong_adapter_and_next_schema():
    with pytest.raises(ValueError):
        n.parse_north_feed("[]", replace(source(), parser_adapter="unknown"), source().listing_url)
    with pytest.raises(ValueError):
        n.parse_north_feed("{}", source("dk_taxation"), source("dk_taxation").listing_url)
    with pytest.raises(ValueError):
        n.parse_north_feed("{}", replace(source("dk_employment"), parser_adapter="north_gobasic"), source("dk_employment").listing_url)
    with pytest.raises(ValueError):
        n.parse_north_feed("[]", source(), "https://foreign.dk/")


def test_gobasic_no_guessed_dates_and_rejected_cards():
    s = source()
    data = json.loads(fixture(s.id))
    soup = BeautifulSoup(data["value"]["page"], "lxml")
    nodes = soup.select("div.item[data-url]")
    first = str(nodes[0])
    nodes[0].select_one("span.date").decompose()
    nodes[1].select_one(".heading").decompose()
    nodes[2]["data-url"] = "https://evil.dk/news"
    nodes[3].select_one(".heading").string = "tiny"
    nodes[4].select_one(".heading a")["href"] = nodes[4]["data-url"] = "https://www.kefm.dk/contact"
    data["value"]["page"] = str(soup) + first + first
    articles = n.parse_north_feed(json.dumps(data), s, s.listing_url)
    assert articles[0].published_at is None and not articles[0].date_confidence
    assert len({a.url for a in articles}) == len(articles)
    data["value"]["page"] = '<div class="item" data-url="/test"><h3 class="heading"><a href="/test">tiny</a></h3></div>'
    assert n.parse_north_feed(json.dumps(data), s, s.listing_url) == []
    data["value"]["page"] = first.replace("Bredt flertal har stemt for akutplanen for elnettet", "tiny")
    assert n.parse_north_feed(json.dumps(data), s, s.listing_url) == []


@pytest.mark.parametrize("field,value", [("parentGId", "bad"), ("parentGId", "00000000-0000-0000-0000-000000000000"),
                                        ("siteName", "other"), ("culture", "en"), ("domainName", "https://evil.dk/"),
                                        ("types", "Pressemeddelelser"), ("types", []), ("url", None), ("title", "tiny"),
                                        ("url", "https://svmn.dk/navigation")])
def test_next_publisher_scope(field, value):
    s = source("dk_taxation")
    row = json.loads(fixture(s.id))[0]
    row[field] = value
    assert n.parse_north_feed(json.dumps([row, None]), s, s.listing_url) == []


def test_next_publication_only_and_duplicates():
    s = source("dk_taxation")
    row = json.loads(fixture(s.id))[0]
    row.pop("date")
    row["createDate"] = row["updateDate"] = "2026-10-01T00:00:00Z"
    articles = n.parse_north_feed(json.dumps({"articles": [row, row]}), s, s.listing_url)
    assert len(articles) == 1 and articles[0].published_at is None and not articles[0].date_confidence


def test_ankiro_security_missing_date():
    s = source("dk_employment")
    soup = BeautifulSoup(fixture(s.id), "lxml")
    node = soup.select_one("li")
    original = str(node)
    node.select_one("span.search-module__list-module__result-tags").decompose()
    assert n.parse_north_listing(str(node), s, s.listing_url)[0].published_at is None
    assert len(n.parse_north_listing(original * 2, s, s.listing_url)) == 1
    for href in ["https://evil.dk/Rest/bm.dk/Redir", "https://[broken", "https://bm.ankiro.dk/Rest/bm.dk/Redir?" +
                 urlencode([("url", "https://bm.dk/nyheder/nyheder/2026/x"), ("url", "https://evil.dk/")])]:
        node.a["href"] = href
        assert n.parse_north_listing(str(node), s, s.listing_url) == []
    node = BeautifulSoup(original, "lxml").select_one("li")
    node.h3.string = "tiny"
    assert n.parse_north_listing(str(node), s, s.listing_url) == []
    with pytest.raises(ValueError):
        n._ankiro_html("", source(), source().listing_url)


@pytest.mark.parametrize("i", IDS[:4])
def test_published_request(i):
    s = source(i)
    url, payload, ctype = n.public_listing_request(bootstrap(i), s)
    assert n._origin(s, url)
    if i == "dk_taxation":
        assert payload["parentGId"].replace("-", "") == n._NEXT_CATALOG
        assert payload["sort"] == "date" and payload["limit"] == 25
        with pytest.raises(ValueError):
            n.public_listing_request(bootstrap(i), s, 2)
    else:
        assert payload["method"] == "GetPage" and ctype.startswith("versus/callback")


def test_bootstrap_rejected_and_modern_unenrolled_contract():
    for s, html, page in [(source(), "", 1), (source(), "", 0), (source("dk_employment"), "", 1),
                          (source("dk_taxation"), "{}", 1), (replace(source(), id="dk_taxation"), "", 1)]:
        with pytest.raises(ValueError):
            n.public_listing_request(html, s, page)
    html = bootstrap()
    assert "itemlist" in html
    with pytest.raises(ValueError):
        n.public_listing_request(html.replace(n._GENERATOR, "unknown"), source())
    config = {"options": {"specification": {"siteSearch": False, "filter": {"t": ["NewsPage"], "rf": ["public-root"]}}}}
    s = replace(source(), id="dk_children", listing_url="https://baebm.dk/nyheder/nyhedsarkiv")
    def markup():
        node = BeautifulSoup('<div class="archive-search-result dynamic-list"></div>', "lxml").div
        node["data-config"] = json.dumps(config)
        return str(node)
    assert n.public_listing_request(markup(), s)[0] == "https://baebm.dk/gbapi/search/getPage"
    with pytest.raises(ValueError):
        n.public_listing_request(markup() + '<input name="__RequestVerificationToken" value="not-used">', s)
    config["options"]["endpoint"] = "unknown"
    with pytest.raises(ValueError):
        n.public_listing_request(markup(), s)
    # Anonymous child contract remains HTTP 400 in live evidence; not a promoted source.
    report = json.loads((FIX / "ministry_round3_north.json").read_text())
    assert next(c for c in report["checks"] if c["canonical_id"] == "dk_children")["result"] == "blocked"
    soup = BeautifulSoup(html, "lxml")
    for node in soup.select("script"):
        if "itemlist" not in node.get_text():
            continue
        text = node.get_text()
        import re
        match = re.search(r"application\.script\.register\(\s*'itemlist'\s*,", text)
        if not match:
            continue
        cfg, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        cfg["context"] = base64.b64encode(json.dumps({"siteSearch": True, "filter": {"t": ["NewsPage"]}}).encode()).decode()
        node.string = "application.script.register('itemlist'," + json.dumps(cfg) + ");"
    with pytest.raises(ValueError):
        n.public_listing_request(str(soup), source())


@pytest.mark.parametrize("status", [200, 302, 401, 403, 429, 503])
@run_async
async def test_post_policy_and_cooldown(status):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        assert request.method == "POST" and "authorization" not in request.headers
        return httpx.Response(status, headers={"Location": "https://evil.dk/private", "Retry-After": "120"},
                              content=b'{"success":true,"value":{"page":"","lastPage":true}}')
    async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler), max_retry_wait=1) as client:
        s = source()
        stats = HttpStats()
        url, payload, ctype = n.public_listing_request(bootstrap(), s)
        before = time.monotonic()
        if status == 200:
            result = await n._post_public_listing(client, s, url, payload, ctype, stats)
            assert stats.bytes_downloaded >= len(result.content)
        else:
            with pytest.raises(ValueError if status == 302 else httpx.HTTPStatusError):
                await n._post_public_listing(client, s, url, payload, ctype, stats)
        assert sum(r.method == "POST" for r in requests) == 1
        assert all(r.url.host == "www.kefm.dk" for r in requests)
        assert str(status) in stats.statuses
        if status in {429, 503}:
            assert client._host_cooldowns["www.kefm.dk"] >= before + 119
            from eu_cyber_news_scraper.http import RetryDeferredError
            with pytest.raises(RetryDeferredError):
                await n._post_public_listing(client, s, url, payload, ctype, stats)
            assert sum(r.method == "POST" for r in requests) == 1


@run_async
async def test_post_limits_robots_and_guards():
    s = source()
    url, payload, ctype = n.public_listing_request(bootstrap(), s)
    for obey, target, body in [(False, url, payload), (True, "https://evil.dk/api", payload),
                               (True, "https://www.kefm.dk/delete", {})]:
        async with HttpClient(obey_robots=obey) as client:
            with pytest.raises(ValueError):
                await n._post_public_listing(client, s, target, body, ctype, HttpStats())
    seen = []
    def blocked(req):
        seen.append(req)
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    async with HttpClient(obey_robots=True, transport=httpx.MockTransport(blocked)) as client:
        with pytest.raises(RobotsDeniedError):
            await n._post_public_listing(client, s, url, payload, ctype, HttpStats())
        assert len(seen) == 1 and seen[0].method == "GET"
    def oversized(req):
        return httpx.Response(200, content=b"User-agent: *\nAllow: /\n" if req.method == "GET" else b"x" * 100)
    async with HttpClient(obey_robots=True, transport=httpx.MockTransport(oversized), max_response_bytes=40) as client:
        with pytest.raises(ResponseTooLargeError):
            await n._post_public_listing(client, s, url, payload, ctype, HttpStats())


@pytest.mark.parametrize("i", IDS[:4])
@run_async
async def test_fetch_production_transport(i):
    s = replace(source(i), max_pages=3, user_agent="North-test")
    body = fixture(i).encode()
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        assert req.headers["User-Agent"] == "North-test"
        return httpx.Response(200, content=body)
    async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
        data = await n.fetch_north_listing(bootstrap(i), s, client)
        assert data["response_sha256"][0] == hashlib.sha256(body).hexdigest()
        assert n.parse_north_feed(json.dumps(data), s, s.listing_url)
        if i != "dk_taxation":
            assert len(data["responses"]) == 3


@pytest.mark.parametrize("i,response", [("dk_taxation", {}), ("dk_climate", []), ("dk_climate", {"value": []})])
@run_async
async def test_fetch_changed_schema(i, response):
    def handler(req):
        return httpx.Response(200, text="User-agent: *\nAllow: /\n") if req.method == "GET" else httpx.Response(200, json=response)
    async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await n.fetch_north_listing(bootstrap(i), source(i), client)


@run_async
async def test_fetch_last_page_and_child_public_headers():
    config = {"options": {"specification": {"siteSearch": False, "filter": {"t": ["NewsPage"], "rf": ["public-root"]}}}}
    soup = BeautifulSoup('<div class="archive-search-result dynamic-list"></div>', "lxml")
    soup.div["data-config"] = json.dumps(config)
    s = replace(source(), id="dk_children", listing_url="https://baebm.dk/nyheder/nyhedsarkiv", max_pages=3)
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        assert req.headers["gp_currentpage"] == s.listing_url
        return httpx.Response(200, json={"success": True, "value": {"page": "", "lastPage": True}})
    async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
        data = await n.fetch_north_listing(str(soup), s, client, HttpStats())
        assert not data["truncated"] and len(data["responses"]) == 1
