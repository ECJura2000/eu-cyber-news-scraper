import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.http import HttpClient
from eu_cyber_news_scraper.parsers import allowed_article_url, parse_feed, parse_listing
from eu_cyber_news_scraper.robots import RobotsPolicy
from eu_cyber_news_scraper.scraper import scrape_source
from eu_cyber_news_scraper.source_audit import assess_parse

FEED_URL = "https://www.bmi.bund.de/DE/service/rss-newsfeed/function/rssnewsfeed-pressemitteilungen.xml"
LISTING_URL = "https://www.bmi.bund.de/DE/presse/presse-node.html"
BLOCKED_URL = "https://www.bmi.bund.de/SiteGlobals/Forms/suche/expertensuche-formular.html"
NOW = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)


@pytest.fixture
def bmi_source():
    return next(source for source in load_sources() if source.id == "de_bmi")


def test_bmi_official_entries_respect_published_robots(bmi_source, fixture_dir):
    policy = RobotsPolicy.parse((fixture_dir / "bmi_robots.txt").read_text())
    assert policy.crawl_delay == 10
    assert not policy.allows(BLOCKED_URL)
    assert not policy.allows(FEED_URL.replace("/service/", "/Service/"))
    assert bmi_source.listing_url == LISTING_URL
    assert bmi_source.feed_urls == (FEED_URL,)
    assert all(policy.allows(url) for url in (LISTING_URL, FEED_URL))


def test_bmi_public_feed_keeps_publication_dates_and_source_boundary(bmi_source, fixture_dir):
    articles = parse_feed((fixture_dir / "bmi_press_feed.xml").read_bytes(), bmi_source, FEED_URL)
    assert len(articles) == 3
    assert [item.published_date_local for item in articles] == ["2026-09-26", "2026-09-23", "2026-09-16"]
    assert articles[0].published_at == datetime(2026, 9, 26, 5, 37, tzinfo=timezone.utc)
    assert articles[0].published_at_raw == "Sat, 26 Sep 2026 07:37:00 +0200"
    assert "München eingeladen" in articles[0].summary
    assert all(item.date_confidence == "high" and item.date_source == "feed-published" for item in articles)
    assert all(not item.date_conflict and allowed_article_url(bmi_source, item.url) for item in articles)
    assert not allowed_article_url(bmi_source, articles[0].url.replace("www.bmi.bund.de", "www.bmas.de"))
    assert not allowed_article_url(bmi_source, LISTING_URL)


def test_bmi_press_fallback_reads_teaser_date_instead_of_body_date(bmi_source, fixture_dir):
    html = (fixture_dir / "bmi_press_listing.html").read_text()
    # A later event date in the summary must not replace the publication date.
    html = html.replace("am 26. September 2026", "am 12. Oktober 2026")
    articles = parse_listing(html, bmi_source, LISTING_URL)
    assert len(articles) == 1
    assert articles[0].published_date_local == "2026-09-26"
    assert articles[0].date_confidence == "high"
    assert articles[0].date_source == "source-selector"


@pytest.mark.parametrize("feed_unavailable", [False, True])
def test_bmi_production_flow_uses_feed_or_allowed_fallback(
    bmi_source, fixture_dir, monkeypatch, feed_unavailable,
):
    requests = []

    async def no_pace(_self, _host):
        return None

    monkeypatch.setattr(HttpClient, "_pace", no_pace)

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=(fixture_dir / "bmi_robots.txt").read_text())
        if str(request.url) == FEED_URL:
            if feed_unavailable:
                return httpx.Response(403)
            return httpx.Response(200, content=(fixture_dir / "bmi_press_feed.xml").read_bytes(),
                                  headers={"content-type": "text/xml;charset=utf-8"})
        if str(request.url) == LISTING_URL:
            return httpx.Response(200, text=(fixture_dir / "bmi_press_listing.html").read_text(),
                                  headers={"content-type": "text/html"})
        pytest.fail(f"Unexpected request: {request.url}")

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            return await scrape_source(
                bmi_source, client, since=datetime(2026, 9, 17, tzinfo=timezone.utc), until=NOW,
                include_unmatched=True, source_budget_seconds=60, observed_at=NOW,
            )

    result = asyncio.run(run())
    assert result.status.success
    assert result.status.raw_count == (1 if feed_unavailable else 3)
    assert result.status.dated_count == result.status.raw_count
    assert result.status.fetched_via == ("html-listing" if feed_unavailable else "configured-feed")
    assert result.status.retry_count == 0  # A 403 is never retried.
    assert requests == ["/robots.txt", httpx.URL(FEED_URL).path] + (
        [httpx.URL(LISTING_URL).path] if feed_unavailable else []
    )
    assessment = assess_parse(result, observed_at=NOW)
    assert assessment["assessment_complete"]
    assert assessment["high_confidence_date_rate"] == 1.0
    assert assessment["conflict_rate"] == 0
    assert assessment["future_count"] == assessment["missing_required_count"] == 0


def test_bmi_period_before_retained_feed_still_requests_allowed_listing(bmi_source, fixture_dir, monkeypatch):
    requests = []
    since = datetime(2026, 5, 1, tzinfo=timezone.utc)
    until = datetime(2026, 6, 1, tzinfo=timezone.utc)
    feed = (fixture_dir / "bmi_archive_feed.xml").read_bytes()
    retained = parse_feed(feed, bmi_source, FEED_URL)
    assert bmi_source.feed_archive_fallback is True
    assert len(retained) == 2
    assert until < min(item.published_at for item in retained)

    async def no_pace(_self, _host):
        return None

    monkeypatch.setattr(HttpClient, "_pace", no_pace)

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=(fixture_dir / "bmi_robots.txt").read_text())
        if str(request.url) == FEED_URL:
            return httpx.Response(200, content=feed, headers={"content-type": "text/xml;charset=utf-8"})
        if str(request.url) == LISTING_URL:
            return httpx.Response(200, text=(fixture_dir / "bmi_press_listing.html").read_text(),
                                  headers={"content-type": "text/html"})
        pytest.fail(f"Unexpected request: {request.url}")

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            return await scrape_source(
                bmi_source, client, since=since, until=until, include_unmatched=True,
                source_budget_seconds=60, observed_at=NOW,
            )

    result = asyncio.run(run())
    assert requests == ["/robots.txt", httpx.URL(FEED_URL).path, httpx.URL(LISTING_URL).path]
    assert httpx.URL(BLOCKED_URL).path not in requests
    assert result.status.pages_fetched == 1
    assert result.status.fetched_via == "feed+html-listing"
    assert result.status.raw_count == 3
    # Traversing the current listing does not establish complete historical coverage.
    assert result.status.in_range_count == 0
    assert result.articles == []


def test_bmi_denied_legacy_path_is_never_requested(bmi_source, fixture_dir, monkeypatch):
    requests = []

    async def no_pace(_self, _host):
        return None

    monkeypatch.setattr(HttpClient, "_pace", no_pace)

    def handler(request):
        requests.append(request.url.path)
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, text=(fixture_dir / "bmi_robots.txt").read_text())

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            return await scrape_source(
                replace(bmi_source, listing_url=BLOCKED_URL, feed_urls=()), client,
                since=datetime(2026, 9, 15, tzinfo=timezone.utc), until=NOW,
                source_budget_seconds=60, observed_at=NOW,
            )

    result = asyncio.run(run())
    assert requests == ["/robots.txt"]
    assert not result.status.success
    assert result.status.error_code == "ROBOTS_DENIED"
