from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from pathlib import Path

from .models import Source


@dataclass(frozen=True)
class CoverageRow:
    topic: str
    country: str
    authorities: str
    source_ids: tuple[str, ...]
    roles: str
    evidence_urls: tuple[str, ...]
    verified_on: str


def load_coverage(
    sources: list[Source] | tuple[Source, ...], *, validate_source_ids: bool = True
) -> tuple[CoverageRow, ...]:
    path = Path(str(files("eu_cyber_news_scraper").joinpath("authority_coverage.toml")))
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    known = {source.id for source in sources}
    source_map = {source.id: source for source in sources}
    if not validate_source_ids:
        from .config import load_sources

        source_map = {source.id: source for source in load_sources()} | source_map
    verified_on = str(data.get("verified_on", ""))
    try:
        date.fromisoformat(verified_on)
    except ValueError as exc:
        raise ValueError("authority coverage requires an ISO verified_on date") from exc
    rows: list[CoverageRow] = []
    for topic in data.get("topics", []):
        for country in ("EU", "FR", "DE", "IE"):
            entry = topic.get(country, {})
            source_ids = tuple(entry.get("source_ids", []))
            unknown = sorted(set(source_ids) - known)
            if unknown and validate_source_ids:
                raise ValueError(f"{topic['name']} {country}: unknown source ids: {', '.join(unknown)}")
            if not entry.get("authorities") or not source_ids:
                raise ValueError(f"{topic['name']} {country}: authority coverage is incomplete")
            evidence_urls = tuple(
                dict.fromkeys(
                    [*entry.get("evidence_urls", []), *(source_map[source_id].homepage for source_id in source_ids if source_id in source_map)]
                )
            )
            roles = "；".join(dict.fromkeys(source_map[source_id].institution_type for source_id in source_ids if source_id in source_map))
            if not evidence_urls or not roles:
                raise ValueError(f"{topic['name']} {country}: evidence or role coverage is incomplete")
            rows.append(
                CoverageRow(topic["name"], country, entry["authorities"], source_ids, roles, evidence_urls, verified_on)
            )
    if len(rows) != 60:
        raise ValueError(f"Expected 15 topics x 4 jurisdictions, got {len(rows)} rows")
    return tuple(rows)
