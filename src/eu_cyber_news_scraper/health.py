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
from .schema_validation import validate_schema_payload
from .state_lock import state_lock


def health_profile_fingerprint(profile: dict[str, Any]) -> str:
    encoded = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def source_config_fingerprint(source: Source) -> str:
    values = {
        "listing_url": source.listing_url,
        "feed_urls": source.feed_urls,
        "allow_domains": source.allow_domains,
        "include_patterns": source.include_patterns,
        "exclude_patterns": source.exclude_patterns,
        "detail_pages": source.detail_pages,
        "timezone": source.timezone,
        "card_selectors": source.card_selectors,
        "link_selectors": source.link_selectors,
        "title_selectors": source.title_selectors,
        "date_selectors": source.date_selectors,
        "summary_selectors": source.summary_selectors,
        "parser_adapter": source.parser_adapter,
        "date_policy": source.date_policy,
        "tls_intermediate_bundle": source.tls_intermediate_bundle,
        "min_listing_bytes": source.min_listing_bytes,
        "user_agent": source.user_agent,
    }
    return health_profile_fingerprint(values)


def assess_and_record_health(
    statuses: list[SourceStatus],
    sources: list[Source],
    path: str | Path,
    *,
    run_id: str,
    recorded_at: datetime,
    profile: dict[str, Any] | None = None,
    observation_key: str | None = None,
    write: bool = True,
) -> list[SourceStatus]:
    health_path = Path(path)
    effective_profile = profile or {"mode": "legacy-compatible"}
    baseline_profile = {
        key: value
        for key, value in effective_profile.items()
        if key not in {"source_ids", "source_settings"}
    }
    fingerprint = health_profile_fingerprint(baseline_profile)
    effective_observation_key = observation_key or recorded_at.date().isoformat()
    if write:
        with state_lock(health_path, run_id):
            payload = _load_v2(health_path)
            assessed = _assess(
                statuses,
                sources,
                payload,
                fingerprint,
                baseline_profile,
                run_id,
                recorded_at,
                effective_observation_key,
                True,
            )
            _atomic_json(health_path, payload)
            return assessed
    payload = _load_v2(health_path)
    return _assess(
        statuses,
        sources,
        payload,
        fingerprint,
        baseline_profile,
        run_id,
        recorded_at,
        effective_observation_key,
        False,
    )


