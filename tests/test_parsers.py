import json
from datetime import timezone

from eu_cyber_news_scraper.models import Article, Source
from eu_cyber_news_scraper.parsers import discover_feeds, enrich_from_detail, parse_datetime, parse_feed, parse_listing


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


def test_detail_prefers_article_heading_over_generic_social_title():
    item = Article("de", "DE", "Agency", "official", "de", "Original title", "https://agency.example/news/item")
    html = """
    <html><head><title>DPMA | 02.07.2026</title>
      <meta property="og:title" content="DPMA | 02.07.2026"></head>
      <body><main><h1>Für besseren Transfer: Amt und Hochschule kooperieren</h1></main></body>
    </html>
    """
    enrich_from_detail(item, html)
    assert item.title == "Für besseren Transfer: Amt und Hochschule kooperieren"


def test_detail_prefers_article_meta_over_title_heuristic_and_records_conflict():
    item = Article("de", "DE", "Agency", "official", "de", "Original title", "https://agency.example/news/item")
    html = """
    <html><head><title>DPMA | 10.03.2026</title><meta name="date" content="2026-07-07"></head>
      <body><main><h1>Official press release</h1></main><p class="stand">Stand: 07.07.2026</p></body>
    </html>
    """
    enrich_from_detail(item, html)
    assert item.published_at.date().isoformat() == "2026-07-07"
    assert item.date_source == "article-meta"
    assert item.date_conflict


def test_dpma_adapter_uses_formal_release_date_instead_of_page_update_meta():
    item = Article("de_dpma", "DE", "DPMA", "official", "de", "Original title", "https://www.dpma.de/item")
    dpma_source = source(id="de_dpma", country="DE", language="de", parser_adapter="dpma_press_release")
    html = """
    <html><head><meta name="date" content="2026-07-07"></head>
      <body><main><h1>DPMA-Jahresstatistik 2025</h1><em>Pressemitteilung vom 10. März 2026</em></main></body>
    </html>
    """
    enrich_from_detail(item, html, dpma_source)
    assert item.published_date_local == "2026-03-10"
    assert item.published_at_raw == "Pressemitteilung vom 10. März 2026"
    assert item.date_source == "source-selector"
    assert not item.date_conflict


def test_detail_accepts_month_first_visible_date_with_compact_comma():
    item = Article("eu", "EU", "Agency", "official", "en", "Original title", "https://agency.example/news/item")
    enrich_from_detail(item, '<main><h1>Frontier AI podcast</h1><span class="date-display">Jul 14,2026</span></main>')
    assert item.published_at is not None
    assert item.published_at.date().isoformat() == "2026-07-14"
    assert item.date_source == "visible-text"


def test_numeric_european_date_uses_day_month_year_order():
    parsed = parse_datetime("08-04-2026 16:00:00", ("en",), "Europe/Brussels")
    assert parsed is not None
    assert parsed.date().isoformat() == "2026-04-08"


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


def test_listing_rejects_navigation_links_and_does_not_borrow_neighbour_date():
    html = """
    <main><section>
      <a href="/news/next">nächste Seite</a>
      <article><time datetime="2026-07-08">8 July 2026</time>
        <a href="/news/real">Official cybersecurity guidance published</a>
      </article>
    </section></main>
    """
    articles = parse_listing(html, source(), "https://agency.example/news/")
    assert [article.title for article in articles] == ["Official cybersecurity guidance published"]


def test_detail_does_not_treat_unscoped_event_date_as_publication_date():
    item = Article("ie", "IE", "Agency", "official", "en", "Original title", "https://agency.example/news/item")
    enrich_from_detail(item, "<html><body><h1>Conference</h1><p>Event date 31 December 2027</p></body></html>")
    assert item.published_at is None


def test_dpc_source_patterns_exclude_section_and_pagination_links():
    dpc_source = source(
        allow_domains=("dataprotection.ie",),
        include_patterns=(
            r"^/en/news-media/(?:latest-news|press-releases)/[^/?]+/?$",
            r"^/en/news-media/[^/?]+/?$",
        ),
        exclude_patterns=(r"^/en/news-media/(?:latest-news|press-releases|contact-us|consultations)/?(?:\?.*)?$",),
    )
    html = """
    <main>
      <a href="/en/news-media/latest-news?page=0">News | Data Protection Commission</a>
      <a href="/en/news-media/press-releases">Press Releases | Data Protection Commission</a>
      <article><a href="/en/news-media/latest-news/final-inquiry-decision">DPC announces final inquiry decision</a></article>
    </main>
    """
    articles = parse_listing(html, dpc_source, "https://dataprotection.ie/en/news-media/latest-news")
    assert [article.title for article in articles] == ["DPC announces final inquiry decision"]


def test_dpma_archive_listing_exposes_current_press_releases():
    dpma_source = source(
        country="DE",
        language="de",
        homepage="https://www.dpma.de/",
        listing_url="https://www.dpma.de/service/presse/pressemitteilungen/archiv/index.html",
        allow_domains=("dpma.de", "www.dpma.de"),
        include_patterns=(r"^/service/presse/pressemitteilungen/\d{8}/index\.html$",),
        exclude_patterns=(r"^/service/presse/pressemitteilungen/(?:archiv/)?index\.html$",),
    )
    html = """
    <main>
      <ul><li><a href="/service/presse/pressemitteilungen/08072026/index.html">08.07.2026</a></li></ul>
      <a href="/service/presse/pressemitteilungen/archiv/index.html">Archiv</a>
    </main>
    """
    articles = parse_listing(html, dpma_source, dpma_source.listing_url)
    assert len(articles) == 1
    assert articles[0].url.endswith("/08072026/index.html")
    assert articles[0].published_at is not None
    assert articles[0].published_date_local == "2026-07-08"
