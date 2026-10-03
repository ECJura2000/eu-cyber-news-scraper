"""Verify south coverage, Wikipedia attribution and exact official news replay."""
import hashlib
import json
from datetime import date
from pathlib import Path

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.topics import OBSERVATION_TOPICS
from eu_cyber_news_scraper.wikipedia_review import validate_news_url_cleanup, validate_wikipedia_review

ROOT = Path(__file__).resolve().parents[1]


def test_south_covers_every_assigned_baseline_ministry_exactly_once():
    report = json.loads((ROOT / 'tests/fixtures/ministry_round5_south.json').read_text())
    baseline = json.loads((ROOT / 'tests/fixtures/ministry_round5_baseline.json').read_text())
    assigned = {row['canonical_id'] for row in baseline['ministries'] if row['country'] in {'ES', 'GR', 'IT', 'MT'}}
    ids = [check['canonical_id'] for check in report['checks']]
    assert len(ids) == len(set(ids)) == 57
    assert set(ids) == assigned
    assert report['wikipedia_search_count'] == 61
    for check in report['checks']:
        validate_wikipedia_review(check, date(2026, 10, 3))
        validate_news_url_cleanup(check, date(2026, 10, 3))
        evidence = json.loads((ROOT / check['wikipedia']['evidence_path']).read_text())
        assert evidence == check['wikipedia']
        assert all(len(page['excerpt']) <= 1000 for page in evidence['pages'])
        assert check['attempts'] and check['next_action']
        assert all(attempt.get('http_status') or attempt.get('error') for attempt in check['attempts'])


def test_industry_generic_source_exact_replay_and_manual_only_contract():
    source = next(source for source in load_sources() if source.id == 'es_industry_tourism')
    registry = load_organisation_registry()
    module = registry.module_for_source(source.id)
    assert module is not None
    assert not source.schedule_enabled and not source.critical
    assert source.detail_pages == 0 and type(source.detail_pages) is int
    assert not source.parser_adapter
    assert module.topics == frozenset(OBSERVATION_TOPICS)
    assert module.payload['responsibility_by_topic'] == {}
    verification = module.payload['verification']
    fixture = (ROOT / verification['fixture_path']).read_bytes()
    provenance = json.loads((ROOT / verification['provenance_path']).read_text())
    assert len(fixture) <= 32768
    assert hashlib.sha256(fixture).hexdigest() == provenance['fixture_sha256']
    assert provenance['response_sha256'] != provenance['fixture_sha256']
    assert provenance['robots_enforced'] and provenance['tls_verified']
    assert provenance['http_status'] == 200
    articles = parse_listing(fixture.decode(), source, provenance['final_url'])
    actual = [{'title':article.title, 'url':article.url,
               'published_date_local':article.published_date_local,
               'date_confidence':article.date_confidence} for article in articles]
    assert actual == provenance['expected']
    assert len(articles) == 6
    assert all(article.published_at is not None and article.date_confidence == 'high'
               and article.date_source == 'source-selector' and not article.date_conflict for article in articles)
    status = provenance['live_status']
    assert status['success'] and status['raw_count'] == status['dated_count'] == 985
    assert status['invalid_date_count'] == status['unexplained_future_date_count'] == 0
    assert status['parse_status'] == 'healthy' and not status['error']


def test_unowned_or_nonpublication_dates_are_not_promoted():
    report = json.loads((ROOT / 'tests/fixtures/ministry_round5_south.json').read_text())
    checks = {check['canonical_id']:check for check in report['checks']}
    assert checks['es_industry_tourism']['result'] == 'manual_verified'
    for identifier in ('es_inclusion', 'es_labour', 'es_interior', 'it_maritime_policies',
                       'it_institutional_reforms', 'mt_youth', 'gr_government_presidency'):
        assert checks[identifier]['result'] not in {'manual_verified', 'existing_source'}
        assert checks[identifier]['blocked_reason']
        assert 'inventory_patch' not in checks[identifier]
    assert 'og:updated_time' in checks['it_institutional_reforms']['date_evidence']['specific_evidence']
    assert checks['mt_youth']['identity_evidence']['specific_evidence'].endswith('The National Youth Agency of Malta')
    assert report['cleanup_count'] == 0
