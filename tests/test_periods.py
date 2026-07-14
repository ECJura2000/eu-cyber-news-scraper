from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from eu_cyber_news_scraper.periods import parse_calendar_date, resolve_period


@pytest.mark.parametrize(
    ("raw", "expected", "calendar"),
    [
        ("2001-07-30", "2001-07-30", "gregorian"),
        ("2001/07/30", "2001-07-30", "gregorian"),
        ("20010730", "2001-07-30", "gregorian"),
        ("113-04-05", "2024-04-05", "roc"),
        ("113/04/05", "2024-04-05", "roc"),
        ("1130405", "2024-04-05", "roc"),
        ("民國113-04-05", "2024-04-05", "roc"),
        ("民國113/04/05", "2024-04-05", "roc"),
        ("民國1130405", "2024-04-05", "roc"),
        ("2024-02-29", "2024-02-29", "gregorian"),
    ],
)
def test_parse_calendar_date_formats(raw, expected, calendar):
    parsed = parse_calendar_date(raw)
    assert parsed.value.isoformat() == expected
    assert parsed.calendar == calendar


@pytest.mark.parametrize("raw", ["", "113040", "0000101", "民國0000101", "20230229", "1130230", "24-01-01"])
def test_parse_calendar_date_rejects_ambiguous_or_invalid_values(raw):
    with pytest.raises(ValueError):
        parse_calendar_date(raw)


def test_resolve_period_supports_mixed_calendars_and_inclusive_end():
    period = resolve_period("1130405", "2024-04-07", None)
    assert period.start_date.isoformat() == "2024-04-05"
    assert period.end_date.isoformat() == "2024-04-07"
    assert period.until - period.since == timedelta(days=3)
    assert period.since_calendar == "roc"
    assert period.until_calendar == "gregorian"


def test_resolve_period_requires_both_explicit_dates_and_rejects_days():
    with pytest.raises(ValueError, match="同時提供"):
        resolve_period("1130405", None, None)
    with pytest.raises(ValueError, match="不可與"):
        resolve_period("1130405", "1130406", 14)


def test_resolve_period_rolling_uses_taipei_calendar_day():
    now = datetime(2026, 7, 14, 8, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    period = resolve_period(None, None, 14, now=now)
    assert period.start_date.isoformat() == "2026-06-30"
    assert period.end_date.isoformat() == "2026-07-14"
    assert period.mode == "rolling"


def test_resolve_period_rejects_reversed_dates():
    with pytest.raises(ValueError, match="不得晚於"):
        resolve_period("1130406", "1130405", None)
