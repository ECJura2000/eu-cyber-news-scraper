from __future__ import annotations

import json
from pathlib import Path

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry


def test_builtin_registry_covers_all_configured_sources():
    sources = load_sources()
    registry = load_organisation_registry(known_source_ids={source.id for source in sources})
    assert {source.id for source in sources} == set(registry.source_ids)
    assert len(registry.modules) == 4
    assert not registry.errors
    assert len(registry.registry_hash) == 64


def test_external_override_wins_and_invalid_new_module_is_reported(tmp_path):
    builtin = load_organisation_registry()
    eu_module = next(module for module in builtin.modules if module.canonical_id == "EU")
    payload = json.loads(Path(eu_module.source_path).read_text(encoding="utf-8"))
    payload["module_version"] = "external-test"
    (tmp_path / "eu.json").write_text(json.dumps(payload), encoding="utf-8")
    invalid = dict(payload)
    invalid["canonical_id"] = "NEW"
    invalid["source_ids"] = ["missing-source"]
    (tmp_path / "new.json").write_text(json.dumps(invalid), encoding="utf-8")

    registry = load_organisation_registry(
        external_dir=tmp_path,
        known_source_ids={source.id for source in load_sources()},
    )

    assert next(module for module in registry.modules if module.canonical_id == "EU").external
    assert any("unknown source_ids" in error for error in registry.errors)
