"""Complete east recheck: local encyclopedia evidence and explicit exclusions."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
from bs4 import BeautifulSoup

from eu_cyber_news_scraper import source_audit
from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.scraper import scrape_source
from eu_cyber_news_scraper.source_audit import AuditHttpClient
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS
from eu_cyber_news_scraper.wikipedia_review import (
    validate_local_wikipedia_review,
    validate_news_url_cleanup,
    validate_user_exclusion,
    validate_wikipedia_review,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures'
BASELINE = json.loads((FIX / 'ministry_round6_baseline.json').read_text())
REPORT = json.loads((FIX / 'ministry_round6_east.json').read_text())
COUNTRIES = {'BG', 'HR', 'HU', 'LT', 'RO', 'SK', 'CY'}
ASSIGNED = {r['canonical_id']: r for r in BASELINE['ministries'] if r['country'] in COUNTRIES}
MINIMUM = date.fromisoformat(BASELINE['observed_on'])
PROOF = json.loads((FIX / 'ministry_round6_hu_defence.provenance.json').read_text())


def verified_source():
    values = PROOF['source_config']
    return Source(**{
        k: tuple(v) if isinstance(Source.__dataclass_fields__[k].default, tuple) else v
        for k, v in values.items()
    })


def publication_signature(articles):
    return [
        {k: getattr(article, k) for k in ('title', 'url', 'published_date_local',
                                        'published_at_raw', 'date_confidence')}
        for article in articles
    ]


def expected_signature():
    return [
        {k: value for k, value in row.items() if k != 'published_at'}
        for row in PROOF['expected']
    ]


def test_complete_assignment_and_observation_totals():
    assert REPORT['schema_version'] == 1 and REPORT['group'] == 'east'
    assert set(REPORT['countries']) == COUNTRIES
    assert date.fromisoformat(REPORT['observed_on']) >= MINIMUM
    checks = REPORT['checks']
    assert len(checks) == len({c['canonical_id'] for c in checks}) == len(ASSIGNED) == 62
    assert {c['canonical_id'] for c in checks} == set(ASSIGNED)
    assert REPORT['assigned_count'] == 62
    assert REPORT['input_country_counts'] == dict(Counter(r['country'] for r in ASSIGNED.values()))
    assert REPORT['summary']['result_counts'] == dict(Counter(c['result'] for c in checks))
    assert REPORT['summary']['search_count'] == sum(len(c['wikipedia']['search_evidence']) for c in checks)
    assert REPORT['summary']['attempts_total'] == sum(len(c['attempts']) for c in checks)


@pytest.mark.parametrize('check', REPORT['checks'], ids=lambda c: c['canonical_id'])
def test_actual_local_language_evidence_and_safe_official_attempts(check):
    row = ASSIGNED[check['canonical_id']]
    assert check['country'] == row['country']
    assert check['baseline_status'] == row['initial_status']
    assert check['baseline_news_url'] == row['initial_news_url']
    validate_wikipedia_review(check, MINIMUM)
    validate_local_wikipedia_review(check, MINIMUM)
    validate_news_url_cleanup(check, MINIMUM)
    review = check['wikipedia']
    assert review['local_language'] == row['language']
    assert len(review['queries']) == len(review['search_evidence'])
    assert Counter(review['queries']) == Counter(e['query'] for e in review['search_evidence'])
    assert all(e.get('observation') or e.get('error') for e in review['search_evidence'])
    page_urls = {p['url'] for p in review['pages']}
    for page in review['pages']:
        assert urlsplit(page['url']).hostname == row['language'] + '.wikipedia.org'
        assert re.fullmatch(r'[0-9a-f]{64}', page['extracted_sha256'])
        assert 0 < len(page['excerpt']) <= 1000
        assert page['title'] and 'exact_retrieved_content' not in page
    for candidate in review['website_candidates']:
        assert candidate['wikipedia_url'] in page_urls
        assert candidate['relationship_excerpt']
    assert check['attempts'] and check['automatic_schedule_changes'] is False
    for attempt in check['attempts']:
        assert urlsplit(attempt['url']).scheme == 'https'
        dt = datetime.fromisoformat(attempt['observed_at'])
        assert dt.tzinfo and dt.astimezone(ZoneInfo('Asia/Taipei')).date() >= MINIMUM
        assert attempt.get('http_status') or attempt.get('error')
        assert attempt['robots_enforced'] is True and attempt['tls_verified'] is True
    assert check['removed_news_urls'] == []


@pytest.mark.parametrize('check', REPORT['checks'], ids=lambda c: c['canonical_id'])
def test_disposition_preserves_user_policy_and_manual_source_contract(check):
    if check['result'] == 'user_excluded':
        validate_user_exclusion(check, MINIMUM, authorized=BASELINE['user_exclusion_authorized'],
                                original_url=ASSIGNED[check['canonical_id']]['initial_news_url'])
        assert check['inventory_patch'] == {'news_url': None}
        assert check['failure_category'] in {'blocked', 'needs_review', 'parser_pending', 'no_news_endpoint'}
        assert check['failure_reason'].strip() and check['user_exclusion']['reason'].strip()
        assert 'explicit review' in check['next_action']
        assert not check.get('source_ids')
    else:
        assert check['result'] == 'manual_verified'
        assert check['source_ids']
        registry = load_organisation_registry()
        for source_id in check['source_ids']:
            module = registry.module_for_source(source_id)
            assert module is not None
            payload = module.payload
            assert payload['filter']['topics'] == list(OBSERVATION_TOPICS)
            assert len(OBSERVATION_TOPICS) == 15
            assert payload['responsibility_by_topic'] == {}
            assert len(payload['verification']['evidence_urls']) >= 2
            for source in payload['sources']:
                assert source['critical'] is False and source['schedule_enabled'] is False
                assert type(source['detail_pages']) is int and source['detail_pages'] == 0


def test_bounded_fixture_replays_actual_live_ministry_publication():
    content = (ROOT / PROOF['fixture_path']).read_bytes()
    assert len(content) == PROOF['fixture_bytes'] <= 32768
    assert hashlib.sha256(content).hexdigest() == PROOF['fixture_sha256']
    soup = BeautifulSoup(content, 'lxml')
    assert not soup.select('script, style, form, input, textarea, button, img, svg')
    assert len(soup.select('.card')) == 2
    source = verified_source()
    articles = parse_listing(content.decode(), source, PROOF['url'])
    assert publication_signature(articles) == expected_signature()
    assert len(articles) == 1 and articles[0].date_confidence == 'high'
    assert articles[0].published_date_local == '2026-10-03'
    assert articles[0].published_at.isoformat() == '2026-10-03T07:00:00+00:00'
    assert PROOF['original_fixture_parity']['title_url_dates_equal'] is True
    assert PROOF['live_status']['success'] is True
    assert PROOF['live_status']['raw_count'] == PROOF['live_status']['dated_count'] == 1
    assert PROOF['live_status']['undated_ratio'] == 0
    assert PROOF['live_status']['invalid_date_count'] == 0
    assert PROOF['publisher_evidence']['excerpt'].startswith(
        'A domainnév tulajdonosa: Honvédelmi Minisztérium'
    )
    assert PROOF['listing_evidence']['main_dated_card_count'] == 10
    assert PROOF['listing_evidence']['heading'] == 'tartalékos rendszer'
    assert any('?page=180' in url for url in PROOF['listing_evidence']['pagination_urls'])
    assert PROOF['coverage_limitations'].startswith('Bounded coverage: only page 1')
    assert source.card_selectors[0].startswith('.articleList #list .card:')
    module = load_organisation_registry().module_for_source('hu_defence')
    assert module.payload['sources'] == [PROOF['source_config']]
    assert module.payload['verification']['last_smoke'] == PROOF['live_status']
    assert PROOF['http_status'] == 200 and PROOF['robots_enforced'] and PROOF['tls_verified']


def test_real_dated_nonministry_card_is_excluded():
    soup = BeautifulSoup((ROOT / PROOF['fixture_path']).read_bytes(), 'lxml')
    negative = next(card for card in soup.select('.card')
                    if PROOF['negative_card_title'] in card.get_text())
    assert negative.select_one('.card-date').get_text(strip=True)
    assert 'Honvédelmi Minisztérium' not in negative.get_text()
    assert parse_listing(str(negative), verified_source(), PROOF['url']) == []


def test_ministry_named_related_widget_outside_category_list_is_excluded():
    soup = BeautifulSoup((ROOT / PROOF['fixture_path']).read_bytes(), 'lxml')
    widget = BeautifulSoup(str(soup.select_one('.card')), 'lxml').select_one('.card')
    widget.select_one('a')['href'] = '/hirek/unrelated-sidebar-widget.html'
    soup.body.append(widget)
    assert publication_signature(parse_listing(str(soup), verified_source(), PROOF['url'])) == expected_signature()


def test_fixture_through_actual_production_dispatch_and_robots(monkeypatch):
    async def mock_dns(host):
        assert host == 'honvedelem.hu'

    monkeypatch.setattr(source_audit, '_validate_public_dns', mock_dns)

    async def run():
        content = (ROOT / PROOF['fixture_path']).read_bytes()
        requested = []

        def respond(request):
            requested.append(request.url.path)
            if request.url.path == '/robots.txt':
                return httpx.Response(200, text='User-agent: *\nAllow: /\n')
            assert str(request.url) == PROOF['url']
            return httpx.Response(200, content=content,
                                  headers={'content-type': 'text/html; charset=utf-8'})

        source = verified_source()
        async with AuditHttpClient(timeout=15, transport=httpx.MockTransport(respond)) as client:
            client.source = source
            result = await scrape_source(
                source, client, since=datetime(2025, 1, 1, tzinfo=timezone.utc),
                until=datetime(2026, 10, 4, tzinfo=timezone.utc), include_unmatched=True,
                include_undated=True, fetch_details=False, source_budget_seconds=30,
            )
        assert '/robots.txt' in requested
        assert result.status.success and result.status.raw_count == result.status.dated_count == 1
        assert result.status.undated_ratio == 0
        assert publication_signature(result.articles) == expected_signature()

    asyncio.run(run())
