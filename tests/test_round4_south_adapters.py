"""Fresh official publication fixtures, publisher exclusions and transport boundaries."""
import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from lxml import etree

from eu_cyber_news_scraper import round4_south_adapters as adapters
from eu_cyber_news_scraper.http import HttpClient, RobotsDeniedError
from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS

FIX = Path(__file__).parent / "fixtures"
ROOT = FIX.parents[1]
IDS = ("es_economy", "it_civil_protection")
D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
M = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
ATOM = "{http://www.w3.org/2005/Atom}"


def proof(identifier):
    return json.loads((FIX / f"ministry_round4_{identifier}.provenance.json").read_text())


def source(identifier="es_economy"):
    config = proof(identifier)["source_config"]
    for key, value in Source.__dataclass_fields__.items():
        if isinstance(value.default, tuple) and key in config:
            config[key] = tuple(config[key])
    return Source(**config)


def payload(identifier="es_economy"):
    return (ROOT / proof(identifier)["fixture_path"]).read_bytes()


@pytest.mark.parametrize("identifier", IDS)
def test_exact_publisher_fixtures_and_live_proof(identifier):
    p = proof(identifier)
    s = source(identifier)
    raw = payload(identifier)
    assert hashlib.sha256(raw).hexdigest() == p["fixture_sha256"]
    assert 0 < p["raw_response_bytes"] < 128 * 1024
    articles = adapters.parse_round4_south_feed(raw, s, s.listing_url)
    assert len(articles) == len(p["expected"]) > 0
    for article, expected in zip(articles, p["expected"], strict=True):
        assert (article.title, article.url, article.published_date_local,
                article.published_at.isoformat(), article.date_confidence, article.published_at_raw) == (
                    expected["title"], expected["url"], expected["published_date_local"],
                    expected["published_at"], "high", expected["raw_date"])
        assert article.published_timezone == s.timezone and not article.date_conflict
    assert p["live_status"]["success"]
    assert p["live_status"]["raw_count"] == p["live_status"]["dated_count"] == len(articles)
    module = json.loads((ROOT / "organisation_registry" / f"{identifier}.json").read_text())
    assert module["verification"]["fixture_path"] == p["fixture_path"]
    assert module["filter"]["topics"] == list(OBSERVATION_TOPICS)
    assert module["responsibility_by_topic"] == {}
    assert not s.critical and not s.schedule_enabled and type(s.detail_pages) is int and s.detail_pages == 0
    assert s.feed_urls == (s.listing_url,)


@pytest.mark.parametrize("identifier", IDS)
def test_production_feed_dispatch_replays_genuine_payload(identifier):
    from eu_cyber_news_scraper.parsers import parse_feed

    s = source(identifier)
    articles = parse_feed(payload(identifier), s, s.feed_urls[0])
    assert len(articles) == proof(identifier)["live_status"]["raw_count"]
    assert all(a.published_at is not None and a.date_confidence == "high" for a in articles)


@pytest.mark.parametrize("changes", [{"id": "mt_youth"}, {"country": "HU"}, {"language": "en"},
                                     {"timezone": "UTC"}, {"parser_adapter": "unknown"},
                                     {"listing_url": "https://evil.example/"}])
def test_source_scope_cannot_be_reused(changes):
    with pytest.raises(ValueError):
        adapters.parse_round4_south_feed(payload(), replace(source(), **changes), source().listing_url)


@pytest.mark.parametrize("url", ["http://portal.mineco.gob.es/", "https://evil.example/",
                                 "https://user@portal.mineco.gob.es/", "https://portal.mineco.gob.es:444/",
                                 "https://[broken", adapters.ES_LISTING + "&$top=9999"])
def test_feed_request_scope_rejects(url):
    with pytest.raises(ValueError):
        adapters.parse_round4_south_feed(payload(), source(), url)


def es_tree():
    return etree.fromstring(payload())


def es_news_entry(root):
    return next(e for e in root.findall(ATOM + "entry")
                if e.find('.//' + D + "WssId").text == "205")


