"""Offline contracts for diagnostic isolation and the existing production gates.

PyYAML is not a project dependency. Follow test_workflow_contract.py's text
checks, but execute the extracted shell blocks with mocked external commands.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = "source-audit.yml"
PRODUCTION = "scrape.yml"
WEEKLY_SOURCE_IDS = frozenset("""
eu_dg_connect eu_enisa_news eu_cert_threat eu_cert_advisories
eu_jrc_news eu_enisa_certification eu_presscorner eu_parliament_press
fr_anssi fr_cnil fr_cybermalveillance fr_arcep fr_inria fr_dge fr_arcom
fr_concurrence fr_viginum de_bsi_news de_bmi de_bnetza de_fraunhofer_aisec
de_cispa de_bfdi de_bundeskartellamt de_dpma ie_ncsc ie_comreg ie_dpc ie_nsai
ie_adapt ie_cnam ie_electoral_commission eu_edpb eu_dg_home eu_eeas fr_culture
fr_dinum de_bbk ie_dete ie_research_ireland eu_eurohpc eu_chips_ju eu_sns_ju
fr_cea_list fr_campus_cyber de_athene de_interface de_swp
ie_ceadar ie_esri ie_tyndall ie_cyber_ireland
""".split())


def workflow(name):
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def step(name, title):
    # Bound the entire step, including its condition, environment and script.
    blocks = re.split(r"(?m)(?=^      - (?:name|uses): )", workflow(name))
    matches = [block for block in blocks if block.startswith(f"      - name: {title}\n")]
    assert len(matches) == 1, f"Expected one {title!r} step in {name}"
    return matches[0]


def script(name, title):
    block = step(name, title)
    match = re.search(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", block)
    assert match, f"Missing literal shell script in {title!r}"
    return textwrap.dedent(match[1])


def run_script(body, tmp_path, *, mocks="", **env):
    # Deliberately omit real credentials and mock every external service call.
    return subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", mocks + "\n" + body],
        cwd=tmp_path,
        env={"PATH": os.defpath, "GITHUB_REPOSITORY": "example/eu", "GITHUB_RUN_ID": "123",
             "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(tmp_path / "github-output"), **env},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_diagnostics_have_read_only_permissions_and_no_production_state_writes():
    text = workflow(AUDIT)
    assert "permissions:\n  contents: read\n  actions: read\n" in text
    assert not re.search(r"(?m)^\s+(?:contents|actions|issues|pull-requests): write\s*$", text)
    assert not re.search(r"(?m)^\s+permissions:\s*(?:write-all|\{)", text)
    assert "pull_request_target:" not in text
    for forbidden in ("ref: state", ".state-branch", ".state/", ".state-ready", "translations.json",
                      ".source-health.json", "--health-write", "--state-dir", "gh issue", "gh pr"):
        assert forbidden not in text
    assert not re.search(r"\bgit\s+(?:push|commit|add)\b", text)
    assert "group: eu-institution-url-audit" in text
    assert "group: weekly-eu-cyber-news" in workflow(PRODUCTION)
    assert "cancel-in-progress: false" in text


@pytest.mark.parametrize("name", [AUDIT, PRODUCTION, "paused-source-canary.yml"])
def test_all_remote_actions_are_pinned_to_full_commit_ids(name):
    actions = re.findall(r"(?m)^\s*(?:- )?uses:\s*(\S+)", workflow(name))
    assert actions
    for action in actions:
        assert re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", action), action


def test_audit_checks_canonical_data_and_uses_separate_generated_paths():
    validation = script(AUDIT, "Validate canonical source data")
    assert "generate_organisation_registry.py --check" in validation
    assert "eu_cyber_news_scraper.source_catalog --check" in validation
    assert "|| true" not in validation
    sources = shlex.split(script(AUDIT, "Inspect registered source URLs and parsers"))
    assert sources[:5] == ["uv", "run", "python", "-m", "eu_cyber_news_scraper.source_audit"]
    assert "--parse" in sources and "--allow-unhealthy" in sources
    assert sources[sources.index("--output-dir") + 1] == "source-audit"
    assert sources[sources.index("--history-dir") + 1] == ".source-inventory/history"
    catalog = script(AUDIT, "Inspect catalog URLs and collect directory candidates")
    assert "--previous .source-inventory/catalog-report.json" in catalog
    assert "--output .source-inventory/catalog-report.next.json" in catalog
    inventory = step(AUDIT, "Save accumulated diagnostic inventory")
    assert "if: always()" in inventory
    assert "path: .source-inventory/" in inventory
    assert "include-hidden-files: true" in inventory
    assert "if-no-files-found: error" in inventory
    evidence = step(AUDIT, "Upload URL audit evidence")
    assert "if: always()" in evidence and "path: source-audit/" in evidence
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"source-audit/", "source-audit-history/", ".source-inventory/"}.issubset(ignored)


def test_summary_keeps_promotion_diagnostic_and_reports_parser_and_endpoint_evidence(tmp_path):
    report_dir = tmp_path / "source-audit"
    report_dir.mkdir()
    (report_dir / "source-audit-example.json").write_text(json.dumps({"sources": [{
        "source_id": "test", "healthy": False,
        "endpoints": [{"kind": "listing", "error_code": "robots_denied", "healthy": False}],
        "parse": {"source_status": {"parse_status": "empty"}},
        "promotion": {"promotion_eligible": False},
    }]}), encoding="utf-8")
    summary = tmp_path / "summary.md"
    result = run_script(
        script(AUDIT, "Publish diagnostic summary"), tmp_path,
        mocks=f'uv() {{ shift 2; {shlex.quote(sys.executable)} "$@"; }}',
        GITHUB_STEP_SUMMARY=str(summary),
    )
    assert result.returncode == 0, result.stderr
    text = summary.read_text(encoding="utf-8")
    assert "| test | listing: robots_denied | empty | False |" in text
    assert "Observations are diagnostic only." in text
    assert "Full translation, artifact and production-state checks are still required" in text


def test_weekly_source_scope_and_existing_pause_metadata_are_preserved():
    rows = tomllib.loads((ROOT / "src/eu_cyber_news_scraper/sources.toml").read_text(encoding="utf-8"))["sources"]
    assert {row["id"] for row in rows if row.get("schedule_enabled", True)} == WEEKLY_SOURCE_IDS
    paused = {row["id"]: row for row in rows if row.get("paused_until")}
    assert set(paused) == {"eu_parliament_press", "fr_cea_list"}
    expected = {
        "eu_parliament_press": (
            "https://www.europarl.europa.eu/at-your-service/en/stay-informed/rss-feeds",
            "The official listing and RSS endpoints returned an HTTP 202 JavaScript challenge to GitHub-hosted "
            "runners on 2026-07-28, while the same RSS feed returned valid XML locally; pause scheduled requests "
            "until review.",
        ),
        "fr_cea_list": (
            "https://list.cea.fr/en/news/",
            "Direct TLS connections to the official home, news and feed endpoints repeatedly exceeded the "
            "connection budget on 2026-07-28; retain the source but avoid weekly no-op waits until review.",
        ),
    }
    for source_id, (evidence, reason) in expected.items():
        assert paused[source_id]["paused_until"] == "2026-10-31"
        assert paused[source_id]["pause_evidence_url"] == evidence
        assert paused[source_id]["pause_reason"] == reason
    canary = workflow("paused-source-canary.yml")
    assert 'cron: "0 2 1 * *"' in canary
    assert "--health-write never" in canary
    assert "--state-dir /tmp/paused-source-canary/state" in canary


@pytest.mark.parametrize("event,source,exit_code", [
    ("schedule", "", 0),
    ("schedule", "", 2),
    ("workflow_dispatch", "fr_cea_list", 1),
    ("workflow_dispatch", '$(touch injected); " --health-write always', 0),
])
def test_production_shell_keeps_quality_gates_and_propagates_cli_exit(tmp_path, event, source, exit_code):
    capture = f"{shlex.quote(sys.executable)} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' \"$@\""
    result = run_script(
        script(PRODUCTION, "Scrape official sources"), tmp_path,
        mocks=f"uv() {{ {capture}; return {exit_code}; }}",
        DAYS="7", SINCE="", UNTIL="", SOURCE=source, EVENT_NAME=event,
    )
    assert result.returncode == exit_code, result.stderr
    args = json.loads(result.stdout)
    for flag in ("--jsonl", "--fail-on-degraded", "--require-complete-artifacts"):
        assert flag in args
    expected = {
        "--state-dir": ".state", "--source-budget": "60",
        "--min-source-success-rate": "0.95", "--min-parse-success-rate": "0.95",
        "--max-empty-sources": "0", "--min-overall-date-rate": "0.75",
        "--min-critical-date-rate": "0.95", "--min-high-confidence-date-rate": "0.75",
        "--max-date-conflict-rate": "0.05", "--max-unexplained-future-dates": "0",
        "--health-write": "always" if event == "schedule" else "auto",
        "--days": "7",
    }
    for flag, value in expected.items():
        assert args[args.index(flag) + 1] == value
    if source:
        assert args[args.index("--source") + 1] == source
    else:
        assert "--source" not in args
    assert "--allow-unhealthy" not in args
    assert not (tmp_path / "injected").exists()


def test_production_persistence_requires_schedule_and_fresh_ready_marker(tmp_path):
    persistence = step(PRODUCTION, "Persist durable state")
    assert "if: always() && github.event_name == 'schedule'" in persistence
    assert "working-directory: .state-branch" in persistence
    result = run_script(
        script(PRODUCTION, "Persist durable state"), tmp_path,
        mocks="git() { echo 'unexpected git write' >&2; return 99; }",
    )
    assert result.returncode == 0, result.stderr
    assert "RUN_NOT_BASELINE_ELIGIBLE" in result.stdout
    assert "unexpected git write" not in result.stderr
    complete = step(PRODUCTION, "Upload completed news artifacts")
    assert "if: steps.scrape.outcome == 'success'" in complete
    assert "path: 新聞放置區/*" in complete and "if-no-files-found: error" in complete
    diagnostics = step(PRODUCTION, "Upload failure diagnostics")
    assert "if: failure()" in diagnostics and "新聞放置區/*" in diagnostics
    cache = step(PRODUCTION, "Restore conditional HTTP cache")
    assert "path: .state/.http-cache" in cache
    assert "${{ hashFiles('uv.lock') }}" in cache


@pytest.mark.parametrize("status", [0, 1, 2, 127])
def test_catalog_workflow_accepts_attention_but_keeps_errors_nonzero_and_old_history(tmp_path, status):
    directory = tmp_path / ".source-inventory"
    directory.mkdir()
    previous = directory / "catalog-report.json"
    previous.write_text('{"previous": true}', encoding="utf-8")
    result = run_script(
        script(AUDIT, "Inspect catalog URLs and collect directory candidates"), tmp_path,
        mocks='uv() { printf \'{"current": true}\\n\' > .source-inventory/catalog-report.next.json; '
              f"return {status}; }}",
    )
    assert result.returncode == (status if status > 1 else 0), result.stderr
    assert json.loads(previous.read_text()) == ({"previous": True} if status > 1 else {"current": True})
    outputs = dict(line.split("=", 1) for line in (tmp_path / "github-output").read_text().splitlines())
    assert outputs["freshness"] == ("fatal" if status > 1 else "current")
    if status > 1:
        assert outputs["exit_code"] == str(status)
        assert (directory / "catalog-report.next.json").exists()


@pytest.mark.parametrize("status,has_failure_report", [(2, True), (127, False)])
def test_fatal_catalog_summary_labels_current_failure_and_retained_history(tmp_path, status, has_failure_report):
    directory = tmp_path / ".source-inventory"
    directory.mkdir()
    previous = directory / "catalog-report.json"
    previous.write_text(json.dumps({
        "status": "complete", "discovery": {"candidate_count": 8, "new_candidate_count": 3},
    }), encoding="utf-8")
    before = previous.read_bytes()
    failure = json.dumps({"status": "invalid", "validation_errors": ["bad current catalog"], "discovery": {}})
    write_report = (f"printf '%s\\n' {shlex.quote(failure)} > .source-inventory/catalog-report.next.json; "
                    if has_failure_report else "")
    result = run_script(
        script(AUDIT, "Inspect catalog URLs and collect directory candidates"), tmp_path,
        mocks=f"uv() {{ {write_report}return {status}; }}",
    )
    assert result.returncode == status
    assert previous.read_bytes() == before
    outputs = dict(line.split("=", 1) for line in (tmp_path / "github-output").read_text().splitlines())
    summary = tmp_path / "summary.md"
    result = run_script(
        script(AUDIT, "Publish diagnostic summary"), tmp_path,
        mocks=f'uv() {{ shift 2; {shlex.quote(sys.executable)} "$@"; }}',
        GITHUB_STEP_SUMMARY=str(summary), CATALOG_FRESHNESS=outputs["freshness"],
        CATALOG_EXIT_CODE=outputs["exit_code"],
    )
    assert result.returncode == 0, result.stderr
    text = summary.read_text(encoding="utf-8")
    assert f"Current catalog check failed (exit code {status})" in text
    assert "Historical catalog inventory retained for retry (not a current result): complete" in text
    assert "Current catalog result: complete" not in text
    if has_failure_report:
        assert "Current fatal catalog report: invalid" in text
        assert "bad current catalog" in text
    assert previous.read_bytes() == before


@pytest.mark.parametrize("status", ["complete", "attention"])
def test_successful_catalog_summary_labels_current_result(tmp_path, status):
    directory = tmp_path / ".source-inventory"
    directory.mkdir()
    (directory / "catalog-report.json").write_text(json.dumps({"status": status, "discovery": {}}))
    summary = tmp_path / "summary.md"
    result = run_script(
        script(AUDIT, "Publish diagnostic summary"), tmp_path,
        mocks=f'uv() {{ shift 2; {shlex.quote(sys.executable)} "$@"; }}',
        GITHUB_STEP_SUMMARY=str(summary), CATALOG_FRESHNESS="current",
    )
    assert result.returncode == 0, result.stderr
    assert f"Current catalog result: {status}" in summary.read_text()
    assert "Historical catalog" not in summary.read_text()


def restore_mocks():
    return textwrap.dedent("""
        gh() {
          if [[ "$1 $2" == 'run list' ]]; then
            printf '%s\\n' "$*" > run-list-arguments.txt
            printf '%s\\n' "$MOCK_RUN_IDS"
          elif [[ "$1 $2" == 'run download' ]]; then
            local run_id="$3" destination=''
            shift 3
            while (( $# )); do
              if [[ "$1" == '--dir' ]]; then destination="$2"; shift; fi
              shift
            done
            [[ -d "$destination" ]] || return 99
            printf '%s %s\\n' "$run_id" "$destination" >> download-attempts.txt
            if [[ "$run_id" == "$MOCK_EMPTY_RUN" ]]; then
              mkdir -p "$destination/history" "$destination/catalog-history"
              : > "$destination/catalog-report.json"
              return 0
            fi
            mkdir -p "$destination/history"
            if [[ "$run_id" == "$MOCK_MISSING_RUN" || "$MOCK_ALL_MISSING" == true ]]; then
              printf 'partial download\\n' > "$destination/history/partial.json"
              printf 'partial catalog\\n' > "$destination/catalog-report.json"
              return 1
            fi
            printf '{"from_run": "%s"}\\n' "$run_id" > "$destination/catalog-report.json"
            printf '{"from_run": "%s"}\\n' "$run_id" > "$destination/history/observation.json"
            mkdir -p "$destination/catalog-history" "$destination/url-checks"
            printf 'catalog history\\n' > "$destination/catalog-history/observation.json"
            printf 'URL evidence\\n' > "$destination/url-checks/report.json"
            printf '{"status": "invalid", "old_failure": true}\\n' > "$destination/catalog-report.next.json"
          else
            return 99
          fi
        }
    """)


@pytest.mark.parametrize("empty_latest", [False, True])
def test_inventory_recovery_tries_older_run_in_fresh_staging_without_partial_downloads(tmp_path, empty_latest):
    result = run_script(
        script(AUDIT, "Restore prior diagnostic inventory"), tmp_path, mocks=restore_mocks(),
        MOCK_RUN_IDS="42\n41\n40", MOCK_MISSING_RUN="42" if not empty_latest else "",
        MOCK_EMPTY_RUN="42" if empty_latest else "",
    )
    assert result.returncode == 0, result.stderr
    args = (tmp_path / "run-list-arguments.txt").read_text()
    assert "--workflow source-audit.yml --branch main --status completed --limit 15" in args
    assert "--json databaseId --jq .[].databaseId" in args
    attempts = [line.split() for line in (tmp_path / "download-attempts.txt").read_text().splitlines()]
    assert [attempt[0] for attempt in attempts] == ["42", "41"]
    assert len({attempt[1] for attempt in attempts}) == 2
    assert all(Path(attempt[1]).parent == tmp_path for attempt in attempts)
    inventory = tmp_path / ".source-inventory"
    assert json.loads((inventory / "catalog-report.json").read_text()) == {"from_run": "41"}
    assert json.loads((inventory / "history/observation.json").read_text()) == {"from_run": "41"}
    assert not (inventory / "history/partial.json").exists()
    assert not (inventory / "catalog-report.next.json").exists()
    assert (inventory / "catalog-history/observation.json").exists()
    assert (inventory / "url-checks/report.json").exists()
    assert "Restored diagnostic inventory from completed run 41." in result.stdout
    assert "new observation baseline" not in result.stdout
    assert not (tmp_path / ".state").exists()


@pytest.mark.parametrize("run_ids", ["", "42\n41"])
def test_empty_or_unavailable_inventory_explicitly_starts_new_baseline(tmp_path, run_ids):
    result = run_script(
        script(AUDIT, "Restore prior diagnostic inventory"), tmp_path, mocks=restore_mocks(),
        MOCK_RUN_IDS=run_ids, MOCK_ALL_MISSING="true",
    )
    assert result.returncode == 0, result.stderr
    assert "No prior diagnostic inventory could be restored; starting a new observation baseline." in result.stdout
    assert (tmp_path / ".source-inventory/history").is_dir()
    assert not list((tmp_path / ".source-inventory").rglob("*.json"))
    assert not (tmp_path / ".state").exists()


@pytest.mark.parametrize("error", [OSError("unreadable history"), ValueError("invalid history")])
def test_allow_unhealthy_does_not_mask_audit_execution_errors(tmp_path, monkeypatch, error):
    from eu_cyber_news_scraper import source_audit
    from eu_cyber_news_scraper.models import Source

    source = Source("test", "EU", "測試", "Test", "official", "en",
                    "https://agency.example/", "https://agency.example/news")
    monkeypatch.setattr(source_audit, "load_sources_and_registry", lambda: (
        (source,), SimpleNamespace(registry_hash="test", errors=()),
    ))
    monkeypatch.setattr(source_audit, "audit_sources", AsyncMock(side_effect=error))
    with pytest.raises(SystemExit) as exc:
        source_audit.main(["--allow-unhealthy", "--output-dir", str(tmp_path)])
    assert exc.value.code == 2


def test_catalog_invalid_input_remains_nonzero_and_writes_diagnostic_json(tmp_path):
    from eu_cyber_news_scraper import source_catalog

    output = tmp_path / "report.next.json"
    status = source_catalog.main(["--check", "--catalog", str(tmp_path / "missing.json"),
                                  "--output", str(output)])
    assert status == 2
    assert json.loads(output.read_text())["status"] == "invalid"
