"""Enroll saved production successes without depending on mutable scratch reports."""
import hashlib
import json
from pathlib import Path

import pytest
from test_ministry_parser_contracts import test_new_ministry_fixture_has_provenance_and_dates as _ministry_contract

from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures"
RECORDS = {r["canonical_id"]: r for r in json.loads((FIX / "ministry_round4_be_fi_live_records.json").read_text())}


def source(identifier):
    config = RECORDS[identifier]["source"].copy()
    for key, field in Source.__dataclass_fields__.items():
        if isinstance(field.default, tuple) and key in config:
            config[key] = tuple(config[key])
    return Source(**config)


@pytest.mark.parametrize("identifier", tuple(RECORDS))
def test_new_sources_satisfy_existing_ministry_parser_contract(identifier):
    _ministry_contract(source(identifier))


@pytest.mark.parametrize("identifier", tuple(RECORDS))
def test_production_exact_source_policy_and_publication_parity(identifier):
    record = RECORDS[identifier]
    registry = load_organisation_registry()
    module = registry.module_for_source(identifier)
    assert module is not None
    actual = module.payload["sources"][0]
    assert {key: actual[key] for key in record["source"]} == record["source"]
    assert set(actual) - set(record["source"]) <= {'date_order', 'date_formats', 'timezone'}
    assert module.payload["filter"]["topics"] == list(OBSERVATION_TOPICS)
    assert module.payload["responsibility_by_topic"] == {}
    s = source(identifier)
    assert s.schedule_enabled is False and s.critical is False
    assert type(s.detail_pages) is int and s.detail_pages == 0
    proof = json.loads((ROOT / module.payload["verification"]["provenance_path"]).read_text())
    fixture = (ROOT / proof["fixture_path"]).read_bytes()
    assert len(fixture) == proof["fixture_bytes"] < 262144
    assert hashlib.sha256(fixture).hexdigest() == proof["fixture_sha256"]
    assert proof["response_sha256"] == record["response_sha256"] == proof["raw_response_sha256"]
    assert proof["original_fixture_parity"]["title_url_dates_equal"]
    assert proof["live_status"] == record["live_status"]
    articles = parse_listing(fixture.decode(), s, record["url"])
    assert len(articles) == len(record["expected"]) == record["dated_count"]
    for article, expected, original in zip(articles, proof["expected"], record["expected"], strict=True):
        assert article.published_at.isoformat() == expected["published_at"]
        for key in ("title", "url", "published_date_local", "published_at_raw", "published_timezone",
                    "date_source", "date_confidence", "date_precision", "date_conflict"):
            assert getattr(article, key) == expected[key]
        for key, value in original.items():
            assert getattr(article, key) == value


def test_inventory_patch_scope_excludes_failed_german_source():
    report = json.loads((FIX / "ministry_be_fi_round4_integration.json").read_text())
    assert {r["canonical_id"] for r in report["checks"]} == set(RECORDS)
    assert report["excluded_ids"][0]["canonical_id"] == "de_bmf"
    for row in report["checks"]:
        assert row["inventory_patch"]["status"] == "manual_verified"
        assert row["inventory_patch"]["source_ids"] == [row["canonical_id"]]
