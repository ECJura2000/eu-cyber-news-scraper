"""Source-specific parliamentary cards must not borrow dates from neighbouring news."""

from eu_cyber_news_scraper.config import load_sources_and_registry
from eu_cyber_news_scraper.parsers import parse_listing


def test_latvian_saeima_uses_date_beside_each_headline():
    sources, registry = load_sources_and_registry()
    source = next(item for item in sources if item.id == "lv_saeima")
    html = """
    <div class="news-block"><div class="post-content">
      <div class="title"><a href="/lv/aktualitates/saeimas-zinas/36210-first">
        Kiberdrošības likums parlamentā</a><span class="date">(25.09.2026.)</span></div>
      <div class="text">Pasākums notiks 2.10.2026.</div>
    </div></div>
    <div class="news-block"><div class="post-content">
      <div class="title"><a href="/lv/aktualitates/saeimas-zinas/36211-second">
        Parlamenta komiteja vērtē mākslīgo intelektu</a>
        <span class="date">(24.09.2026.)</span></div>
    </div></div>
    """
    articles = parse_listing(html, source, source.listing_url)
    assert [item.published_date_local for item in articles] == ["2026-09-25", "2026-09-24"]
    assert all(item.date_source == "source-selector" for item in articles)
    assert not source.schedule_enabled
    assert next(item for item in registry.audit_payload()["organisation_modules"]
                if item["canonical_id"] == "lv_saeima")["verification_status"] == "smoke_healthy"


def test_lithuanian_seimas_uses_own_news_time_not_adjacent_or_nav_date():
    sources, registry = load_sources_and_registry()
    source = next(item for item in sources if item.id == "lt_seimas")
    html = """
    <nav><a href="/sip/portal.show?p_r=35403&p_k=1&p_t=42">Future event 2026-10-12</a></nav>
    <div class="naujiena-row">
      <div class="naujiena-left naujiena">
        <p class="naujiena-laikas">2026-09-24 09:00</p>
        <p class="naujiena-title"><a href="/sip/portal.show?p_r=35403&p_k=1&p_t=43">
          Dirbtinio intelekto valdymas Seime</a></p>
      </div>
      <div class="naujiena-middle naujiena">
        <p class="naujiena-laikas">2026-09-25 14:43</p>
        <p class="naujiena-title"><a href="/sip/portal.show?p_r=35403&p_k=1&p_t=44">
          Duomenų apsaugos svarstymas Seime</a></p>
      </div>
    </div>
    """
    articles = parse_listing(html, source, source.listing_url)
    assert [item.published_date_local for item in articles] == ["2026-09-24", "2026-09-25"]
    assert all(item.date_source == "source-selector" for item in articles)
    assert not source.schedule_enabled
    assert next(item for item in registry.audit_payload()["organisation_modules"]
                if item["canonical_id"] == "lt_seimas")["verification_status"] == "smoke_healthy"


def test_polish_human_verification_is_not_publication_evidence():
    sources, registry = load_sources_and_registry()
    source = next(item for item in sources if item.id == "pl_sejm")
    challenge = "<html><head><title>Human Verification</title></head><body>Verify you are human</body></html>"
    assert parse_listing(challenge, source, source.listing_url) == []
    assert not source.schedule_enabled
    assert next(
        item for item in registry.audit_payload()["organisation_modules"]
        if item["canonical_id"] == "pl_sejm"
    )["verification_status"] == "smoke_attention"
