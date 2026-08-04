import json
from datetime import datetime, timedelta, timezone

import pytest

from eu_cyber_news_scraper.artifacts import ArtifactBundle, verify_artifact_bundle
from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.exporter import export_workbook, write_jsonl, write_run_summary
from eu_cyber_news_scraper.models import Article, SourceStatus


def test_artifact_bundle_publishes_manifest_last_and_replaces_existing_files(tmp_path):
    output = tmp_path / "result.xlsx"
    manifest = tmp_path / "result.run.json"
    output.write_text("old", encoding="utf-8")
    with ArtifactBundle(output, "run") as bundle:
        staged_output = bundle.staged(output)
        staged_manifest = bundle.staged(manifest)
        staged_output.write_text("new", encoding="utf-8")
        staged_manifest.write_text(json.dumps({"complete": True}), encoding="utf-8")
        bundle.publish([(staged_output, output), (staged_manifest, manifest)], manifest=manifest)
    assert output.read_text(encoding="utf-8") == "new"
    assert manifest.exists()


def test_artifact_bundle_rolls_back_when_a_staged_file_is_missing(tmp_path):
    output = tmp_path / "result.xlsx"
    manifest = tmp_path / "result.run.json"
    output.write_text("old", encoding="utf-8")
    with ArtifactBundle(output, "run") as bundle:
        staged_output = bundle.staged(output)
        staged_output.write_text("new", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            bundle.publish(
                [(staged_output, output), (bundle.staged(manifest), manifest)],
                manifest=manifest,
            )
    assert output.read_text(encoding="utf-8") == "old"
    assert not manifest.exists()


def test_artifact_verifier_cross_checks_workbook_jsonl_and_manifest(tmp_path):
    run_id = "run-123"
    since = datetime(2026, 7, 3, 16, tzinfo=timezone.utc)
    until = since + timedelta(days=14)
    article = Article(
        "eu_dg_connect",
        "EU",
        "European Commission",
        "official",
        "en",
        "Cybersecurity guidance published",
        "https://digital-strategy.ec.europa.eu/en/news/example",
        published_at=since,
    )
    status = SourceStatus("eu_dg_connect", "European Commission", "EU", True, True, "feed", 1, 1, 0.1)
    workbook = export_workbook(
        [article],
        [status],
        list(load_sources()),
        tmp_path / "result.xlsx",
        run_id=run_id,
        since=since,
        until=until,
    )
    jsonl = write_jsonl([article], tmp_path / "result.jsonl", run_id=run_id)
    summary = write_run_summary(
        workbook,
        started_at=since,
        finished_at=until,
        since=since,
        until=until,
        articles=[article],
        statuses=[status],
        run_id=run_id,
        artifact_paths=[workbook, jsonl],
    )
    verify_artifact_bundle(workbook, jsonl, summary, run_id=run_id, article_count=1)

    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["artifact_manifest"].append(dict(payload["artifact_manifest"][0]))
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact set mismatch"):
        verify_artifact_bundle(workbook, jsonl, summary, run_id=run_id, article_count=1)

    payload["artifact_manifest"].pop()
    payload["period"]["normalized_since"] = "2026-01-01"
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="period mismatch"):
        verify_artifact_bundle(workbook, jsonl, summary, run_id=run_id, article_count=1)


def test_artifact_verifier_rejects_checksum_tampering(tmp_path):
    run_id = "run-checksum"
    since = datetime(2026, 7, 3, 16, tzinfo=timezone.utc)
    article = Article(
        "eu_dg_connect", "EU", "European Commission", "official", "en",
        "Cybersecurity guidance published", "https://digital-strategy.ec.europa.eu/en/news/example",
        published_at=since,
    )
    status = SourceStatus("eu_dg_connect", "European Commission", "EU", True, True, "feed", 1, 1, 0.1)
    workbook = export_workbook(
        [article], [status], list(load_sources()), tmp_path / "result.xlsx",
        run_id=run_id, since=since, until=since + timedelta(days=1),
    )
    jsonl = write_jsonl([article], tmp_path / "result.jsonl", run_id=run_id)
    summary = write_run_summary(
        workbook, started_at=since, finished_at=since, since=since,
        until=since + timedelta(days=1), articles=[article], statuses=[status],
        run_id=run_id, artifact_paths=[workbook, jsonl],
    )
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["artifact_manifest"][0]["sha256"] = "0" * 64
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_artifact_bundle(workbook, jsonl, summary, run_id=run_id, article_count=1)


def test_artifact_verifier_rejects_unsafe_relative_path(tmp_path):
    run_id = "run-path"
    since = datetime(2026, 7, 3, 16, tzinfo=timezone.utc)
    article = Article("eu", "EU", "EU", "official", "en", "News", "https://example.eu/news", published_at=since)
    status = SourceStatus("eu", "EU", "EU", False, True, "html", 1, 1, 0.1)
    workbook = export_workbook(
        [article], [status], list(load_sources()), tmp_path / "result.xlsx",
        run_id=run_id, since=since, until=since + timedelta(days=1),
    )
    summary = write_run_summary(
        workbook, started_at=since, finished_at=since, since=since,
        until=since + timedelta(days=1), articles=[article], statuses=[status],
        run_id=run_id, artifact_paths=[workbook],
    )
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["artifact_manifest"][0]["relative_path"] = "../result.xlsx"
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="relative_path|unsafe"):
        verify_artifact_bundle(workbook, None, summary, run_id=run_id, article_count=1)
