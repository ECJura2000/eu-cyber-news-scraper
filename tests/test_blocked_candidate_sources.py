"""Regression checks for parliament candidates that require manual validation."""

import asyncio
from datetime import datetime, timezone

import httpx

from eu_cyber_news_scraper.config import load_sources_and_registry
from eu_cyber_news_scraper.scraper import scrape_source


def test_riigikogu_uses_officially_linked_rss_without_enabling_schedule():
    sources, registry = load_sources_and_registry()
    source = next(item for item in sources if item.id == "ee_riigikogu")
    module = registry.module_for_source(source.id)
    assert module is not None
    assert source.feed_urls == ("https://feeds.feedburner.com/RiigikoguPressiteated",)
    assert set(source.allow_domains) == {"www.riigikogu.ee", "feeds.feedburner.com"}
    assert "https://www.riigikogu.ee/telli-rss/" in module.payload["verification"]["evidence_urls"]
    assert module.payload["verification"]["status"] == "smoke_healthy"
    assert not source.schedule_enabled


def test_riigikogu_feed_parses_dated_official_article_without_listing_request():
    source = next(item for item in load_sources_and_registry()[0] if item.id == "ee_riigikogu")
    feed = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel><item>
      <title>Riigikogu arutas tehisintellekti seadust</title>
      <link>https://www.riigikogu.ee/pressiteated/tehisintellekti-seadus/</link>
      <pubDate>Thu, 24 Sep 2026 12:40:05 +0000</pubDate>
    </item></channel></rss>"""

    class FeedClient:
        def __init__(self):
            self.urls = []

        async def get(self, url, *, stats=None):
            self.urls.append(url)
            return httpx.Response(200, content=feed, request=httpx.Request("GET", url))

    client = FeedClient()
    result = asyncio.run(
        scrape_source(
            source,
            client,
            since=datetime(2026, 9, 23, tzinfo=timezone.utc),
            until=datetime(2026, 9, 26, tzinfo=timezone.utc),
            include_unmatched=True,
            fetch_details=False,
        )
    )
    assert client.urls == [source.feed_urls[0]]
    assert result.status.fetch_status == "ok"
    assert result.status.parse_status == "healthy"
    assert result.status.raw_count == 1
    assert result.articles[0].published_date_local == "2026-09-24"
    assert result.articles[0].date_confidence == "high"


def test_other_blocked_parliaments_remain_manual_and_unmodified():
    loaded, registry = load_sources_and_registry()
    sources = {item.id: item for item in loaded}
    assert sources["es_congreso"].listing_url == "https://www.congreso.es/es/notas-de-prensa"
    assert sources["dk_folketing"].listing_url == "https://www.ft.dk/da/aktuelt/nyheder"
    for key in ("es_congreso", "dk_folketing"):
        source = sources[key]
        module = registry.module_for_source(key)
        assert module is not None
        assert not source.feed_urls
        assert not source.schedule_enabled
        assert module.payload["verification"]["status"] == "blocked_runner"
