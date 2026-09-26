from __future__ import annotations

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_listing


def test_previously_unlisted_eu_countries_have_manual_audited_sources():
    countries = {"AT", "BE", "BG", "CY", "CZ", "GR", "HR", "HU", "LU", "MT", "SK", "SI"}
    sources = [source for source in load_sources() if source.country in countries]
    registry = load_organisation_registry()
    assert {source.country for source in sources} == countries
    assert len(sources) == 24
    for source in sources:
        assert not source.schedule_enabled
        module = registry.module_for_source(source.id)
        assert module is not None
        verification = module.payload["verification"]
        assert len(verification["evidence_urls"]) >= 2
        assert verification["last_smoke"]["tested_on"] == "2026-09-26"
        assert verification["status"] != "official_url_confirmed_parser_pending"


def test_new_dutch_sources_are_manual_and_auditable():
    sources = {source.id: source for source in load_sources()}
    registry = load_organisation_registry()
    for source_id in ("nl_acm", "nl_rdi", "nl_tno", "nl_nwo"):
        source = sources[source_id]
        module = registry.module_for_source(source_id)
        assert not source.schedule_enabled
        assert not source.critical
        assert module is not None
        assert module.payload["responsibility_by_topic"] == {}
        assert len(module.payload["verification"]["evidence_urls"]) >= 2
    assert registry.module_for_source("nl_rdi").payload["verification"]["status"] == "parse_empty"


def test_tno_card_uses_article_title_and_own_date():
    source = next(item for item in load_sources() if item.id == "nl_tno")
    html = """<main><div class="rol-collage-card"><div class="collage-card-content">
      <h3>Cybersecurity research programme launched</h3>
      <div class="meta-date">25 September 2026</div>
      <div class="iprox-content">Research summary.</div>
      <div class="tno-button"><a href="/en/newsroom/2026/09/cybersecurity-research/">Read more</a></div>
    </div></div></main>"""
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 1
    assert articles[0].title == "Cybersecurity research programme launched"
    assert articles[0].published_date_local == "2026-09-25"
    assert articles[0].summary == "Research summary."


def test_acm_listing_excludes_subscription_link():
    source = next(item for item in load_sources() if item.id == "nl_acm")
    html = """<main><ul>
      <li><a href="/nl/nieuws/blijf-op-de-hoogte_">Schrijf u in</a></li>
      <li><a href="/nl/publicaties/acm-digital-market-news">ACM digital market investigation</a>
      <time datetime="2026-09-24">24 September 2026</time></li>
    </ul></main>"""
    articles = parse_listing(html, source, source.listing_url)
    assert [article.title for article in articles] == ["ACM digital market investigation"]


def test_list_news_card_uses_heading_and_local_date():
    source = next(item for item in load_sources() if item.id == "lu_list")
    html = """<main><article class="lt-event-card"><div class="lt-event-card__content">
      <h6 class="lt-heading">Trusted AI research project</h6>
      <div class="lt-info"><p>24.09.2026</p></div>
      <a class="lt-button" href="/media-events/news/news-detail/trusted-ai-research">View more</a>
    </div></article></main>"""
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 1
    assert articles[0].title == "Trusted AI research project"
    assert articles[0].published_date_local == "2026-09-24"


def test_belgian_dpa_press_card_has_english_date():
    source = next(item for item in load_sources() if item.id == "be_apd")
    html = """<main><div class="media"><div class="media-img"><div class="text">13 Jul<br>2026</div></div>
      <div class="media-body"><h3 class="media-title"><a href="/citizen/press-release">
      Belgian DPA investigates data protection complaint</a></h3></div></div></main>"""
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 1
    assert articles[0].published_date_local == "2026-07-13"
