import hashlib
import ssl
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from eu_cyber_news_scraper import __version__
from eu_cyber_news_scraper.config import USER_AGENT, _validate_sources, load_sources


def test_default_sources_cover_all_target_jurisdictions():
    sources = load_sources()
    assert len(sources) >= 33
    assert {source.country for source in sources} == {"EU", "FR", "DE", "IE"}
    assert any(source.id == "fr_anssi" and source.feed_urls for source in sources)
    assert any(source.id == "ie_ncsc" and source.critical for source in sources)
    assert any(source.id == "fr_viginum" for source in sources)
    assert any(source.id == "de_bfdi" for source in sources)
    assert any(source.id == "ie_cnam" for source in sources)


def test_source_ids_are_unique():
    sources = load_sources()
    assert len({source.id for source in sources}) == len(sources)


def test_user_agent_identifies_version_and_public_repository():
    assert f"eu-cyber-news-scraper/{__version__}" in USER_AGENT
    assert "github.com/ECJura2000/eu-cyber-news-scraper" in USER_AGENT


def test_paused_source_has_auditable_review_metadata():
    source = next(item for item in load_sources() if item.id == "fr_cea_list")
    assert source.paused_until == "2026-10-31"
    assert source.pause_reason
    assert source.pause_evidence_url == source.listing_url


def test_europarl_runner_challenge_is_auditable_and_overridable():
    source = next(item for item in load_sources() if item.id == "eu_parliament_press")
    assert source.paused_until == "2026-08-31"
    assert "HTTP 202" in source.pause_reason
    assert source.pause_evidence_url == "https://www.europarl.europa.eu/at-your-service/en/stay-informed/rss-feeds"


def test_comreg_uses_complete_listing_without_slow_detail_requests():
    source = next(item for item in load_sources() if item.id == "ie_comreg")
    assert source.card_selectors
    assert source.date_selectors
    assert source.detail_pages == 0


def test_tls_intermediate_bundles_are_limited_to_affected_sources():
    bundles = {source.id: source.tls_intermediate_bundle for source in load_sources() if source.tls_intermediate_bundle}
    assert bundles == {
        "ie_dpc": "sectigo-dv-r36.pem",
        "fr_cea_list": "geant-tls-rsa-1.pem",
    }
    expected_fingerprints = {
        "sectigo-dv-r36.pem": "8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0",
        "geant-tls-rsa-1.pem": "5b678dc44095a52895b63b31f27227f4b36c3e347491bf2bfa691837a5fb8c79",
    }
    certificate_dir = Path("src/eu_cyber_news_scraper/certificates")
    for name, expected in expected_fingerprints.items():
        path = certificate_dir / name
        der = ssl.PEM_cert_to_DER_cert(path.read_text(encoding="ascii"))
        assert hashlib.sha256(der).hexdigest() == expected
        decoded = ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined]
        expires_at = datetime.strptime(decoded["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        assert expires_at > datetime.now(timezone.utc) + timedelta(days=180)


def test_source_validation_rejects_empty_and_duplicate_configs():
    source = load_sources()[0]
    with pytest.raises(ValueError, match="No sources"):
        _validate_sources([])
    with pytest.raises(ValueError, match="Duplicate source ids"):
        _validate_sources([source, source])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"country": "XX"}, "Unsupported country"),
        ({"name": " "}, "must not be blank"),
        ({"detail_pages": -1}, "detail_pages"),
        ({"min_listing_bytes": -1}, "min_listing_bytes"),
        ({"max_pages": 0}, "max_pages"),
        ({"date_policy": "sometimes"}, "invalid date_policy"),
        ({"date_policy": "best_effort"}, "date policy requires"),
        ({"tls_intermediate_bundle": "../bad.pem"}, "unknown TLS"),
        ({"paused_until": "2026-09-01"}, "paused source requires"),
        (
            {
                "paused_until": "not-a-date",
                "pause_reason": "test",
                "pause_evidence_url": "https://example.eu/evidence",
            },
            "invalid paused_until",
        ),
        (
            {
                "paused_until": "2026-09-01",
                "pause_reason": "test",
                "pause_evidence_url": "not-a-url",
            },
            "invalid pause_evidence_url",
        ),
        ({"timezone": "Mars/Olympus"}, "invalid timezone"),
        ({"homepage": "not-a-url"}, "invalid homepage"),
        ({"listing_url": "https://outside.example/news"}, "outside allow_domains"),
        ({"yearly_listing_url": "https://outside.example/{year}"}, "yearly_listing_url is outside"),
        ({"pagination_url": "https://outside.example/page/{page}"}, "pagination_url is outside"),
        ({"include_patterns": ("[",)}, "invalid URL regex"),
    ],
)
def test_source_validation_rejects_unsafe_values(changes, message):
    source = replace(load_sources()[0], **changes)
    with pytest.raises(ValueError, match=message):
        _validate_sources([source])
