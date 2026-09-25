import json

import pytest
from openpyxl import load_workbook

from eu_cyber_news_scraper.offline_search import main


def test_offline_search_index_reuse_and_coverage(tmp_path, capsys):
    corpus = tmp_path / "data"
    corpus.mkdir()
    path = corpus / "weekly.corpus.jsonl"
    row = {
        "url": "https://www.comreg.ie/example/", "source_id": "ie_comreg", "country": "IE",
        "source_name": "ComReg", "institution_type": "監理機關", "language": "en",
        "title": "NIS2 cyber incident report", "summary": "Cybersecurity incident notification",
        "published_at": "2026-09-20T00:00:00+00:00", "published_date_local": "2026-09-20",
        "date_confidence": "high", "title_zh_tw": "資安事件",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    manifest = {
        "period": {"period_start_utc": "2026-09-01T00:00:00+00:00", "period_end_exclusive_utc": "2026-10-01T00:00:00+00:00"},
        "artifact_bundle_complete": True, "quality_gate": {"passed": True},
        "sources": [{"source_id": "ie_comreg", "fetch_status": "ok", "parse_status": "ok"}],
    }
    (corpus / "weekly.run.json").write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "results.xlsx"
    args = ["--corpus-dir", str(corpus), "--source", "ie_comreg", "--since", "2026-09-19", "--until", "2026-09-21", "--output", str(output)]
    main(args)
    workbook = load_workbook(output, read_only=True)
    assert workbook["查詢資訊"]["B4"].value == "是"
    assert sum(1 for _ in workbook["查詢結果"].values) == 2
    workbook.close()
    main(args)
    assert "沿用未變規則" in capsys.readouterr().out
    main(["--corpus-dir", str(corpus), "--source", "ie_comreg", "--since", "2026-08-01", "--until", "2026-09-21", "--output", str(output)])
    assert "部分搜尋" in capsys.readouterr().err


def test_offline_search_requires_corpus(tmp_path):
    with pytest.raises(SystemExit, match="找不到"):
        main(["--corpus-dir", str(tmp_path), "--days", "1"])
