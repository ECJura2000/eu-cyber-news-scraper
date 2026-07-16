import json
from dataclasses import replace
from urllib.parse import urljoin

import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.parsers import parse_listing


def contract_rows():
    path = __file__.replace("test_source_contracts.py", "fixtures/source_contracts.json")
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


@pytest.mark.parametrize("row", contract_rows(), ids=lambda row: row["source_id"])
def test_source_listing_contract(row):
    source = next(item for item in load_sources() if item.id == row["source_id"])
    official_url = urljoin(source.homepage, f"contract-fixture/{source.id}")
    parser_source = replace(source, include_patterns=(), exclude_patterns=())
    if source.id == "fr_anssi":
        html = f'<div class="fr-card__content"><h3 class="fr-card__title"><a href="{official_url}">{row["title"]}</a></h3><p class="fr-card__desc">Publié le 3 juillet 2026</p></div>'
    elif source.id == "de_bsi_news":
        html = f'<table class="textualData"><tbody><tr><td>05.07.2026</td><td><a href="{official_url}">{row["title"]}</a></td></tr></tbody></table>'
    elif source.id == "fr_cnil":
        html = f'<div class="view-content"><div class="views-row"><h3 class="ctn-gen-liste-titre"><a href="{official_url}">{row["title"]}</a></h3><span class="date">3 juillet 2026</span></div></div>'
    else:
        html = f'<main><article><h2><a href="{official_url}">{row["title"]}</a></h2><time datetime="2026-07-03">3 July 2026</time><p>Official publication summary.</p></article><a href="{source.listing_url}">Next page</a></main>'
    articles = parse_listing(html, parser_source, source.listing_url)
    assert len(articles) == 1
    assert articles[0].title == row["title"]
    assert articles[0].url.startswith(("http://", "https://"))
    assert articles[0].published_at is not None
    assert "Next page" not in articles[0].title


def test_all_configured_sources_have_one_contract_fixture():
    source_ids = {source.id for source in load_sources()}
    fixture_ids = {row["source_id"] for row in contract_rows()}
    assert len(fixture_ids) == 55
    assert fixture_ids == source_ids
