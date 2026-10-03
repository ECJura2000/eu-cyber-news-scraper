import json

import pytest

from eu_cyber_news_scraper.ministry_rechecks import latest_checks, load_rechecks


def write_round(directory, number, *, result='blocked', observed='2026-10-02T16:30:00+00:00'):
    baseline = {'observed_on': '2026-10-03', 'remaining_count': 1, 'initial_registered': 0,
                'ministries': [{'canonical_id': 'de_test', 'country': 'DE', 'initial_status': 'blocked'}]}
    report = {'schema_version': 1, 'group': 'test', 'observed_on': '2026-10-03', 'countries': ['DE'],
              'checks': [{'canonical_id': 'de_test', 'country': 'DE', 'result': result,
                          'next_action': 'Verify official news',
                          'attempts': [{'url': 'https://official.example/', 'observed_at': observed,
                                        'http_status': 200}]}]}
    (directory/f'ministry_round{number}_baseline.json').write_text(json.dumps(baseline))
    (directory/f'ministry_round{number}_test.json').write_text(json.dumps(report))
    return baseline, report


def test_rechecks_keep_history_and_update_only_latest_disposition(tmp_path):
    write_round(tmp_path, 3)
    write_round(tmp_path, 4, result='manual_verified')
    rounds = load_rechecks(tmp_path)
    assert rounds[0]['checks']['de_test']['result'] == 'blocked'
    assert latest_checks(rounds)['de_test']['result'] == 'manual_verified'


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'unknown', 'country', 'status', 'action',
                                  'attempts', 'url', 'timezone', 'stale', 'no_evidence', 'group', 'schema', 'report_stale'])
def test_invalid_recheck_cannot_be_called_complete(tmp_path, change):
    baseline, report = write_round(tmp_path, 3)
    check = report['checks'][0]
    if change == 'duplicate':
        report['checks'].append(check)
    elif change == 'missing':
        report['checks'] = []
    elif change == 'unknown':
        check['canonical_id'] = 'de_other'
    elif change == 'country':
        check['country'] = 'FR'
    elif change == 'status':
        check['result'] = 'complete'
    elif change == 'action':
        check['next_action'] = ''
    elif change == 'attempts':
        check['attempts'] = []
    elif change == 'url':
        check['attempts'][0]['url'] = 'http://official.example/'
    elif change == 'timezone':
        check['attempts'][0]['observed_at'] = '2026-10-03T00:00:00'
    elif change == 'stale':
        check['attempts'][0]['observed_at'] = '2026-10-01T00:00:00+00:00'
    elif change == 'no_evidence':
        del check['attempts'][0]['http_status']
    elif change == 'group':
        report['group'] = 'other'
    elif change == 'schema':
        report['schema_version'] = 2
    else:
        report['observed_on'] = '2026-10-01'
    (tmp_path/'ministry_round3_test.json').write_text(json.dumps(report))
    with pytest.raises(ValueError):
        load_rechecks(tmp_path)


@pytest.mark.parametrize('duplicate', [False, True])
def test_baseline_size_and_identifiers_are_verified(tmp_path, duplicate):
    baseline, _ = write_round(tmp_path, 3)
    if duplicate:
        baseline['ministries'].append(baseline['ministries'][0])
    else:
        baseline['remaining_count'] = 2
    (tmp_path/'ministry_round3_baseline.json').write_text(json.dumps(baseline))
    with pytest.raises(ValueError):
        load_rechecks(tmp_path)


def test_registered_ministry_cannot_be_silently_reopened(tmp_path):
    write_round(tmp_path, 3, result='manual_verified')
    write_round(tmp_path, 4)
    with pytest.raises(ValueError, match='reopens registered'):
        load_rechecks(tmp_path)


def test_later_baseline_cannot_change_country(tmp_path):
    write_round(tmp_path, 3)
    baseline, _ = write_round(tmp_path, 4)
    baseline['ministries'][0]['country'] = 'FR'
    (tmp_path/'ministry_round4_baseline.json').write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match='changes a ministry country'):
        load_rechecks(tmp_path)


def test_empty_history_cannot_claim_complete(tmp_path):
    with pytest.raises(ValueError, match='No ministry'):
        load_rechecks(tmp_path)


def test_publication_fixtures_and_provenance_are_not_disposition_reports(tmp_path):
    write_round(tmp_path, 3)
    (tmp_path/'ministry_round3_article.json').write_text('[{"title":"Original publication"}]')
    (tmp_path/'ministry_round3_article.provenance.json').write_text('{"sha256":"fixture"}')
    assert len(load_rechecks(tmp_path)) == 1


def test_invalid_baseline_filename_is_reported(tmp_path):
    (tmp_path/'ministry_roundinvalid_baseline.json').write_text('{}')
    with pytest.raises(ValueError, match='filename'):
        load_rechecks(tmp_path)
