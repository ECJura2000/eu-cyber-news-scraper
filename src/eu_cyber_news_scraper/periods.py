from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import DEFAULT_DAYS, DEFAULT_TIMEZONE

ROC_YEAR_OFFSET = 1911


@dataclass(frozen=True)
class ParsedDate:
    value: date
    calendar: str
    raw: str


@dataclass(frozen=True)
class PeriodSelection:
    since: datetime
    until: datetime
    mode: str
    timezone: str
    start_date: date
    end_date: date
    raw_since: str = ""
    raw_until: str = ""
    since_calendar: str = "gregorian"
    until_calendar: str = "gregorian"
    days: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "mode": self.mode,
            "timezone": self.timezone,
            "raw_since": self.raw_since or None,
            "raw_until": self.raw_until or None,
            "since_calendar": self.since_calendar,
            "until_calendar": self.until_calendar,
            "normalized_since": self.start_date.isoformat(),
            "normalized_until": self.end_date.isoformat(),
            "period_start_utc": self.since.isoformat(),
            "period_end_exclusive_utc": self.until.isoformat(),
            "days": self.days,
        }


def parse_calendar_date(value: str) -> ParsedDate:
    raw = value.strip()
    if not raw:
        raise ValueError("日期不得為空白")
    explicit_roc = raw.startswith("民國")
    normalized = raw[2:].strip() if explicit_roc else raw

    if normalized.isdigit():
        if explicit_roc:
            if len(normalized) != 7:
                raise ValueError("民國純數字日期必須為 YYYMMDD")
            calendar = "roc"
        elif len(normalized) == 7:
            calendar = "roc"
        elif len(normalized) == 8:
            calendar = "gregorian"
        else:
            raise ValueError("純數字日期必須為民國 YYYMMDD 或西元 YYYYMMDD")
        year_digits = 3 if calendar == "roc" else 4
        year = int(normalized[:year_digits])
        month = int(normalized[year_digits : year_digits + 2])
        day = int(normalized[year_digits + 2 :])
    else:
        match = re.fullmatch(r"(\d{1,4})([-/])(\d{1,2})\2(\d{1,2})", normalized)
        if not match:
            raise ValueError("日期格式不受支援")
        year_text, _, month_text, day_text = match.groups()
        if explicit_roc:
            calendar = "roc"
        elif len(year_text) == 3:
            calendar = "roc"
        elif len(year_text) == 4:
            calendar = "gregorian"
        else:
            raise ValueError("分隔日期年份必須為三位民國年或四位西元年")
        year, month, day = int(year_text), int(month_text), int(day_text)

    if calendar == "roc":
        if year < 1:
            raise ValueError("民國年必須大於 0")
        year += ROC_YEAR_OFFSET
    try:
        parsed = date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"無效日期：{raw}") from exc
    return ParsedDate(parsed, calendar, raw)


def resolve_period(
    since_value: str | None,
    until_value: str | None,
    days: int | None,
    *,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> PeriodSelection:
    has_explicit = since_value is not None or until_value is not None
    if has_explicit:
        if not since_value or not until_value:
            raise ValueError("--since 與 --until 必須同時提供")
        if days is not None:
            raise ValueError("--days 不可與 --since、--until 同時使用")
        parsed_since = parse_calendar_date(since_value)
        parsed_until = parse_calendar_date(until_value)
        start_date, end_date = parsed_since.value, parsed_until.value
        mode = "fixed"
        raw_since, raw_until = parsed_since.raw, parsed_until.raw
        since_calendar, until_calendar = parsed_since.calendar, parsed_until.calendar
        resolved_days = None
    else:
        resolved_days = DEFAULT_DAYS if days is None else days
        if resolved_days < 0:
            raise ValueError("--days 不可為負數")
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone) if now else datetime.now(zone)
        end_date = local_now.date()
        start_date = end_date - timedelta(days=resolved_days)
        mode = "rolling"
        raw_since = raw_until = ""
        since_calendar = until_calendar = "gregorian"

    if start_date > end_date:
        raise ValueError("起始日不得晚於結束日")
    zone = ZoneInfo(timezone_name)
    since = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(timezone.utc)
    until = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    return PeriodSelection(
        since=since,
        until=until,
        mode=mode,
        timezone=timezone_name,
        start_date=start_date,
        end_date=end_date,
        raw_since=raw_since,
        raw_until=raw_until,
        since_calendar=since_calendar,
        until_calendar=until_calendar,
        days=resolved_days,
    )
