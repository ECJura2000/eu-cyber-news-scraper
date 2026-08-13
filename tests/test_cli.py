import sys
from datetime import datetime, timedelta, timezone

import pytest

from eu_cyber_news_scraper.cli import (
    _date_range,
    _default_output,
    _health_observation_key,
    _quality_failures,
    _select_sources,
    _state_write_eligible,
    build_parser,
)
from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.models import Article, Source
from eu_cyber_news_scraper.periods import resolve_period


def test_date_range_treats_until_as_inclusive_calendar_day():
    since, until = _date_range("2026-05-01", "2026-05-03", 14)
    assert (until - since) == timedelta(days=3)
    assert since.date().isoformat() == "2026-04-30"  # Taipei midnight expressed in UTC
    assert _default_output(since, until).name == "歐盟資安法制新聞_20260501-20260503.xlsx"


def test_health_observation_key_normalizes_equivalent_calendar_inputs():
    profile = {"period_mode": "fixed", "fetch_details": True}
    roc = resolve_period("1150721", "1150804", None)
    gregorian = resolve_period("2026-07-21", "2026-08-04", None)
    assert _health_observation_key(roc, roc.since, roc.until, profile) == _health_observation_key(
        gregorian, gregorian.since, gregorian.until, profile
    )


def test_date_range_rejects_invalid_calendar_dates():
    with pytest.raises(SystemExit, match="無效日期"):
        _date_range("2026-02-30", "2026-03-01", 14)


def test_select_sources_combines_country_and_source_filters():
    sources = load_sources()
    selected = _select_sources(sources, ["FR"], ["fr_anssi"])
    assert [source.id for source in selected] == ["fr_anssi"]


def test_select_sources_rejects_unknown_ids():
    with pytest.raises(SystemExit, match="未知來源代碼"):
        _select_sources(load_sources(), None, ["missing-source"])


def test_select_sources_skips_paused_sources_unless_explicitly_requested():
    source = Source(
        id="paused",
        country="EU",
        name_zh="暫停來源",
        name="Paused",
        institution_type="test",
        language="en",
        homepage="https://example.eu/",
        listing_url="https://example.eu/news",
        paused_until="2999-12-31",
        pause_reason="temporary outage",
        pause_evidence_url="https://example.eu/status",
    )
    assert _select_sources([source], None, None) == []
    assert _select_sources([source], None, ["paused"]) == [source]


def test_cli_parser_exposes_resilience_controls():
    args = build_parser().parse_args(
        ["--workers", "8", "--source-budget", "45", "--state-dir", ".state", "--no-translate", "--fail-on-degraded"]
    )
    assert args.workers == 8
    assert args.no_translate
    assert args.fail_on_degraded
    assert args.source_budget == 45
    assert args.state_dir == ".state"


def test_quality_gate_reports_stable_error_codes():
    from eu_cyber_news_scraper.models import SourceStatus

    args = build_parser().parse_args(
        ["--min-source-success-rate", "0.95", "--max-unexplained-future-dates", "0"]
    )
    statuses = [
        SourceStatus(
            "bad",
            "來源",
            "EU",
            False,
            False,
            "",
            0,
            0,
            0,
            invalid_date_count=1,
            unexplained_future_date_count=1,
            fetch_status="failed",
        ),
        SourceStatus("ok", "來源", "EU", False, True, "html", 1, 0, 0),
    ]
    assert [row["code"] for row in _quality_failures(statuses, args)] == [
        "SOURCE_SUCCESS_RATE_LOW",
        "FUTURE_DATE_LIMIT_EXCEEDED",
    ]


def test_source_success_gate_uses_fetch_status_not_parsed_card_count():
    from eu_cyber_news_scraper.models import SourceStatus

    args = build_parser().parse_args(["--min-source-success-rate", "1"])
    connected_but_empty = SourceStatus(
        "empty",
        "來源",
        "EU",
        False,
        False,
        "",
        0,
        0,
        0,
        fetch_status="ok",
        parse_status="empty",
    )

    assert _quality_failures([connected_but_empty], args) == []


def test_parse_and_empty_source_quality_gates_are_independent_from_transport():
    from eu_cyber_news_scraper.models import SourceStatus

    args = build_parser().parse_args(["--min-parse-success-rate", "1", "--max-empty-sources", "0"])
    connected_but_empty = SourceStatus(
        "empty",
        "來源",
        "EU",
        False,
        False,
        "",
        0,
        0,
        0,
        fetch_status="ok",
        parse_status="empty",
    )

    assert [row["code"] for row in _quality_failures([connected_but_empty], args)] == [
        "PARSE_SUCCESS_RATE_LOW",
        "EMPTY_SOURCE_LIMIT_EXCEEDED",
    ]


