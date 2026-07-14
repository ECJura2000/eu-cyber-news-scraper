from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.coverage import load_coverage
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS


def test_all_topics_cover_all_four_jurisdictions_with_known_sources():
    sources = load_sources()
    rows = load_coverage(sources)
    topics = {row.topic for row in rows}

    assert len(sources) == 55
    assert len(topics) == 15
    assert topics == set(OBSERVATION_TOPICS)
    assert len(rows) == 60
    for topic in topics:
        assert {row.country for row in rows if row.topic == topic} == {"EU", "FR", "DE", "IE"}
    assert all(row.roles and row.evidence_urls and row.verified_on == "2026-07-11" for row in rows)
    assert all(url.startswith("https://") for row in rows for url in row.evidence_urls)
