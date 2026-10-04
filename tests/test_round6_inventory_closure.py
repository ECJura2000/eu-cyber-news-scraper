"""Every remaining candidate ends in a verified source or a reversible user exclusion."""
from pathlib import Path

from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.ministry_inventory import inventory_report, load_inventory
from eu_cyber_news_scraper.ministry_rechecks import load_rechecks
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry

ROOT = Path(__file__).resolve().parents[1]


def test_round6_closes_every_pending_id_without_claiming_full_search_coverage():
    rounds = load_rechecks(ROOT / 'tests/fixtures')
    current = next(round_ for round_ in rounds if round_['number'] == 6)
    initial = {row['canonical_id']: row for row in current['baseline']['ministries']}
    assert len(initial) == len(current['checks']) == 156
    assert set(initial) == set(current['checks'])
    registry = load_organisation_registry(builtin_dir=ROOT / 'organisation_registry',
                                          external_dir=ROOT / 'tests/fixtures/no-external-overrides')
    assert not registry.errors
    inventory = load_inventory(ROOT / 'ministry_inventory', registry)
    rows = {row['canonical_id']: row for country in inventory for row in country['ministries']}
    assert len(rows) == 460
    promoted = 0
    excluded = 0
    for identifier, check in current['checks'].items():
        row = rows[identifier]
        if row.get('user_exclusion', {}).get('policy') == 'exclude_unreadable_registered_source':
            assert check['result'] == 'manual_verified'
            assert row['status'] == 'user_excluded' and not row['source_ids'] and row['news_url'] is None
            promoted += 1
            continue
        assert row['status'] == check['result']
        if check['result'] == 'manual_verified':
            promoted += 1
            assert row['news_url'] and row['source_ids'] and 'user_exclusion' not in row
            for source_id in row['source_ids']:
                module = registry.module_for_source(source_id)
                assert module is not None
                source = next(source for source in module.payload['sources'] if source['id'] == source_id)
                assert not source['schedule_enabled'] and not source['critical']
        else:
            assert check['result'] == 'user_excluded'
            excluded += 1
            assert row['news_url'] is None and row['source_ids'] == []
            assert row['homepage'] == initial[identifier]['homepage']
            assert row['user_exclusion'] == check['user_exclusion']
            assert row['user_exclusion']['candidate_news_url'] == initial[identifier]['initial_news_url']
            assert check['failure_category'] and check['failure_reason']
        assert row['evidence_urls']
    report = inventory_report(inventory)
    assert promoted + excluded == 156
    subsequently_removed = sum(row.get('user_exclusion', {}).get('policy') == 'exclude_unreadable_registered_source'
                               for row in rows.values())
    assert report['registered_ministries'] == 304 + promoted - subsequently_removed
    assert report['user_excluded_ministries'] == excluded + subsequently_removed
    assert report['pending_ministries'] == 0
    assert report['searchable_inventory_complete'] == (excluded == 0)
    assert sum(source.schedule_enabled and not source.paused_until for source in load_sources()) == 50
