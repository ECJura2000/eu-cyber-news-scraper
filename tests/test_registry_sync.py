from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_organisation_registry.py"
SPEC = importlib.util.spec_from_file_location("registry_sync", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


@pytest.fixture
def payload():
    return json.loads((ROOT / "organisation_registry/at_cert.json").read_text(encoding="utf-8"))


def write_module(directory, payload, name="module.json"):
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def snapshot(directory):
    return {
        path.relative_to(directory): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in directory.rglob("*") if path.is_file()
    }


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd or ROOT,
        capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("action", ["output", "export-sources", "export-and-output"])
def test_export_never_rewrites_registry_metadata(payload, tmp_path, action):
    registry_dir = tmp_path / "registry"
    payload["history"]["predecessors"] = ["older_cert"]
    payload["history"]["transitional_sources"] = ["transitional_cert"]
    payload["verification"]["last_smoke"]["reason"] = "Preserve evidence and smoke history"
    write_module(registry_dir, payload)
    (registry_dir / "organisation.example.json").write_text("example remains untouched", encoding="utf-8")
    before = snapshot(registry_dir)
    output = tmp_path / "sources.toml"
    if action == "output":
        args = ["--output", output]
    elif action == "export-sources":
        args = ["--export-sources", output]
    else:
        args = ["--export-sources", "--output", output]

    result = run_cli("--registry-dir", registry_dir, *args, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert snapshot(registry_dir) == before
    assert tomllib.loads(output.read_text(encoding="utf-8")) == {"sources": payload["sources"]}
    assert sync.main(["--check", "--registry-dir", str(registry_dir), "--output", str(output)]) == 0
    assert snapshot(registry_dir) == before


@pytest.mark.parametrize("action", ["--output", "--export-sources"])
@pytest.mark.parametrize("kind", ["direct", "symlink", "hardlink", "inside-directory", "example"])
def test_explicit_export_cannot_overwrite_canonical_json(payload, tmp_path, action, kind):
    registry_dir = tmp_path / "registry"
    module = write_module(registry_dir, payload)
    if kind == "direct":
        destination = module
    elif kind == "example":
        destination = registry_dir / "organisation.example.json"
        destination.write_text("preserve template", encoding="utf-8")
    elif kind == "inside-directory":
        destination = registry_dir / "sources.toml"
    else:
        destination = tmp_path / "alias.toml"
        if kind == "symlink":
            destination.symlink_to(module)
        else:
            os.link(module, destination)
    before = snapshot(registry_dir)

    result = run_cli("--registry-dir", registry_dir, action, destination)

    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr
    assert snapshot(registry_dir) == before


def test_check_and_default_action_are_read_only(payload, tmp_path, monkeypatch):
    registry_dir = tmp_path / "registry"
    write_module(registry_dir, payload)
    compatibility = tmp_path / "sources.toml"
    compatibility.write_text(sync.serialize_sources(payload["sources"]), encoding="utf-8")
    before = snapshot(tmp_path)

    def forbid_write(*args, **kwargs):
        pytest.fail("read-only check attempted to write a file")

    monkeypatch.setattr(Path, "write_text", forbid_write)
    for args in (["--check"], []):
        assert sync.main([*args, "--registry-dir", str(registry_dir), "--sources-path", str(compatibility)]) == 0
    assert snapshot(tmp_path) == before


def test_external_overrides_are_ignored(payload, tmp_path, monkeypatch):
    registry_dir = tmp_path / "registry"
    write_module(registry_dir, payload)
    external_dir = tmp_path / "external"
    override = copy.deepcopy(payload)
    override["sources"][0]["listing_url"] = "https://www.cert.at/tampered"
    write_module(external_dir, override)
    monkeypatch.setenv("EU_CYBER_ORGANISATION_DIR", str(external_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(external_dir))

    assert sync.load_source_rows(registry_dir) == payload["sources"]
    output = tmp_path / "sources.toml"
    result = run_cli("--builtin-dir", registry_dir, "--output", output)
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(output.read_text(encoding="utf-8"))["sources"] == payload["sources"]


@pytest.mark.parametrize("scope", ["within-module", "across-modules"])
def test_duplicate_sources_are_fatal(payload, tmp_path, scope):
    if scope == "within-module":
        payload["sources"].append(copy.deepcopy(payload["sources"][0]))
        write_module(tmp_path, payload)
    else:
        write_module(tmp_path, payload)
        other = copy.deepcopy(payload)
        other["canonical_id"] = "another_module"
        write_module(tmp_path, other, "other.json")
    with pytest.raises(ValueError, match="duplicate source id"):
        sync.load_source_rows(tmp_path)


def test_duplicate_canonical_ids_are_fatal(payload, tmp_path):
    write_module(tmp_path, payload)
    payload["sources"][0]["id"] = "another_source"
    write_module(tmp_path, payload, "other.json")
    with pytest.raises(ValueError, match="duplicate canonical_id"):
        sync.load_source_rows(tmp_path)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(schema_version=999), "schema_version"),
        (lambda p: p.update(schema_version=2.0), "schema_version"),
        (lambda p: p.pop("verification")["status"], None),
        (lambda p: p.update(canonical_id=""), "canonical_id"),
        (lambda p: p.update(module_version=None), "module_version"),
        (lambda p: p.update(history=[]), "history"),
        (lambda p: p.update(health=None), "health"),
        (lambda p: p.update(sources=[]), "non-empty"),
        (lambda p: p["sources"][0].update(country="XX"), "country"),
        (lambda p: p["sources"][0].update(schedule_enabled="false"), "boolean"),
        (lambda p: p["sources"][0].update(critical=1), "critical"),
        (lambda p: p["sources"][0].update(detail_pages=True), "detail_pages"),
        (lambda p: p["sources"][0].update(feed_urls="https://example.org"), "array of strings"),
        (lambda p: p["sources"][0].update(include_patterns=["["]), "regex"),
        (lambda p: p["sources"][0].update(date_policy="bad"), "date_policy"),
        (lambda p: p["sources"][0].update(homepage="http://example.org"), "https"),
        (lambda p: p["sources"][0].update(extra=None), "cannot be represented"),
        (lambda p: p["sources"][0].update(extra=2**63), "64-bit"),
        (lambda p: p["sources"][0].update(extra=float("nan")), "JSON constant"),
        (lambda p: p["sources"][0].update(extra=float("inf")), "JSON constant"),
        (lambda p: p["verification"].update(status="bad"), "verification status"),
        (lambda p: p["verification"].update(verified_on="yesterday"), "ISO date"),
        (lambda p: p["filter"].update(topics=["unknown"]), "unknown topics"),
    ],
)
def test_invalid_registry_fails_before_any_output_write(payload, tmp_path, mutate, message):
    # Verification is optional in schema-v2; removing it is valid.
    mutate(payload)
    registry_dir = tmp_path / "registry"
    write_module(registry_dir, payload)
    output = tmp_path / "sources.toml"
    output.write_text("preserve old compatibility file", encoding="utf-8")
    before = snapshot(tmp_path)

    result = run_cli("--registry-dir", registry_dir, "--output", output)

    if message is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert message in result.stderr
        assert snapshot(tmp_path) == before
        checked = run_cli("--registry-dir", registry_dir, "--check", "--output", output)
        assert checked.returncode != 0
        assert message in checked.stderr
        assert snapshot(tmp_path) == before


