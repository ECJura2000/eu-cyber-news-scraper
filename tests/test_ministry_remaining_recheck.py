"""Every previously unresolved ministry receives a fresh, explicit disposition."""
import json
from datetime import datetime
from pathlib import Path

from eu_cyber_news_scraper.ministry_inventory import inventory_directory, load_inventory
from eu_cyber_news_scraper.ministry_rechecks import latest_checks, load_rechecks
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.source_catalog import https_url

FIXTURES = Path(__file__).parent / "fixtures"


def test_all_201_remaining_ministries_have_one_evidence_backed_recheck():
    baseline = json.loads((FIXTURES / "ministry_round3_baseline.json").read_text())
    initial = {r["canonical_id"]: r for r in baseline["ministries"]}
    assert len(initial) == baseline["remaining_count"] == 201
    current = {
        row["canonical_id"]: row
        for country in load_inventory(inventory_directory(), load_organisation_registry())
        for row in country["ministries"]
    }
    checked = set()
    for group in ("north", "south", "portugal"):
        report = json.loads((FIXTURES / f"ministry_round3_{group}.json").read_text())
        assert report["schema_version"] == 1 and report["group"] == group
        assert report["observed_on"] >= baseline["observed_on"]
        for check in report["checks"]:
            identifier = check["canonical_id"]
            assert identifier in initial and identifier not in checked
            checked.add(identifier)
            assert check["country"] == initial[identifier]["country"]
            assert check["country"] in report["countries"]
            assert check["next_action"].strip()
            assert check["attempts"], "No live check must not be described as completed"
            for attempt in check["attempts"]:
                https_url(attempt["url"])
                observed = datetime.fromisoformat(attempt["observed_at"])
                assert observed.tzinfo is not None
                assert observed.date().isoformat() >= baseline["observed_on"]
                assert attempt.get("http_status") or attempt.get("error")
    assert checked == set(initial), "Missing ministries cannot disappear from the remaining audit"
    latest = latest_checks(load_rechecks(FIXTURES))
    assert set(latest) == set(initial)
    for identifier, check in latest.items():
        assert check['result'] == current[identifier]['status']
