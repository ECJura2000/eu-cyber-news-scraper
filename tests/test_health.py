import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from eu_cyber_news_scraper.health import (
    _prune_profiles,
    assess_and_record_health,
    health_profile_fingerprint,
    source_config_fingerprint,
)
from eu_cyber_news_scraper.models import Source, SourceStatus

PROFILE = {"period_mode": "rolling", "fetch_details": True}
LEGACY_FR_ANSSI_FINGERPRINT = "dce6d40a1b698ef5"


def write_v2(path, rows):
    fingerprint = health_profile_fingerprint(PROFILE)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "profiles": {
                    fingerprint: {
                        "profile": PROFILE,
                        "sources": {"s": rows},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def assess(status, source, path, *, write=True):
    return assess_and_record_health(
        [status],
        [source],
        path,
        run_id="run",
        recorded_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        profile=PROFILE,
        write=write,
    )[0]


def test_health_baseline_flags_a_large_drop_for_critical_source(tmp_path):
    path = tmp_path / ".source-health.json"
    write_v2(path, [{"success": True, "raw_count": value} for value in (20, 24, 22)])
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news", critical=True)
    status = SourceStatus("s", "來源", "EU", True, True, "html", 2, 0, 1.0)
    result = assess(status, source, path)
    assert result.success
    assert result.health_status == "attention"
    assert result.historical_median_count == 22
    assert result.health_alerts


def test_health_flags_stale_critical_source(tmp_path):
    path = tmp_path / ".source-health.json"
    source = Source(
        "s", "EU", "來源", "Source", "主管機關", "en",
        "https://x.eu", "https://x.eu/news", critical=True, freshness_days=30,
    )
    status = SourceStatus(
        "s", "來源", "EU", True, True, "html", 10, 0, 1.0,
        newest_published_at="2026-01-01T00:00:00+00:00",
        freshness_lag_days=59,
        freshness_status="stale",
    )
    result = assess(status, source, path)
    assert result.success
    assert result.health_status == "attention"
    assert any("最新可辨識文章" in value for value in result.health_alerts)


def test_content_no_hits_does_not_create_health_alert(tmp_path):
    path = tmp_path / ".source-health.json"
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus(
        "s", "來源", "EU", False, True, "html", 10, 0, 1.0,
        content_status="no_hits",
    )
    result = assess(status, source, path)
    assert result.health_status == "healthy"
    assert not result.health_alerts


def test_second_consecutive_stale_critical_run_is_degraded(tmp_path):
    path = tmp_path / ".source-health.json"
    write_v2(path, [{"success": True, "raw_count": 10, "baseline_failure": True}])
    source = Source(
        "s", "EU", "來源", "Source", "主管機關", "en",
        "https://x.eu", "https://x.eu/news", critical=True, freshness_days=30,
    )
    status = SourceStatus(
        "s", "來源", "EU", True, True, "html", 10, 0, 1.0,
        newest_published_at="2026-01-01T00:00:00+00:00",
        freshness_lag_days=59,
        freshness_status="stale",
    )
    result = assess(status, source, path)
    assert result.health_status == "degraded"


def test_third_consecutive_noncritical_failure_is_degraded(tmp_path):
    path = tmp_path / ".source-health.json"
    write_v2(
        path,
        [
            {"success": True, "raw_count": 0, "baseline_failure": True},
            {"success": True, "raw_count": 0, "baseline_failure": True},
        ],
    )
    source = Source("s", "EU", "來源", "Source", "研究", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus(
        "s", "來源", "EU", False, False, "html", 0, 0, 1.0,
        fetch_status="ok", parse_status="empty",
    )
    assert assess(status, source, path).health_status == "degraded"


def test_performance_regression_uses_source_history_without_marking_baseline_failure(tmp_path):
    path = tmp_path / ".source-health.json"
    write_v2(
        path,
        [
            {
                "success": True, "raw_count": 10, "baseline_failure": False,
                "request_count": 4, "bytes_downloaded": 1000, "duration_seconds": 2,
            }
            for _ in range(3)
        ],
    )
    source = Source("s", "EU", "來源", "Source", "研究", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus(
        "s", "來源", "EU", False, True, "html", 10, 0, 8.0,
        request_count=12, bytes_downloaded=3000,
    )
    result = assess(status, source, path)
    assert result.health_status == "attention"
    assert result.historical_median_requests == 4
    assert any("2.5 倍" in alert for alert in result.health_alerts)


def test_v1_history_is_preserved_as_legacy_but_not_used(tmp_path):
    path = tmp_path / ".source-health.json"
    path.write_text(json.dumps({"schema_version": 1, "sources": {"s": [{"raw_count": 99}]}}), encoding="utf-8")
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus("s", "來源", "EU", False, True, "html", 10, 0, 1.0)
    result = assess(status, source, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert result.historical_median_count == 0
    assert payload["schema_version"] == 2
    assert payload["legacy"]["schema_version"] == 1


def test_read_only_health_does_not_create_or_modify_state(tmp_path):
    path = tmp_path / ".source-health.json"
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus("s", "來源", "EU", False, True, "html", 10, 0, 1.0)
    assess(status, source, path, write=False)
    assert not path.exists()


def test_same_observation_replaces_prior_row_instead_of_incrementing_streak(tmp_path):
    path = tmp_path / ".source-health.json"
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus("s", "來源", "EU", False, True, "html", 10, 0, 1.0)
    for run_id in ("first", "rerun"):
        assess_and_record_health(
            [status],
            [source],
            path,
            run_id=run_id,
            recorded_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            profile=PROFILE,
            observation_key="rolling-2026-03-01",
            write=True,
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = next(iter(payload["profiles"].values()))["sources"]["s"]
    assert len(rows) == 1
    assert rows[0]["run_id"] == "rerun"


def test_source_config_change_resets_only_that_source_baseline(tmp_path):
    path = tmp_path / ".source-health.json"
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus("s", "來源", "EU", False, True, "html", 20, 0, 1.0)
    assess_and_record_health(
        [status], [source], path, run_id="first", recorded_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        profile=PROFILE, observation_key="one", write=True,
    )
    changed = Source(
        "s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/updated-news"
    )
    current = assess_and_record_health(
        [status], [changed], path, run_id="second", recorded_at=datetime(2026, 3, 8, tzinfo=timezone.utc),
        profile=PROFILE, observation_key="two", write=False,
    )[0]
    assert current.historical_median_count == 0


@pytest.fixture
def legacy_fr_anssi_baseline(tmp_path):
    # Freeze the source settings and fingerprint from before the optional fields.
    source = Source(
        id="fr_anssi",
        country="FR",
        name_zh="法國國家資訊系統安全局",
        name="Agence nationale de la sécurité des systèmes d'information",
        institution_type="國家主管機關",
        language="fr",
        homepage="https://cyber.gouv.fr/",
        listing_url="https://cyber.gouv.fr/actualites/",
        feed_urls=("https://cyber.gouv.fr/actualites/rss/", "https://cyber.gouv.fr/actualites/atom/"),
        allow_domains=("cyber.gouv.fr",),
        include_patterns=("/actualites/.+",),
        exclude_patterns=("/actualites/(rss|atom)/?$", r"^/actualites/\?(tag|page)="),
        critical=True,
        detail_pages=16,
        pagination_url="https://cyber.gouv.fr/actualites/?page={page}",
        max_pages=10,
        freshness_days=45,
        timezone="Europe/Paris",
        card_selectors=("div.fr-card__content",),
        link_selectors=("h3.fr-card__title a[href]",),
        date_selectors=("p.fr-card__desc",),
    )
    path = tmp_path / ".source-health.json"
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "profiles": {
                health_profile_fingerprint(PROFILE): {
                    "profile": PROFILE,
                    "sources": {
                        source.id: [
                            {
                                "source_fingerprint": LEGACY_FR_ANSSI_FINGERPRINT,
                                "observation_key": f"legacy-{index}",
                                "success": True,
                                "raw_count": 20,
                                "baseline_failure": False,
                            }
                            for index in range(3)
                        ],
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    status = SourceStatus(source.id, source.name_zh, source.country, True, True, "feed", 1, 0, 1.0)
    return source, status, path


def test_default_fetch_policies_preserve_legacy_fr_anssi_baseline(legacy_fr_anssi_baseline):
    source, status, path = legacy_fr_anssi_baseline
    assert source.feed_archive_fallback is False
    assert source.minimum_budget_seconds == 0
    assert source_config_fingerprint(source) == LEGACY_FR_ANSSI_FINGERPRINT

    result = assess(status, source, path, write=False)

    assert result.historical_median_count == 20
    assert result.health_status == "attention"
    assert any("原始筆數 1 低於歷史中位數 20" in alert for alert in result.health_alerts)


@pytest.mark.parametrize("changes", [
    {"feed_archive_fallback": True},
    {"minimum_budget_seconds": 600},
    {"feed_archive_fallback": True, "minimum_budget_seconds": 600},
])
def test_nondefault_fetch_policies_reset_legacy_fr_anssi_baseline(legacy_fr_anssi_baseline, changes):
    source, status, path = legacy_fr_anssi_baseline
    changed = replace(source, **changes)
    assert source_config_fingerprint(changed) != LEGACY_FR_ANSSI_FINGERPRINT

    result = assess(status, changed, path, write=False)

    assert result.historical_median_count == 0
    assert result.health_status == "healthy"
    assert not result.health_alerts


def test_health_reports_parse_duplicate_and_overdue_date_exception_alerts(tmp_path):
    path = tmp_path / ".source-health.json"
    source = Source(
        "s", "EU", "來源", "Source", "研究", "en", "https://x.eu", "https://x.eu/news",
        date_policy="best_effort", date_review_due="invalid-date",
    )
    status = SourceStatus(
        "s", "來源", "EU", False, True, "html", 8, 0, 1.0,
        parse_status="attention", undated_ratio=0.75, unique_title_ratio=0.5,
    )

    result = assess(status, source, path)

    assert result.health_status == "attention"
    assert any("無日期新聞" in alert for alert in result.health_alerts)
    assert any("唯一標題比例" in alert for alert in result.health_alerts)
    assert any("複查期限" in alert for alert in result.health_alerts)


def test_health_profile_pruning_keeps_newest_and_archives_older_profiles():
    payload = {
        "profiles": {
            f"profile-{index}": {"updated_at": f"2026-01-{index + 1:02d}T00:00:00+00:00"}
            for index in range(10)
        }
    }

    _prune_profiles(payload, keep=8)

    assert len(payload["profiles"]) == 8
    assert "profile-9" in payload["profiles"]
    assert payload["legacy_profiles"] == [
        {"fingerprint": "profile-1", "updated_at": "2026-01-02T00:00:00+00:00"},
        {"fingerprint": "profile-0", "updated_at": "2026-01-01T00:00:00+00:00"},
    ]


def test_invalid_health_json_starts_a_clean_v2_state(tmp_path):
    path = tmp_path / ".source-health.json"
    path.write_text("{invalid", encoding="utf-8")
    source = Source("s", "EU", "來源", "Source", "研究", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus("s", "來源", "EU", False, True, "html", 2, 1, 0.1)

    assess(status, source, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert "legacy" not in payload
