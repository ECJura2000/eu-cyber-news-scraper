from datetime import datetime, timezone

from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.scraper import _listing_urls, scrape_source


class Response:
    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode("utf-8")


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url):
        return Response(self.payload)


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
    result = scrape_source(
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
    result = scrape_source(
        source,
        FakeClient(b"<html><main></main></html>"),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert not result.status.success
    assert "未解析出新聞" in result.status.warning


def test_no_topic_hit_is_content_result_not_fetch_warning(fixture_dir):
    source = Source(
        "content", "EU", "來源", "Source", "official", "en",
        "https://agency.example/", "https://agency.example/news/",
        feed_urls=("https://agency.example/feed.xml",), allow_domains=("agency.example",),
    )
    result = scrape_source(
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