@pytest.mark.parametrize("field", ["FechaPublicacionSP", "FechaPublicacionCalculadaSP"])
def test_sharepoint_never_uses_modified_created_or_feed_updated(field):
    root = es_tree()
    e = es_news_entry(root)
    props = e.find(ATOM + "content/" + M + "properties")
    props.remove(props.find(D + field))
    for name in ("Modified", "Created", "FechaInicioSP"):
        etree.SubElement(props, D + name).text = "2026-10-03T00:00:00Z"
    raw = etree.tostring(root)
    assert len(adapters.parse_round4_south_feed(raw, source(), source().listing_url)) == 17


@pytest.mark.parametrize("route", ["https://evil.example/news", "//evil.example/news", "/es-es/comunicacion/Paginas/default.aspx",
                                   "/es-es/comunicacion/Paginas/../news.aspx", "/es-es/comunicacion/Paginas/%252e%252e.aspx",
                                   "/es-es/comunicacion/Paginas/news.aspx#fragment", "/es-es/comunicacion/Paginas/news.aspx?x=1"])
def test_sharepoint_real_file_routes_only(route):
    root = es_tree()
    es_news_entry(root).find('.//' + D + "FileRef").text = route
    assert len(adapters.parse_round4_south_feed(etree.tostring(root), source(), source().listing_url)) == 17


@pytest.mark.parametrize("field,value", [("Label", "Other publisher"), ("WssId", "209"),
                                        ("TermGuid", "wrong"), ("FechaPublicacionSP", "2026-09-99T00:00:00Z"),
                                        ("FechaPublicacionCalculadaSP", "2026-10-03"), ("TituloSP", "tiny")])
def test_sharepoint_published_channel_and_date_consistency(field, value):
    root = es_tree()
    es_news_entry(root).find('.//' + D + field).text = value
    assert len(adapters.parse_round4_south_feed(etree.tostring(root), source(), source().listing_url)) == 17


def test_sharepoint_navigation_layout_and_xml_external_entities():
    root = es_tree()
    e = es_news_entry(root)
    e.find('.//' + D + "PublishingPageLayout/" + D + "Url").text = "https://portal.mineco.gob.es/contact.aspx"
    assert len(adapters.parse_round4_south_feed(etree.tostring(root), source(), source().listing_url)) == 17
    with pytest.raises(ValueError, match="entities"):
        adapters.parse_round4_south_feed(b'<!DOCTYPE feed [<!ENTITY x SYSTEM "file:///etc/passwd">]><feed/>', source(), source().listing_url)
    for raw in (b"broken", b"<feed/>"):
        with pytest.raises(ValueError):
            adapters.parse_round4_south_feed(raw, source(), source().listing_url)


def dpc():
    return json.loads(payload("it_civil_protection"))


@pytest.mark.parametrize("mutation", ["no_publication", "foreign_subdomain", "map_type", "foreign_route", "null_relationships"])
def test_dpc_publisher_publication_and_news_types(mutation):
    data = dpc()
    row = data["result"]["data"]["node"]["relationships"]["field_primo_piano_contenuto"]
    if mutation == "no_publication":
        row.pop("field_data")
        row["changed"] = row["created"] = "2026-10-03T00:00:00Z"
    elif mutation == "foreign_subdomain":
        row["relationships"]["field_sottodominio"]["name"] = "Rischi"
    elif mutation == "map_type":
        row["__typename"] = "node__mappa"
    elif mutation == "foreign_route":
        row["fields"]["slug"] = "https://evil.example/notizia/story/"
    else:
        row["relationships"] = None
    s = source("it_civil_protection")
    assert len(adapters.parse_round4_south_feed(json.dumps(data), s, s.listing_url)) == 1


@pytest.mark.parametrize("raw", ["[]", "null", "{}", "broken", '{"componentChunkName":"other","path":"/it/"}'])
def test_dpc_schema_fail_closed(raw):
    s = source("it_civil_protection")
    with pytest.raises(ValueError):
        adapters.parse_round4_south_feed(raw, s, s.listing_url)


