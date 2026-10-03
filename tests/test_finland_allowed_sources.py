"""Finnish allowed-source replay, publisher identity, dates and false-card rejection."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest
from bs4 import BeautifulSoup

from eu_cyber_news_scraper.config import load_sources_and_registry
from eu_cyber_news_scraper.finland_adapters import (
    FINLAND_FEED_ADAPTERS,
    FINLAND_LISTING_ADAPTERS,
    FINLAND_PUBLISHERS,
    parse_finland_feed,
    parse_finland_listing,
)
from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.organisation_registry import _validate_payload
from eu_cyber_news_scraper.robots import RobotsPolicy

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
IDS = ("fi_education_agency", "fi_judicial_administration_portal")


def module(identifier):
    return json.loads((ROOT / f"organisation_registry/{identifier}.json").read_text())


def source(identifier):
    return Source(**module(identifier)["sources"][0])


def provenance(identifier):
    return json.loads((FIXTURES / f"finland_{identifier}.provenance.json").read_text())


def replay(identifier, payload=None, config=None):
    config = config or source(identifier)
    feed = identifier == IDS[1]
    if payload is None:
        payload = (ROOT / provenance(identifier)["fixture_path"]).read_text()
    return (parse_finland_feed if feed else parse_finland_listing)(payload, config, config.listing_url)


def card(title="Opetushallituksen uusi tiedote", raw="11.9.2026", route="/fi/uutiset/2026/uutinen"):
    return f'''<main><div class="listing-item node--type-news">
    <div class="listing-item-bundle">Tiedote</div>
    <h3 class="listing-title"><a class="listing-title__link" href="{route}">{title}</a></h3>
    <div class="body"><div class="text-long">Tapahtuma 19.11.2026; uppdaterad 3.10.2026</div></div>
    <div class="listing-item-footer"><div class="node-post-date">{raw}</div></div>
    </div></main>'''


def rss(url="https://www.korkeinoikeus.fi/ajankohtaiset/tiedote/", title="Korkein oikeus tiedottaa",
        raw="Thu, 01 Oct 2026 23:30:00 +0000", updated="", build="Fri, 02 Oct 2026 23:00:00 +0000"):
    root = Element("rss", version="2.0")
    channel = SubElement(root, "channel")
    SubElement(channel, "lastBuildDate").text = build
    item = SubElement(channel, "item")
    for tag, text in [("title", title), ("link", url), ("pubDate", raw), ("updated", updated)]:
        SubElement(item, tag).text = text
    return tostring(root, encoding="utf-8")


@pytest.mark.parametrize("identifier,count", [(IDS[0], 20), (IDS[1], 30)])
def test_all_saved_records_have_exact_titles_urls_original_dates_and_publishers(identifier, count):
    articles = replay(identifier)
    expected = provenance(identifier)["expected"]
    assert len(articles) == len(expected) == count
    assert len({a.url for a in articles}) == count
    for article, row in zip(articles, expected, strict=True):
        assert article.title == row["title"].strip()
        assert article.url == row["url"]
        assert article.published_at_raw == row["raw_date"]
        assert article.published_at and article.published_date_local
        assert article.published_timezone == "Europe/Helsinki"
        assert article.date_confidence == "high" and not article.date_conflict
        assert article.date_precision == ("date" if identifier == IDS[0] else "datetime")
        assert article.date_source == ("source-selector" if identifier == IDS[0] else "feed-published")
        assert article.date_candidates[0].raw_value == row["raw_date"]
        assert article.discovered_by == [identifier]
        assert article.source_name == source(identifier).name_zh
        assert article.publisher_organisation == row.get(
            "publisher_organisation", "Opetushallitus (Finnish National Agency for Education)")


def test_saved_oph_detail_confirms_publication_not_event_or_updated_date():
    detail = provenance(IDS[0])["detail"]
    soup = BeautifulSoup((ROOT / detail["fixture_path"]).read_text(), "lxml")
    assert soup.select_one("main .node-post-date").get_text(strip=True) == "11.9.2026"
    assert replay(IDS[0])[0].published_date_local == "2026-09-11"
    assert replay(IDS[0])[0].published_at.isoformat() == "2026-09-10T21:00:00+00:00"
    assert "19.11.2026" in soup.get_text()


@pytest.mark.parametrize("identifier", IDS)
def test_registry_is_valid_separate_manual_only_and_preserves_date_health_requirements(identifier):
    data = module(identifier)
    _validate_payload(data)
    config = source(identifier)
    assert data["canonical_id"] == config.id == identifier
    assert not config.schedule_enabled and not config.critical
    assert config.detail_pages == 0 and config.max_pages == 1
    assert config.date_policy == "required" and not config.date_exception_reason
    assert config.freshness_days == data["health"]["maximum_age_days"] == 45
    assert "ministry" not in config.institution_type
    assert not data["history"]["predecessors"]
    assert not data["responsibility_by_topic"]
    assert config.id not in {"fi_education_culture", "fi_justice"}
    assert data["verification"]["parser_replay"]["raw_count"] == len(replay(identifier))


def test_exports_for_parent_dispatch_integration():
    assert FINLAND_LISTING_ADAPTERS == frozenset({"fi_oph_listing"})
    assert FINLAND_FEED_ADAPTERS == frozenset({"fi_oikeus_aggregate_rss"})
    assert source(IDS[0]).parser_adapter in FINLAND_LISTING_ADAPTERS
    assert source(IDS[1]).parser_adapter in FINLAND_FEED_ADAPTERS


@pytest.mark.parametrize("identifier", IDS)
def test_production_registry_loader_accepts_listing_and_article_domains(identifier):
    sources, registry = load_sources_and_registry()
    config = next(item for item in sources if item.id == identifier)
    assert registry.module_for_source(identifier) is not None
    assert not config.schedule_enabled
    assert config.listing_url == source(identifier).listing_url
    assert "oikeus.fi" in config.allow_domains if identifier == IDS[1] else "oph.fi" in config.allow_domains


@pytest.mark.parametrize("identifier", IDS)
def test_fixture_urls_status_timestamps_checksums_and_bounded_size(identifier):
    data = provenance(identifier)
    assert data["status"] == 200 and data["url"] == source(identifier).listing_url
    assert data["observed_at"] and data["timestamp_basis"]
    assert len(data["original_body_sha256"]) == 64
    for evidence in [data, data["robots"]] + ([data["detail"]] if "detail" in data else []):
        body = (ROOT / evidence["fixture_path"]).read_bytes()
        assert 0 < len(body) < 262144
        expected = evidence.get("fixture_sha256", evidence.get("body_sha256"))
        assert hashlib.sha256(body).hexdigest() == expected
        assert evidence["status"] == 200 and evidence["observed_at"]


@pytest.mark.parametrize("identifier", IDS)
def test_saved_robots_allows_configured_endpoint_and_oph_detail(identifier):
    data = provenance(identifier)
    policy = RobotsPolicy.parse((ROOT / data["robots"]["fixture_path"]).read_text())
    assert policy.allows(data["url"])
    if "detail" in data:
        assert policy.allows(data["detail"]["url"])


def test_live_official_identity_and_robots_validate_every_publisher_host():
    data = json.loads((FIXTURES / "finland_official_identity.provenance.json").read_text())
    responses = {r["url"]: r for r in data["responses"]}
    markers = {
        "www.oph.fi": "Opetushallitus", "www.oikeus.fi": "Oikeus.fi",
        "www.ulosottolaitos.fi": "Ulosottolaitos", "www.tuomioistuimet.fi": "Tuomioistuimet.fi",
        "www.korkeinoikeus.fi": "Korkein oikeus", "www.oikeusrekisterikeskus.fi": "Oikeusrekisterikeskus",
        "www.oikeuspalveluvirasto.fi": "Oikeuspalveluvirasto", "www.kho.fi": "Korkein hallinto-oikeus",
        "www.vakuutusoikeus.fi": "Vakuutusoikeus",
    }
    for host, marker in markers.items():
        home, robots = (responses[f"https://{host}{route}"] for route in ("/", "/robots.txt"))
        for evidence in (home, robots):
            assert evidence["status"] == 200 and evidence["observed_at"]
            assert urlsplit(evidence["final_url"]).hostname == host
            assert len(evidence["body_sha256"]) == 64
        assert marker in home["title"] and marker in home["identity_text"]
        assert hashlib.sha256(robots["body"].encode()).hexdigest() == robots["body_sha256"]
        policy = RobotsPolicy.parse(robots["body"])
        assert policy.allows(home["url"])
        for article in replay(IDS[1]):
            if urlsplit(article.url).hostname == host:
                assert policy.allows(article.url)
    articles = replay(IDS[1])
    assert {urlsplit(a.url).hostname for a in articles} == set(FINLAND_PUBLISHERS)
    assert len({a.publisher_organisation for a in articles}) == 7
    assert "multi-court" in FINLAND_PUBLISHERS["www.tuomioistuimet.fi"]


@pytest.mark.parametrize("title", ["Älylasit ja oppimisen tuki", "Utbildningsstyrelsens nya anvisningar",
                                  "Finnish education and AI policy"])
def test_multilingual_titles_are_preserved_without_changing_finnish_source_identity(title):
    article = replay(IDS[0], card(title=title))[0]
    assert article.title == title and article.language == "fi"
    article = replay(IDS[1], rss(title=title))[0]
    assert article.title == title and article.language == "fi"


@pytest.mark.parametrize("raw,utc", [
    ("11.9.2026", "2026-09-10T21:00:00+00:00"),
    ("1.1.2026", "2025-12-31T22:00:00+00:00"),
    ("29.3.2026", "2026-03-28T22:00:00+00:00"),
    ("30.3.2026", "2026-03-29T21:00:00+00:00"),
])
def test_oph_numeric_dates_use_helsinki_midnight_and_dst(raw, utc):
    article = replay(IDS[0], card(raw=raw))[0]
    assert article.published_at.isoformat() == utc
    assert article.published_at_raw == raw and article.date_precision == "date"


@pytest.mark.parametrize("raw", ["", "31.2.2026", "2026", "19.11.2026 updated 3.10.2026", "2026-09-11"])
def test_oph_requires_unambiguous_valid_original_post_date(raw):
    assert replay(IDS[0], card(raw=raw)) == []


@pytest.mark.parametrize("wrapper", ["aside", "nav", "footer", 'section class="related-news"',
                                    'section class="sidebar"'])
def test_oph_rejects_related_and_navigation_cards_inside_main(wrapper):
    tag = wrapper.split()[0]
    html = card().replace("<main>", f"<main><{wrapper}>").replace("</main>", f"</{tag}></main>")
    assert replay(IDS[0], html) == []


@pytest.mark.parametrize("old,new", [
    ("<main>", "<section>"), ("node--type-news", "node--type-event"),
    ("Tiedote", "Tapahtuma"), ("listing-title__link", "navigation-link"),
    ("node-post-date", "updated-date"), ("listing-item-footer", "event-details"),
])
def test_oph_rejects_false_cards_and_unrelated_dates(old, new):
    assert replay(IDS[0], card().replace(old, new)) == []


@pytest.mark.parametrize("route", ["https://www.oph.fi.evil.test/fi/uutiset/2026/story",
    "https://user@www.oph.fi/fi/uutiset/2026/story", "https://www.oph.fi:444/fi/uutiset/2026/story",
    "http://www.oph.fi/fi/uutiset/2026/story", "/fi/uutiset/2026/story?updated=2026-10-03",
    "/fi/uutiset/2026/story#date", "/fi/uutiset/2026/../2026/story",
    "/fi/uutiset/2026/%2e%2e/story", "/fi/tiedotteet", "/fi/tapahtumat/2026/story"])
def test_oph_rejects_wrong_publisher_or_non_article_routes(route):
    assert replay(IDS[0], card(route=route)) == []


@pytest.mark.parametrize("url", ["https://www.korkeinoikeus.fi.evil.test/ajankohtaiset/story/",
    "https://evil.test/ajankohtaiset/story/", "https://www.oikeus.fi/ajankohtaiset/story/",
    "https://oikeusministerio.fi/ajankohtaiset/story/", "https://user@www.kho.fi/ajankohtaiset/story/",
    "https://www.kho.fi:444/ajankohtaiset/story/", "http://www.kho.fi/ajankohtaiset/story/",
    "https://www.kho.fi/ajankohtaiset/story/?date=2026", "https://www.kho.fi/ajankohtaiset/story/#date",
    "https://www.kho.fi/ajankohtaiset/../story/", "https://www.kho.fi/ajankohtaiset/%2e%2e/story/",
    "https://www.kho.fi/yhteystiedot/", "//www.kho.fi/ajankohtaiset/story/"])
def test_aggregate_rejects_unvalidated_publishers_and_false_article_urls(url):
    assert replay(IDS[1], rss(url=url)) == []


def test_aggregate_uses_pubdate_not_channel_build_updated_or_date_in_title():
    article = replay(IDS[1], rss(title="Tuomio koskee tapahtumaa 10.5.2026",
                               updated="Sat, 03 Oct 2026 12:00:00 +0000"))[0]
    assert article.published_at.isoformat() == "2026-10-01T23:30:00+00:00"
    assert article.published_date_local == "2026-10-02"
    assert article.published_at_raw == "Thu, 01 Oct 2026 23:30:00 +0000"


@pytest.mark.parametrize("raw", ["", "invalid", "Thu, 01 Oct 2026 23:30:00", "31 Feb 2026 12:00:00 +0000"])
def test_aggregate_does_not_fall_back_from_missing_or_invalid_pubdate_to_updated(raw):
    assert replay(IDS[1], rss(raw=raw, updated="Sat, 03 Oct 2026 12:00:00 +0000")) == []


@pytest.mark.parametrize("payload", [b"<rss>", b"<html><p>challenge</p></html>", b"{}",
    b'<!DOCTYPE rss [<!ENTITY x "publisher">]><rss><channel/></rss>'])
def test_aggregate_rejects_invalid_rss_challenge_and_dtd(payload):
    with pytest.raises(ValueError):
        replay(IDS[1], payload)


@pytest.mark.parametrize("identifier", IDS)
def test_duplicate_records_emit_one_article(identifier):
    if identifier == IDS[0]:
        html = card()
        payload = html.replace("</main>", html.removeprefix("<main>"))
    else:
        text = rss().decode()
        item = text[text.index("<item>"):text.index("</item>") + len("</item>")]
        payload = text.replace("</channel>", item + "</channel>")
    assert len(replay(identifier, payload)) == 1


@pytest.mark.parametrize("identifier", IDS)
@pytest.mark.parametrize("field,value", [("id", "fi_justice"), ("country", "SE"),
                                         ("language", "sv"), ("timezone", "UTC")])
def test_adapters_cannot_be_reused_as_excluded_ministries_or_other_sources(identifier, field, value):
    with pytest.raises(ValueError, match="identity"):
        replay(identifier, config=replace(source(identifier), **{field: value}))


@pytest.mark.parametrize("url", ["https://www.oikeus.fi/feed/rss-feed?post_type=page",
    "https://www.oikeus.fi/feed/rss-feed?post_type=ajankohtaiset&post_type=page",
    "https://www.oikeus.fi/feed/rss-feed?post_type=ajankohtaiset&lang=en",
    "https://www.oikeus.fi/ajankohtaista/", "https://evil.test/feed/rss-feed?post_type=ajankohtaiset"])
def test_aggregate_cannot_parse_other_post_types_or_origins(url):
    with pytest.raises(ValueError):
        parse_finland_feed(rss(), source(IDS[1]), url)
