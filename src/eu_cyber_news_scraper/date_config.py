"""Validate source-local publication date settings before network access."""
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateparser.data.languages_info import language_order


def validate_date_settings(language: Any, timezone_name: Any, order: Any, formats: Any) -> None:
    if not isinstance(language, str) or language.split('-')[0] not in {*language_order, 'no'}:
        raise ValueError('invalid date language')
    if not isinstance(timezone_name, str):
        raise ValueError('invalid timezone')
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f'invalid timezone: {timezone_name}') from exc
    if order not in ('DMY', 'MDY', 'YMD'):
        raise ValueError('date_order must be DMY, MDY or YMD')
    if not isinstance(formats, (list, tuple)):
        raise ValueError('date_formats must be an array')
    for value in formats:
        if not isinstance(value, str) or not value or len(value) > 120 or '%Y' not in value:
            raise ValueError('date_formats must contain nonblank formats with a four-digit year (%Y)')
        if re.search(r'%(?![aAwdbBmYHIpMSfzZjUWGuV%])', value):
            raise ValueError(f'invalid date format directive: {value}')
        directives = set(re.findall(r'%(?:%|([A-Za-z]))', value))
        if not {'Y', 'd'} <= directives or not {'m', 'b', 'B'} & directives:
            raise ValueError('date_formats must specify a complete year, month and day')
