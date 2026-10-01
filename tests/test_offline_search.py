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
    main([*args, "--country", "IE"])
    workbook = load_workbook(output, read_only=True)
    assert sum(1 for _ in workbook["查詢結果"].values) == 2
    workbook.close()
    with pytest.raises(SystemExit, match="沒有符合條件"):
        main([*args, "--country", "ES"])
    main(args)
    assert "沿用未變規則" in capsys.readouterr().out
    main(["--corpus-dir", str(corpus), "--source", "ie_comreg", "--since", "2026-08-01", "--until", "2026-09-21", "--output", str(output)])
    assert "部分搜尋" in capsys.readouterr().err


def test_offline_search_requires_corpus(tmp_path):
    with pytest.raises(SystemExit, match="找不到"):
        main(["--corpus-dir", str(tmp_path), "--days", "1"])


def test_default_search_excludes_retired_and_manual_only_sources(tmp_path):
    rows = [{
        "url": f"https://www.comreg.ie/example-{source_id}/", "source_id": source_id,
        "country": "IE", "source_name": source_id, "institution_type": "監理機關", "language": "en",
        "title": "NIS2 cyber incident report", "summary": "Cybersecurity incident notification",
        "published_at": "2026-09-20T00:00:00+00:00",
    } for source_id in ("ie_comreg", "ie_insight", "fr_institut_montaigne", "eu_enisa_publications", "es_incibe")]
    corpus = tmp_path / "data"
    corpus.mkdir()
    saved = corpus / "weekly.corpus.jsonl"
    saved.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    original = saved.read_bytes()
    output = tmp_path / "query.xlsx"
    args = ["--corpus-dir", str(corpus), "--since", "2026-09-19", "--until", "2026-09-21", "--output", str(output)]
    main(args)
    workbook = load_workbook(output, read_only=True)
    try:
        assert sum(1 for _ in workbook["查詢結果"].values) == 2
        assert workbook["查詢結果"]["B2"].value == "ie_comreg"
    finally:
        workbook.close()
    assert saved.read_bytes() == original
    for source_id in ("ie_insight", "fr_institut_montaigne", "eu_enisa_publications"):
        with pytest.raises(SystemExit, match="未知來源代碼"):
            main([*args, "--source", source_id])


def test_application_version_change_invalidates_workbook_cache(tmp_path, monkeypatch, capsys):
    from eu_cyber_news_scraper import offline_search

    corpus = tmp_path / "data"
    corpus.mkdir()
    (corpus / "weekly.corpus.jsonl").write_text(json.dumps({
        "url": "https://www.comreg.ie/versioned/", "source_id": "ie_comreg", "country": "IE",
        "source_name": "ComReg", "institution_type": "監理機關", "language": "en",
        "title": "NIS2 cybersecurity rules", "published_at": "2026-09-20T00:00:00+00:00",
    }) + "\n", encoding="utf-8")
    args = ["--corpus-dir", str(corpus), "--source", "ie_comreg", "--since", "2026-09-19",
            "--until", "2026-09-21", "--output", str(tmp_path / "query.xlsx")]
    main(args)
    capsys.readouterr()
    main(args)
    assert "沿用未變規則" in capsys.readouterr().out
    monkeypatch.setattr(offline_search, "__version__", "next-version")
    main(args)
    assert "沿用未變規則" not in capsys.readouterr().out


@pytest.mark.parametrize("color", ["FFD966", "FFE699", "FFF2CC"])
def test_offline_yellow_targets_preserve_date_source_and_url(tmp_path, monkeypatch, color):
    from openpyxl.styles import PatternFill

    from eu_cyber_news_scraper import offline_search

    monkeypatch.setattr(offline_search, "relevance_fill", lambda article: PatternFill("solid", fgColor=color))
    corpus = tmp_path / "data"
    corpus.mkdir()
    (corpus / "weekly.corpus.jsonl").write_text(json.dumps({
        "url": "https://www.comreg.ie/shaded/", "source_id": "ie_comreg", "country": "IE",
        "source_name": "ComReg", "institution_type": "監理機關", "language": "en",
        "title": "NIS2 cybersecurity rules", "published_at": "2026-09-20T00:00:00+00:00",
    }) + "\n", encoding="utf-8")
    output = tmp_path / "shaded.xlsx"
    main(["--corpus-dir", str(corpus), "--source", "ie_comreg", "--since", "2026-09-19",
          "--until", "2026-09-21", "--output", str(output)])
    workbook = load_workbook(output, read_only=True)
    try:
        row = list(workbook["查詢結果"].iter_rows(min_row=2))[0]
        assert len(row) == 8
        for index, cell in enumerate(row):
            if 2 <= index < 6:
                assert cell.fill.fill_type == "solid"
                assert cell.fill.fgColor.rgb == f"00{color}"
            else:
                assert cell.fill.fill_type is None
        assert row[7].value == "https://www.comreg.ie/shaded/"
    finally:
        workbook.close()
