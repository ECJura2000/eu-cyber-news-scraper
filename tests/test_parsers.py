import json
from datetime import timezone

from eu_cyber_news_scraper.models import Article, Source
from eu_cyber_news_scraper.parsers import discover_feeds, enrich_from_detail, parse_feed, parse_listing


def source(**overrides):
    values = {
        "id": "test",
        "country": "EU",
        "name_zh": "測試機關",
        "name": "Test Agency",
        "institution_type": "官方機關",
        "language": "en",
        "homepage": "https://agency.example/",
        "listing_url": "https://agency.example/news/",
        "allow_domains": ("agency.example",),
        "include_patterns": (r"/news/.+",),
    }
    values.update(overrides)
    return Source(**values)


def test_parse_rss_applies_domain_and_path_policy(fixture_dir):
    payload = (fixture_dir / "sample.rss").read_bytes()
    articles = parse_feed(payload, source(), "fixture")
    assert [article.title for article in articles] == ["NIS2 incident reporting templates adopted"]
    assert articles[0].published_at.tzinfo == timezone.utc


def test_discover_and_parse_french_listing(fixture_dir):
    html = (fixture_dir / "listing_fr.html").read_text(encoding="utf-8")
    fr_source = source(
        country="FR",
        language="fr",
        listing_url="https://cyber.example/actualites/",
        allow_domains=("cyber.example",),
        include_patterns=(r"/actualites/.+",),
    )
    assert discover_feeds(html, fr_source.listing_url) == ["https://cyber.example/actualites/rss/"]
    articles = parse_listing(html, fr_source, fr_source.listing_url)
    assert len(articles) == 1
    assert articles[0].published_at.date().isoformat() == "2026-03-18"


def test_enrich_article_from_open_graph(fixture_dir):
    article = Article(
        source_id="de",
        country="DE",
        source_name="研究機構",
        institution_type="公共研究",
        language="de",
        title="Kurz",
        url="https://example.de/news/cra",
    )
    html = (fixture_dir / "detail_de.html").read_text(encoding="utf-8")
    enrich_from_detail(article, html)
    assert article.title.startswith("Cyber Resilience Act")
    assert "Produkte mit digitalen Elementen" in article.summary
    assert article.published_at.isoformat().startswith("2026-05-07T07:30:00")


def test_listing_respects_base_and_skips_non_article_candidates():
    html = """
    <html><head><base href="/"></head><body><main>
      <article><img alt="decorative image"></article>
      <ul><li><a href="DE/news/item.html"><h2>Neue Regeln für Cybersicherheit</h2></a></li></ul>
    </main></body></html>
    """
    de_source = source(
        country="DE",
        language="de",
        listing_url="https://agency.example/DE/list/index.html",
        include_patterns=(r"/DE/news/.+",),
    )
    articles = parse_listing(html, de_source, de_source.listing_url)
    assert len(articles) == 1
    assert articles[0].url == "https://agency.example/DE/news/item.html"


def test_detail_falls_back_to_visible_ordinal_date():
    item = Article("ie", "IE", "Agency", "official", "en", "Original title", "https://agency.example/news/item")
    enrich_from_detail(item, "<html><body><h1>Updated official title</h1><p class='date'>08th May 2026</p></body></html>")
    assert item.published_at.date().isoformat() == "2026-05-08"


def test_listing_reads_empty_overlay_link_from_card():
    card_source = source(include_patterns=(r"^/news/.+_en$",))
    html = """
    <div class="card"><h3>EDPB adopts guidance on generative AI</h3>
      <time datetime="2026-07-08T12:00:00Z">8 July 2026</time>
      <a href="/news/generative-ai_en"></a>
    </div>
    """
    articles = parse_listing(html, card_source, "https://agency.example/news_en")
    assert articles[0].title == "EDPB adopts guidance on generative AI"
    assert articles[0].published_at is not None


def test_parse_presscorner_json_feed():
    payload = json.dumps(
        {
            "docuLanguageListResources": [
                {
                    "title": "Commission publishes cybersecurity guidance",
                    "eventDate": "2026-07-10",
                    "leadText": "New guidance for secure digital services.",
                    "refCode": "IP/26/1579",
                }
            ]
        }
    )
    press_source = source(
        listing_url="https://ec.europa.eu/commission/presscorner/home/en",
        allow_domains=("ec.europa.eu",),
        include_patterns=(r"/commission/presscorner/detail/",),
    )
    articles = parse_feed(payload, press_source, "official-api")
    assert articles[0].url.endswith("/ip_26_1579")
    assert articles[0].published_at.date().isoformat() == "2026-07-10"
