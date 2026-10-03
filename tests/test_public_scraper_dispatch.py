"""The runtime must dispatch public ministry queries and preserve incompleteness."""
import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from eu_cyber_news_scraper import scraper
from eu_cyber_news_scraper.http import HttpClient, HttpStats
from eu_cyber_news_scraper.models import Source


class ListingClient:
    async def get(self, url, *, stats=None):
        return httpx.Response(200, text='<main>Official listing bootstrap</main>',
                              request=httpx.Request('GET', url))


def source():
    return Source(id='dk_climate', country='DK', name='Ministry', name_zh='氣候部',
                  institution_type='ministry', language='da', homepage='https://kefm.dk/',
                  listing_url='https://kefm.dk/aktuelt/nyheder', allow_domains=('kefm.dk',),
                  parser_adapter='north_gobasic', timezone='Europe/Copenhagen', detail_pages=0)


@pytest.mark.parametrize('truncated', [False, True])
def test_north_public_dispatch_keeps_pagination_warning(monkeypatch, truncated):
    calls = []

    async def fetch(html, configured, client, stats):
        calls.append(configured.id)
        return {'truncated': truncated, 'responses': [{'success': True, 'value': {'page': '''
            <div class="item" data-url="/aktuelt/nyheder/2026/news">
            <div class="heading"><a href="/aktuelt/nyheder/2026/news">NIS2 offentlig nyhed</a></div>
            <span class="date">23-09-2026</span></div>'''}}]}

    monkeypatch.setattr(scraper, 'fetch_north_listing', fetch)
    result = asyncio.run(scraper.scrape_source(source(), ListingClient(),
                         since=datetime(2026, 9, 1, tzinfo=timezone.utc),
                         until=datetime(2026, 10, 3, tzinfo=timezone.utc),
                         fetch_details=False, include_unmatched=True))
    assert calls == ['dk_climate']
    assert result.status.success and result.status.raw_count == result.status.dated_count == 1
    assert ('不完整' in result.status.warning) is truncated


def test_north_public_query_failure_is_not_a_successful_html_shell(monkeypatch):
    async def fetch(*args):
        raise ValueError('Published query changed; review required')

    monkeypatch.setattr(scraper, 'fetch_north_listing', fetch)
    result = asyncio.run(scraper.scrape_source(source(), ListingClient(),
                         since=datetime(2026, 9, 1, tzinfo=timezone.utc),
                         until=datetime(2026, 10, 3, tzinfo=timezone.utc), fetch_details=False))
    assert not result.status.success and result.status.raw_count == 0
    assert 'Published query changed' in result.status.error


def test_cross_origin_redirect_is_rejected_before_external_request():
    requests = []

    async def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'Location': 'https://unrelated.example/return'}, request=request)

    async def run():
        async with HttpClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.InvalidURL, match='outside source scope'):
                await scraper._get_source_response(client, source().listing_url, source(), HttpStats())

    asyncio.run(run())
    assert requests == [source().listing_url]


def test_robots_redirect_cannot_escape_the_source_guard():
    requests = []

    async def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'Location': 'https://unrelated.example/robots.txt'}, request=request)

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.InvalidURL, match='outside source scope'):
                await scraper._get_source_response(client, source().listing_url, source(), HttpStats())

    asyncio.run(run())
    assert requests == ['https://kefm.dk/robots.txt']
