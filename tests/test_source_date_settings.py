"""Configurable date interpretation, absolute dates and source-local boundaries."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from eu_cyber_news_scraper.config import _validate_sources, load_sources
from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.organisation_registry import _validate_payload
from eu_cyber_news_scraper.parsers import apply_publication_date, enrich_from_detail, parse_datetime, parse_listing

ROOT = Path(__file__).resolve().parents[1]


def test_every_builtin_source_has_explicit_settings_and_toml_matches():
    rows = []
    for path in (ROOT / 'organisation_registry').glob('*.json'):
        for row in json.loads(path.read_text())['sources']:
            assert all(key in row for key in ('language', 'timezone', 'date_order', 'date_formats'))
            assert row['date_formats']
            rows.append(row)
    assert len(rows) == 410  # 409 runnable sources plus the replaceable example.
    assert load_sources() == load_sources(ROOT / 'src/eu_cyber_news_scraper/sources.toml')


@pytest.mark.parametrize('order,expected', [('DMY', '2026-04-03'), ('MDY', '2026-03-04')])
def test_explicit_order_overrides_english_locale(order, expected):
    parsed = parse_datetime('03/04/2026', ('en',), date_order=order)
    assert parsed.date().isoformat() == expected


def test_conflicting_formats_do_not_guess_or_discard_original_date():
    article = Article(source_id='test', country='EU', source_name='Test', title='News', url='https://example.eu/news',
                      institution_type='official', language='en')
    assert not apply_publication_date(article, '03/04/2026', timezone_name='Europe/Brussels', languages=('en',),
                                      source='source-selector', confidence='high',
                                      date_formats=('%d/%m/%Y', '%m/%d/%Y'))
    assert article.published_at is None and article.published_at_raw == '03/04/2026'
    assert article.date_confidence == 'low' and not article.date_candidates


@pytest.mark.parametrize('raw', ['March 2026', '3 April'])
def test_missing_day_or_year_is_not_invented(raw):
    assert parse_datetime(raw, ('en',)) is None


@pytest.mark.parametrize('raw,expected', [
    ('2026-01-07', '2026-01-06T23:00:00+00:00'),
    ('2026-07-07', '2026-07-06T22:00:00+00:00'),
    ('2026-07-07T09:30:00', '2026-07-07T07:30:00+00:00'),
    ('2026-07-07T09:30:00Z', '2026-07-07T09:30:00+00:00'),
])
def test_naive_dates_use_source_zone_but_explicit_offsets_are_preserved(raw, expected):
    assert parse_datetime(raw, ('en',), 'Europe/Brussels').isoformat() == expected


@pytest.mark.parametrize('field,value', [('date_order', 'AUTO'), ('date_formats', 'DMY'),
                                      ('date_formats', ['%d/%m']), ('date_formats', ['%Y']),
                                      ('date_formats', ['%Y %%m %%d']), ('date_formats', ['%Q/%Y']),
                                      ('timezone', 'Unknown/Nowhere'), ('language', 'xx')])
def test_invalid_settings_rejected_by_json_validator(field, value):
    payload = json.loads((ROOT / 'organisation_registry/eu_edpb.json').read_text())
    payload['sources'][0][field] = value
    with pytest.raises(ValueError):
        _validate_payload(payload)


def test_invalid_direct_source_rejected_and_legacy_module_still_valid():
    source = next(row for row in load_sources() if row.id == 'eu_edpb')
    with pytest.raises(ValueError, match='date_order'):
        _validate_sources([replace(source, date_order='AUTO')])
    payload = json.loads((ROOT / 'organisation_registry/eu_edpb.json').read_text())
    for key in ('date_order', 'date_formats', 'timezone'):
        payload['sources'][0].pop(key)
    _validate_payload(payload)


def test_listing_and_detail_both_use_overridden_date_profile():
    source = next(row for row in load_sources() if row.id == 'eu_edpb')
    source = replace(source, homepage='https://example.eu/', listing_url='https://example.eu/news',
                     allow_domains=('example.eu',), include_patterns=('/news/',), exclude_patterns=(),
                     card_selectors=('article',), link_selectors=('a',), title_selectors=(),
                     date_selectors=('.date',), date_order='MDY', date_formats=('%m/%d/%Y',))
    html = '<article><a href="/news/test">Artificial intelligence policy</a><span class="date">03/04/2026</span></article>'
    item = parse_listing(html, source, source.listing_url)[0]
    assert item.published_date_local == '2026-03-04'
    enrich_from_detail(item, '<time datetime="04/05/2026"></time>', source)
    assert item.published_date_local == '2026-04-05' and item.date_conflict


def test_replacing_external_json_changes_loaded_profile_and_registry_hash(tmp_path, monkeypatch):
    from eu_cyber_news_scraper.config import load_sources_and_registry

    monkeypatch.setenv('EU_CYBER_ORGANISATION_DIR', str(tmp_path))
    _, original_registry = load_sources_and_registry()
    payload = json.loads((ROOT / 'organisation_registry/eu_edpb.json').read_text())
    payload['sources'][0].update(language='en', timezone='Europe/Dublin', date_order='MDY',
                                 date_formats=['%m/%d/%Y'])
    target = tmp_path / 'eu_edpb.json'
    target.write_text(json.dumps(payload), encoding='utf-8')
    sources, overridden_registry = load_sources_and_registry()
    source = next(row for row in sources if row.id == 'eu_edpb')
    assert (source.language, source.timezone, source.date_order, source.date_formats) == (
        'en', 'Europe/Dublin', 'MDY', ('%m/%d/%Y',))
    assert overridden_registry.registry_hash != original_registry.registry_hash
    payload['sources'][0]['date_order'] = 'DMY'
    payload['sources'][0]['date_formats'] = ['%d/%m/%Y']
    target.write_text(json.dumps(payload), encoding='utf-8')
    changed_sources, changed_registry = load_sources_and_registry()
    assert next(row for row in changed_sources if row.id == 'eu_edpb').date_order == 'DMY'
    assert changed_registry.registry_hash != overridden_registry.registry_hash
