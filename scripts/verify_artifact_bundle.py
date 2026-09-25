"""Verify downloaded weekly Excel, selected JSONL, corpus JSONL and manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eu_cyber_news_scraper.artifacts import verify_artifact_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path, help="Downloaded *.run.json path")
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    names = {row["name"] for row in summary["artifact_manifest"]}
    workbook = next((args.summary.parent / name for name in names if name.endswith(".xlsx")), None)
    selected = next((args.summary.parent / name for name in names if name.endswith(".jsonl") and not name.endswith(".corpus.jsonl")), None)
    corpus = next((args.summary.parent / name for name in names if name.endswith(".corpus.jsonl")), None)
    if workbook is None:
        raise SystemExit("manifest does not declare an Excel workbook")
    verify_artifact_bundle(
        workbook, selected, args.summary, run_id=summary["run_id"], article_count=summary["article_count"],
        corpus_path=corpus, corpus_count=summary.get("pre_filter_article_count") if corpus else None,
    )
    print(f"Verified {summary['run_id']}: {summary['article_count']} selected / {summary.get('pre_filter_article_count', 'unknown')} corpus rows")


if __name__ == "__main__":
    main()
