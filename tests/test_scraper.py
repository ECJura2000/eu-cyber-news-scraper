import asyncio
from datetime import datetime, timezone

import httpx

from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.scraper import _is_non_html_url, _listing_urls, scrape_source


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, url, *, stats=None):
        return httpx.Response(200, content=self.payload, request=httpx.Request("GET", url))


class MappingClient:
    def __init__(self, payloads):
        self.payloads = payloads

    async def get(self, url, *, stats=None):
        value = self.payloads[url]
        if isinstance(value, Exception):
            raise value
        return httpx.Response(200, content=value, request=httpx.Request("GET", url))


def run_scraper(*args, **kwargs):
    return asyncio.run(scrape_source(*args, **kwargs))


def test_scrape_source_filters_date_and_topic(fixture_dir):
    source = Source(
        id="test",
        country="EU",
        name_zh="測試機關",
        name="Test",
        institution_type="official",
        language="en",
        homepage="https://agency.example/",
        listing_url="https://agency.example/news/",
        feed_urls=("https://agency.example/feed.xml",),
        allow_domains=("agency.example",),
        include_patterns=(r"/news/.+",),
    )
    result = run_scraper(
        source,
        FakeClient((fixture_dir / "sample.rss").read_bytes()),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
        fetch_details=False,
    )
    assert result.status.success
    assert result.status.relevant_count == 1
    assert result.status.in_range_count == 1
    assert "NIS2、關鍵基礎設施保護" in result.articles[0].matched_topics


def test_empty_parse_is_not_reported_as_healthy():
    source = Source(
        id="empty",
        country="EU",
        name_zh="空來源",
        name="Empty",
        institution_type="official",
        language="en",
        homepage="https://agency.example/",
        listing_url="https://agency.example/news/",
        allow_domains=("agency.example",),
        include_patterns=(r"/news/.+",),
    )
    result = run_scraper(
        source,
        FakeClient(b"<html><main></main></html>"),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert not result.status.success
    assert result.status.fetch_status == "ok"
    assert result.status.parse_status == "empty"
    assert result.status.error_code == "PARSE_EMPTY"
    assert "未解析出新聞" in result.status.warning


def test_undersized_html_challenge_is_not_reported_as_successful_transport():
    source = Source(
        "challenge", "FR", "來源", "Source", "official", "fr",
        "https://agency.example/", "https://agency.example/news/",
        allow_domains=("agency.example",), min_listing_bytes=50000,
    )

    class ChallengeClient:
        async def get(self, url, *, stats=None):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<html><title>Checking your browser</title></html>",
                request=httpx.Request("GET", url),
            )

    result = run_scraper(
        source,
        ChallengeClient(),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
        fetch_details=False,
    )
    assert result.status.fetch_status == "failed"
    assert result.status.error_code == "HTTP_CHALLENGE"


def test_configured_feed_challenge_is_not_reported_as_successful_transport():
    source = Source(
        "feed-challenge", "FR", "來源", "Source", "official", "fr",
        "https://agency.example/", "https://agency.example/news",
        feed_urls=("https://agency.example/feed.xml",),
        allow_domains=("agency.example",), min_listing_bytes=50000,
    )

    class FeedChallengeClient:
        async def get(self, url, *, stats=None):
            if url.endswith("feed.xml"):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    content=b"<html><title>Checking your browser</title></html>",
                    request=httpx.Request("GET", url),
                )
            raise RuntimeError("listing unavailable")

    client = FeedChallengeClient()

    result = asyncio.run(
        scrape_source(
            source,
            client,
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
            until=datetime(2026, 2, 1, tzinfo=timezone.utc),
            include_unmatched=True,
            include_undated=True,
            fetch_details=False,
        )
    )

    assert result.status.fetch_status == "failed"
    assert result.status.error_code == "HTTP_CHALLENGE"
    assert "ChallengePageError" in result.status.error


def test_no_topic_hit_is_content_result_not_fetch_warning(fixture_dir):
    source = Source(
        "content", "EU", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        feed_urls=("https://agency.example/feed.xml",), allow_domains=("agency.example",),
    )
    result = run_scraper(
        source,
        FakeClient((fixture_dir / "sample.rss").read_bytes()),
        since=datetime(2026, 4, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 1, tzinfo=timezone.utc),
        fetch_details=False,
    )
    assert result.status.warning == ""
    assert "沒有命中" in result.status.content_warning


