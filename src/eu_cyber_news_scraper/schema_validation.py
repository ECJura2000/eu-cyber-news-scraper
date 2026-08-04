from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def validate_schema_payload(payload: dict[str, Any], schema_name: str) -> None:
    schema_path = files("eu_cyber_news_scraper").joinpath("schemas", schema_name)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
