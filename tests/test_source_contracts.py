import hashlib
import json
from pathlib import Path

import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.parsers import allowed_article_url, parse_listing


def contract_rows():
    path = Path(__file__).parent / "fixtures" / "source_contracts.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", contract_rows(), ids=lambda row: row["source_id"])
def test_real_official_url_contract(row):
    source = next(item for item in load_sources() if item.id == row["source_id"])
    assert allowed_article_url(source, row["url"])
    assert row["source_url"].startswith("https://")
    assert row["captured_at"] == "2026-07-18"
    digest = hashlib.sha256(f"{row['title']}\n{row['url']}".encode()).hexdigest()
    assert digest == row["sha256"]
    assert row["title"].casefold().strip() not in {"next", "next page", "nächste seite", "page suivante"}


LAYOUT_CONTRACTS = {
    "ie_dpc": ("contract_ie_dpc.html", "Data Protection Commission Publishes Annual Report", "2026-06-29"),
    "ie_cyber_ireland": ("contract_ie_cyber_ireland.html", "AI Changes the Rules of Cybersecurity", "2026-07-16"),
    "de_bnetza": ("contract_de_bnetza.html", "Digital Services Coordinator", "2026-07-05"),
    "de_bfdi": ("contract_de_bfdi.html", "datenschutzfreundlicher Altersverifizierung", "2026-06-25"),
    "de_bundeskartellamt": ("contract_de_bundeskartellamt.html", "RWE-Anteile an Amprion", "2026-07-16"),
}


@pytest.mark.parametrize("source_id", LAYOUT_CONTRACTS)
def test_high_risk_listing_layout_contract(source_id):
    fixture_name, expected_title, expected_utc_date = LAYOUT_CONTRACTS[source_id]
    source = next(item for item in load_sources() if item.id == source_id)
    html = (Path(__file__).parent / "fixtures" / fixture_name).read_text(encoding="utf-8")
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 1
    assert expected_title in articles[0].title
    assert articles[0].published_at.date().isoformat() == expected_utc_date
    assert "Next page" not in articles[0].title


def test_all_configured_sources_have_one_real_url_contract():
    source_ids = {source.id for source in load_sources()}
    fixture_ids = {row["source_id"] for row in contract_rows()}
    assert len(fixture_ids) == 55
    assert fixture_ids == source_ids