def test_yearly_listing_and_pagination_cover_cross_year_range():
    source = Source(
        "yearly", "IE", "來源", "Source", "official", "en", "https://x.ie", "https://x.ie/news",
        yearly_listing_url="https://x.ie/news/{year}/",
        pagination_url="https://x.ie/news/{year}/?page={page}",
        max_pages=3,
    )
    urls = _listing_urls(
        source,
        datetime(2025, 12, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    assert urls == [
        "https://x.ie/news/2026/", "https://x.ie/news/2026/?page=1", "https://x.ie/news/2026/?page=2",
        "https://x.ie/news/2025/", "https://x.ie/news/2025/?page=1", "https://x.ie/news/2025/?page=2",
    ]


def test_future_dates_are_invalidated_before_range_filtering():
    source = Source(
        "future", "EU", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        feed_urls=("https://agency.example/feed.xml",), allow_domains=("agency.example",),
    )
    payload = b"""<?xml version='1.0'?><rss><channel><item>
      <title>NIS2 future event</title><link>https://agency.example/news/future</link>
      <pubDate>Thu, 31 Dec 2026 08:00:00 GMT</pubDate></item></channel></rss>"""
    result = run_scraper(
        source,
        FakeClient(payload),
        since=datetime(2026, 7, 1, tzinfo=timezone.utc),
        until=datetime(2027, 1, 1, tzinfo=timezone.utc),
        observed_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        fetch_details=False,
    )
    assert result.status.invalid_date_count == 1
    assert result.status.in_range_count == 0
    assert "未來日期" in result.status.warning


def test_listing_discovers_feed_after_configured_feed_failure():
    source = Source(
        "fallback", "EU", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        feed_urls=("https://agency.example/bad.xml",), allow_domains=("agency.example",),
    )
    listing = b"<html><head><link rel='alternate' type='application/rss+xml' href='/good.xml'></head></html>"
    feed = b"""<rss><channel><item><title>NIS2 security update</title>
      <link>https://agency.example/news/item</link><pubDate>Fri, 01 May 2026 08:00:00 GMT</pubDate>
      <description>NIS2 risk management requirements</description></item></channel></rss>"""
    client = MappingClient(
        {
            "https://agency.example/bad.xml": RuntimeError("broken feed"),
            "https://agency.example/news/": listing,
            "https://agency.example/good.xml": feed,
        }
    )
    result = run_scraper(
        source,
        client,
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
        fetch_details=False,
    )
    assert result.status.success
    assert result.status.fetched_via == "feed+html-listing"
    assert "備援" in result.status.warning


def test_yearly_listing_is_parsed_even_when_a_discovered_feed_has_entries():
    source = Source(
        "yearly-feed", "IE", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        allow_domains=("agency.example",), include_patterns=(r"/news/.+",),
        yearly_listing_url="https://agency.example/news/{year}/",
    )
    listing = b"""<html><head>
      <link rel='alternate' type='application/rss+xml' href='/comments/feed/' />
      <link rel='alternate' type='application/rss+xml' href='/feed.xml' />
      </head><main><article><h2><a href='/news/current'>Current NIS2 guidance</a></h2>
      <time datetime='2026-05-10'>10 May 2026</time></article></main></html>"""
    feed = b"""<rss><channel><item><title>Older NIS2 guidance</title>
      <link>https://agency.example/news/older</link><pubDate>Fri, 01 May 2020 08:00:00 GMT</pubDate>
      </item></channel></rss>"""
    client = MappingClient(
        {
            "https://agency.example/news/2026/": listing,
            "https://agency.example/feed.xml": feed,
        }
    )
    result = run_scraper(
        source,
        client,
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2027, 1, 1, tzinfo=timezone.utc),
        fetch_details=False,
    )
    assert result.status.newest_published_at.startswith("2026-05-10")
    assert result.status.in_range_count == 1


def test_source_budget_stops_network_paths():
    source = Source(
        "budget", "EU", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        feed_urls=("https://agency.example/feed.xml",),
    )
    class SlowClient:
        async def get(self, url, *, stats=None):
            await asyncio.sleep(5)
            raise AssertionError("cancelled request unexpectedly completed")

    result = run_scraper(
        source,
        SlowClient(),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
        source_budget_seconds=1,
    )
    assert not result.status.success
    assert result.status.timeout_count == 1
    assert result.status.budget_exhausted
    assert "SourceBudgetExceeded" in result.status.error
    assert result.status.duration_seconds < 2


def test_non_html_url_detection():
    assert _is_non_html_url("https://example.eu/report.pdf")
    assert _is_non_html_url("https://example.eu/news/feed/")
    assert not _is_non_html_url("https://example.eu/news/item")


def test_cross_domain_redirect_is_rejected():
    source = Source(
        "redirect", "EU", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        allow_domains=("agency.example",),
    )

    class RedirectClient:
        async def get(self, url, *, stats=None):
            return httpx.Response(200, content=b"<html></html>", request=httpx.Request("GET", "https://evil.example/"))

    result = run_scraper(
        source,
        RedirectClient(),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert result.status.fetch_status == "failed"
    assert "RedirectDomainError" in result.status.error
