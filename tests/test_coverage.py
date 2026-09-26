from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.coverage import load_coverage
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS


def test_all_topics_cover_four_legacy_and_thirteen_additional_jurisdictions():
    sources = load_sources()
    rows = load_coverage(sources)
    topics = {row.topic for row in rows}

    assert len(sources) == 101
    assert len(topics) == 15
    assert topics == set(OBSERVATION_TOPICS)
    assert len(rows) == 255
    for topic in topics:
        assert {row.country for row in rows if row.topic == topic} == {"EU", "FR", "DE", "IE", "ES", "PT", "IT", "PL", "DK", "NO", "SE", "EE", "LV", "LT", "NL", "RO", "FI"}
    assert all(row.roles and (row.verified_on == "2026-07-11" if row.country in {"EU", "FR", "DE", "IE"} else row.verified_on >= "2026-09-25") for row in rows)
    assert all(row.evidence_urls for row in rows if row.source_ids)
    assert all(row.authorities == "未覆蓋" for row in rows if not row.source_ids)
    assert all(url.startswith("https://") for row in rows for url in row.evidence_urls)
