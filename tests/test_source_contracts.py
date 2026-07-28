import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.parsers import allowed_article_url, enrich_from_detail, parse_listing


def contract_rows():
    path = Path(__file__).parent / "fixtures" / "source_contracts.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", contract_rows(), ids=lambda row: row["source_id"])
def test_real_official_url_contract(row):
    source = next(item for item in load_sources() if item.id == row["source_id"])
    assert allowed_article_url(source, row["url"])
    assert row["source_url"].startswith("https://")
    assert date.fromisoformat(row["captured_at"]) <= date.today()
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


def attention_layout_rows():
    path = Path(__file__).parent / "fixtures" / "attention_layout_contracts.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", attention_layout_rows(), ids=lambda row: row["source_id"])
def test_attention_source_layout_contract(row):
    fixture = Path(__file__).parent / "fixtures" / row["fixture"]
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == row["sha256"]
    assert date.fromisoformat(row["captured_at"]) <= date.today()
    assert row["source_url"].startswith("https://")

    source = next(item for item in load_sources() if item.id == row["source_id"])
    articles = parse_listing(fixture.read_text(encoding="utf-8"), source, source.listing_url)
    assert len(articles) == row["count"]
    assert row["title"] in articles[0].title
    assert articles[0].published_date_local == row["date"]
    assert all("next page" not in article.title.casefold() for article in articles)


def test_interface_listing_and_detail_date_contract():
    fixture_dir = Path(__file__).parent / "fixtures"
    listing = fixture_dir / "contract_de_interface.html"
    detail = fixture_dir / "contract_de_interface_detail.html"
    assert hashlib.sha256(listing.read_bytes()).hexdigest() == (
        "626acc00ad36b916213e10556886acdd1d6a31cf36feef3da27ddb67f538bf11"
    )
    assert hashlib.sha256(detail.read_bytes()).hexdigest() == (
        "60127469c1f8b5c7d91ede9e4e77d0fb49872142fad8a43a2841a5ac9ed9a1e1"
    )
    source = next(item for item in load_sources() if item.id == "de_interface")
    article = parse_listing(listing.read_text(encoding="utf-8"), source, source.listing_url)[0]
    assert article.published_at is None
    enrich_from_detail(article, detail.read_text(encoding="utf-8"), source)
    assert article.published_date_local == "2026-07-15"
