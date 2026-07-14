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
