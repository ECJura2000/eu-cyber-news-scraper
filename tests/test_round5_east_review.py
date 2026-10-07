"""Round-five east coverage, provenance, publisher scope and real parser contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from eu_cyber_news_scraper import source_audit
from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.scraper import scrape_source
from eu_cyber_news_scraper.source_audit import AuditHttpClient
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS
from eu_cyber_news_scraper.wikipedia_review import (
    validate_news_url_cleanup,
    validate_wikipedia_review,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
REPORT = json.loads((FIXTURES / "ministry_round5_east.json").read_text())
PROOF = json.loads((FIXTURES / "ministry_round5_bg_youth_sport.provenance.json").read_text())
LIVE = json.loads((FIXTURES / "ministry_round5_east_live_records.json").read_text())[0]


def source() -> Source:
    payload = PROOF["source_config"].copy()
    for key, field in Source.__dataclass_fields__.items():
        if isinstance(field.default, tuple) and key in payload:
            payload[key] = tuple(payload[key])
    return Source(**payload)


def signature(articles):
    return [(a.title, a.url, a.published_date_local, a.date_confidence, a.published_at_raw) for a in articles]


def expected(rows):
    return [
        (r["title"], r["url"], r["published_date_local"], r["date_confidence"], r["published_at_raw"]) for r in rows
    ]


def test_exact_country_assignment_and_complete_dispositions():
    assert REPORT["schema_version"] == 1 and REPORT["group"] == "east"
    assert REPORT["observed_on"] == "2026-10-03"
    assert REPORT["input_country_counts"] == {
        "BG": 4,
        "HR": 19,
        "HU": 2,
        "LT": 15,
        "RO": 11,
        "SK": 2,
        "CY": 10,
    }
    assert len(REPORT["checks"]) == len({c["canonical_id"] for c in REPORT["checks"]}) == 63
    assert REPORT["summary"]["result_counts"] == {
        "manual_verified": 1,
        "blocked": 60,
        "parser_pending": 2,
    }
    # Frozen assignment is in the report; registered ministry rows may change on integration.
    for check in REPORT["checks"]:
        inventory = json.loads((ROOT / "ministry_inventory" / (check["country"] + ".json")).read_text())
        assert check["canonical_id"] in {r["canonical_id"] for r in inventory["ministries"]}
        assert check["baseline_status"] not in {"manual_verified", "existing_source"}
        assert check["next_action"] and check["attempts"]
        assert check["automatic_schedule_changes"] is False
        for attempt in check["attempts"]:
            assert attempt["url"].startswith("https://")
            assert datetime.fromisoformat(attempt["observed_at"]).tzinfo is not None
            assert attempt.get("http_status") or attempt.get("error")


@pytest.mark.parametrize("check", REPORT["checks"], ids=lambda c: c["canonical_id"])
def test_shared_wikipedia_and_cleanup_validation(check):
    validate_wikipedia_review(check, date(2026, 10, 3))
    validate_news_url_cleanup(check, date(2026, 10, 3))
    for page in check["wikipedia"]["pages"]:
        assert len(page.get("excerpt", "")) <= 1000
        assert "exact_retrieved_content" not in page
    assert check["removed_news_urls"] == []
    if check["result"] == "blocked":
        assert "inventory_patch" not in check


def test_new_source_policy_and_independent_saved_live_record():
    registry = load_organisation_registry()
    module = registry.module_for_source("bg_youth_sport")
    assert module is not None
    payload = module.payload
    assert LIVE["source"] == PROOF["source_config"]
    actual = payload["sources"][0]
    assert {key: actual[key] for key in LIVE["source"]} == LIVE["source"]
    assert set(actual) - set(LIVE["source"]) <= {"date_order", "date_formats", "timezone"}
    assert payload["filter"]["topics"] == list(OBSERVATION_TOPICS)
    assert len(OBSERVATION_TOPICS) == 15
    assert payload["responsibility_by_topic"] == {}
    s = source()
    assert s.critical is False and s.schedule_enabled is False
    assert type(s.detail_pages) is int and s.detail_pages == 0
    assert len(payload["verification"]["evidence_urls"]) >= 2
    assert PROOF["http_status"] == 200 and PROOF["robots_enforced"] and PROOF["tls_verified"]
    assert PROOF["response_sha256"] == PROOF["raw_response_sha256"] == LIVE["response_sha256"]
    assert PROOF["live_status"] == LIVE["live_status"] == payload["verification"]["last_smoke"]
    assert LIVE["live_status"]["success"]
    assert LIVE["live_status"]["raw_count"] == LIVE["live_status"]["dated_count"] == 2
    assert LIVE["live_status"]["undated_ratio"] == 0
    assert LIVE["live_status"]["invalid_date_count"] == 0


def test_bounded_clean_dom_exact_publication_replay():
    content = (ROOT / PROOF["fixture_path"]).read_bytes()
    assert len(content) == PROOF["fixture_bytes"] <= 32768
    assert hashlib.sha256(content).hexdigest() == PROOF["fixture_sha256"]
    soup = BeautifulSoup(content, "lxml")
    assert not soup.select("script, style, form, input, textarea, joomla-hidden-mail")
    articles = parse_listing(content.decode(), source(), PROOF["url"])
    assert signature(articles) == expected(PROOF["expected"])
    assert sorted(signature(articles)) == sorted(expected(LIVE["expected"]))
    assert all(a.published_at and a.date_confidence == "high" for a in articles)
    assert PROOF["original_fixture_parity"]["title_url_dates_equal"]


def test_community_cards_are_excluded_even_when_they_have_genuine_dates():
    # Real alternate card retained only in scratch; derive the negative case by
    # replacing its issuer sentence, while keeping an otherwise valid dated card.
    soup = BeautifulSoup((ROOT / PROOF["fixture_path"]).read_bytes(), "lxml")
    cards = soup.select("article.item")
    assert len(cards) == 2
    cards[1].select_one(".newsberg-article-introtext > p:first-child").string = "Partner organisation announcement"
    selected = parse_listing(str(soup), source(), PROOF["url"])
    assert len(selected) == 1
    assert selected[0].url == PROOF["expected"][0]["url"]


def test_fixture_through_actual_production_dispatch_with_robots(monkeypatch):
    async def fixture_dns(host):
        assert host == 'www.nism.bg'

    # Mock transport has no DNS; keep URL/robots/dispatch validation active.
    monkeypatch.setattr(source_audit, '_validate_public_dns', fixture_dns)
    asyncio.run(_fixture_through_actual_production_dispatch_with_robots())


async def _fixture_through_actual_production_dispatch_with_robots():
    content = (ROOT / PROOF["fixture_path"]).read_bytes()
    requests = []

    def respond(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        assert str(request.url) == PROOF["url"]
        return httpx.Response(200, content=content, headers={"content-type": "text/html; charset=utf-8"})

    s = source()
    async with AuditHttpClient(timeout=15, transport=httpx.MockTransport(respond)) as client:
        client.source = s
        result = await scrape_source(
            s,
            client,
            since=datetime(2025, 1, 1, tzinfo=timezone.utc),
            until=datetime(2026, 10, 4, tzinfo=timezone.utc),
            include_unmatched=True,
            include_undated=True,
            fetch_details=False,
            source_budget_seconds=60,
        )
    assert "/robots.txt" in requests
    assert result.status.success and result.status.raw_count == result.status.dated_count == 2
    assert result.status.undated_ratio == 0
    assert sorted(signature(result.articles)) == sorted(expected(PROOF["expected"]))
