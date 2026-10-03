"""A bounded publication sample must never claim complete period coverage."""
import asyncio
from datetime import datetime, timezone

import httpx

from eu_cyber_news_scraper import scraper
from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.models import Article


def test_detail_sample_retains_incomplete_history_warning(monkeypatch):
    source = next(item for item in load_sources() if item.id == 'be_science_policy')

    class Client:
        async def get(self, url, **kwargs):
            return httpx.Response(200, text='<html><main>Official press listing</main></html>',
                                  request=httpx.Request('GET', url))

    async def details(*args):
        return [Article(source.id, source.country, source.name_zh, source.institution_type,
                        source.language, 'Synthetic publication for coverage test',
                        'https://www.belspo.be/belspo/organisation/press/test_fr.stm',
                        published_at=datetime(2026, 9, 15, tzinfo=timezone.utc))]

    monkeypatch.setattr(scraper, 'fetch_round4_details', details)
    result = asyncio.run(scraper.scrape_source(
        source, Client(), since=datetime(2026, 9, 1, tzinfo=timezone.utc),
        until=datetime(2026, 10, 1, tzinfo=timezone.utc), include_unmatched=True,
        fetch_details=False, observed_at=datetime(2026, 10, 3, tzinfo=timezone.utc)))
    assert result.status.success
    assert result.status.raw_count == 1
    assert '有界樣本' in result.status.warning
    assert '可能不完整' in result.status.warning
