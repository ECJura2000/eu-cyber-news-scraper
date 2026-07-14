from __future__ import annotations

import json
import os
import statistics
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .models import Source, SourceStatus


def assess_and_record_health(
    statuses: list[SourceStatus],
    sources: list[Source],
    path: str | Path,
    *,
    run_id: str,
    recorded_at: datetime,
) -> list[SourceStatus]:
    health_path = Path(path)
    payload = _load(health_path)
    history = payload.setdefault("sources", {})
    source_map = {source.id: source for source in sources}
    assessed: list[SourceStatus] = []

    for status in statuses:
        prior = [row for row in history.get(status.source_id, []) if row.get("success")]
        counts = [int(row.get("raw_count", 0)) for row in prior[-8:] if int(row.get("raw_count", 0)) > 0]
        median = float(statistics.median(counts)) if counts else 0.0
        alerts: list[str] = []
        baseline_failure = False
        source = source_map[status.source_id]
        if len(counts) >= source.observation_runs and median >= 4 and status.raw_count < median * 0.25:
            alerts.append(f"原始筆數 {status.raw_count} 低於歷史中位數 {median:g} 的 25%。")
            baseline_failure = True
        if status.raw_count and not status.newest_published_at:
            alerts.append("已解析新聞但全部缺少發布日期。")
        elif status.raw_count >= 4 and status.undated_ratio > 0.5:
            alerts.append(f"無日期新聞比例過高（{status.undated_ratio:.0%}）。")
        if status.raw_count >= 4 and status.unique_title_ratio < 0.7:
            alerts.append(f"原始標題重複率異常（唯一標題比例 {status.unique_title_ratio:.0%}）。")
        recent_in_range = [row.get("in_range_count") for row in prior[-2:] if "in_range_count" in row]
        if status.in_range_count == 0 and len(recent_in_range) == 2 and all(value == 0 for value in recent_in_range):
            alerts.append("連續 3 次執行在指定期間內沒有解析到新文章。")
        if status.newest_published_at:
            stale_days = status.freshness_lag_days
            if stale_days > source.freshness_days:
                alerts.append(
                    f"最新可辨識文章距今 {stale_days:.0f} 天，超過來源門檻 {source.freshness_days} 天。"
                )
                baseline_failure = True

        warning = status.warning
        if alerts:
            warning = f"{warning} 健康基線警示：{' '.join(alerts)}".strip()
        assessed_status = replace(
            status,
            success=status.success and not (status.critical and baseline_failure),
            warning=warning,
            historical_median_count=median,
            health_alerts=tuple(alerts),
        )
        assessed.append(assessed_status)
        rows = history.setdefault(status.source_id, [])
        rows.append(
            {
                "run_id": run_id,
                "recorded_at": recorded_at.isoformat(),
                "success": assessed_status.success,
                "raw_count": status.raw_count,
                "newest_published_at": status.newest_published_at,
                "in_range_count": status.in_range_count,
                "freshness_lag_days": status.freshness_lag_days,
            }
        )
        history[status.source_id] = rows[-12:]

    payload["schema_version"] = 1
    _atomic_json(health_path, payload)
    return assessed


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict) -> None:
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
