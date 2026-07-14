from datetime import timedelta

import pytest

from eu_cyber_news_scraper.cli import _date_range, _default_output, _select_sources, build_parser
from eu_cyber_news_scraper.config import load_sources


def test_date_range_treats_until_as_inclusive_calendar_day():
    since, until = _date_range("2026-05-01", "2026-05-03", 14)
    assert (until - since) == timedelta(days=3)
    assert since.date().isoformat() == "2026-04-30"  # Taipei midnight expressed in UTC
    assert _default_output(since, until).name == "歐盟資安法制新聞_20260501-20260503.xlsx"


def test_date_range_rejects_invalid_calendar_dates():
    with pytest.raises(SystemExit, match="YYYY-MM-DD"):
        _date_range("2026-02-30", None, 14)


def test_select_sources_combines_country_and_source_filters():
    sources = load_sources()
    selected = _select_sources(sources, ["FR"], ["fr_anssi"])
    assert [source.id for source in selected] == ["fr_anssi"]


def test_select_sources_rejects_unknown_ids():
    with pytest.raises(SystemExit, match="未知來源代碼"):
        _select_sources(load_sources(), None, ["missing-source"])


def test_cli_parser_exposes_resilience_controls():
    args = build_parser().parse_args(["--workers", "8", "--no-translate", "--fail-on-degraded"])
    assert args.workers == 8
    assert args.no_translate
    assert args.fail_on_degraded