def test_dpc_publication_date_differs_from_event_signature_date():
    path = FIX / "ministry_round4_it_civil_protection_publication.html"
    soup = BeautifulSoup(path.read_text(), "lxml")
    assert soup.select_one(".category-top .data").get_text() == "30 settembre 2026"
    assert "Firmato a Roma il 29 settembre" in soup.get_text()
    s = source("it_civil_protection")
    articles = adapters.parse_round4_south_feed(payload(s.id), s, s.listing_url)
    assert articles[1].published_date_local == "2026-09-30"


def test_reforms_genuine_fixture_rejects_event_and_updated_time():
    row = next(c for c in json.loads((FIX / "ministry_round4_south.json").read_text())["checks"]
               if c["canonical_id"] == "it_institutional_reforms")
    html = (ROOT / row["fixture_path"]).read_text()
    assert "2026-06-16T06:56:38.823Z" in html and "10 giugno 2026" in html
    s = Source("it_institutional_reforms", "IT", "義大利制度改革", "Ministro", "central ministry", "it",
               "https://www.riformeistituzionali.gov.it/", "https://www.riformeistituzionali.gov.it/it/comunicazione/notizie/",
               timezone="Europe/Rome", parser_adapter="round4_it_reforms_detail",
               allow_domains=("www.riformeistituzionali.gov.it",))
    url = "https://www.riformeistituzionali.gov.it/it/comunicazione/notizie/il-ministro-casellati-al-forum-pa-2026/"
    assert adapters.parse_round4_reforms_detail(html, s, url) == []
    with pytest.raises(ValueError):
        adapters.parse_round4_reforms_detail(html, replace(s, id="it_defence"), url)


def test_all_seven_fresh_checks_and_evidence_hashes():
    report = json.loads((FIX / "ministry_round4_south.json").read_text())
    assert len(report["checks"]) == 7 and report["promotions_count"] == 2 and report["remaining_count"] == 5
    for row in report["checks"]:
        assert hashlib.sha256((ROOT / row["fixture_path"]).read_bytes()).hexdigest() == row["fixture_sha256"]
        assert row["attempts"] and row["next_action"]
        for attempt in row["attempts"]:
            observed = datetime.fromisoformat(attempt["observed_at"])
            assert observed.tzinfo is not None and observed.date().isoformat() == "2026-10-03"
            assert "http_status" in attempt or "error" in attempt
    for identifier in ("hu_defence", "hu_prime_minister"):
        evidence = json.loads((FIX / f"ministry_round4_{identifier}_evidence.json").read_text())
        assert all(row["ministry"] is None and row["column"] is None
                   for row in evidence["latest_global_news"][0]["data"])
    mt = json.loads((FIX / "ministry_round4_mt_youth_evidence.json").read_text())
    assert "Agenzija Zghazagh" in mt["title"]


def test_fetch_preserves_robots_and_same_origin_redirect_guard():
    async def run():
        requested = []

        def respond(request):
            requested.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /es-es/comunicacion/_api/")
            return httpx.Response(200, content=payload())

        async with HttpClient(obey_robots=True, min_interval=.001, transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(RobotsDeniedError):
                await adapters.fetch_round4_south_feed(client, source())
        assert len(requested) == 1 and requested[0].endswith("/robots.txt")

        def redirect(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /")
            return httpx.Response(302, headers={"Location": "https://evil.example/feed"})

        async with HttpClient(obey_robots=True, min_interval=.001, transport=httpx.MockTransport(redirect)) as client:
            with pytest.raises(httpx.InvalidURL, match="scope"):
                await adapters.fetch_round4_south_feed(client, source())
        async with HttpClient(obey_robots=False, min_interval=.001) as client:
            with pytest.raises(ValueError, match="robots"):
                await adapters.fetch_round4_south_feed(client, source())

    asyncio.run(run())
