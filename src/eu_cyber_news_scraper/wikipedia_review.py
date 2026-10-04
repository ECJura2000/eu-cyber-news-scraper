"""Wikipedia discovers candidates; first-party evidence governs URL cleanup."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .source_catalog import https_url

LOCAL_WIKIPEDIA_LANGUAGES = {
    'AT': {'de'}, 'BE': {'nl', 'fr', 'de'}, 'BG': {'bg'}, 'CY': {'el', 'tr'},
    'CZ': {'cs'}, 'DE': {'de'}, 'DK': {'da'}, 'FI': {'fi', 'sv'}, 'FR': {'fr'},
    'GR': {'el'}, 'HR': {'hr'}, 'HU': {'hu'}, 'IT': {'it'}, 'LT': {'lt'},
    'MT': {'mt'}, 'RO': {'ro'}, 'SK': {'sk'}, 'ES': {'es'},
}
USER_EXCLUSION_POLICY = 'exclude_unverified_after_local_wikipedia_recheck'


def _observed(value: str, minimum: date) -> None:
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None or observed.astimezone(ZoneInfo('Asia/Taipei')).date() < minimum:
        raise ValueError('Wikipedia review observation has no timezone or is stale')


def validate_wikipedia_review(check: dict[str, Any], minimum: date) -> None:
    review = check.get('wikipedia')
    if not isinstance(review, dict) or review.get('status') not in {'matched', 'not_found', 'ambiguous', 'blocked'}:
        raise ValueError('Missing Wikipedia review disposition')
    queries = review.get('queries')
    if not isinstance(queries, list) or not queries or any(not isinstance(q, str) or not q.strip() for q in queries):
        raise ValueError('Wikipedia lookup requires recorded queries')
    pages = review.get('pages', [])
    if not isinstance(pages, list):
        raise ValueError('Invalid Wikipedia page evidence')
    urls = set()
    for page in pages:
        https_url(page['url'])
        parsed = urlsplit(page['url'])
        if not re.fullmatch(r'[a-z]{2,12}(?:-[a-z0-9]{1,8})?\.wikipedia\.org', parsed.hostname or '') or not parsed.path.startswith('/wiki/'):
            raise ValueError('Wikipedia page evidence is not an encyclopedia article')
        _observed(page['observed_at'], minimum)
        if not page.get('title', '').strip():
            raise ValueError('Wikipedia page title is missing')
        if review['status'] == 'matched':
            digest = page.get('response_sha256') or page.get('extracted_sha256')
            if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
                raise ValueError('Matched Wikipedia page requires retrieved-content checksum')
        urls.add(page['url'])
    if review['status'] == 'matched' and not pages:
        raise ValueError('Matched Wikipedia review requires an inspected article')
    candidates = review.get('website_candidates', [])
    if not isinstance(candidates, list):
        raise ValueError('Invalid Wikipedia website candidates')
    for candidate in candidates:
        parsed = urlsplit(candidate['url'])
        if parsed.scheme not in {'http', 'https'}:
            raise ValueError('Wikipedia website candidate must use HTTP or HTTPS')
        # Legacy HTTP links are discovery data only, never a TLS downgrade.
        https_url(urlunsplit(parsed._replace(scheme='https')))
        if candidate['wikipedia_url'] not in urls:
            raise ValueError('Website candidate has no inspected Wikipedia attribution')


def validate_news_url_cleanup(check: dict[str, Any], minimum: date) -> None:
    for removal in check.get('removed_news_urls', []):
        https_url(removal['url'])
        _observed(removal['observed_at'], minimum)
        if not removal.get('reason', '').strip():
            raise ValueError('News URL cleanup requires an explicit reason')
        if removal.get('http_status') not in {404, 410}:
            if removal.get('http_status') != 200 or not removal.get('specific_evidence', '').strip():
                raise ValueError('Access failure or Wikipedia absence cannot justify news URL deletion')
            https_url(removal['verification_url'])
        patch = check.get('inventory_patch', {})
        if 'news_url' not in patch or patch['news_url'] == removal['url']:
            raise ValueError('Removed news URL must not remain the declared endpoint')


def validate_local_wikipedia_review(check: dict[str, Any], minimum: date) -> None:
    """An English lookup cannot stand in for the requested local encyclopedia."""
    validate_wikipedia_review(check, minimum)
    review = check['wikipedia']
    language = review.get('local_language')
    if language not in LOCAL_WIKIPEDIA_LANGUAGES.get(check['country'], set()):
        raise ValueError('Wikipedia review requires a local country language')
    host = f'{language}.wikipedia.org'
    if not any(re.search(r'(?<!\S)site:' + re.escape(host) + r'(?:/|(?=\s|$))', query)
               for query in review['queries']):
        raise ValueError('Wikipedia queries must target the local encyclopedia')
    if any(urlsplit(page['url']).hostname != host for page in review.get('pages', [])):
        raise ValueError('Wikipedia article evidence must use the declared local language')
    evidence = review.get('search_evidence', [])
    if not isinstance(evidence, list) or {item['query'] for item in evidence} != set(review['queries']):
        raise ValueError('Local Wikipedia lookup requires actual search observations')
    for item in evidence:
        _observed(item['observed_at'], minimum)
        digest = item.get('response_sha256')
        if not item.get('error') and (not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('Local Wikipedia search requires a checksum or recorded failure')


def validate_user_exclusion(
    check: dict[str, Any], minimum: date, *, authorized: bool, original_url: str | None,
) -> None:
    """A user decision removes a candidate, never proves the website obsolete."""
    exclusion = check.get('user_exclusion')
    if not authorized or not isinstance(exclusion, dict):
        raise ValueError('Candidate exclusion requires explicit user authorization')
    reason = exclusion.get('reason')
    if exclusion.get('policy') not in {USER_EXCLUSION_POLICY, 'exclude_unreadable_registered_source'} or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Candidate exclusion requires policy and reason')
    _observed(exclusion['observed_at'], minimum)
    if exclusion.get('candidate_news_url') != original_url:
        raise ValueError('Candidate exclusion must identify the original declared URL')
    if original_url is not None:
        https_url(original_url)
    patch = check.get('inventory_patch', {})
    if 'news_url' not in patch or patch['news_url'] is not None:
        raise ValueError('Excluded candidate must not remain a runnable news URL')
    if check.get('source_ids'):
        raise ValueError('Excluded candidate must not reference runnable sources')