def _assess(
    statuses: list[SourceStatus],
    sources: list[Source],
    payload: dict[str, Any],
    fingerprint: str,
    profile: dict[str, Any],
    run_id: str,
    recorded_at: datetime,
    observation_key: str,
    write: bool,
) -> list[SourceStatus]:
    profiles = payload.setdefault("profiles", {})
    profile_state = profiles.get(fingerprint, {})
    history = profile_state.get("sources", {})
    source_map = {source.id: source for source in sources}
    assessed: list[SourceStatus] = []

    for status in statuses:
        source = source_map[status.source_id]
        source_fingerprint = source_config_fingerprint(source)
        source_observation_key = health_profile_fingerprint(
            {
                "source_id": status.source_id,
                "source_fingerprint": source_fingerprint,
                "observation_key": observation_key,
            }
        )
        source_rows = [
            row
            for row in history.get(status.source_id, [])
            if row.get("observation_key") != source_observation_key
            and row.get("source_fingerprint", source_fingerprint) == source_fingerprint
        ]
        prior = source_rows[-12:]
        counts = [
            int(row.get("raw_count", 0))
            for row in prior[-8:]
            if row.get("success") and int(row.get("raw_count", 0)) > 0
        ]
        median = float(statistics.median(counts)) if counts else 0.0
        successful_prior = [row for row in prior[-8:] if row.get("success")]
        median_requests = _positive_median(successful_prior, "request_count")
        median_bytes = _positive_median(successful_prior, "bytes_downloaded")
        median_duration = _positive_median(successful_prior, "duration_seconds")
        alerts: list[str] = []
        baseline_failure = False
        if status.fetch_status == "failed":
            alerts.append("來源抓取失敗。")
            baseline_failure = True
        if len(counts) >= source.observation_runs and median >= 4 and status.raw_count < median * 0.25:
            alerts.append(f"原始筆數 {status.raw_count} 低於歷史中位數 {median:g} 的 25%。")
            baseline_failure = True
        if status.parse_status == "empty":
            alerts.append("來源可連線，但未解析出任何新聞卡片。")
            baseline_failure = True
        elif status.parse_status == "attention":
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

        performance_metrics = (
            ("HTTP 請求數", float(status.request_count), median_requests),
            ("下載位元組", float(status.bytes_downloaded), median_bytes),
            ("來源耗時", status.duration_seconds, median_duration),
        )
        if len(successful_prior) >= source.observation_runs:
            for label, current, historical in performance_metrics:
                if historical > 0 and current > historical * 2.5:
                    alerts.append(f"{label} {current:g} 超過歷史中位數 {historical:g} 的 2.5 倍。")

        if source.date_policy != "required" and source.date_review_due:
            try:
                exception_overdue = recorded_at.date() > datetime.fromisoformat(source.date_review_due).date()
            except ValueError:
                exception_overdue = True
            if exception_overdue:
                alerts.append(f"日期例外已超過複查期限 {source.date_review_due}。")
                baseline_failure = True

        consecutive_prior_failures = 0
        for row in reversed(prior):
            if not row.get("baseline_failure"):
                break
            consecutive_prior_failures += 1
        if status.fetch_status == "failed":
            health_status = "degraded" if status.critical or consecutive_prior_failures >= 2 else "attention"
        elif baseline_failure and (
            (status.critical and consecutive_prior_failures >= 1)
            or (not status.critical and consecutive_prior_failures >= 2)
        ):
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
            historical_median_requests=median_requests,
            historical_median_bytes=median_bytes,
            historical_median_duration=median_duration,
            health_alerts=tuple(alerts),
            health_status=health_status,
        )
        assessed.append(assessed_status)
        if write:
            rows = history.setdefault(status.source_id, [])
            rows[:] = [row for row in rows if row.get("observation_key") != source_observation_key]
            rows.append(
                {
                    "run_id": run_id,
                    "recorded_at": recorded_at.isoformat(),
                    "observation_key": source_observation_key,
                    "source_fingerprint": source_fingerprint,
                    "success": status.success,
                    "raw_count": status.raw_count,
                    "newest_published_at": status.newest_published_at,
                    "in_range_count": status.in_range_count,
                    "freshness_lag_days": status.freshness_lag_days,
                    "parse_status": status.parse_status,
                    "freshness_status": status.freshness_status,
                    "baseline_failure": baseline_failure,
                    "health_status": health_status,
                    "request_count": status.request_count,
                    "bytes_downloaded": status.bytes_downloaded,
                    "duration_seconds": status.duration_seconds,
                }
            )
            history[status.source_id] = rows[-12:]

    if write:
        profiles[fingerprint] = {
            "profile": profile,
            "updated_at": recorded_at.isoformat(),
            "sources": history,
        }
        _prune_profiles(payload)
    payload["schema_version"] = 2
    return assessed


def _positive_median(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row.get(field, 0)) for row in rows if float(row.get(field, 0)) > 0]
    return float(statistics.median(values)) if values else 0.0


def _prune_profiles(payload: dict[str, Any], *, keep: int = 8) -> None:
    profiles = payload.get("profiles", {})
    if not isinstance(profiles, dict) or len(profiles) <= keep:
        return
    ordered = sorted(
        profiles.items(),
        key=lambda item: str(item[1].get("updated_at", "")) if isinstance(item[1], dict) else "",
        reverse=True,
    )
    payload["profiles"] = dict(ordered[:keep])
    archived = payload.setdefault("legacy_profiles", [])
    for fingerprint, row in ordered[keep:]:
        archived.append(
            {
                "fingerprint": fingerprint,
                "updated_at": row.get("updated_at", "") if isinstance(row, dict) else "",
            }
        )
    payload["legacy_profiles"] = archived[-24:]


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
    validate_schema_payload(payload, "health-v2.schema.json")
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
