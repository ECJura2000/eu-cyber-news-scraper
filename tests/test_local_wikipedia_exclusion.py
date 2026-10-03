"""Local discovery and user removal cannot manufacture a searchable source."""
import asyncio
import copy
import json
from datetime import date

import pytest

from eu_cyber_news_scraper.ministry_inventory import audit_inventory_urls, inventory_report, validate_country
from eu_cyber_news_scraper.ministry_rechecks import load_rechecks
from eu_cyber_news_scraper.organisation_registry import OrganisationRegistry
from eu_cyber_news_scraper.wikipedia_review import (
    USER_EXCLUSION_POLICY,
    validate_local_wikipedia_review,
    validate_user_exclusion,
)

DAY = date(2026, 10, 3)
STAMP = '2026-10-03T02:00:00+00:00'
URL = 'https://department.example.eu/news'
QUERY = 'site:de.wikipedia.org Bundesministerium Test'


def item():
    return {
        'canonical_id': 'de_test', 'country': 'DE', 'result': 'user_excluded',
        'next_action': 'Restore only after explicit review.',
        'failure_category': 'blocked', 'failure_reason': 'Robots access denied; site not declared obsolete.',
        'attempts': [{'url': URL, 'observed_at': STAMP, 'error': 'robots_denied'}],
        'wikipedia': {'status': 'matched', 'local_language': 'de', 'queries': [QUERY],
                      'search_evidence': [{'query': QUERY, 'observed_at': STAMP, 'response_sha256': 'b'*64}],
                      'pages': [{'url': 'https://de.wikipedia.org/wiki/Testministerium',
                                 'title': 'Testministerium', 'observed_at': STAMP, 'extracted_sha256': 'a'*64}],
                      'website_candidates': []},
        'user_exclusion': {'policy': USER_EXCLUSION_POLICY, 'observed_at': STAMP,
                           'reason': 'User requested removal after unsuccessful local recheck.',
                           'candidate_news_url': URL},
        'inventory_patch': {'news_url': None},
    }


def test_local_article_and_search_observation_are_both_required():
    validate_local_wikipedia_review(item(), DAY)


@pytest.mark.parametrize('change', ['language', 'english_query', 'english_page', 'search_missing',
                                  'search_other_query', 'search_digest', 'search_naive'])
def test_english_or_unobserved_search_cannot_satisfy_local_request(change):
    check = item()
    review = check['wikipedia']
    if change == 'language':
        review['local_language'] = 'en'
    elif change == 'english_query':
        review['queries'] = ['site:en.wikipedia.org Ministry of Test']
    elif change == 'english_page':
        review['pages'][0]['url'] = 'https://en.wikipedia.org/wiki/Test'
    elif change == 'search_missing':
        del review['search_evidence']
    elif change == 'search_other_query':
        review['search_evidence'][0]['query'] = 'Different query'
    elif change == 'search_digest':
        review['search_evidence'][0]['response_sha256'] = 'snippet'
    else:
        review['search_evidence'][0]['observed_at'] = '2026-10-03T02:00:00'
    with pytest.raises(ValueError):
        validate_local_wikipedia_review(check, DAY)


def test_local_search_failure_is_recorded_not_invented_as_absence():
    check = item()
    review = check['wikipedia']
    review.update(status='blocked', pages=[])
    review['search_evidence'][0].update(error='service timeout', response_sha256=None)
    validate_local_wikipedia_review(check, DAY)


@pytest.mark.parametrize('change', ['authorization', 'record', 'policy', 'reason', 'null_reason', 'url', 'patch', 'source'])
def test_exclusion_cannot_silently_remove_registered_or_wrong_url(change):
    check = item()
    authorized = True
    if change == 'authorization':
        authorized = False
    elif change == 'record':
        del check['user_exclusion']
    elif change == 'policy':
        check['user_exclusion']['policy'] = 'website_obsolete'
    elif change == 'reason':
        check['user_exclusion']['reason'] = ' '
    elif change == 'null_reason':
        check['user_exclusion']['reason'] = None
    elif change == 'url':
        check['user_exclusion']['candidate_news_url'] = None
    elif change == 'patch':
        check['inventory_patch']['news_url'] = URL
    else:
        check['source_ids'] = ['registered']
    with pytest.raises(ValueError):
        validate_user_exclusion(check, DAY, authorized=authorized, original_url=URL)


def test_exclusion_can_cover_missing_candidate_and_is_nonmutating():
    check = item()
    check['user_exclusion']['candidate_news_url'] = None
    before = copy.deepcopy(check)
    validate_user_exclusion(check, DAY, authorized=True, original_url=None)
    assert check == before


