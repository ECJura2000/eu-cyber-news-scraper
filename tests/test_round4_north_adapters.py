"""Literal official publication evidence, publisher boundaries and transport policy."""
import asyncio
import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from eu_cyber_news_scraper import round4_north_adapters as n
from eu_cyber_news_scraper.http import HttpClient, HttpStats, ResponseTooLargeError, RobotsDeniedError
from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.scraper import scrape_source

FIX = Path(__file__).parent / "fixtures"
PROMOTED = ("cy_education", "cz_interior", "dk_environment", "dk_resilience", "dk_foreign_affairs", "be_science_policy")


def provenance(identifier):
    return json.loads((FIX / f"ministry_round4_{identifier}.provenance.json").read_text())


def source(identifier="dk_environment"):
    return Source(**provenance(identifier)["source_config"])


def fixture(identifier):
    return (FIX.parent.parent / provenance(identifier)["fixture_path"]).read_text()


@pytest.mark.parametrize("identifier", (*PROMOTED, "at_bmlv"))
def test_real_fixture_through_runtime_dispatch(identifier):
    p = provenance(identifier)
    text = fixture(identifier)
    assert hashlib.sha256(text.encode()).hexdigest() == p["fixture_sha256"]
    s = source(identifier)
    items = parse_listing(text, s, p["url"])
    assert len(items) == len(p["expected"])
    for a, expected in zip(items, p["expected"], strict=True):
        assert (a.title, a.url, a.published_date_local, a.date_confidence) == (
            expected["title"], expected["url"], expected["published_date_local"], "high")
        assert a.published_timezone == s.timezone and not a.date_conflict
    if identifier != "at_bmlv":
        assert items
    assert not s.schedule_enabled and not s.critical and type(s.detail_pages) is int and s.detail_pages == 0


@pytest.mark.parametrize("url", ["http://mim.dk/", "https://evil.dk/", "https://user@mim.dk/", "https://mim.dk:444/", "https://[broken", "https://mim.dk/%2e%2e/news"])
def test_origin_scope(url):
    with pytest.raises(ValueError):
        n.parse_round4_listing("", source(), url)


@pytest.mark.parametrize("field,value", [("id", "another"), ("country", "FR"), ("language", "en"), ("timezone", "UTC")])
def test_source_identity(field, value):
    s = replace(source(), **{field: value})
    with pytest.raises(ValueError):
        n.parse_round4_listing(fixture("dk_environment"), s, s.listing_url)


def test_cy_publication_registration_and_minister_scope():
    s = source("cy_education")
    soup = BeautifulSoup(fixture(s.id), "lxml")
    row = soup.select_one("tr")
    cells = row.find_all("td", recursive=False)
    cells[3].string = "01/01/2000"  # Event/notice date does not replace publication registration.
    assert n.parse_round4_listing(str(row), s, s.listing_url)[0].published_date_local == "2026-10-02"
    cells[6].string = "School department"
    assert not n.parse_round4_listing(str(row), s, s.listing_url)


def test_cz_missing_published_label_and_visible_title_alignment():
    s = source("cz_interior")
    text = fixture(s.id)
    assert not n.parse_round4_listing(text.replace("Publikováno: ", "Updated: "), s, s.listing_url)
    soup = BeautifulSoup(text, "lxml")
    for a in soup.select("article h3 a"):
        a.string = "Injected unverified title"
    assert not n.parse_round4_listing(str(soup), s, s.listing_url)
    assert not n.parse_round4_listing("<script>arbitraryJavaScript()</script>", s, s.listing_url)


@pytest.mark.parametrize("identifier,key", [("dk_environment", "searchResults"), ("dk_resilience", "items")])
def test_danish_no_update_dates_or_foreign_links(identifier, key):
    s = source(identifier)
    data = json.loads(fixture(identifier))
    row = data[key][0]
    row.pop("date")
    row["updated_time"] = row["created"] = "2026-10-03T00:00:00Z"
    assert not n.parse_round4_listing(json.dumps({key: [row]}), s, s.listing_url)
    row["date"] = "2026-10-02T00:00:00Z"
    row["url" if key == "searchResults" else "link"] = "https://evil.dk/nyheder/pressemeddelelser/2026/x"
    assert not n.parse_round4_listing(json.dumps({key: [row]}), s, s.listing_url)


def test_environment_local_naive_timestamp():
    s = source()
    row = json.loads(fixture(s.id))["searchResults"][0]
    row["date"] = "2026-09-29T11:41:43"
    a = n.parse_round4_listing(json.dumps({"searchResults": [row]}), s, s.listing_url)[0]
    assert a.published_at.isoformat() == "2026-09-29T09:41:43+00:00"
    assert a.published_at_raw == row["date"]


def test_foreign_ministry_publisher_not_provider_alias():
    s = source("dk_foreign_affairs")
    data = json.loads(fixture(s.id))
    data["pressroom"]["publisher"]["id"] = 999
    with pytest.raises(ValueError):
        n.parse_round4_listing(json.dumps(data), s, s.listing_url)
    data = json.loads(fixture(s.id))
    row = data["release_listing"]["releases"][0]
    row["versions"]["da"]["url"] = row["versions"]["da"]["url"].replace("publisherId=2012662", "publisherId=999")
    data["release_listing"]["releases"] = [row]
    assert not n.parse_round4_listing(json.dumps(data), s, s.listing_url)


