"""Actual SI central-ministry roster and genuine live-parser regressions."""
import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from eu_cyber_news_scraper.ministry_inventory import validate_country
from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_feed, parse_listing
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS

ROOT = Path(__file__).resolve().parents[1]
COUNTRY = "SI"
PREFIX = "si"
EXPECTED_COUNT = 16

def inventory():
    return json.loads((ROOT / "ministry_inventory" / f"{COUNTRY}.json").read_text())

def new_modules():
    return [
        json.loads(p.read_text())
        for p in sorted((ROOT / "organisation_registry").glob(f"{PREFIX}_*.json"))
        if json.loads(p.read_text()).get("verification", {}).get("schedule_batch") == "eu27_central_ministries"
    ]

def test_official_roster_and_source_identity(tmp_path):
    payload = inventory()
    isolated = tmp_path / "registry"
    isolated.mkdir()
    for path in (ROOT / "organisation_registry").glob(f"{PREFIX}_*.json"):
        shutil.copyfile(path, isolated / path.name)
    registry = load_organisation_registry(builtin_dir=isolated, external_dir=tmp_path / "external")
    assert not registry.errors
    validate_country(payload, registry, today=date(2026, 10, 2))
    assert payload["roster_complete"] is True
    assert len(payload["ministries"]) == EXPECTED_COUNT
    assert any(m["kind"] == "government_head_office" for m in payload["ministries"])
    expected = {sid for m in payload["ministries"] if m["status"] == "manual_verified" for sid in m["source_ids"]}
    assert {s["id"] for m in new_modules() for s in m["sources"]} == expected
    for m in payload["ministries"]:
        if m["status"] in {"blocked", "parser_pending", "no_news_endpoint", "needs_review"}:
            assert m["source_ids"] == []
    roster = ROOT / "tests" / "fixtures" / f"ministry_{PREFIX}_roster.html"
    provenance = json.loads(roster.with_suffix(".provenance.json").read_text())
    assert hashlib.sha256(roster.read_bytes()).hexdigest() == provenance["sha256"]
    assert provenance["url"] in payload["official_roster_urls"]
    assert provenance["robots_enforced"] and provenance["tls_verified"]
    assert roster.stat().st_size <= 32768
    def normalize(text):
        return re.sub(r"\s+", " ", text.replace("\xad", "")).strip()
    anchors = BeautifulSoup(roster.read_text(), "html.parser").select("a")
    actual = {normalize(m["name_local"]) for m in payload["ministries"]}
    departments = {normalize(a.get_text(" ", strip=True)) for a in anchors if normalize(a.get_text(" ", strip=True)).startswith("Ministrstvo")}
    assert departments
    assert departments <= actual


@pytest.mark.parametrize("module", new_modules(), ids=lambda m: m["canonical_id"])
def test_genuine_fixture_replays_original_dates_without_attribution_guess(module):
    assert set(module["filter"]["topics"]) == set(OBSERVATION_TOPICS)
    assert module["responsibility_by_topic"] == {}
    assert module["verification"]["status"] == "smoke_healthy"
    source = Source(**module["sources"][0])
    assert source.id == module["canonical_id"]
    assert source.country == COUNTRY
    assert source.name == next(m["name_local"] for m in inventory()["ministries"] if source.id in m["source_ids"])
    assert source.schedule_enabled is False and source.critical is False
    fixture = ROOT / module["verification"]["fixture_path"]
    evidence = json.loads((ROOT / module["verification"]["provenance_path"]).read_text())
    assert evidence["source_id"] == source.id
    assert evidence["url"] == source.listing_url
    assert evidence["robots_enforced"] and evidence["tls_verified"]
    assert evidence["observed_on"] == module["verification"]["verified_on"]
    assert evidence["parsed_count"] == evidence["dated_count"] > 0
    assert fixture.stat().st_size <= 32768
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == evidence["sha256"]
    if fixture.suffix == ".xml":
        assert source.listing_url in source.feed_urls
        articles = parse_feed(fixture.read_bytes(), source, source.listing_url)
    else:
        articles = parse_listing(fixture.read_text(), source, source.listing_url)
    actual = [
        {"title": a.title, "url": a.url, "published_date_local": a.published_date_local, "date_source": a.date_source}
        for a in articles
    ]
    assert actual == [{key: row[key] for key in actual[0]} for row in evidence["expected"]]
    assert len(articles) == evidence["fixture_count"] > 0
    assert all(a.source_id == source.id and a.country == COUNTRY for a in articles)
    assert all(a.published_at and a.published_timezone == source.timezone for a in articles)
    assert all(a.publisher_organisation == "" for a in articles)
