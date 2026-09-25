"""Comparable 10,000-article offline query plus Excel export benchmark."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from eu_cyber_news_scraper.offline_search import main


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        corpus = root / "weekly.corpus.jsonl"
        with corpus.open("w", encoding="utf-8") as stream:
            for index in range(10_000):
                stream.write(json.dumps({
                    "url": f"https://www.comreg.ie/benchmark-{index}/",
                    "source_id": "ie_comreg", "country": "IE", "source_name": "ComReg",
                    "institution_type": "監理機關", "language": "en",
                    "title": (f"NIS2 cybersecurity update {index}" if index % 2
                              else f"Artificial intelligence model security {index}"),
                    "summary": "Official implementation guidance",
                    "published_at": "2026-09-20T00:00:00+00:00",
                }) + "\n")
        (root / "weekly.run.json").write_text(json.dumps({
            "period": {"period_start_utc": "2026-09-01T00:00:00+00:00",
                       "period_end_exclusive_utc": "2026-10-01T00:00:00+00:00"},
            "artifact_bundle_complete": True, "quality_gate": {"passed": True},
            "sources": [{"source_id": "ie_comreg", "fetch_status": "ok", "parse_status": "ok"}],
        }), encoding="utf-8")
        args = ["--corpus-dir", str(root), "--source", "ie_comreg", "--since", "2026-09-20",
                "--until", "2026-09-20", "--output", str(root / "result.xlsx")]
        started = time.perf_counter()
        main(args)
        print(f"cold query + Excel: {time.perf_counter() - started:.3f}s")
        started = time.perf_counter()
        main(args)
        print(f"unchanged query + Excel: {time.perf_counter() - started:.3f}s")


if __name__ == "__main__":
    run()
