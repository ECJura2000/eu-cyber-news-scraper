from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA_VERSION = 1
TEMPLATE_NAME = "organisation.example.json"
TOPICS = frozenset(
    {
        "AI法", "跨境資料流通", "隱私框架", "數位身份", "著作權", "平台責任",
        "媒體多元", "NIS2", "產品資安", "半導體", "量子技術", "供應鏈安全",
        "事件應變", "數位治理", "研究創新",
    }
)


@dataclass(frozen=True)
class OrganisationModule:
    canonical_id: str
    module_version: str
    payload: dict[str, Any]
    source_path: str
    external: bool

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(self.payload["source_ids"])


@dataclass(frozen=True)
class OrganisationRegistry:
    modules: tuple[OrganisationModule, ...]
    errors: tuple[str, ...]
    registry_hash: str

    @property
    def source_ids(self) -> frozenset[str]:
        return frozenset(source_id for module in self.modules for source_id in module.source_ids)


def builtin_registry_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "organisation_registry"
    return Path(__file__).resolve().parents[2] / "organisation_registry"


def external_registry_dir() -> Path:
    if configured := os.environ.get("EU_CYBER_ORGANISATION_DIR"):
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/EUCyberNewsScraper/organisations.d"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "eu-cyber-news-scraper/organisations.d"


def load_organisation_registry(
    *, builtin_dir: Path | None = None, external_dir: Path | None = None,
    known_source_ids: set[str] | None = None,
) -> OrganisationRegistry:
    builtin_dir = builtin_dir or builtin_registry_dir()
    external_dir = external_dir or external_registry_dir()
    builtins, builtin_errors = _load_directory(builtin_dir, False)
    if builtin_errors:
        raise ValueError("Invalid built-in organisation registry: " + "; ".join(builtin_errors))
    active = {module.canonical_id: module for module in builtins}
    external, errors = _load_directory(external_dir, True)
    for module in external:
        active[module.canonical_id] = module
    valid: dict[str, OrganisationModule] = {}
    for module in active.values():
        unknown = sorted(set(module.source_ids) - known_source_ids) if known_source_ids is not None else []
        if unknown:
            errors.append(f"{module.source_path}: unknown source_ids: {unknown}")
            if module.external and module.canonical_id in {item.canonical_id for item in builtins}:
                valid[module.canonical_id] = next(item for item in builtins if item.canonical_id == module.canonical_id)
            continue
        valid[module.canonical_id] = module
    modules = tuple(sorted(valid.values(), key=lambda item: item.canonical_id.casefold()))
    normalized = [module.payload for module in modules]
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return OrganisationRegistry(modules, tuple(sorted(errors)), hashlib.sha256(encoded).hexdigest())


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
            if not isinstance(payload, dict) or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
                raise ValueError("invalid schema_version")
            required = {"module_version", "canonical_id", "names", "source_ids", "topics", "responsibility_by_topic"}
            if missing := required - payload.keys():
                raise ValueError(f"missing fields: {sorted(missing)}")
            canonical_id = str(payload["canonical_id"]).strip()
            if not canonical_id or canonical_id in seen:
                raise ValueError(f"duplicate canonical_id: {canonical_id}")
            if not payload["source_ids"] or not all(isinstance(value, str) and value for value in payload["source_ids"]):
                raise ValueError("source_ids must be a non-empty string list")
            if unknown := sorted(set(payload["topics"]) - TOPICS):
                raise ValueError(f"unknown topics: {unknown}")
            seen.add(canonical_id)
            modules.append(OrganisationModule(canonical_id, str(payload["module_version"]), payload, str(path), external))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return modules, errors