def test_detail_bundle_and_attribution():
    s = source("be_science_policy")
    data = json.loads(fixture(s.id))
    data["source_url"] = "https://www.belspo.be/"
    with pytest.raises(ValueError):
        n.parse_round4_listing(json.dumps(data), s, s.listing_url)
    data = json.loads(fixture(s.id))
    data["details"][0]["html"] = data["details"][0]["html"].replace("@belspo.be", "@museum.example")
    assert len(n.parse_round4_listing(json.dumps(data), s, s.listing_url)) == 2
    data["details"][0]["url"] = "https://evil.be/press/test_fr.stm"
    with pytest.raises(ValueError):
        n.parse_round4_listing(json.dumps(data), s, s.listing_url)
    at = source("at_bmlv")
    assert not n.parse_round4_listing(fixture(at.id), at, at.listing_url)


@pytest.mark.parametrize("identifier", ["dk_environment", "dk_resilience"])
def test_frontend_request_scope(identifier):
    s = source(identifier)
    html = (FIX / f"ministry_round4_{identifier}_bootstrap.html").read_text()
    url, payload, _ = n.public_round4_request(html, s)
    assert payload
    with pytest.raises(ValueError):
        n.public_round4_request(html.replace(n._MIM_ROOT, "wrong").replace(n._MSSB_MODULE, "wrong"), s)
    with pytest.raises(ValueError):
        n.parse_round4_feed("{}", s, url + "?foreign=true")


@pytest.mark.parametrize("status,kind", [(302, ValueError), (429, httpx.HTTPStatusError), (503, httpx.HTTPStatusError), (200, ResponseTooLargeError)])
def test_post_transport_limits_redirects_retry_after(status, kind):
    async def check():
        s = source("dk_resilience")
        html = (FIX / "ministry_round4_dk_resilience_bootstrap.html").read_text()
        url, payload, headers = n.public_round4_request(html, s)
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            return httpx.Response(status, content=b"x" * 101,
                                  headers={"location": "https://evil.dk/", "retry-after": "120"})
        async with HttpClient(transport=httpx.MockTransport(handler), obey_robots=True, max_response_bytes=100) as client:
            with pytest.raises(kind):
                await n._post(client, s, url, payload, headers, HttpStats())
            if status in {429, 503}:
                assert client._host_cooldowns["mssb.dk"] > time.monotonic() + 100
    asyncio.run(check())


def test_post_requires_robots_and_obeys_denial():
    async def check():
        s = source("dk_resilience")
        url, payload, headers = n.public_round4_request((FIX / "ministry_round4_dk_resilience_bootstrap.html").read_text(), s)
        async with HttpClient(obey_robots=False) as client:
            with pytest.raises(ValueError):
                await n._post(client, s, url, payload, headers, HttpStats())
        calls = []
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, text="User-agent: *\nDisallow: /umbraco/\n")
        async with HttpClient(transport=httpx.MockTransport(handler), obey_robots=True) as client:
            with pytest.raises(RobotsDeniedError):
                await n._post(client, s, url, payload, headers, HttpStats())
        assert calls == ["/robots.txt"]
    asyncio.run(check())


def test_report_all_assigned_ids_preserves_manual_policy():
    report = json.loads((FIX / "ministry_round4_north.json").read_text())
    assert len(report["checks"]) == 12
    assert {c["canonical_id"] for c in report["checks"]} == set(report["assigned_ids"])
    for check in report["checks"]:
        assert check["attempts"] and check["next_action"]
        assert all(a["observed_at"].startswith("2026-10-03") for a in check["attempts"])
        assert check["negative_endpoint_failure_is_not_obsolete"]


@pytest.mark.parametrize("wrong_publisher", [False, True])
def test_foreign_affairs_actual_production_dispatch(wrong_publisher):
    """Exercise real dispatch, both public GETs and robots; no parser/helper replacement."""
    async def check():
        s = source("dk_foreign_affairs")
        bundle = json.loads(fixture(s.id))
        if wrong_publisher:
            bundle["pressroom"]["publisher"]["id"] = 999
        bootstrap = (FIX / "ministry_round4_dk_foreign_affairs_bootstrap.html").read_text()
        base = "https://via.ritzau.dk/public-website-api/pressroom/2012662"
        calls = []

        def handler(request):
            calls.append((request.method, str(request.url)))
            assert request.method == "GET"
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            if str(request.url) == s.listing_url:
                return httpx.Response(200, text=bootstrap, headers={"Content-Type": "text/html"})
            if str(request.url) == base:
                return httpx.Response(200, json=bundle["pressroom"])
            if str(request.url) == base + "/releases/20/0":
                return httpx.Response(200, json=bundle["release_listing"])
            pytest.fail(f"Unexpected production request: {request.url}")

        async with HttpClient(transport=httpx.MockTransport(handler), obey_robots=True) as client:
            result = await scrape_source(s, client,
                                         since=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                         until=datetime(2026, 10, 3, tzinfo=timezone.utc),
                                         observed_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
                                         include_unmatched=True, fetch_details=False)
        assert ("GET", s.listing_url) in calls
        assert ("GET", base) in calls and ("GET", base + "/releases/20/0") in calls
        assert ("GET", "https://um.dk/robots.txt") in calls
        assert ("GET", "https://via.ritzau.dk/robots.txt") in calls
        if wrong_publisher:
            assert not result.status.success and not result.articles
            assert "publisher-scoped pressroom identity changed" in result.status.error
        else:
            expected = provenance(s.id)["expected"]
            assert result.status.success
            assert result.status.raw_count == result.status.dated_count == len(expected) == 20
            assert "搜尋可能不完整" in result.status.warning
            assert [(a.title, a.url, a.published_date_local) for a in result.parsed_articles] == [
                (a["title"], a["url"], a["published_date_local"]) for a in expected]
            assert not s.schedule_enabled and not s.critical and s.detail_pages == 0
    asyncio.run(check())
