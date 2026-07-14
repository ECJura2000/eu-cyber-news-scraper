from eu_cyber_news_scraper.config import load_sources


def test_default_sources_cover_all_target_jurisdictions():
    sources = load_sources()
    assert len(sources) >= 33
    assert {source.country for source in sources} == {"EU", "FR", "DE", "IE"}
    assert any(source.id == "fr_anssi" and source.feed_urls for source in sources)
    assert any(source.id == "ie_ncsc" and source.critical for source in sources)
    assert any(source.id == "fr_viginum" for source in sources)
    assert any(source.id == "de_bfdi" for source in sources)
    assert any(source.id == "ie_cnam" for source in sources)


def test_source_ids_are_unique():
    sources = load_sources()
    assert len({source.id for source in sources}) == len(sources)
