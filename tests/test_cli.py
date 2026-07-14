import sys
from datetime import timedelta

import pytest

from eu_cyber_news_scraper.cli import _date_range, _default_output, _select_sources, build_parser
from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.models import Source


def test_date_range_treats_until_as_inclusive_calendar_day():
    since, until = _date_range("2026-05-01", "2026-05-03", 14)
    assert (until - since) == timedelta(days=3)
    assert since.date().isoformat() == "2026-04-30"  # Taipei midnight expressed in UTC
    assert _default_output(since, until).name == "歐盟資安法制新聞_20260501-20260503.xlsx"


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


def test_cli_parser_exposes_resilience_controls():
    args = build_parser().parse_args(
        ["--workers", "8", "--source-budget", "45", "--state-dir", ".state", "--no-translate", "--fail-on-degraded"]
    )
    assert args.workers == 8
    assert args.no_translate
    assert args.fail_on_degraded
    assert args.source_budget == 45
    assert args.state_dir == ".state"


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


def test_main_reports_period_and_lock_errors(monkeypatch, tmp_path):
    from eu_cyber_news_scraper import cli

    monkeypatch.setattr(sys, "argv", ["eu-cyber-news", "--since", "1130405"])
    with pytest.raises(SystemExit, match="同時提供"):
        cli.main()
    monkeypatch.setattr(sys, "argv", ["eu-cyber-news", "--days", "1", "--output", str(tmp_path / "x.xlsx")])
    monkeypatch.setattr(cli, "acquire_run_lock", lambda output, run_id: (_ for _ in ()).throw(RuntimeError("busy")))
    with pytest.raises(SystemExit, match="busy"):
        cli.main()