@pytest.mark.parametrize("contents", ["{", "[]", '{"schema_version": 2, "schema_version": 2}'])
def test_bad_json_is_fatal(tmp_path, contents):
    (tmp_path / "broken.json").write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid registry module"):
        sync.load_source_rows(tmp_path)


@pytest.mark.parametrize("directory", ["missing", "empty", "template-only"])
def test_missing_or_empty_registry_is_fatal(tmp_path, directory):
    registry_dir = tmp_path / directory
    if directory != "missing":
        registry_dir.mkdir()
    if directory == "template-only":
        (registry_dir / "organisation.example.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="does not exist|non-empty"):
        sync.load_source_rows(registry_dir)


def test_roundtrip_preserves_every_key_regex_unicode_arrays_and_types(payload, tmp_path):
    row = payload["sources"][0]
    row.update(
        name='國家 CERT／é "quoted" \\ slash 🛰️\n第二行\tTab\x00\x7f',
        include_patterns=[r'^/news/\d{4}/(?P<slug>[\w-]+)\?q=".+"$', r"\b資安\b"],
        exclude_patterns=[r"/archive(?:\?|$)", "literal's quote"],
        date_policy="unavailable", date_exception_reason="保留例外理由",
        date_evidence_url="https://www.cert.at/evidence", date_reviewed_on="2026-09-30",
        date_review_due="2027-01-01", custom_float=1.0, tiny_float=1e-200,
        negative_zero=-0.0, big_integer=2**63 - 1, empty_array=[], empty_table={},
        mixed_array=[True, 1, 1.0, "2026-09-30", {"資料": ["é", False]}],
    )
    row['quoted.key "\\"'] = {"nested.key": [{"Unicode": "資料", "enabled": False}], "empty": []}
    write_module(tmp_path, payload)
    rows = sync.load_source_rows(tmp_path)

    text = sync.serialize_sources(rows)
    parsed = tomllib.loads(text)["sources"]

    assert sync._same_value(parsed, payload["sources"])
    assert isinstance(parsed[0]["date_reviewed_on"], str)
    assert type(parsed[0]["custom_float"]) is float
    assert type(parsed[0]["mixed_array"][0]) is bool
    assert type(parsed[0]["mixed_array"][1]) is int
    assert "資安" in text
    reordered = [{key: value for key, value in reversed(list(row.items()))}]
    assert sync.serialize_sources(reordered) == text


def test_serializer_preserves_native_toml_date_and_time_types():
    row = {
        "id": "native_toml_types", "date": date(2026, 9, 30), "time": time(12, 34, 56, 123456),
        "local_datetime": datetime(2026, 9, 30, 12, 34),
        "offset_datetime": datetime(2026, 9, 30, 12, 34, tzinfo=timezone.utc),
    }
    assert sync._same_value(tomllib.loads(sync.serialize_sources([row]))["sources"], [row])


def test_builtin_registry_exports_all_eu_members_plus_eu_and_norway():
    rows = sync.load_source_rows()
    countries = {row["country"] for row in rows}
    assert len(countries) > 27
    assert {"EU", "NO", "AT", "BG", "CY", "SK", "SI"} <= countries
    document = tomllib.loads(sync.serialize_sources(rows))
    assert sync._same_value(document["sources"], rows)
    assert len(document["sources"]) == len(rows)


def test_check_ignores_comments_key_order_and_source_order(payload, tmp_path):
    first = payload["sources"][0]
    second = {**first, "id": "zz_second"}
    rows = [first, second]
    compatibility = tmp_path / "sources.toml"
    blocks = sync.serialize_sources(rows).split("[[sources]]")
    compatibility.write_text("# handwritten comments\n\n" + "[[sources]]" + blocks[2] + "[[sources]]" + blocks[1])

    sync.check_sources(rows, compatibility)


@pytest.mark.parametrize("change", ["modify", "omit", "extra-field", "missing-source", "extra-source", "type", "array"])
def test_stale_or_tampered_toml_is_detected_without_writes(payload, tmp_path, change):
    registry_dir = tmp_path / "registry"
    write_module(registry_dir, payload)
    rows = copy.deepcopy(payload["sources"])
    rows.append({**rows[0], "id": "obsolete"})
    if change == "modify":
        rows[0]["listing_url"] = "https://www.cert.at/tampered"
    elif change == "omit":
        rows[0].pop("schedule_enabled")
    elif change == "extra-field":
        rows[0]["unknown_extra"] = "tampered"
    elif change == "extra-source":
        pass
    elif change == "missing-source":
        rows.pop(0)
    elif change == "type":
        rows[0]["detail_pages"] = float(rows[0]["detail_pages"])
    else:
        rows[0]["feed_urls"].reverse()
    if change not in {"missing-source", "extra-source"}:
        rows.pop()
    compatibility = tmp_path / "sources.toml"
    compatibility.write_text(sync.serialize_sources(rows), encoding="utf-8")
    before = snapshot(tmp_path)

    result = run_cli("--check", "--registry-dir", registry_dir, "--output", compatibility)

    assert result.returncode != 0
    assert "out of sync" in result.stderr
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("kind", ["missing", "invalid", "duplicate", "other-top-level"])
def test_bad_compatibility_toml_is_fatal(payload, tmp_path, kind):
    registry_dir = tmp_path / "registry"
    write_module(registry_dir, payload)
    compatibility = tmp_path / "sources.toml"
    text = sync.serialize_sources(payload["sources"])
    if kind == "invalid":
        compatibility.write_text("[[sources]\n", encoding="utf-8")
    elif kind == "duplicate":
        compatibility.write_text(text + text, encoding="utf-8")
    elif kind == "other-top-level":
        compatibility.write_text('unexpected = true\n' + text, encoding="utf-8")
    before = snapshot(tmp_path)

    result = run_cli("--check", "--registry-dir", registry_dir, "--sources-path", compatibility)

    assert result.returncode != 0
    assert result.stderr
    assert snapshot(tmp_path) == before


def test_boolean_integer_and_float_tampering_is_detected_recursively(payload, tmp_path):
    row = payload["sources"][0]
    row["future_options"] = {"flags": [True, 1, 1.0]}
    rows = [row]
    changed = copy.deepcopy(rows)
    changed[0]["future_options"]["flags"] = [1, 1.0, True]
    assert rows == changed  # Ordinary Python equality cannot catch this change.
    compatibility = tmp_path / "sources.toml"
    compatibility.write_text(sync.serialize_sources(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="future_options"):
        sync.check_sources(rows, compatibility)
