"""Whole-inventory invariants: no lost sources and no unverified enrollment."""
import json
from pathlib import Path

from eu_cyber_news_scraper.ministry_inventory import inventory_directory, inventory_report, load_inventory
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS

ROOT = Path(__file__).resolve().parents[1]


def test_all_27_rosters_and_only_verified_new_runnable_sources():
    registry = load_organisation_registry()
    records = load_inventory(inventory_directory(), registry)
    report = inventory_report(records)
    assert report["status"] == "complete"
    assert report["country_count"] == 27
    baseline = set(json.loads((ROOT / "tests/fixtures/v170_source_ids.json").read_text())["source_ids"])
    assert len(baseline) == 145 and baseline <= registry.source_ids
    additions = registry.source_ids - baseline
    declared = {source_id for record in records for row in record["ministries"]
                if row["status"] == "manual_verified" for source_id in row["source_ids"]}
    # These separately verified institutions are not replacement ministry IDs.
    # Keep an exact allowlist so an undeclared source cannot slip into enrollment.
    independent = {"fi_education_agency", "fi_judicial_administration_portal"}
    assert not independent & declared
    assert additions == declared | independent
    for source_id in additions:
        module = registry.module_for_source(source_id)
        assert module is not None
        assert module.payload["verification"]["status"] == "smoke_healthy"
        assert not module.payload["responsibility_by_topic"]
        assert set(module.payload["filter"]["topics"]) == set(OBSERVATION_TOPICS)
        assert all(row.get("schedule_enabled") is False and not row.get("critical", False)
                   for row in module.payload["sources"])


def test_ministry_inventory_does_not_restore_removed_sources():
    registry = load_organisation_registry()
    records = load_inventory(inventory_directory(), registry)
    referenced = {source_id for record in records for row in record["ministries"] for source_id in row["source_ids"]}
    assert not {"fr_institut_montaigne", "eu_enisa_publications", "ie_insight"} & referenced
