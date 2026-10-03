"""Complete native-language round-six coverage and reversible user exclusions."""
import copy
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

from eu_cyber_news_scraper.wikipedia_review import (
    validate_local_wikipedia_review,
    validate_user_exclusion,
    validate_wikipedia_review,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures"
COUNTRIES = {"AT", "BE", "CZ", "DE", "DK", "FI", "FR"}


def report():
    return json.loads((FIX / "ministry_round6_north.json").read_text())


def baseline():
    return json.loads((FIX / "ministry_round6_baseline.json").read_text())


def test_exact_assigned_coverage_and_observation_totals():
    data = report()
    rows = {r["canonical_id"]: r for r in baseline()["ministries"] if r["country"] in COUNTRIES}
    assert data["schema_version"] == 1 and data["group"] == "north"
    assert set(data["countries"]) == COUNTRIES
    assert len(data["checks"]) == data["checked_count"] == len(rows) == 38
    assert set(rows) == {c["canonical_id"] for c in data["checks"]}
    assert data["country_counts"] == {"AT": 2, "BE": 3, "CZ": 2, "DE": 3, "DK": 2, "FI": 11, "FR": 15}
    assert data["search_count"] == sum(len(c["wikipedia"]["search_evidence"]) for c in data["checks"]) == 50
    assert data["attempt_count"] == data["total_official_attempts"] == sum(
        len(c["attempts"]) for c in data["checks"]
    ) == 133
    minimum = date.fromisoformat(baseline()["observed_on"])
    assert date.fromisoformat(data["observed_on"]) >= minimum
    for check in data["checks"]:
        assert check["country"] == rows[check["canonical_id"]]["country"]
        assert check["baseline_status"] == rows[check["canonical_id"]]["initial_status"]


def test_actual_local_queries_page_checksums_and_bounded_evidence():
    minimum = date.fromisoformat(baseline()["observed_on"])
    for check in report()["checks"]:
        validate_wikipedia_review(check, minimum)
        validate_local_wikipedia_review(check, minimum)
        review = check["wikipedia"]
        language = review["local_language"]
        if check["country"] == "FI":
            assert language == "fi"
        host = f"{language}.wikipedia.org"
        assert all(f"site:{host}" in query for query in review["queries"])
        assert {e["query"] for e in review["search_evidence"]} == set(review["queries"])
        for evidence in review["search_evidence"]:
            assert re.fullmatch(r"[a-f0-9]{64}", evidence["response_sha256"])
            assert evidence["cli_sha256"] == "04a501664ff07b898a1712b9cdd1fe73cee446fc830677d774fca55c9841df77"
            assert 0 < len(evidence["excerpt"]) <= 1000
        for page in review["pages"]:
            assert urlsplit(page["url"]).hostname == host
            assert page["title"] and not page["title"].startswith('{"url":')
            assert re.fullmatch(r"[a-f0-9]{64}", page["extracted_sha256"])
            assert 0 < len(page["excerpt"]) <= 1000
            assert len(page["official_relationship_excerpt"]) <= 1000
        pages = {p["url"] for p in review["pages"]}
        assert all(c["wikipedia_url"] in pages and c["relationship_excerpt"] for c in review["website_candidates"])


def test_every_official_failure_preserves_enforced_transport_and_timestamp():
    minimum = date.fromisoformat(baseline()["observed_on"])
    for check in report()["checks"]:
        assert check["attempts"]
        for attempt in check["attempts"]:
            assert attempt["url"].startswith("https://")
            observed = datetime.fromisoformat(attempt["observed_at"])
            assert observed.tzinfo is not None
            assert observed.astimezone(ZoneInfo("Asia/Taipei")).date() >= minimum
            assert attempt.get("http_status") or attempt.get("error")
            assert attempt["robots_enforced"] is True and attempt["tls_verified"] is True
            if attempt.get("response_sha256"):
                assert re.fullmatch(r"[a-f0-9]{64}", attempt["response_sha256"])
            assert "__RequestVerificationToken" not in json.dumps(attempt)


def test_all_exclusions_preserve_exact_original_candidate_and_no_runnable_source():
    data = report()
    base = baseline()
    rows = {r["canonical_id"]: r for r in base["ministries"]}
    assert base["user_exclusion_authorized"] is True
    assert data["new_source_ids"] == []
    assert data["result_counts"] == {"user_excluded": 38}
    assert data["failure_category_counts"] == dict(Counter(c["failure_category"] for c in data["checks"]))
    assert data["failure_category_counts"] == {"blocked": 35, "needs_review": 2, "parser_pending": 1}
    for check in data["checks"]:
        original = rows[check["canonical_id"]]["initial_news_url"]
        validate_user_exclusion(check, date.fromisoformat(base["observed_on"]), authorized=True, original_url=original)
        assert check["inventory_patch"] == {"news_url": None}
        assert check["user_exclusion"]["candidate_news_url"] == original
        assert check["failure_reason"] and check["next_action"]
        assert "restore only after explicit review" in check["next_action"]
        assert not check.get("removed_news_urls")
        assert not check.get("source_ids") and not check.get("source_config")


def test_readable_shared_portal_and_http_200_challenges_never_promote():
    checks = {c["canonical_id"]: c for c in report()["checks"]}
    for identifier in ("fr_territorial_decentralisation", "fr_ecological_transition", "fr_transport", "fr_city_housing"):
        check = checks[identifier]
        scope = check["publisher_scope"]
        assert scope["form_method"] == "GET" and scope["ministry_label"]
        assert any(a["url"] == scope["url"] and a.get("error_code") == "robots_denied" for a in check["attempts"])
        assert check["failure_category"] == "blocked"
    challenge = checks["de_bmwe"]
    assert any(a.get("http_status") == 200 and a.get("challenge_detected") for a in challenge["attempts"])
    assert challenge["failure_category"] == "blocked"
    danish = checks["dk_children"]
    assert any(a.get("method") == "POST" and a.get("http_status") == 400 for a in danish["attempts"])
    assert danish["live_status"]["success"] is False and danish["live_status"]["raw_count"] == 0
    austrian = checks["at_bmlv"]
    assert austrian["live_status"]["raw_count"] == 10 and austrian["live_status"]["dated_count"] == 1
    assert austrian["production_sample"][0]["date_confidence"] == "low"


def test_local_review_cannot_accept_english_substitution():
    check = copy.deepcopy(report()["checks"][0])
    check["wikipedia"]["local_language"] = "en"
    with pytest.raises(ValueError, match="local country language"):
        validate_local_wikipedia_review(check, date(2026, 10, 3))


def test_original_url_cannot_be_erased_from_history():
    check = copy.deepcopy(next(c for c in report()["checks"] if c["canonical_id"] == "at_bmlv"))
    check["user_exclusion"]["candidate_news_url"] = None
    with pytest.raises(ValueError, match="original declared URL"):
        validate_user_exclusion(check, date(2026, 10, 3), authorized=True, original_url=check["initial_news_url"])
