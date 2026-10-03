"""Real ministry fixtures plus adversarial attribution and publication-date checks."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from eu_cyber_news_scraper.ministry_adapters import parse_ministry_feed, parse_ministry_listing
from eu_cyber_news_scraper.models import Source

FIXTURES = Path(__file__).parent / "fixtures"
ADAPTERS = {
    "bg_defence": "bg_defence_onclick",
    "bg_labour": "bg_labour_english_dates",
    "bg_justice": "bg_justice_json",
    "it_defence": "it_defence_json",
}


def source(identifier):
    provenance = json.loads((FIXTURES / f"ministry_round3_{identifier}_adapter.provenance.json").read_text())
    url = provenance["url"]
    italy = identifier.startswith("it_")
    return Source(id=identifier, country="IT" if italy else "BG", name_zh=identifier, name=identifier,
                  institution_type="ministry", language="it" if italy else "bg", homepage=url,
                  listing_url=url, timezone="Europe/Rome" if italy else "Europe/Sofia",
                  parser_adapter=ADAPTERS[identifier], schedule_enabled=False, detail_pages=0)


def replay(identifier, payload=None, config=None):
    config = config or source(identifier)
    if payload is None:
        suffix = "json" if identifier in {"bg_justice", "it_defence"} else "html"
        payload = (FIXTURES / f"ministry_round3_{identifier}_adapter.{suffix}").read_bytes()
    parser = parse_ministry_feed if identifier in {"bg_justice", "it_defence"} else parse_ministry_listing
    return parser(payload if parser is parse_ministry_feed else payload.decode(), config, config.listing_url)


@pytest.mark.parametrize("identifier", ADAPTERS)
def test_exact_real_fixture_fields_and_dates(identifier):
    expected = json.loads((FIXTURES / f"ministry_round3_{identifier}_adapter.provenance.json").read_text())
    articles = replay(identifier)
    assert len(articles) == len(expected["expected_after_adapter"])
    for article, row in zip(articles, expected["expected_after_adapter"], strict=True):
        assert article.title == row["title"].strip()
        assert article.url == row["url"]
        assert article.published_date_local == row["published_date_local"]
        assert article.published_at_raw == row["raw_date"]
        assert article.published_at and article.date_confidence == "high" and not article.date_conflict
        assert article.language == ("it" if identifier.startswith("it_") else "bg")
        assert article.date_candidates[0].raw_value == row["raw_date"]


@pytest.mark.parametrize("identifier", ADAPTERS)
def test_adapter_cannot_be_reused_as_other_ministry(identifier):
    with pytest.raises(ValueError, match="identity"):
        replay(identifier, config=replace(source(identifier), id="other_ministry"))


@pytest.mark.parametrize("identifier", ADAPTERS)
def test_adapter_rejects_unattributable_fetch_origin(identifier):
    with pytest.raises(ValueError, match="publisher"):
        replay(identifier, config=replace(source(identifier), listing_url="https://official.example.invalid/news"))


def test_justice_naive_timestamp_is_ministry_local_time():
    article = replay("bg_justice")[0]
    assert article.published_at.isoformat() == "2026-10-01T02:23:00+00:00"
    assert article.published_timezone == "Europe/Sofia"


def test_italian_midnight_preserves_local_publication_date():
    article = replay("it_defence")[0]
    assert article.published_at.isoformat() == "2026-10-01T22:00:00+00:00"
    assert article.date_precision == "date"


def test_labour_english_month_does_not_change_article_language():
    article = replay("bg_labour")[0]
    assert article.published_at.isoformat() == "2026-10-01T21:00:00+00:00"
    assert article.language == "bg" and article.date_precision == "date"


@pytest.mark.parametrize("route", ["https://evil.example/a", "//evil.example/a", "javascript:alert(1)",
                                   "/primopiano/../foreign/123.html", "/primopiano/%2e%2e/foreign/123.html",
                                   "https://user:secret@www.difesa.it/primopiano/story/123.html",
                                   "/primopiano/story/123.html?auth=token", "/primopiano/story/123.html#date"])
def test_json_rejects_external_or_malformed_article_routes(route):
    row = json.loads((FIXTURES / "ministry_round3_it_defence_adapter.json").read_text())[0]
    row["url"] = route
    assert replay("it_defence", json.dumps([row]).encode()) == []


@pytest.mark.parametrize("payload", [b"{", b"{}", b'"string"'])
def test_malformed_json_fails_explicitly(payload):
    with pytest.raises(ValueError, match="JSON feed"):
        replay("it_defence", payload)


def test_wrong_justice_block_cannot_look_like_ministry_news():
    with pytest.raises(ValueError, match="scope"):
        replay("bg_justice", config=replace(source("bg_justice"), listing_url=source("bg_justice").listing_url.replace("blockId=5", "blockId=6")))


def test_missing_or_conflicting_json_dates_remain_undated():
    row = json.loads((FIXTURES / "ministry_round3_it_defence_adapter.json").read_text())[0]
    row["sdata"] = "01 ott 2026"
    article = replay("it_defence", json.dumps([row]).encode())[0]
    assert article.published_at is None
    row["contentitemdata"] = None
    article = replay("it_defence", json.dumps([row]).encode())[0]
    assert article.published_at is None


def test_justice_does_not_infer_dates_from_article_body():
    row = json.loads((FIXTURES / "ministry_round3_bg_justice_adapter.json").read_text())[0]
    row["date"] = "tomorrow"
    article = replay("bg_justice", json.dumps([row]).encode())[0]
    assert article.published_at is None


def test_onclick_is_literal_mapping_not_javascript_execution():
    fixture = (FIXTURES / "ministry_round3_bg_defence_adapter.html").read_text()
    hostile = fixture.replace("location.href='/news", "alert('bad');location.href='/news")
    assert replay("bg_defence", hostile.encode()) == []


def test_labour_does_not_infer_date_from_title_or_summary():
    fixture = (FIXTURES / "ministry_round3_bg_labour_adapter.html").read_text()
    fixture = fixture.replace("Oct 02, 2026", "tomorrow")
    articles = replay("bg_labour", fixture.encode())
    assert len(articles) == 4 and articles[0].published_at is None
    assert all(article.published_at for article in articles[1:])


def test_labour_scope_also_accepts_an_explicit_bulgarian_month():
    fixture = (FIXTURES / "ministry_round3_bg_labour_adapter.html").read_text()
    fixture = fixture.replace("Oct 02, 2026", "2 октомври 2026")
    article = replay("bg_labour", fixture.encode())[0]
    assert article.language == "bg" and article.published_date_local == "2026-10-02"
    assert article.published_at_raw == "2 октомври 2026"


@pytest.mark.parametrize("identifier", ADAPTERS)
def test_shared_production_dispatch_matches_ministry_adapter(identifier):
    from eu_cyber_news_scraper.parsers import parse_feed, parse_listing

    config = source(identifier)
    suffix = "json" if identifier in {"bg_justice", "it_defence"} else "html"
    payload = (FIXTURES / f"ministry_round3_{identifier}_adapter.{suffix}").read_bytes()
    actual = parse_feed(payload, config, config.listing_url) if suffix == "json" else parse_listing(
        payload.decode(), config, config.listing_url,
    )
    expected = replay(identifier)
    assert [(a.title, a.url, a.published_date_local, a.published_at_raw) for a in actual] == [
        (a.title, a.url, a.published_date_local, a.published_at_raw) for a in expected
    ]
