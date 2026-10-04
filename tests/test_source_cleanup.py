"""Removal must be evidence-backed, reversible, and absent from both loaders."""
import json
from pathlib import Path

import pytest

from eu_cyber_news_scraper.cli import _select_sources
from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.ministry_inventory import inventory_directory, inventory_report, load_inventory
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "source_exclusions/manifest.json").read_text())


def test_removal_accounting_and_two_actual_failures():
    entries = MANIFEST["exclusions"]
    ids = {entry["source_id"] for entry in entries}
    assert len(entries) == len(ids) == MANIFEST["removed_source_count"] == 39
    assert MANIFEST["checked_unpaused_source_count"] == 446
    assert MANIFEST["rechecked_source_count"] == 72
    assert MANIFEST["remaining_source_count"] == 409
    assert MANIFEST["baseline_source_count"] == 409 + 39
    assert set(MANIFEST["paused_sources_skipped"]) == {"eu_parliament_press", "fr_cea_list"}
    for entry in entries:
        archive = json.loads((ROOT / entry["archive"]).read_text())
        assert archive["canonical_id"] == entry["source_id"]
        source = next(row for row in archive["sources"] if row["id"] == entry["source_id"])
        assert source["listing_url"] == entry["listing_url"]
        assert source["schedule_enabled"] is False
        first, second = entry["first_observation"], entry["recheck"]
        assert first["run_id"] == MANIFEST["first_run_id"]
        assert second["timestamp"] > first["timestamp"]
        for observation in (first, second):
            assert observation["source_status"]["success"] is False
            assert observation["source_status"]["raw_count"] == 0
            assert observation["source_status"]["error_code"]
        assert not second["source_status"]["budget_exhausted"]
        assert entry["reason"] == second["source_status"]["error_code"]


@pytest.mark.parametrize("entry", MANIFEST["exclusions"], ids=lambda entry: entry["source_id"])
def test_removed_sources_are_not_queryable_from_json_or_toml(entry):
    for sources in (load_sources(), load_sources(ROOT / "src/eu_cyber_news_scraper/sources.toml")):
        assert entry["source_id"] not in {source.id for source in sources}
        with pytest.raises(SystemExit, match="未知來源代碼"):
            _select_sources(sources, None, [entry["source_id"]])


def test_ministry_links_and_schedule_preserve_current_truth():
    sources = load_sources()
    registry = load_organisation_registry()
    assert not registry.errors and len(sources) == 409
    records = load_inventory(inventory_directory(), registry)
    report = inventory_report(records)
    assert report["registered_ministries"] == 290
    assert report["user_excluded_ministries"] == 170
    assert report["pending_ministries"] == 0
    assert sum(source.schedule_enabled and not source.paused_until for source in sources) == 50
    removed_ids = {entry["source_id"] for entry in MANIFEST["exclusions"]}
    removed_ministries = [row for country in records for row in country["ministries"]
                         if row.get("user_exclusion", {}).get("policy") == "exclude_unreadable_registered_source"]
    assert len(removed_ministries) == 16
    for row in removed_ministries:
        assert row["status"] == "user_excluded" and row["news_url"] is None and not row["source_ids"]
        assert row["canonical_id"] in removed_ids
