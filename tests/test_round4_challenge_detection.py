import httpx
import pytest

from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.scraper import ChallengePageError, _validate_source_response
from eu_cyber_news_scraper.source_audit import _content_error

SOURCE = Source(id='de_test', country='DE', name='Ministry', name_zh='測試部',
                institution_type='ministry', language='de', homepage='https://official.example/',
                listing_url='https://official.example/news')


@pytest.mark.parametrize('title,blocked', [('Radware Page', True), (' RADWARE PAGE ', True),
                                         ('Radware page security research results', False),
                                         ('Ministry news: Radware protection', False)])
def test_radware_loader_is_not_successful_ministry_content(title, blocked):
    response = httpx.Response(200, headers={'Content-Type': 'text/html'},
                              text=f'<html><title>{title}</title><body>Public page</body></html>',
                              request=httpx.Request('GET', SOURCE.listing_url))
    assert (_content_error(response, 'listing', SOURCE) == 'challenge_page') is blocked
    if blocked:
        with pytest.raises(ChallengePageError):
            _validate_source_response(response, SOURCE, SOURCE.listing_url)
    else:
        _validate_source_response(response, SOURCE, SOURCE.listing_url)