def country():
    return {'schema_version': 1, 'country': 'DE', 'reviewed_on': DAY.isoformat(),
            'official_roster_urls': ['https://department.example.eu/roster'],
            'roster_complete': True, 'limitations': [], 'ministries': [{
                'canonical_id': 'de_test', 'name_zh': '測試部', 'name_local': 'Testministerium',
                'name_en': 'Test Ministry', 'kind': 'ministry', 'language': 'de',
                'homepage': 'https://department.example.eu/', 'news_url': None, 'source_ids': [],
                'status': 'user_excluded', 'reason': 'User excluded; actual site access blocked.',
                'evidence_urls': ['https://department.example.eu/roster'],
                'user_exclusion': item()['user_exclusion'],
            }]}


def test_inventory_exclusion_is_not_searchable_or_pending():
    value = country()
    validate_country(value, OrganisationRegistry((), (), 'test'), today=DAY)
    report = inventory_report([value])
    assert report['registered_ministries'] == report['pending_ministries'] == 0
    assert report['unresolved_ministries'] == report['user_excluded_ministries'] == 1
    assert not report['searchable_inventory_complete']


def test_complete_eu27_roster_with_exclusions_is_not_complete_search_coverage():
    from eu_cyber_news_scraper.source_catalog import EU27
    records = []
    for code in sorted(EU27):
        value = country()
        value['country'] = code
        value['ministries'][0]['canonical_id'] = code.lower() + '_test'
        records.append(value)
    report = inventory_report(records)
    assert report['status'] == 'complete' and report['ministry_count'] == 27
    assert report['pending_ministries'] == 0 and report['user_excluded_ministries'] == 27
    assert not report['searchable_inventory_complete']


@pytest.mark.parametrize('change', ['url', 'sources', 'metadata', 'status'])
def test_inventory_rejects_exclusion_with_active_url_or_inconsistent_metadata(change):
    value = country()
    row = value['ministries'][0]
    if change == 'url':
        row['news_url'] = URL
    elif change == 'sources':
        row['source_ids'] = ['registered']
    elif change == 'metadata':
        del row['user_exclusion']
    else:
        row['status'] = 'blocked'
    with pytest.raises(ValueError):
        validate_country(value, OrganisationRegistry((), (), 'test'), today=DAY)


def test_url_audit_does_not_reopen_user_excluded_homepage(tmp_path):
    report = asyncio.run(audit_inventory_urls([country()], tmp_path))
    assert report['endpoints'] == []
    assert report['user_excluded_ministries'] == ['de_test']
    assert report['status'] == 'attention'


def write_round(directory, number=6):
    baseline = {'observed_on': DAY.isoformat(), 'remaining_count': 1,
                'discovery_method': 'wikipedia', 'local_language_required': True,
                'user_exclusion_authorized': True,
                'ministries': [{'canonical_id': 'de_test', 'country': 'DE', 'initial_news_url': URL}]}
    report = {'schema_version': 1, 'group': 'test', 'countries': ['DE'],
              'observed_on': DAY.isoformat(), 'checks': [item()]}
    (directory / f'ministry_round{number}_baseline.json').write_text(json.dumps(baseline))
    (directory / f'ministry_round{number}_test.json').write_text(json.dumps(report))
    return baseline, report


def test_authorized_round_preserves_failure_and_clears_candidate(tmp_path):
    write_round(tmp_path)
    check = load_rechecks(tmp_path)[0]['checks']['de_test']
    assert check['result'] == 'user_excluded' and check['failure_category'] == 'blocked'
    assert 'removed_news_urls' not in check


@pytest.mark.parametrize('change', ['authorization', 'failure', 'reason', 'wrong_url', 'old_round', 'not_local'])
def test_recheck_refuses_unauthorized_or_unexplained_exclusion(tmp_path, change):
    baseline, report = write_round(tmp_path)
    if change == 'authorization':
        baseline['user_exclusion_authorized'] = False
    elif change == 'failure':
        report['checks'][0]['failure_category'] = 'obsolete'
    elif change == 'reason':
        report['checks'][0]['failure_reason'] = ''
    elif change == 'wrong_url':
        report['checks'][0]['user_exclusion']['candidate_news_url'] = None
    elif change == 'not_local':
        baseline['local_language_required'] = False
    else:
        del baseline['discovery_method']
    (tmp_path / 'ministry_round6_baseline.json').write_text(json.dumps(baseline))
    (tmp_path / 'ministry_round6_test.json').write_text(json.dumps(report))
    with pytest.raises(ValueError):
        load_rechecks(tmp_path)


def test_user_excluded_candidates_do_not_silently_reopen_next_round(tmp_path):
    write_round(tmp_path, 6)
    write_round(tmp_path, 7)
    with pytest.raises(ValueError, match='reopens registered'):
        load_rechecks(tmp_path)
