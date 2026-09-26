from __future__ import annotations

import json
from pathlib import Path

import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.organisation_registry import (
    _validate_payload,
    export_example,
    external_registry_dir,
    load_organisation_registry,
)


def test_builtin_registry_covers_all_configured_sources():
    sources = load_sources()
    registry = load_organisation_registry()
    assert {source.id for source in sources} == set(registry.source_ids)
    assert len(registry.modules) == 148
    assert not registry.errors
    assert len(registry.registry_hash) == 64
    assert all(module.topics for module in registry.modules)
    assert len(registry.source_rows) == 148
    assert registry.module_for_source("missing") is None


def test_external_override_wins_and_invalid_new_module_is_reported(tmp_path):
    builtin = load_organisation_registry()
    module = next(module for module in builtin.modules if module.canonical_id == "eu_dg_connect")
    payload = json.loads(Path(module.source_path).read_text(encoding="utf-8"))
    payload["module_version"] = "external-test"
    (tmp_path / "eu_dg_connect.json").write_text(json.dumps(payload), encoding="utf-8")
    invalid = dict(payload)
    invalid["schema_version"] = 999
    invalid["canonical_id"] = "new_invalid"
    (tmp_path / "new-invalid.json").write_text(json.dumps(invalid), encoding="utf-8")

    registry = load_organisation_registry(external_dir=tmp_path)

    overridden = next(module for module in registry.modules if module.canonical_id == "eu_dg_connect")
    assert overridden.external
    assert registry.overrides == ("eu_dg_connect",)
    assert any("invalid schema_version" in error for error in registry.errors)
    assert registry.audit_payload()["organisation_audit_status"] == "degraded"


def test_invalid_external_override_falls_back_to_builtin(tmp_path):
    builtin = load_organisation_registry()
    module = next(module for module in builtin.modules if module.canonical_id == "eu_edpb")
    payload = json.loads(Path(module.source_path).read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    (tmp_path / "eu_edpb.json").write_text(json.dumps(payload), encoding="utf-8")

    registry = load_organisation_registry(external_dir=tmp_path)

    active = next(module for module in registry.modules if module.canonical_id == "eu_edpb")
    assert not active.external
    assert registry.errors


def test_valid_external_new_module_loads_and_duplicate_source_is_skipped(tmp_path):
    builtin = load_organisation_registry()
    source_module = next(module for module in builtin.modules if module.canonical_id == "eu_edpb")
    payload = json.loads(Path(source_module.source_path).read_text(encoding="utf-8"))
    payload["canonical_id"] = "new_authority"
    payload["sources"][0]["id"] = "new_authority"
    payload["sources"][0]["homepage"] = "https://new.example.eu/"
    payload["sources"][0]["listing_url"] = "https://new.example.eu/news"
    payload["history"]["transitional_sources"] = ["eu_edpb"]
    (tmp_path / "new.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_organisation_registry(external_dir=tmp_path)
    assert loaded.module_for_source("new_authority").external
    assert loaded.audit_payload()["transitional_sources"] == ["eu_edpb"]

    payload["canonical_id"] = "duplicate_authority"
    payload["sources"][0]["id"] = "eu_edpb"
    (tmp_path / "duplicate.json").write_text(json.dumps(payload), encoding="utf-8")
    duplicated = load_organisation_registry(external_dir=tmp_path)
    assert any("already provided" in error for error in duplicated.errors)
    assert duplicated.module_for_source("eu_edpb") is not None


def test_registry_paths_and_example_export(monkeypatch, tmp_path):
    configured = tmp_path / "organisations.d"
    monkeypatch.setenv("EU_CYBER_ORGANISATION_DIR", str(configured))
    assert external_registry_dir() == configured
    exported = export_example(tmp_path / "exported" / "example.json")
    assert json.loads(exported.read_text(encoding="utf-8"))["schema_version"] == 2


def test_invalid_builtin_registry_is_fatal(tmp_path):
    (tmp_path / "broken.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid built-in"):
        load_organisation_registry(builtin_dir=tmp_path)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda payload: payload.pop("health"), "missing fields"),
        (lambda payload: payload.update(canonical_id=""), "must not be blank"),
        (lambda payload: payload.update(sources=[]), "non-empty list"),
        (lambda payload: payload["sources"][0].pop("name"), "source missing fields"),
        (lambda payload: payload["sources"][0].update(country="UK"), "unsupported source country"),
        (lambda payload: payload["sources"][0].update(homepage="http://example.eu"), "must use https"),
        (lambda payload: payload.update(filter={"topics": []}), "non-empty list"),
        (lambda payload: payload.update(filter={"topics": ["unknown"]}), "unknown topics"),
        (
            lambda payload: payload.update(responsibility_by_topic={"數位身份": "owner"}),
            "responsibility topics",
        ),
    ],
)
def test_registry_schema_validation_rejects_invalid_fields(mutation, message):
    module = next(module for module in load_organisation_registry().modules if module.canonical_id == "eu_edpb")
    payload = json.loads(Path(module.source_path).read_text(encoding="utf-8"))
    mutation(payload)
    with pytest.raises(ValueError, match=message):
        _validate_payload(payload)
