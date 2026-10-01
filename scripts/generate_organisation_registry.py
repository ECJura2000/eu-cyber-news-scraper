"""Export/check compatibility TOML from the canonical built-in JSON registry.

No arguments performs a read-only check. Writing requires --output or
--export-sources. Organisation metadata is never regenerated or written.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from dataclasses import fields
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, get_origin, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "src/eu_cyber_news_scraper/sources.toml"
REGISTRY_DIR = ROOT / "organisation_registry"

# Make direct execution independent of an editable install and the working directory.
if __name__ == "__main__":
    sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
from eu_cyber_news_scraper.config import _validate_sources  # noqa: E402
from eu_cyber_news_scraper.models import Source  # noqa: E402
from eu_cyber_news_scraper.organisation_registry import TEMPLATE_NAME, _validate_payload  # noqa: E402


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


def _source_index(rows: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError(f"{label}: sources must be a non-empty array")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            raise ValueError(f"{label}: each source needs a non-blank string id")
        if row["id"] in indexed:
            raise ValueError(f"{label}: duplicate source id: {row['id']}")
        indexed[row["id"]] = row
    return indexed


def _validate_source_rows(rows: list[dict[str, Any]]) -> None:
    """Use runtime contracts without coercing values or dropping export fields."""
    hints = get_type_hints(Source)
    sources = []
    for row in rows:
        values: dict[str, Any] = {}
        for field in fields(Source):
            if field.name not in row:
                continue
            value = row[field.name]
            expected = hints[field.name]
            if get_origin(expected) is tuple:
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise ValueError(f"{row['id']}: {field.name} must be an array of strings")
                values[field.name] = tuple(value)
            else:
                if type(value) is not expected:
                    raise ValueError(f"{row['id']}: {field.name} must be {expected.__name__}")
                values[field.name] = value
        if "date_optional" in row:
            if type(row["date_optional"]) is not bool:
                raise ValueError(f"{row['id']}: date_optional must be boolean")
            values.setdefault("date_policy", "best_effort" if row["date_optional"] else "required")
        sources.append(Source(**values))
    _validate_sources(sources)


def load_source_rows(registry_dir: Path = REGISTRY_DIR) -> list[dict[str, Any]]:
    """Load only built-ins; never consult environment or per-user overrides."""
    if not registry_dir.is_dir():
        raise ValueError(f"Registry directory does not exist: {registry_dir}")
    rows: list[dict[str, Any]] = []
    canonical_ids: set[str] = set()
    for path in sorted(registry_dir.glob("*.json")):
        if path.name == TEMPLATE_NAME:
            continue
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=_json_object, parse_constant=_reject_constant,
            )
            if not isinstance(payload, dict):
                raise ValueError("module must be an object")
            if type(payload.get("schema_version")) is not int:
                raise ValueError("schema_version must be an integer")
            for name in ("canonical_id", "module_version"):
                if not isinstance(payload.get(name), str) or not payload[name].strip():
                    raise ValueError(f"{name} must be a non-blank string")
            for name in ("names", "filter", "health", "history", "responsibility_by_topic"):
                if not isinstance(payload.get(name), dict):
                    raise ValueError(f"{name} must be an object")
            _validate_payload(payload)
            canonical_id = payload["canonical_id"].strip()
            if canonical_id in canonical_ids:
                raise ValueError(f"duplicate canonical_id: {canonical_id}")
            canonical_ids.add(canonical_id)
            rows.extend(payload["sources"])
        except (OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
            raise ValueError(f"Invalid registry module {path}: {exc}") from exc
    _source_index(rows, str(registry_dir))
    _validate_source_rows(rows)
    # Also reject values that cannot be represented by TOML, before any write.
    for row in rows:
        _toml_value(row)
    return sorted(rows, key=lambda row: row["id"])


def _toml_string(value: str) -> str:
    value.encode("utf-8")  # Unpaired Unicode surrogates are not valid TOML strings.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if not -(2**63) <= value < 2**63:
            raise ValueError("integer is outside the TOML signed 64-bit range")
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number cannot be exported")
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return "{ " + ", ".join(
            f"{_toml_string(key)} = {_toml_value(value[key])}" for key in sorted(value)
        ) + " }"
    raise ValueError(f"value of type {type(value).__name__} cannot be represented in TOML")


def _same_value(left: Any, right: Any) -> bool:
    """Python equality alone conflates TOML booleans, integers and floats."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_value(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right, strict=True))
    return bool(left == right)


