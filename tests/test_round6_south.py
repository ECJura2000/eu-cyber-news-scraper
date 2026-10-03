"""South round-six coverage, actual local evidence and bounded publication replay."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_feed
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS
from eu_cyber_news_scraper.wikipedia_review import (
    validate_local_wikipedia_review,
    validate_news_url_cleanup,
    validate_user_exclusion,
    validate_wikipedia_review,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
BASELINE = json.loads((FIXTURES / 'ministry_round6_baseline.json').read_text())
REPORT = json.loads((FIXTURES / 'ministry_round6_south.json').read_text())
COUNTRIES = {'ES', 'GR', 'IT', 'MT'}
LANGUAGES = {'ES': 'es', 'GR': 'el', 'IT': 'it', 'MT': 'mt'}
ASSIGNED = {row['canonical_id']: row for row in BASELINE['ministries'] if row['country'] in COUNTRIES}
MINIMUM = date.fromisoformat(BASELINE['observed_on'])


def test_complete_assignment_and_actual_totals():
    assert REPORT['schema_version'] == 1 and REPORT['group'] == 'south'
    assert set(REPORT['countries']) == COUNTRIES
    assert date.fromisoformat(REPORT['observed_on']) >= MINIMUM
    checks = REPORT['checks']
    identifiers = [check['canonical_id'] for check in checks]
    assert len(identifiers) == len(set(identifiers)) == len(ASSIGNED) == 56
    assert set(identifiers) == set(ASSIGNED)
    assert REPORT['assigned_count'] == 56
    assert REPORT['input_country_counts'] == dict(Counter(row['country'] for row in ASSIGNED.values()))
    assert REPORT['wikipedia_search_count'] == sum(len(check['wikipedia']['queries']) for check in checks)
    assert REPORT['official_attempt_count'] == sum(len(check['attempts']) for check in checks)
    assert REPORT['summary']['result_counts'] == dict(Counter(check['result'] for check in checks))
    assert REPORT['summary']['search_count'] == REPORT['wikipedia_search_count']
    assert REPORT['summary']['attempts_total'] == REPORT['official_attempt_count']


@pytest.mark.parametrize('check', REPORT['checks'], ids=lambda check: check['canonical_id'])
def test_every_ministry_has_actual_local_search_and_fresh_official_attempts(check):
    row = ASSIGNED[check['canonical_id']]
    assert check['country'] == row['country']
    assert check['initial_status'] == row['initial_status']
    assert check['initial_news_url'] == row['initial_news_url']
    validate_wikipedia_review(check, MINIMUM)
    validate_local_wikipedia_review(check, MINIMUM)
    validate_news_url_cleanup(check, MINIMUM)
    review = check['wikipedia']
    assert review['local_language'] == LANGUAGES[check['country']]
    assert len(review['search_evidence']) == len(review['queries'])
    assert {item['query'] for item in review['search_evidence']} == set(review['queries'])
    assert all(query.startswith(f'site:{review["local_language"]}.wikipedia.org ') for query in review['queries'])
    for evidence in review['search_evidence']:
        assert re.fullmatch('[a-f0-9]{64}', evidence['response_sha256'])
        assert isinstance(evidence['results'], list)
        assert all(len(result.get('snippet', '')) <= 500 for result in evidence['results'])
    page_urls = {page['url'] for page in review['pages']}
    for page in review['pages']:
        assert urlsplit(page['url']).hostname == f'{review["local_language"]}.wikipedia.org'
        assert page['title'] and page['excerpt'] and len(page['excerpt']) <= 1000
        assert re.fullmatch('[a-f0-9]{64}', page['extracted_sha256'])
    assert all(candidate['wikipedia_url'] in page_urls for candidate in review['website_candidates'])
    assert check['attempts'] and check['next_action']
    for attempt in check['attempts']:
        assert attempt['robots_enforced'] is True and attempt['tls_verified'] is True
        assert attempt.get('http_status') or attempt.get('error')
        observed = datetime.fromisoformat(attempt['observed_at'])
        assert observed.tzinfo is not None
        assert observed.astimezone(ZoneInfo('Asia/Taipei')).date() >= MINIMUM
        assert urlsplit(attempt['url']).scheme == 'https'
        assert len(attempt.get('first_party_content_excerpt', '')) <= 1000
    assert 'removed_news_urls' not in check


@pytest.mark.parametrize('check', REPORT['checks'], ids=lambda check: check['canonical_id'])
def test_excluded_failures_preserve_the_exact_baseline_candidate(check):
    if check['result'] == 'manual_verified':
        assert check['source_ids']
        assert check['inventory_patch']['source_ids'] == check['source_ids']
        assert 'user_exclusion' not in check
        return
    assert check['result'] == 'user_excluded'
    assert check['failure_category'] in {'blocked', 'needs_review', 'parser_pending', 'no_news_endpoint'}
    assert check['failure_reason'].strip()
    assert check['inventory_patch'] == {'news_url': None}
    validate_user_exclusion(check, MINIMUM, authorized=BASELINE['user_exclusion_authorized'],
                            original_url=ASSIGNED[check['canonical_id']]['initial_news_url'])
    assert check['user_exclusion']['candidate_news_url'] == ASSIGNED[check['canonical_id']]['initial_news_url']
    assert check['user_exclusion']['reason'] == check['failure_reason']
    assert 'explicit review' in check['next_action']
    assert not check.get('source_ids')


def test_ministry_feed_exact_replay_and_manual_only_contract():
    source = next(source for source in load_sources() if source.id == 'mt_foreign_affairs')
    module = load_organisation_registry().module_for_source(source.id)
    assert module is not None
    assert not source.schedule_enabled and not source.critical
    assert type(source.detail_pages) is int and source.detail_pages == 0
    assert source.parser_adapter == ''
    assert module.topics == frozenset(OBSERVATION_TOPICS) and len(module.topics) == 15
    assert module.payload['responsibility_by_topic'] == {}
    verification = module.payload['verification']
    fixture = (ROOT / verification['fixture_path']).read_bytes()
    provenance = json.loads((ROOT / verification['provenance_path']).read_text())
    assert len(fixture) == provenance['fixture_bytes'] <= 32768
    assert hashlib.sha256(fixture).hexdigest() == provenance['fixture_sha256']
    assert provenance['fixture_sha256'] != provenance['response_sha256']
    assert provenance['http_status'] == 200
    assert provenance['robots_enforced'] and provenance['tls_verified']
    assert source.feed_urls == ('https://foreign.gov.mt/feed/',)
    assert all(urlsplit(url).hostname == 'foreign.gov.mt' for url in verification['evidence_urls'])
    assert len(set(verification['evidence_urls'])) >= 2
    articles = parse_feed(fixture, source, provenance['final_url'])
    actual = [{'title': article.title, 'url': article.url,
               'published_date_local': article.published_date_local,
               'date_confidence': article.date_confidence, 'date_source': article.date_source,
               'summary': article.summary} for article in articles]
    assert actual == provenance['expected'] and len(articles) == 3
    assert all(article.published_at and article.date_source == 'feed-published'
               and article.date_confidence == 'high' and not article.date_conflict for article in articles)
    assert articles[0].published_date_local == '2026-07-24'
    assert 'Ministry for Foreign and European Affairs' in provenance['publisher_identity']['first_party_content_excerpt']
    status = provenance['live_status']
    assert status['success'] and status['raw_count'] == status['dated_count'] >= 1
    assert status['parse_status'] == 'healthy' and not status['error']
    assert status['invalid_date_count'] == status['unexplained_future_date_count'] == 0
    assert source.freshness_days == 90
    check = next(check for check in REPORT['checks'] if check['canonical_id'] == source.id)
    assert verification['coverage'] == provenance['coverage'] == check['verification']['coverage']
    coverage = verification['coverage']
    assert coverage['latest_published_at'] == status['newest_published_at'] == '2026-07-24T11:32:23+00:00'
    assert coverage['manual_freshness_days'] == source.freshness_days
    assert coverage['recent_weekly_coverage_verified'] is False
    assert coverage['formal_release_acceptance_verified'] is False
    assert coverage['formal_gates_changed'] is False
    assert verification['coverage_warning'] == provenance['coverage_warning'] == check['verification']['coverage_warning']
    assert 'not recent weekly coverage' in verification['coverage_warning']


def test_other_publishers_and_event_or_deadline_dates_do_not_pass():
    checks = {check['canonical_id']: check for check in REPORT['checks']}
    youth = checks['mt_youth']
    assert youth['result'] == 'user_excluded' and youth['failure_category'] == 'needs_review'
    assert 'National Youth Agency' in youth['failure_reason']
    reforms = checks['it_institutional_reforms']
    assert reforms['result'] == 'user_excluded' and reforms['failure_category'] == 'parser_pending'
    assert 'og:updated_time' in reforms['date_evidence']['specific_evidence']
    assert 'event date' in reforms['failure_reason'] and 'deadline' in reforms['failure_reason']
    labour = checks['es_labour']
    assert labour['result'] == 'user_excluded' and labour['failure_category'] == 'blocked'
    assert 'inspectorate' in labour['failure_reason']
    assert {check['canonical_id'] for check in REPORT['checks'] if check['result'] == 'manual_verified'} == {'mt_foreign_affairs'}
