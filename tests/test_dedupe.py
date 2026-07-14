from datetime import datetime, timezone

from eu_cyber_news_scraper.dedupe import canonical_url, dedupe_articles
from eu_cyber_news_scraper.models import Article


def make(url):
    return Article("s", "EU", "S", "official", "en", "Title", url)


def test_canonical_url_removes_tracking_and_fragment():
    assert canonical_url("HTTPS://Example.eu/news/a/?utm_source=x&id=2#top") == "https://example.eu/news/a?id=2"


def test_dedupe_uses_canonical_url():
    articles = dedupe_articles([make("https://example.eu/a?utm_source=x"), make("https://example.eu/a")])
    assert len(articles) == 1


def test_dedupe_merges_better_metadata_and_provenance():
    first = make("https://example.eu/a")
    first.summary = "short"
    second = make("https://example.eu/a?utm_source=x")
    second.source_id = "other"
    second.summary = "a much more complete summary"
    second.matched_topics = ["NIS2、關鍵基礎設施保護"]
    merged = dedupe_articles([first, second])[0]
    assert merged.summary == second.summary
    assert merged.discovered_by == ["s", "other"]
    assert merged.matched_topics == second.matched_topics


def test_dedupe_merges_same_title_and_date_across_official_urls():
    first = make("https://agency.example/news/item")
    second = make("https://press.example/releases/42")
    first.published_at = second.published_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    second.source_id = "press"
    merged = dedupe_articles([first, second])
    assert len(merged) == 1
    assert merged[0].url == first.url
    assert merged[0].alternate_urls == [second.url]
    assert merged[0].discovered_by == ["s", "press"]


def test_dedupe_does_not_merge_same_title_on_different_dates():
    first = make("https://agency.example/news/one")
    second = make("https://agency.example/news/two")
    first.published_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    second.published_at = datetime(2026, 7, 9, tzinfo=timezone.utc)
    assert len(dedupe_articles([first, second])) == 2
