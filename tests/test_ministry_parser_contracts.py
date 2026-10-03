"""Re-run every enrolled ministry parser against its captured official sample."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.ministry_inventory import inventory_directory, load_inventory
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_feed, parse_listing

ROOT = Path(__file__).resolve().parents[1]
BASELINE = set(json.loads((ROOT / "tests/fixtures/v170_source_ids.json").read_text())["source_ids"])
REGISTRY = load_organisation_registry()
MANUAL_VERIFIED = {
    source_id
    for record in load_inventory(inventory_directory(), REGISTRY)
    for ministry in record["ministries"]
    if ministry["status"] == "manual_verified"
    for source_id in ministry["source_ids"]
}


def _verification_paths(verification):
    fixture_key = next(key for key in ("fixture_path", "fixture", "evidence_fixture") if key in verification)
    fixture = ROOT / verification[fixture_key]
    provenance_key = next(
        (key for key in ("provenance_path", "provenance", "evidence_provenance") if key in verification),
        None,
    )
    provenance = ROOT / verification[provenance_key] if provenance_key else fixture.with_suffix(".provenance.json")
    return fixture, provenance


def _provenance_source_id(provenance):
    return provenance.get("source_id") or provenance.get("id") or provenance["source"]["id"]


def _expected_rows(provenance):
    return provenance.get("expected") or provenance.get("expected_articles", [])


@pytest.mark.parametrize(
    "source",
    [source for source in load_sources() if source.id not in BASELINE and source.id in MANUAL_VERIFIED],
    ids=lambda s: s.id,
)
def test_new_ministry_fixture_has_provenance_and_dates(source):
    module = REGISTRY.module_for_source(source.id)
    assert module is not None
    verification = module.payload["verification"]
    fixture, provenance_path = _verification_paths(verification)
    provenance = json.loads(provenance_path.read_text())
    assert fixture.resolve().is_relative_to((ROOT / "tests/fixtures").resolve())
    assert provenance_path.resolve().is_relative_to((ROOT / "tests/fixtures").resolve())
    assert _provenance_source_id(provenance) == source.id
    assert provenance.get("robots_enforced", provenance.get("robots_obeyed"))
    assert provenance.get("tls_verified", provenance.get("tls_verification"))
    http_status = provenance.get("http_status")
    if http_status is None:
        live_status = provenance.get("live_status") or provenance.get("live_scrape_status") or {}
        statuses = live_status.get("http_statuses")
        assert statuses, "HTTP success requires recorded response status evidence"
        http_status = statuses[0]
    assert str(http_status) == "200"
    content = fixture.read_bytes()
    assert len(content) <= 262144
    expected_sha256 = provenance.get("sha256") or provenance["fixture_sha256"]
    assert hashlib.sha256(content).hexdigest() == expected_sha256
    url = provenance["url"]
    articles = parse_feed(content, source, url) if source.feed_urls else parse_listing(content.decode(), source, url)
    expected = _expected_rows(provenance)
    assert len(articles) == len(expected) > 0
    assert [article.url for article in articles] == [row["url"] for row in expected]
    for article, row in zip(articles, expected, strict=True):
        hostname = urlsplit(article.url).hostname
        assert hostname and "." in hostname, "Hostless/malformed official feed links are not verified articles"
        assert article.title == row["title"]
        assert article.source_id == source.id and article.country == source.country
        assert article.published_at is not None
        if "date_confidence" in row:
            assert article.date_confidence == row["date_confidence"]
        assert not article.date_conflict
        assert article.published_date_local == row.get("published_date_local", row.get("date"))
