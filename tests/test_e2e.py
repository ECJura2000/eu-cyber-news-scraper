import json
from datetime import datetime, timezone
from types import SimpleNamespace

from openpyxl import load_workbook

from eu_cyber_news_scraper.cli import _run_pipeline
from eu_cyber_news_scraper.models import Source


class Response:
    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode("utf-8")


class FakeHttpClient:
    def __init__(self, timeout: int):
        self.payload = b""

    def get(self, url: str):
        return Response(
            b"<?xml version='1.0'?><rss><channel><item><title>NIS2 security guidance</title>"
            b"<link>https://agency.example/news/nis2</link><pubDate>Fri, 01 May 2026 08:00:00 GMT</pubDate>"
            b"<description>NIS2 risk management requirements</description></item></channel></rss>"
        )


def test_offline_pipeline_writes_atomic_artifacts_and_quality_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr("eu_cyber_news_scraper.cli.HttpClient", FakeHttpClient)
    monkeypatch.setattr(
        "eu_cyber_news_scraper.translation._translate_titles",
        lambda titles: {title: "NIS2 資安指引" for title in titles},
    )
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(tmp_path / "translations.json"))
    source = Source(
        "test", "EU", "測試主管機關", "Test Authority", "國家主管機關", "en",
        "https://agency.example", "https://agency.example/news", feed_urls=("https://agency.example/rss",),
        allow_domains=("agency.example",), include_patterns=(r"/news/.+",), critical=True,
    )
    args = SimpleNamespace(
        timeout=1, workers=1, all=False, include_undated=False, no_detail=True,
        topic=None, jsonl=True, fail_on_degraded=False,
    )
    output = tmp_path / "result.xlsx"
    _run_pipeline(
        args, [source], datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 3, tzinfo=timezone.utc), output, "run-e2e",
    )
    workbook = load_workbook(output, read_only=True)
    assert "官方規範與執法" in workbook.sheetnames
    summary = json.loads(output.with_suffix(".run.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "run-e2e"
    assert summary["translation"]["success_rate"] == 1
    assert (tmp_path / ".source-health.json").exists()
    assert output.with_suffix(".jsonl").exists()
