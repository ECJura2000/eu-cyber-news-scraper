import json
from datetime import datetime, timezone

from eu_cyber_news_scraper.health import assess_and_record_health
from eu_cyber_news_scraper.models import Source, SourceStatus


def test_health_baseline_flags_a_large_drop_for_critical_source(tmp_path):
    path = tmp_path / ".source-health.json"
    path.write_text(
        json.dumps({"sources": {"s": [{"success": True, "raw_count": value} for value in (20, 24, 22)]}}),
        encoding="utf-8",
    )
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news", critical=True)
    status = SourceStatus("s", "來源", "EU", True, True, "html", 2, 0, 1.0)
    result = assess_and_record_health(
        [status], [source], path, run_id="run", recorded_at=datetime.now(timezone.utc)
    )[0]
    assert not result.success
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
    )
    result = assess_and_record_health(
        [status], [source], path, run_id="run", recorded_at=datetime(2026, 3, 1, tzinfo=timezone.utc)
    )[0]
    assert not result.success
    assert any("最新可辨識文章" in value for value in result.health_alerts)


def test_health_flags_three_consecutive_zero_in_range_runs(tmp_path):
    path = tmp_path / ".source-health.json"
    path.write_text(
        json.dumps({"sources": {"s": [{"success": True, "raw_count": 10, "in_range_count": 0}] * 2}}),
        encoding="utf-8",
    )
    source = Source("s", "EU", "來源", "Source", "主管機關", "en", "https://x.eu", "https://x.eu/news")
    status = SourceStatus("s", "來源", "EU", False, True, "html", 10, 0, 1.0, in_range_count=0)
    result = assess_and_record_health(
        [status], [source], path, run_id="run", recorded_at=datetime.now(timezone.utc)
    )[0]
    assert any("連續 3 次" in value for value in result.health_alerts)
