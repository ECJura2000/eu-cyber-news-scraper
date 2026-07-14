import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.parsers import parse_listing

EXPECTED = {
    "eu_dg_connect": "AI Office publishes model guidance",
    "eu_enisa_news": "ENISA publishes cybersecurity report",
    "fr_anssi": "Guide français pour NIS2",
    "fr_cybermalveillance": "Conseils contre les rançongiciels",
    "de_bsi_news": "BSI veröffentlicht Lagebericht",
    "ie_ncsc": "NCSC publishes security alert",
    "ie_comreg": "ComReg issues NIS2 update",
}


@pytest.mark.parametrize("source_id", sorted(EXPECTED))
def test_critical_source_listing_contract(source_id, fixture_dir):
    source = next(item for item in load_sources() if item.id == source_id)
    html = (fixture_dir / f"critical_{source_id}.html").read_text(encoding="utf-8")
    articles = parse_listing(html, source, source.listing_url)
    assert [item.title for item in articles] == [EXPECTED[source_id]]
    assert articles[0].published_at is not None
    assert articles[0].url != source.listing_url


def test_every_critical_source_has_a_contract_fixture(fixture_dir):
    critical = {item.id for item in load_sources() if item.critical}
    fixtures = {path.stem.removeprefix("critical_") for path in fixture_dir.glob("critical_*.html")}
    assert fixtures == critical
