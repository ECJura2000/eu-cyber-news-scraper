"""Wikipedia discovers candidates; first-party evidence governs URL cleanup."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .source_catalog import https_url


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
