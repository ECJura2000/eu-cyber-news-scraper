from __future__ import annotations

import hashlib
import json
import os
import statistics
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Source, SourceStatus
from .state_lock import state_lock


def health_profile_fingerprint(profile: dict[str, Any]) -> str:
    encoded = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def assess_and_record_health(
    statuses: list[SourceStatus],
    sources: list[Source],
    path: str | Path,
    *,
    run_id: str,
    recorded_at: datetime,
    profile: dict[str, Any] | None = None,
    write: bool = True,
) -> list[SourceStatus]:
    health_path = Path(path)
    effective_profile = profile or {"mode": "legacy-compatible"}
    fingerprint = health_profile_fingerprint(effective_profile)
    if write:
        with state_lock(health_path, run_id):
            payload = _load_v2(health_path)
            assessed = _assess(statuses, sources, payload, fingerprint, effective_profile, run_id, recorded_at, True)
            _atomic_json(health_path, payload)
            return assessed
    payload = _load_v2(health_path)
    return _assess(statuses, sources, payload, fingerprint, effective_profile, run_id, recorded_at, False)


def _assess(
    statuses: list[SourceStatus],
    sources: list[Source],
    payload: dict[str, Any],
    fingerprint: str,
    profile: dict[str, Any],
    run_id: str,
    recorded_at: datetime,
    write: bool,
) -> list[SourceStatus]:
    profiles = payload.setdefault("profiles", {})
    profile_state = profiles.get(fingerprint, {})
    history = profile_state.get("sources", {})
    source_map = {source.id: source for source in sources}
    assessed: list[SourceStatus] = []

    for status in statuses:
        prior = [row for row in history.get(status.source_id, []) if row.get("success")]
        counts = [int(row.get("raw_count", 0)) for row in prior[-8:] if int(row.get("raw_count", 0)) > 0]
        median = float(statistics.median(counts)) if counts else 0.0
        alerts: list[str] = []
        source = source_map[status.source_id]
        baseline_failure = False
        if len(counts) >= source.observation_runs and median >= 4 and status.raw_count < median * 0.25:
            alerts.append(f"原始筆數 {status.raw_count} 低於歷史中位數 {median:g} 的 25%。")
            baseline_failure = True
        if status.parse_status == "attention":
            alerts.append(f"無日期新聞比例過高（{status.undated_ratio:.0%}）。")
            baseline_failure = True
        if status.raw_count >= 4 and status.unique_title_ratio < 0.7:
            alerts.append(f"原始標題重複率異常（唯一標題比例 {status.unique_title_ratio:.0%}）。")
            baseline_failure = True
        if status.freshness_status == "stale":
            alerts.append(
                f"最新可辨識文章距今 {status.freshness_lag_days:.0f} 天，"
                f"超過來源門檻 {source.freshness_days} 天。"
            )
            baseline_failure = True

        previous_baseline_failure = bool(prior and prior[-1].get("baseline_failure"))
        if status.fetch_status == "failed":
            health_status = "degraded" if status.critical else "attention"
        elif status.critical and baseline_failure and previous_baseline_failure:
            health_status = "degraded"
        elif alerts:
            health_status = "attention"
        else:
            health_status = "healthy"

        warning = status.warning
        if alerts:
            warning = f"{warning} 健康基線警示：{' '.join(alerts)}".strip()
        assessed_status = replace(
            status,
            warning=warning,
            historical_median_count=median,
            health_alerts=tuple(alerts),
            health_status=health_status,
        )
        assessed.append(assessed_status)
        if write:
            rows = history.setdefault(status.source_id, [])
            rows.append(
                {
                    "run_id": run_id,
                    "recorded_at": recorded_at.isoformat(),
                    "success": status.success,
                    "raw_count": status.raw_count,
                    "newest_published_at": status.newest_published_at,
                    "in_range_count": status.in_range_count,
                    "freshness_lag_days": status.freshness_lag_days,
                    "parse_status": status.parse_status,
                    "freshness_status": status.freshness_status,
                    "baseline_failure": baseline_failure,
                    "health_status": health_status,
                }
            )
            history[status.source_id] = rows[-12:]

    if write:
        profiles[fingerprint] = {
            "profile": profile,
            "updated_at": recorded_at.isoformat(),
            "sources": history,
        }
    payload["schema_version"] = 2
    return assessed


def _load_v2(path: Path) -> dict[str, Any]:
    payload = _load(path)
    if payload.get("schema_version") == 2 and isinstance(payload.get("profiles"), dict):
        return payload
    result: dict[str, Any] = {"schema_version": 2, "profiles": {}}
    if payload:
        result["legacy"] = payload
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
