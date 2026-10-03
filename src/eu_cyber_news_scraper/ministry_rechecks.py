"""Validate complete recheck rounds without rewriting earlier observations."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .source_catalog import https_url

REGISTERED = frozenset({'existing_source', 'manual_verified'})
RESULTS = REGISTERED | {'blocked', 'parser_pending', 'needs_review', 'no_news_endpoint'}


def _round_number(path: Path) -> int:
    match = re.fullmatch(r'ministry_round(\d+)_baseline.json', path.name)
    if match is None:
        raise ValueError('Invalid recheck baseline filename')
    return int(match[1])


def load_rechecks(directory: Path) -> list[dict[str, Any]]:
    rounds: list[dict[str, Any]] = []
    previous: dict[str, dict[str, Any]] = {}
    for baseline_path in sorted(directory.glob('ministry_round*_baseline.json'),
                                key=_round_number):
        number = _round_number(baseline_path)
        baseline = json.loads(baseline_path.read_text())
        initial = {row['canonical_id']: row for row in baseline['ministries']}
        if len(initial) != len(baseline['ministries']) or len(initial) != baseline['remaining_count']:
            raise ValueError('Invalid or duplicate recheck baseline')
        if rounds and set(initial) != {identifier for identifier, check in previous.items()
                                     if check['result'] not in REGISTERED}:
            raise ValueError('Recheck baseline omits unresolved ministries or reopens registered sources')
        if rounds and any(row['country'] != previous[identifier]['country']
                          for identifier, row in initial.items()):
            raise ValueError('Recheck baseline changes a ministry country')
        checks: dict[str, dict[str, Any]] = {}
        paths = []
        for path in sorted(directory.glob(f'ministry_round{number}_*.json')):
            if path == baseline_path:
                continue
            report = json.loads(path.read_text())
            # Publication fixtures and provenance share the round prefix but
            # are not disposition reports.
            if not isinstance(report, dict) or 'checks' not in report:
                continue
            if report.get('schema_version') != 1 or path.stem != f'ministry_round{number}_{report.get("group")}':
                raise ValueError('Invalid recheck report identity')
            if date.fromisoformat(report['observed_on']) < date.fromisoformat(baseline['observed_on']):
                raise ValueError('Recheck report precedes its baseline')
            paths.append(path.name)
            for check in report['checks']:
                identifier = check['canonical_id']
                if identifier not in initial or identifier in checks:
                    raise ValueError('Missing, duplicate or unexpected recheck identifier')
                if (check['country'] != initial[identifier]['country'] or check['country'] not in report['countries']
                        or check['result'] not in RESULTS or not check['next_action'].strip() or not check['attempts']):
                    raise ValueError('Invalid recheck disposition')
                for attempt in check['attempts']:
                    https_url(attempt['url'])
                    observed = datetime.fromisoformat(attempt['observed_at'])
                    if (observed.tzinfo is None or observed.astimezone(ZoneInfo('Asia/Taipei')).date()
                            < date.fromisoformat(baseline['observed_on'])):
                        raise ValueError('Recheck observation has no timezone or is stale')
                    if not attempt.get('http_status') and not attempt.get('error'):
                        raise ValueError('Recheck observation has no response or failure evidence')
                checks[identifier] = check
        if set(checks) != set(initial):
            raise ValueError('Recheck reports do not cover every unresolved ministry')
        previous.update(checks)
        rounds.append({'number': number, 'baseline': baseline, 'checks': checks, 'reports': paths})
    if not rounds:
        raise ValueError('No ministry recheck observations')
    return rounds


def latest_checks(rounds: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for round_ in rounds:
        result.update(round_['checks'])
    return result
