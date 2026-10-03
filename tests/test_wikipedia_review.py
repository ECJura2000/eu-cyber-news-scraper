"""Discovery never substitutes for first-party publication or deletion proof."""
import copy
from datetime import date

import pytest

from eu_cyber_news_scraper.wikipedia_review import validate_news_url_cleanup, validate_wikipedia_review

DAY = date(2026, 10, 3)
WIKI = 'https://en.wikipedia.org/wiki/Ministry_of_Test_(Country)'
OFFICIAL = 'https://ministry.example.eu/news'


def check():
    return {'wikipedia': {'status': 'matched', 'queries': ['Ministry of Test Country Wikipedia'],
                         'pages': [{'url': WIKI, 'title': 'Ministry of Test',
                                    'observed_at': '2026-10-03T01:00:00+00:00',
                                    'extracted_sha256': 'a'*64}],
                         'website_candidates': [{'url': OFFICIAL, 'wikipedia_url': WIKI}]}}


def test_retrieved_wikipedia_only_records_a_candidate():
    value = check()
    validate_wikipedia_review(value, DAY)
    assert 'inventory_patch' not in value
    value['wikipedia']['website_candidates'][0]['url'] = 'http://ministry.example.eu/'
    validate_wikipedia_review(value, DAY)
    assert value['wikipedia']['website_candidates'][0]['url'].startswith('http:')


@pytest.mark.parametrize('status', ['blocked', 'ambiguous', 'not_found'])
def test_unsuccessful_wikipedia_lookup_is_not_institution_absence(status):
    value = {'wikipedia': {'status': status, 'queries': ['Actual lookup'], 'pages': [], 'website_candidates': []}}
    validate_wikipedia_review(value, DAY)
    validate_news_url_cleanup(value, DAY)
    assert 'removed_news_urls' not in value


@pytest.mark.parametrize('change', ['review', 'status', 'queries', 'empty_query', 'pages', 'host', 'path',
                                  'timestamp', 'stale', 'title', 'digest', 'no_page', 'candidates', 'scheme', 'attribution'])
def test_invalid_wikipedia_evidence_cannot_be_called_matched(change):
    value = check()
    review = value['wikipedia']
    page = review['pages'][0]
    if change == 'review':
        value['wikipedia'] = []
    elif change == 'status':
        review['status'] = 'verified_official'
    elif change == 'queries':
        review['queries'] = []
    elif change == 'empty_query':
        review['queries'] = [None]
    elif change == 'pages':
        review['pages'] = {}
    elif change == 'host':
        page['url'] = 'https://en.wikipedia.org.example.com/wiki/Test'
    elif change == 'path':
        page['url'] = 'https://en.wikipedia.org/'
    elif change == 'timestamp':
        page['observed_at'] = '2026-10-03T01:00:00'
    elif change == 'stale':
        page['observed_at'] = '2026-10-02T15:00:00+00:00'
    elif change == 'title':
        page['title'] = ' '
    elif change == 'digest':
        page['extracted_sha256'] = 'snippet'
    elif change == 'no_page':
        review['pages'] = []
    elif change == 'candidates':
        review['website_candidates'] = {}
    elif change == 'scheme':
        review['website_candidates'][0]['url'] = 'javascript:alert(1)'
    elif change == 'attribution':
        review['website_candidates'][0]['wikipedia_url'] = 'https://en.wikipedia.org/wiki/Other'
    with pytest.raises(ValueError):
        validate_wikipedia_review(value, DAY)


def removal(status=404):
    return {'inventory_patch': {'news_url': None}, 'removed_news_urls': [
        {'url': OFFICIAL, 'observed_at': '2026-10-03T01:00:00+00:00',
         'http_status': status, 'reason': 'Official response confirms obsolete route.'}]}


@pytest.mark.parametrize('status', [404, 410])
def test_confirmed_dead_news_path_can_be_removed_but_evidence_retained(status):
    value = removal(status)
    before = copy.deepcopy(value)
    validate_news_url_cleanup(value, DAY)
    assert value == before and value['removed_news_urls'][0]['url'] == OFFICIAL


@pytest.mark.parametrize('status', [None, 401, 403, 429, 500, 503, 200])
def test_access_failure_and_unexplained_200_cannot_delete_a_source(status):
    with pytest.raises(ValueError, match='cannot justify'):
        validate_news_url_cleanup(removal(status), DAY)


def test_specific_first_party_no_news_content_can_clear_candidate():
    value = removal(200)
    value['removed_news_urls'][0].update(specific_evidence='Exact response is an institution contact directory, not news.',
                                        verification_url=OFFICIAL)
    validate_news_url_cleanup(value, DAY)


@pytest.mark.parametrize('change', ['reason', 'patch', 'same_url', 'timezone', 'old'])
def test_cleanup_requires_time_reason_and_effective_replacement(change):
    value = removal()
    if change == 'reason':
        value['removed_news_urls'][0]['reason'] = ''
    elif change == 'patch':
        value['inventory_patch'] = {}
    elif change == 'same_url':
        value['inventory_patch']['news_url'] = OFFICIAL
    elif change == 'timezone':
        value['removed_news_urls'][0]['observed_at'] = '2026-10-03T01:00:00'
    else:
        value['removed_news_urls'][0]['observed_at'] = '2026-10-01T01:00:00+00:00'
    with pytest.raises(ValueError):
        validate_news_url_cleanup(value, DAY)