def test_overall_date_quality_gate_uses_article_weighted_rate():
    from eu_cyber_news_scraper.models import SourceStatus

    args = build_parser().parse_args(["--min-overall-date-rate", "0.8"])
    statuses = [
        SourceStatus("large", "來源", "EU", False, True, "html", 9, 0, 0, dated_count=9),
        SourceStatus("small", "來源", "EU", False, True, "html", 1, 0, 0, dated_count=0),
    ]
    assert _quality_failures(statuses, args) == []
    statuses[0] = SourceStatus("large", "來源", "EU", False, True, "html", 9, 0, 0, dated_count=7)
    assert [row["code"] for row in _quality_failures(statuses, args)] == ["OVERALL_DATE_RATE_LOW"]


def test_output_date_confidence_and_conflict_quality_gates():
    args = build_parser().parse_args(
        ["--min-high-confidence-date-rate", "0.75", "--max-date-conflict-rate", "0.05"]
    )
    articles = [
        Article(
            f"s{index}", "EU", "來源", "official", "en", f"Title {index}",
            f"https://example.eu/news/{index}",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            date_confidence="high" if index < 7 else "low",
            date_conflict=index == 0,
        )
        for index in range(10)
    ]
    articles[-1].published_at = None
    assert [row["code"] for row in _quality_failures([], args, articles)] == [
        "HIGH_CONFIDENCE_DATE_RATE_LOW",
        "DATE_CONFLICT_RATE_HIGH",
    ]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--min-parse-success-rate", "1.1"], "--min-parse-success-rate"),
        (["--min-overall-date-rate", "-0.1"], "--min-overall-date-rate"),
        (["--max-date-conflict-rate", "1.1"], "--max-date-conflict-rate"),
        (["--max-empty-sources", "-1"], "--max-empty-sources"),
    ],
)
def test_quality_options_reject_invalid_values(arguments, message):
    from eu_cyber_news_scraper.cli import _validate_quality_options

    with pytest.raises(SystemExit, match=message):
        _validate_quality_options(build_parser().parse_args(arguments))


def test_health_state_requires_a_successful_quality_eligible_run():
    from eu_cyber_news_scraper.models import SourceStatus

    healthy = SourceStatus("ok", "來源", "EU", True, True, "html", 1, 1, 0)
    failed_critical = SourceStatus(
        "bad", "來源", "EU", True, False, "", 0, 0, 0, fetch_status="failed", health_status="degraded"
    )
    assert _state_write_eligible([healthy], [])
    assert not _state_write_eligible([healthy], [{"code": "QUALITY_FAILED", "message": "failed"}])
    assert not _state_write_eligible([failed_critical], [])


def test_main_resolves_roc_period_and_releases_lock(monkeypatch, tmp_path):
    from eu_cyber_news_scraper import cli

    source = Source(
        "test", "EU", "來源", "Source", "official", "en",
        "https://example.eu", "https://example.eu/news",
    )
    calls = {}
    monkeypatch.setattr(cli, "load_sources", lambda path: (source,))
    monkeypatch.setattr(cli, "acquire_run_lock", lambda output, run_id: tmp_path / "run.lock")
    monkeypatch.setattr(cli, "release_run_lock", lambda lock, run_id: calls.update(released=(lock, run_id)))

    def run_pipeline(args, selected, since, until, output, run_id, *, period):
        calls.update(period=period, selected=selected, output=output, run_id=run_id)

    monkeypatch.setattr(cli, "_run_pipeline", run_pipeline)
    output = tmp_path / "result.xlsx"
    monkeypatch.setattr(
        sys,
        "argv",
        ["eu-cyber-news", "--source", "test", "--since", "1130405", "--until", "1130406", "--output", str(output)],
    )
    cli.main()
    assert calls["period"].start_date.isoformat() == "2024-04-05"
    assert calls["selected"] == [source]
    assert calls["output"] == output
    assert calls["released"][1] == calls["run_id"]


def test_main_lists_sources_without_starting_run(monkeypatch, capsys):
    from eu_cyber_news_scraper import cli

    monkeypatch.setattr(sys, "argv", ["eu-cyber-news", "--list-sources"])
    cli.main()
    assert "eu_dg_connect" in capsys.readouterr().out


def test_cli_reports_package_version(capsys):
    with pytest.raises(SystemExit, match="0"):
        build_parser().parse_args(["--version"])
    assert capsys.readouterr().out.endswith(" 1.3.1\n")


def test_main_reports_period_and_lock_errors(monkeypatch, tmp_path):
    from eu_cyber_news_scraper import cli

    monkeypatch.setattr(sys, "argv", ["eu-cyber-news", "--since", "1130405"])
    with pytest.raises(SystemExit, match="同時提供"):
        cli.main()
    monkeypatch.setattr(sys, "argv", ["eu-cyber-news", "--days", "1", "--output", str(tmp_path / "x.xlsx")])
    monkeypatch.setattr(cli, "acquire_run_lock", lambda output, run_id: (_ for _ in ()).throw(RuntimeError("busy")))
    with pytest.raises(SystemExit, match="busy"):
        cli.main()
