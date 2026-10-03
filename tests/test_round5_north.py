"""Round-five Wikipedia coverage, literal finance fixture and production replay."""
import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from eu_cyber_news_scraper.models import Source
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.scraper import scrape_source
from eu_cyber_news_scraper.wikipedia_review import validate_news_url_cleanup, validate_wikipedia_review

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures'
COUNTRIES = {'AT', 'BE', 'CZ', 'DE', 'DK', 'FI', 'FR'}


def report():
    return json.loads((FIX / 'ministry_round5_north.json').read_text())


def provenance():
    return json.loads((FIX / 'ministry_round5_de_bmf.provenance.json').read_text())


def fields(article):
    return {key: getattr(article, key) for key in ('title', 'url', 'published_date_local', 'date_confidence')}


def test_exact_assigned_coverage_and_actual_wikipedia_evidence():
    data = report()
    baseline = json.loads((FIX / 'ministry_round5_baseline.json').read_text())
    assigned = {r['canonical_id'] for r in baseline['ministries'] if r['country'] in COUNTRIES}
    assert assigned == {r['canonical_id'] for r in data['checks']}
    assert len(data['checks']) == len(assigned) == data['checked_count'] == 39
    assert data['country_counts'] == {'AT': 2, 'BE': 3, 'CZ': 2, 'DE': 4, 'DK': 2, 'FI': 11, 'FR': 15}
    for check in data['checks']:
        validate_wikipedia_review(check, date(2026, 10, 3))
        validate_news_url_cleanup(check, date(2026, 10, 3))
        assert check['next_action'] and check['attempts']
        assert all('site:wikipedia.org' in query for query in check['wikipedia']['queries'])
        for page in check['wikipedia']['pages']:
            assert page['title'] and page['excerpt'] and len(page['excerpt']) <= 1000
            assert len(page['official_relationship_excerpt']) <= 1000
        for attempt in check['attempts']:
            assert attempt['url'].startswith('https://')
            assert datetime.fromisoformat(attempt['observed_at']).tzinfo is not None
            assert attempt.get('http_status') or attempt.get('error')


def test_only_observed_404_candidate_is_removed():
    checks = report()['checks']
    cleaned = [c for c in checks if c.get('removed_news_urls')]
    assert [c['canonical_id'] for c in cleaned] == ['de_bmf']
    bmf = cleaned[0]
    assert bmf['removed_news_urls'][0]['http_status'] == 404
    assert '/Web/DE/Home/Web/DE/' in bmf['removed_news_urls'][0]['url']
    assert bmf['inventory_patch']['news_url'] == provenance()['url']
    bmv = next(c for c in checks if c['canonical_id'] == 'de_bmv')
    assert bmv['result'] == 'blocked' and 'inventory_patch' not in bmv


def test_bounded_literal_fixture_matches_exact_live_publications():
    p = provenance()
    raw = (ROOT / p['fixture_path']).read_bytes()
    assert len(raw) <= 32768
    assert hashlib.sha256(raw).hexdigest() == p['fixture_sha256']
    assert p['response_sha256'] != p['fixture_sha256'] and p['response_bytes'] > len(raw)
    s = Source(**p['source_config'])
    articles = parse_listing(raw.decode(), s, p['url'])
    assert [fields(a) for a in articles] == p['expected']
    assert all(a.published_at and a.date_confidence == 'high' and not a.date_conflict for a in articles)
    assert all('/Content/DE/Pressemitteilungen/' in a.url for a in articles)
    assert p['live_status']['success'] and p['live_status']['raw_count'] == p['live_status']['dated_count'] == 10
    assert p['live_status']['invalid_date_count'] == p['live_status']['unexplained_future_date_count'] == 0
    assert p['live_status']['duration_seconds'] < 60 and not p['live_status']['budget_exhausted']


def test_replay_actual_production_dispatch_without_overlay():
    p = provenance()
    s = Source(**p['source_config'])
    content = (ROOT / p['fixture_path']).read_bytes()

    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /\n')
        assert str(request.url) == p['url']
        return httpx.Response(200, content=content, headers={'content-type': 'text/html; charset=utf-8'})

    async def run():
        # AuditHttpClient also checks real public DNS; deterministic fixture
        # replay uses HttpClient with the same robots/TLS flags and transport.
        from eu_cyber_news_scraper.http import HttpClient

        async with HttpClient(timeout=15, obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            result = await scrape_source(s, client, since=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                         until=datetime.fromisoformat(p['observed_at']), include_unmatched=True,
                                         fetch_details=False, source_budget_seconds=60,
                                         observed_at=datetime.fromisoformat(p['observed_at']))
        assert result.status.success and result.status.raw_count == result.status.dated_count == 5
        assert [fields(a) for a in result.articles] == p['expected']

    asyncio.run(run())


def test_ministry_specific_manual_registry_contract():
    registry = load_organisation_registry(builtin_dir=ROOT / 'organisation_registry',
                                          external_dir=FIX / 'no-external-overrides')
    assert not registry.errors
    module = registry.module_for_source('de_bmf')
    assert module is not None and module.canonical_id == 'de_bmf'
    source = module.payload['sources'][0]
    assert not source['schedule_enabled'] and not source['critical']
    assert type(source['detail_pages']) is int and source['detail_pages'] == 0
    assert len(module.payload['filter']['topics']) == 15 and not module.payload['responsibility_by_topic']
    assert len(module.payload['verification']['evidence_urls']) >= 2
    assert source['parser_adapter'] == ''
