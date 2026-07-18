import json
from datetime import datetime, timezone

from eu_cyber_news_scraper.health import assess_and_record_health, health_profile_fingerprint
from eu_cyber_news_scraper.models import Source, SourceStatus

PROFILE = {"period_mode": "rolling", "fetch_details": True}


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
