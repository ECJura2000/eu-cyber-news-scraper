from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .topics import OBSERVATION_TOPICS

REGISTRY_SCHEMA_VERSION = 2
TEMPLATE_NAME = "organisation.example.json"
TOPICS = frozenset(OBSERVATION_TOPICS)


@dataclass(frozen=True)
class OrganisationModule:
    canonical_id: str
    module_version: str
    payload: dict[str, Any]
    source_path: str
    external: bool

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(row["id"] for row in self.payload["sources"])

    @property
    def topics(self) -> frozenset[str]:
        return frozenset(self.payload["filter"]["topics"])

    def responsibility_owner(self, topic: str) -> str:
        return str(self.payload["responsibility_by_topic"].get(topic, ""))


@dataclass(frozen=True)
class OrganisationRegistry:
    modules: tuple[OrganisationModule, ...]
    errors: tuple[str, ...]
    registry_hash: str
    overrides: tuple[str, ...] = ()

    @property
    def source_ids(self) -> frozenset[str]:
        return frozenset(source_id for module in self.modules for source_id in module.source_ids)

    @property
    def source_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(row for module in self.modules for row in module.payload["sources"])

    def module_for_source(self, source_id: str) -> OrganisationModule | None:
        return next((module for module in self.modules if source_id in module.source_ids), None)

    def audit_payload(self) -> dict[str, Any]:
        transitional_sources = [
            value
            for module in self.modules
            for value in module.payload["history"].get("transitional_sources", [])
        ]
        return {
            "organisation_registry_hash": self.registry_hash,
            "organisation_registry_version": self.registry_hash,
            "organisation_modules": [
                {
                    "canonical_id": module.canonical_id,
                    "module_version": module.module_version,
                    "source_path": module.source_path,
                    "external": module.external,
                    "source_ids": list(module.source_ids),
                }
                for module in self.modules
            ],
            "organisation_module_errors": list(self.errors),
            "organisation_module_overrides": list(self.overrides),
            "organisation_changes": list(self.errors),
            "transitional_sources": transitional_sources,
            "organisation_audit_status": "degraded" if self.errors else "complete",
        }


def builtin_registry_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "organisation_registry"
    candidates = (
        Path(__file__).resolve().parents[2] / "organisation_registry",
        Path(sys.prefix) / "organisation_registry",
        Path(__file__).resolve().parent / "organisation_registry",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])


def external_registry_dir() -> Path:
    if configured := os.environ.get("EU_CYBER_ORGANISATION_DIR"):
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/EUCyberNewsScraper/organisations.d"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "eu-cyber-news-scraper/organisations.d"


def export_example(destination: str | Path) -> Path:
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(builtin_registry_dir() / TEMPLATE_NAME, target)
    return target


def load_organisation_registry(
    *, builtin_dir: Path | None = None, external_dir: Path | None = None,
) -> OrganisationRegistry:
    builtin_dir = builtin_dir or builtin_registry_dir()
    external_dir = external_dir or external_registry_dir()
    builtins, builtin_errors = _load_directory(builtin_dir, False)
    if builtin_errors:
        raise ValueError("Invalid built-in organisation registry: " + "; ".join(builtin_errors))
    builtin_by_id = {module.canonical_id: module for module in builtins}
    active = dict(builtin_by_id)
    external, errors = _load_directory(external_dir, True)
    overrides: list[str] = []
    for module in external:
        if module.canonical_id in active:
            overrides.append(module.canonical_id)
        active[module.canonical_id] = module

    valid: dict[str, OrganisationModule] = {}
    used_source_ids: dict[str, str] = {}
    for module in sorted(active.values(), key=lambda item: item.canonical_id.casefold()):
        duplicate = next((source_id for source_id in module.source_ids if source_id in used_source_ids), "")
        if duplicate:
            errors.append(f"{module.source_path}: source id {duplicate} already provided by {used_source_ids[duplicate]}")
            fallback = builtin_by_id.get(module.canonical_id)
            if fallback is not None and fallback is not module:
                module = fallback
            else:
                continue
        valid[module.canonical_id] = module
        for source_id in module.source_ids:
            used_source_ids[source_id] = module.canonical_id

    modules = tuple(valid.values())
    normalized = [module.payload for module in modules]
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return OrganisationRegistry(
        modules, tuple(sorted(errors)), hashlib.sha256(encoded).hexdigest(), tuple(sorted(overrides))
    )


def _load_directory(directory: Path, external: bool) -> tuple[list[OrganisationModule], list[str]]:
    modules: list[OrganisationModule] = []
    errors: list[str] = []
    seen: set[str] = set()
    if not directory.exists():
        return modules, errors
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name.casefold()):
        if path.name == TEMPLATE_NAME:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            _validate_payload(payload)
            canonical_id = str(payload["canonical_id"]).strip()
            if canonical_id in seen:
                raise ValueError(f"duplicate canonical_id: {canonical_id}")
            seen.add(canonical_id)
            modules.append(
                OrganisationModule(canonical_id, str(payload["module_version"]), payload, str(path), external)
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return modules, errors


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("invalid schema_version")
    required = {
        "module_version", "canonical_id", "names", "sources", "filter", "health", "history",
        "responsibility_by_topic",
    }
    if missing := required - payload.keys():
        raise ValueError(f"missing fields: {sorted(missing)}")
    if not str(payload["canonical_id"]).strip():
        raise ValueError("canonical_id must not be blank")
    if not isinstance(payload["sources"], list) or not payload["sources"]:
        raise ValueError("sources must be a non-empty list")
    required_source = {"id", "country", "name_zh", "name", "institution_type", "language", "homepage", "listing_url"}
    for row in payload["sources"]:
        if not isinstance(row, dict) or (missing := required_source - row.keys()):
            raise ValueError(f"source missing fields: {sorted(missing)}")
        if row["country"] not in {"EU", "FR", "DE", "IE"}:
            raise ValueError(f"unsupported source country: {row['country']}")
        if not str(row["homepage"]).startswith("https://") or not str(row["listing_url"]).startswith("https://"):
            raise ValueError("source URLs must use https")
    topics = payload["filter"].get("topics") if isinstance(payload["filter"], dict) else None
    if not isinstance(topics, list) or not topics:
        raise ValueError("filter.topics must be a non-empty list")
    if unknown := sorted(set(topics) - TOPICS):
        raise ValueError(f"unknown topics: {unknown}")
    if unknown := sorted(set(payload["responsibility_by_topic"]) - set(topics)):
        raise ValueError(f"responsibility topics not in filter.topics: {unknown}")