def serialize_sources(rows: list[dict[str, Any]]) -> str:
    indexed = _source_index(rows, "registry")
    ordered = [indexed[source_id] for source_id in sorted(indexed)]
    lines = [
        "# Generated from organisation_registry/*.json; edit the canonical JSON modules.",
        "# Regenerate with: python scripts/generate_organisation_registry.py --export-sources",
    ]
    for row in ordered:
        lines.extend(("", "[[sources]]"))
        for key in sorted(row, key=lambda key: (key != "id", key)):
            lines.append(f"{_toml_string(key)} = {_toml_value(row[key])}")
    output = "\n".join(lines) + "\n"
    if not _same_value(tomllib.loads(output), {"sources": ordered}):
        raise ValueError("TOML serialization changed source values or types")
    return output


def check_sources(rows: list[dict[str, Any]], sources_path: Path = SOURCES_PATH) -> None:
    expected = _source_index(rows, "registry")
    with sources_path.open("rb") as stream:
        document = tomllib.load(stream)
    if document.keys() != {"sources"}:
        raise ValueError(f"{sources_path}: expected only the sources table array")
    actual = _source_index(document["sources"], str(sources_path))
    differences = []
    if missing := sorted(expected.keys() - actual.keys()):
        differences.append(f"missing sources: {', '.join(missing)}")
    if extra := sorted(actual.keys() - expected.keys()):
        differences.append(f"unexpected sources: {', '.join(extra)}")
    for source_id in sorted(expected.keys() & actual.keys()):
        left, right = expected[source_id], actual[source_id]
        changed = sorted(
            key for key in left.keys() | right.keys()
            if key not in left or key not in right or not _same_value(left[key], right[key])
        )
        if changed:
            differences.append(f"{source_id}: differing fields: {', '.join(changed)}")
    if differences:
        raise ValueError(f"{sources_path} is out of sync with the registry: " + "; ".join(differences))


def _export_sources(rows: list[dict[str, Any]], output: Path, registry_dir: Path) -> None:
    target = output.resolve()
    protected_dirs = {REGISTRY_DIR.resolve(), registry_dir.resolve()}
    if target.suffix.lower() == ".json" or any(target.is_relative_to(directory) for directory in protected_dirs):
        raise ValueError(f"Refusing to overwrite canonical registry metadata: {output}")
    if target.exists() and any(
        target.samefile(path) for directory in protected_dirs for path in directory.glob("*.json")
    ):
        raise ValueError(f"Refusing to overwrite a link to canonical registry metadata: {output}")
    output_text = serialize_sources(rows)
    target.write_text(output_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true", help="Check semantic compatibility without writing")
    actions.add_argument(
        "--export-sources", nargs="?", const=SOURCES_PATH, type=Path, metavar="PATH",
        help="Explicitly export to sources.toml (or PATH)",
    )
    parser.add_argument("--output", type=Path, help="Explicit export destination; with --check, the file to check")
    parser.add_argument("--registry-dir", "--builtin-dir", type=Path, default=REGISTRY_DIR, help="Built-in JSON directory")
    parser.add_argument("--sources-path", type=Path, default=SOURCES_PATH, help="Compatibility TOML to check")
    args = parser.parse_args(argv)
    try:
        rows = load_source_rows(args.registry_dir)
        if args.check or (args.output is None and args.export_sources is None):
            check_sources(rows, args.output or args.sources_path)
            print(f"Registry and compatibility TOML are in sync ({len(rows)} sources).")
        else:
            destination = args.output or args.export_sources
            _export_sources(rows, destination, args.registry_dir)
            print(f"Exported {len(rows)} sources to {destination}.")
    except (OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
        print(f"Registry export/check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
