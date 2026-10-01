"""Bundeskartellamt quality contracts; synthetic cases do not prove live coverage."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from eu_cyber_news_scraper import http as http_module
from eu_cyber_news_scraper import scraper as scraper_module
from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.health import source_config_fingerprint
from eu_cyber_news_scraper.http import HttpClient, HttpStats
from eu_cyber_news_scraper.parsers import enrich_from_detail, parse_listing
from eu_cyber_news_scraper.scraper import scrape_source
from eu_cyber_news_scraper.source_audit import assess_parse, config_hash, promotion_evidence

SINCE = datetime(2026, 7, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 8, 1, tzinfo=timezone.utc)


@pytest.fixture
def source(monkeypatch, tmp_path):
    # Test canonical data without a machine-specific external override.
    monkeypatch.setenv("EU_CYBER_ORGANISATION_DIR", str(tmp_path))
    return next(item for item in load_sources() if item.id == "de_bundeskartellamt")


def historical_listing(fixture_dir):
    return (fixture_dir / "contract_de_bundeskartellamt.html").read_text(encoding="utf-8")


def test_historical_news_date_has_local_day_and_high_confidence(source, fixture_dir):
    payload = (fixture_dir / "contract_de_bundeskartellamt.html").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "fc89e49b6cd18dd8d339d57091d9de53577852ecce8dde949e767cd2fe54d579"
    articles = parse_listing(payload.decode(), source, source.listing_url)
    assert len(articles) == 1
    article = articles[0]
    assert article.title == "Erhöhung der RWE-Anteile an Amprion freigegeben"
    assert article.published_date_local == "2026-07-17"
    assert article.published_at.isoformat() == "2026-07-16T22:00:00+00:00"
    assert article.date_source == "source-selector"
    assert article.date_confidence == "high"
    assert not article.date_conflict
    assert len(article.summary) < 40  # Still a detail candidate despite its high-confidence date.


@pytest.mark.parametrize("base_href", ["/", "https://www.bundeskartellamt.de/"])
def test_document_base_resolves_relative_news_urls_without_changing_date_quality(source, fixture_dir, base_href):
    html = (fixture_dir / "bundeskartellamt_listing_quality.html").read_text(encoding="utf-8")
    html = html.replace('<base href="/">', f'<base href="{base_href}">')
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 3
    assert articles[0].url == (
        "https://www.bundeskartellamt.de/SharedDocs/Meldung/DE/Pressemitteilungen/2026/"
        "07_17_2026_RWE_Amprion.html?nn=52004"
    )
    assert all(urlsplit(article.url).path.startswith("/SharedDocs/Meldung/DE/Pressemitteilungen/")
               for article in articles)
    assert articles[0].published_date_local == "2026-07-17"
    assert articles[0].date_confidence == "high"
    assert not articles[0].date_conflict
    assert all(article.published_at is None for article in articles[1:])


def test_malformed_and_missing_dates_are_not_replaced_by_event_or_navigation_dates(source, fixture_dir):
    html = (fixture_dir / "bundeskartellamt_listing_quality.html").read_text(encoding="utf-8")
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 3
    assert articles[0].published_date_local == "2026-07-17"
    assert articles[0].date_confidence == "high"
    for article in articles[1:]:
        assert article.published_at is None
        assert article.published_date_local == ""
        assert article.date_confidence != "high"
        assert article.date_candidates == []
    assert "01.10.2026" in articles[1].title
    assert all(urlsplit(article.url).hostname == "www.bundeskartellamt.de" for article in articles)
    assert all("/SharedDocs/Meldung/DE/Pressemitteilungen/" in urlsplit(article.url).path for article in articles)
    assert all(article.title != "Nächste Seite" for article in articles)


@pytest.mark.parametrize("conflicting", [False, True])
def test_detail_keeps_news_title_and_records_credible_date_conflicts(source, fixture_dir, conflicting):
    article = parse_listing(historical_listing(fixture_dir), source, source.listing_url)[0]
    html = (fixture_dir / "bundeskartellamt_detail_quality.html").read_text(encoding="utf-8")
    if conflicting:
        html = html.replace("2026-07-17T09:00:00+02:00", "2026-07-18T09:00:00+02:00")
    enrich_from_detail(article, html, source)
    assert article.title == "Erhöhung der RWE-Anteile an Amprion freigegeben"
    assert article.date_source == "article-meta"
    assert article.date_confidence == "high"
    assert article.published_date_local == ("2026-07-18" if conflicting else "2026-07-17")
    assert article.date_conflict is conflicting
    assert sum(candidate.selected for candidate in article.date_candidates) == 1
    assert any(candidate.local_date == "2026-10-01" and candidate.confidence == "low"
               for candidate in article.date_candidates)
    assert len(article.summary) >= 40


def mock_scrape(source, html, detail_html="", *, robots="User-agent: *\nDisallow:\n", fetch_details=True,
                source_budget_seconds=60):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.url.host == "www.bundeskartellamt.de"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots, headers={"content-type": "text/plain"})
        if str(request.url) == source.listing_url:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        assert detail_html, f"Unexpected detail request: {request.url}"
        return httpx.Response(200, text=detail_html, headers={"content-type": "text/html"})

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            return await scrape_source(source, client, since=SINCE, until=UNTIL,
                                       observed_at=UNTIL, source_budget_seconds=source_budget_seconds,
                                       fetch_details=fetch_details)

    return asyncio.run(run()), calls


def test_high_confidence_listing_still_fetches_detail_for_short_summary(source, fixture_dir):
    detail = (fixture_dir / "bundeskartellamt_detail_quality.html").read_text(encoding="utf-8")
    result, calls = mock_scrape(source, historical_listing(fixture_dir), detail)
    assert result.status.success
    assert not result.status.budget_exhausted
    assert len(calls) == 3  # robots, listing, detail
    assert calls[0] == "https://www.bundeskartellamt.de/robots.txt"
    assert calls[1] == source.listing_url
    assert "/SharedDocs/Meldung/DE/Pressemitteilungen/" in urlsplit(calls[2]).path
    assessment = assess_parse(result, observed_at=UNTIL)
    assert assessment["high_confidence_date_rate"] == 1
    assert assessment["conflict_rate"] == 0
    assert assessment["missing_required_count"] == 0
    assert assessment["assessment_complete"]


def test_undated_news_remains_in_raw_health_assessment(source, fixture_dir):
    html = (fixture_dir / "bundeskartellamt_listing_quality.html").read_text(encoding="utf-8")
    result, calls = mock_scrape(source, html, fetch_details=False)
    assert len(calls) == 2
    assert result.status.raw_count == 3
    assert result.status.dated_count == 1
    assert result.status.parse_status == "attention"
    assessment = assess_parse(result, observed_at=UNTIL)
    assert assessment["assessed_count"] == 3
    assert assessment["assessment_complete"]
    assert assessment["high_confidence_date_rate"] == pytest.approx(1 / 3)
    assert assessment["missing_required_count"] == 2


def test_summary_only_topic_hit_is_lost_when_details_are_skipped(source, fixture_dir):
    # Synthetic counterexample, not evidence about the real RWE article's body.
    listing = historical_listing(fixture_dir)
    detail = (fixture_dir / "bundeskartellamt_detail_quality.html").read_text(encoding="utf-8")
    detail = detail.replace("Die Prüfung digitaler Plattformen", "Die Prüfung nach dem Digital Markets Act")
    listing_only, _ = mock_scrape(source, listing, fetch_details=False)
    enriched, _ = mock_scrape(source, listing, detail)
    assert listing_only.status.raw_count == enriched.status.raw_count == 1
    assert listing_only.status.dated_count == enriched.status.dated_count == 1
    assert listing_only.status.relevant_count == 0
    assert enriched.status.relevant_count == 1
    assert enriched.articles[0].published_date_local == "2026-07-17"


def test_detail_conflict_prevents_promotion_even_with_high_confidence_dates(source, fixture_dir):
    detail = (fixture_dir / "bundeskartellamt_detail_quality.html").read_text(encoding="utf-8")
    detail = detail.replace("2026-07-17T09:00:00+02:00", "2026-07-18T09:00:00+02:00")
    result, _ = mock_scrape(source, historical_listing(fixture_dir), detail)
    assessment = assess_parse(result, observed_at=UNTIL)
    assert assessment["high_confidence_date_rate"] == 1
    assert assessment["conflict_rate"] == 1
    observation = {
        "source_id": source.id, "run_id": "synthetic-conflict", "timestamp": UNTIL.isoformat(),
        "config_hash": "synthetic", "healthy": True, "endpoints": [{"healthy": True}],
        "parse": assessment, "parse_request_failures": [],
    }
    assert not promotion_evidence(observation, [])["promotion_eligible"]


@pytest.mark.parametrize("robots,error", [
    ("User-agent: *\nDisallow: /DE/Home/", "ROBOTS_DENIED"),
    ("<!doctype html><html>challenge</html>", "ROBOTS_UNAVAILABLE"),
])
def test_unconfirmed_or_denied_robots_never_fetches_listing_or_details(source, fixture_dir, robots, error):
    result, calls = mock_scrape(source, historical_listing(fixture_dir), robots=robots)
    assert calls == ["https://www.bundeskartellamt.de/robots.txt"]
    assert not result.status.success
    assert result.status.error_code == error
    assert result.status.raw_count == 0


@pytest.mark.parametrize("floor,global_budget,expected", [
    (0, 60, 60), (600, 1, 600), (600, 60, 600), (600, 900, 900),
])
def test_source_budget_floor_reaches_actual_scrape_deadline(source, fixture_dir, monkeypatch,
                                                          floor, global_budget, expected):
    # The coordinating task added this field centrally during the audit.
    deadlines = []

    def timeout(seconds):
        deadlines.append(seconds)
        return asyncio.timeout(seconds)

    monkeypatch.setattr(scraper_module, "asyncio", SimpleNamespace(timeout=timeout, gather=asyncio.gather))
    configured = replace(source, minimum_budget_seconds=floor)
    result, _ = mock_scrape(configured, historical_listing(fixture_dir), fetch_details=False,
                           source_budget_seconds=global_budget)
    assert deadlines == [expected]
    assert result.status.success
    assert result.status.dated_count == 1
    assert result.parsed_articles[0].date_confidence == "high"
    assert not result.parsed_articles[0].date_conflict


def test_bka_floor_preserves_detail_quality_and_changes_both_configuration_fingerprints(source):
    assert source.minimum_budget_seconds == 600
    assert source.detail_pages == 12
    assert source.date_policy == "required"
    inherited = replace(source, minimum_budget_seconds=0)
    assert config_hash(source) != config_hash(inherited)
    assert source_config_fingerprint(source) != source_config_fingerprint(inherited)


@pytest.mark.parametrize("audit_warmed", [False, True])
@pytest.mark.parametrize("retry_every_page", [False, True])
def test_thirty_second_pacing_explains_budget_floor_and_retry_limit(source, monkeypatch,
                                                                 audit_warmed, retry_every_page):
    """Virtual time, real HttpClient pacing; no network and no real waiting.

    Robots markup is synthetic; only its 30-second delay comes from the user's
    primary live observation. Applying the observed 5.78-second home latency to
    every page models a scenario, not measured detail-request performance.
    """
    clock = [0.0]
    starts = []
    attempts = {}

    async def advance(seconds):
        clock[0] += seconds
        await asyncio.sleep(0)

    # Replace module references, not the process-wide clock or asyncio module:
    # real event-loop deadlines must not be driven by this simulated timeline.
    monkeypatch.setattr(http_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(http_module, "asyncio", SimpleNamespace(
        Semaphore=asyncio.Semaphore, Lock=asyncio.Lock, gather=asyncio.gather, sleep=advance,
    ))
    monkeypatch.setattr(http_module, "_retry_delay", lambda _response, _attempt: 0.5)

    def handler(request):
        assert request.url.host == "www.bundeskartellamt.de"
        starts.append((request.url.path, clock[0]))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\nCrawl-delay: 30\n",
                                  headers={"content-type": "text/plain"})
        if request.url.path == "/":
            return httpx.Response(302, headers={"location": source.listing_url})
        clock[0] += 5.78
        key = str(request.url)
        attempts[key] = attempts.get(key, 0) + 1
        if retry_every_page and attempts[key] % 2 == 1:
            return httpx.Response(503, text="synthetic transient error")
        return httpx.Response(200, text="synthetic page", headers={"content-type": "text/html"})

    async def run():
        async with HttpClient(obey_robots=True, min_interval=0.5,
                              transport=httpx.MockTransport(handler)) as client:
            if audit_warmed:
                # Existing source-audit checks both endpoints outside its parse deadline.
                await client.get(source.homepage)
                await client.get(source.listing_url)
            first = len(starts)
            began = clock[0]
            stats = HttpStats()
            await client.get(source.listing_url, stats=stats)
            for index in range(12):
                url = ("https://www.bundeskartellamt.de/SharedDocs/Meldung/DE/"
                       f"Pressemitteilungen/2026/synthetic_budget_{index}.html")
                await client.get(url, stats=stats)
            assert client._host_delays["www.bundeskartellamt.de"] == 30
            return clock[0] - began, starts[first:], stats

    elapsed, requests, stats = asyncio.run(run())
    pages = [(path, at) for path, at in requests if path != "/robots.txt"]
    assert len(pages) == (26 if retry_every_page else 13)
    assert all(second[1] - first[1] >= 30 - 1e-9 for first, second in zip(pages, pages[1:]))
    assert elapsed > 60
    if retry_every_page:
        assert pages[-1][1] - pages[0][1] == pytest.approx(750)
        assert elapsed > 600  # A finite 600-second floor cannot guarantee all retries.
        assert stats.retry_count == 13
    else:
        assert pages[-1][1] - pages[0][1] == pytest.approx(360)
        assert elapsed == pytest.approx(390 if audit_warmed else 366.28)
        assert elapsed < 600
        assert stats.retry_count == 0
