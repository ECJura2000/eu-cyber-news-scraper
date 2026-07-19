from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .artifacts import ArtifactBundle, verify_artifact_bundle
from .config import (
    DEFAULT_DAYS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_BUDGET,
    DEFAULT_TIMEOUT,
    DEFAULT_TIMEZONE,
    DEFAULT_WORKERS,
    load_sources,
)
from .dedupe import dedupe_articles
from .events import emit_event
from .exporter import export_workbook, write_jsonl, write_run_summary
from .health import assess_and_record_health, health_profile_fingerprint
from .http import HttpClient
from .models import Source, SourceResult, SourceStatus
from .periods import PeriodSelection, resolve_period
from .runtime_lock import acquire_run_lock, release_run_lock
from .scraper import scrape_source
from .translation import skip_article_title_translation, translate_article_titles

COUNTRY_LABELS = {"EU": "歐盟", "FR": "法國", "DE": "德國", "IE": "愛爾蘭"}
TOPIC_ALIASES = {
    "AI": "AI法、模型評估、演算法問責、自動化決策、AI與著作權",
    "DATA": "跨境資料流通、資料主權、資料開放與再利用",
    "PRIVACY": "隱私框架（含個人資料保護）",
    "IDENTITY": "數位身份",
    "COPYRIGHT": "著作權",
    "PLATFORM": "平台責任、內容審查、推薦演算法",
    "INFO": "媒體多元與資訊操縱",
    "COMPETITION": "競爭規範面向（平台責任的市場結構面）",
    "NIS2": "NIS2、關鍵基礎設施保護",
    "PRODUCT": "產品資安、漏洞揭露義務、SBOM",
    "SUPPLY": "供應鏈安全",
    "CERT": "資安產品認證",
    "HYBRID": "關鍵基礎設施的實體與數位融合保護",
    "CHIPS": "半導體",
    "QUANTUM": "量子技術",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="抓取歐盟、法國、德國與愛爾蘭官方機關及公共研究機構的資安法制新聞。"
    )
    parser.add_argument("--days", type=int, default=None, help=f"回推日數；未指定期間時預設 {DEFAULT_DAYS} 天。")
    parser.add_argument("--since", help="起始日；支援西元或民國日期。")
    parser.add_argument("--until", help="結束日；支援西元或民國日期，並包含該日。")
    parser.add_argument("--country", action="append", choices=sorted(COUNTRY_LABELS), help="可重複指定 EU、FR、DE、IE。")
    parser.add_argument("--source", action="append", help="可重複指定來源代碼；用 --list-sources 查看。")
    parser.add_argument("--topic", action="append", choices=sorted(TOPIC_ALIASES), help="只輸出指定主題；可重複。")
    parser.add_argument("--all", action="store_true", help="保留未命中觀測主題的官方新聞。")
    parser.add_argument("--include-undated", action="store_true", help="保留無法辨識發布日的資料。")
    parser.add_argument("--no-detail", action="store_true", help="不進入新聞內頁補抓日期與摘要。")
    parser.add_argument("--no-translate", action="store_true", help="不呼叫外部翻譯服務，中文標題欄保留原文。")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"來源併發數，預設 {DEFAULT_WORKERS}。")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"單次連線逾時秒數，預設 {DEFAULT_TIMEOUT}。")
    parser.add_argument(
        "--source-budget",
        type=int,
        default=DEFAULT_SOURCE_BUDGET,
        help=f"每個來源的總抓取時間預算，預設 {DEFAULT_SOURCE_BUDGET} 秒。",
    )
    parser.add_argument("--state-dir", help="來源健康紀錄與翻譯快取目錄。")
    parser.add_argument(
        "--health-write",
        choices=("auto", "always", "never"),
        default="auto",
        help="健康基線寫入策略；auto 僅寫入完整 rolling 且啟用內頁的標準執行。",
    )
    parser.add_argument("--output", help="Excel 輸出路徑。")
    parser.add_argument("--jsonl", action="store_true", help="另輸出同名 JSONL。")
    parser.add_argument("--config", help="自訂 sources.toml 路徑。")
    parser.add_argument("--list-sources", action="store_true", help="列出來源後結束。")
    parser.add_argument("--fail-on-degraded", action="store_true", help="必要來源失敗時回傳非零結束碼。")
    parser.add_argument("--min-source-success-rate", type=float, help="最低來源成功率，範圍 0 至 1。")
    parser.add_argument("--min-critical-date-rate", type=float, help="最低必要來源日期完整率，範圍 0 至 1。")
    parser.add_argument("--max-unexplained-future-dates", type=int, help="允許的未來日期筆數上限。")
    parser.add_argument("--require-complete-artifacts", action="store_true", help="要求完整且交叉驗證成功的產物集合。")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _validate_quality_options(args)
    sources = list(load_sources(args.config))
    if args.list_sources:
        _print_sources(sources)
        return

    selected = _select_sources(sources, args.country, args.source)
    if not selected:
        raise SystemExit("[error] 沒有符合條件的來源。")
    try:
        period = resolve_period(args.since, args.until, args.days)
    except ValueError as exc:
        raise SystemExit(f"[error] {exc}") from exc
    output = Path(args.output) if args.output else _default_output(period.since, period.until)
    run_id = uuid.uuid4().hex
    try:
        lock_path = acquire_run_lock(output, run_id)
    except RuntimeError as exc:
        raise SystemExit(f"[error] {exc}") from exc
    try:
        _run_pipeline(args, selected, period.since, period.until, output, run_id, period=period)
    finally:
        release_run_lock(lock_path, run_id)


def _run_pipeline(
    args: argparse.Namespace,
    selected: list[Source],
    since: datetime,
    until: datetime,
    output: Path,
    run_id: str,
    *,
    period: PeriodSelection | None = None,
) -> None:
    asyncio.run(
        _run_pipeline_async(
            args,
            selected,
            since,
            until,
            output,
            run_id,
            period=period,
        )
    )


async def _run_pipeline_async(
    args: argparse.Namespace,
    selected: list[Source],
    since: datetime,
    until: datetime,
    output: Path,
    run_id: str,
    *,
    period: PeriodSelection | None = None,
) -> None:
    started_at = datetime.now(timezone.utc)
    results: list[SourceResult] = []
    worker_count = max(1, min(args.workers, len(selected)))
    state_dir_value = getattr(args, "state_dir", None)
    state_dir = Path(state_dir_value).expanduser() if state_dir_value else output.parent
    state_dir.mkdir(parents=True, exist_ok=True)
    state_ready = state_dir / ".state-ready"
    state_ready.unlink(missing_ok=True)
    if state_dir_value and "EU_CYBER_NEWS_TRANSLATION_CACHE" not in os.environ:
        os.environ["EU_CYBER_NEWS_TRANSLATION_CACHE"] = str(state_dir / "translations.json")

    display_since, display_until = _display_dates(since, until)
    emit_event(
        "run_started",
        run_id=run_id,
        period_start=str(display_since),
        period_end=str(display_until),
        source_count=len(selected),
    )
    source_limiter = asyncio.Semaphore(worker_count)

    async with HttpClient(timeout=max(1, args.timeout)) as client:
        async def run_one(source: Source) -> tuple[Source, SourceResult]:
            async with source_limiter:
                try:
                    result = await scrape_source(
                        source,
                        client,
                        since=since,
                        until=until,
                        include_unmatched=args.all,
                        include_undated=args.include_undated,
                        fetch_details=not args.no_detail,
                        source_budget_seconds=max(1, getattr(args, "source_budget", DEFAULT_SOURCE_BUDGET)),
                        observed_at=started_at,
                    )
                except Exception as exc:  # defensive boundary around every source job
                    emit_event(
                        "source_failed",
                        run_id=run_id,
                        source_id=source.id,
                        stage="source_boundary",
                        error_code="UNHANDLED_SOURCE_ERROR",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    result = SourceResult(
                        source=source,
                        articles=[],
                        status=SourceStatus(
                            source_id=source.id,
                            source_name=source.name_zh,
                            country=source.country,
                            critical=source.critical,
                            success=False,
                            fetched_via="",
                            raw_count=0,
                            relevant_count=0,
                            duration_seconds=0.0,
                            error=f"{type(exc).__name__}: {exc}",
                            fetch_status="failed",
                            parse_status="not_run",
                            freshness_status="unknown",
                            content_status="unknown",
                            error_code="UNHANDLED_SOURCE_ERROR",
                        ),
                    )
                return source, result

        tasks = [asyncio.create_task(run_one(source)) for source in selected]
        for task in asyncio.as_completed(tasks):
            source, result = await task
            results.append(result)
            emit_event(
                "source_completed",
                run_id=run_id,
                source_id=source.id,
                fetch_status=result.status.fetch_status,
                parse_status=result.status.parse_status,
                health_status=result.status.health_status,
                raw_count=result.status.raw_count,
                relevant_count=result.status.relevant_count,
                duration_seconds=result.status.duration_seconds,
                request_count=result.status.request_count,
                bytes_downloaded=result.status.bytes_downloaded,
                error_code=result.status.error_code,
            )

    order = {source.id: index for index, source in enumerate(selected)}
    results.sort(key=lambda result: order[result.source.id])
    discovered_articles = [article for result in results for article in result.articles]
    articles = dedupe_articles(discovered_articles)
    if args.topic:
        wanted = {TOPIC_ALIASES[value] for value in args.topic}
        articles = [article for article in articles if wanted.intersection(article.matched_topics)]
    articles.sort(key=lambda item: item.published_at or since, reverse=True)
    translation = (
        skip_article_title_translation(articles)
        if getattr(args, "no_translate", False)
        else translate_article_titles(articles)
    )
    output_counts: dict[str, int] = {}
    for article in articles:
        for source_id in article.discovered_by or [article.source_id]:
            output_counts[source_id] = output_counts.get(source_id, 0) + 1
    statuses = [replace(result.status, relevant_count=output_counts.get(result.source.id, 0)) for result in results]
    health_profile = {
        "period_mode": period.mode if period else "fixed",
        "source_ids": [source.id for source in selected],
        "source_settings": [
            {
                "id": source.id,
                "listing_url": source.listing_url,
                "feed_urls": list(source.feed_urls),
                "detail_pages": source.detail_pages,
                "timezone": source.timezone,
                "date_policy": source.date_policy,
            }
            for source in selected
        ],
        "fetch_details": not args.no_detail,
        "include_undated": args.include_undated,
        "include_unmatched": args.all,
        "source_budget": max(1, getattr(args, "source_budget", DEFAULT_SOURCE_BUDGET)),
    }
    health_mode = getattr(args, "health_write", "auto")
    health_write = health_mode == "always" or (
        health_mode == "auto"
        and (period is None or period.mode == "rolling")
        and not args.no_detail
        and not getattr(args, "source", None)
        and not getattr(args, "country", None)
    )
    observation_key = _health_observation_key(period, since, until, health_profile)
    statuses = assess_and_record_health(
        statuses,
        selected,
        state_dir / ".source-health.json",
        run_id=run_id,
        recorded_at=datetime.now(timezone.utc),
        profile=health_profile,
        observation_key=observation_key,
        write=False,
    )
    quality_failures = _quality_failures(statuses, args)
    jsonl_output = output.with_suffix(".jsonl") if args.jsonl else None
    summary_output = output.with_suffix(".run.json")
    with ArtifactBundle(output, run_id) as bundle:
        staged_workbook = export_workbook(
            articles,
            statuses,
            selected,
            bundle.staged(output),
            run_id=run_id,
            period=period,
            since=since,
            until=until,
        )
        staged_jsonl = (
            write_jsonl(articles, bundle.staged(jsonl_output), run_id=run_id)
            if jsonl_output is not None
            else None
        )
        finished_at = datetime.now(timezone.utc)
        staged_summary = write_run_summary(
            staged_workbook,
            started_at=started_at,
            finished_at=finished_at,
            since=since,
            until=until,
            articles=articles,
            statuses=statuses,
            run_id=run_id,
            translation_report=translation,
            period=period,
            discovered_article_count=len(discovered_articles),
            config_path=getattr(args, "config", None),
            run_profile={**health_profile, "health_write": health_write, "observation_key": observation_key},
            artifact_names=[output.name, summary_output.name, *([jsonl_output.name] if jsonl_output else [])],
            artifact_paths=[staged_workbook, *([staged_jsonl] if staged_jsonl else [])],
            published_output_path=output,
            quality_failures=quality_failures,
        )
        verify_artifact_bundle(
            staged_workbook,
            staged_jsonl,
            staged_summary,
            run_id=run_id,
            article_count=len(articles),
        )
        bundle.publish(
            [
                (staged_workbook, output),
                *([(staged_jsonl, jsonl_output)] if staged_jsonl and jsonl_output else []),
                (staged_summary, summary_output),
            ],
            manifest=summary_output,
        )

    degraded = [
        status.source_id
        for status in statuses
        if status.critical and (not status.success or status.health_status == "degraded")
    ]
    state_write_eligible = _state_write_eligible(statuses, quality_failures)
    if health_write and state_write_eligible:
        assess_and_record_health(
            statuses,
            selected,
            state_dir / ".source-health.json",
            run_id=run_id,
            recorded_at=finished_at,
            profile=health_profile,
            observation_key=observation_key,
            write=True,
        )

    if state_write_eligible:
        state_ready_temporary = state_ready.with_suffix(".tmp")
        state_ready_temporary.write_text(
            f'{{"run_id":"{run_id}","manifest":"{summary_output.name}"}}\n',
            encoding="utf-8",
        )
        state_ready_temporary.replace(state_ready)
    else:
        emit_event(
            "state_update_skipped",
            run_id=run_id,
            stage="state",
            error_code="RUN_NOT_BASELINE_ELIGIBLE",
            quality_failure_count=len(quality_failures),
            degraded_sources=degraded,
        )

    emit_event(
        "artifact_bundle_published",
        run_id=run_id,
        workbook=str(output),
        manifest=str(summary_output),
        jsonl=str(jsonl_output) if jsonl_output else "",
        article_count=len(articles),
    )

    if translation.success_rate < 0.95:
        print(f"[warning] 標題翻譯成功率：{translation.success_rate:.1%}", file=sys.stderr)
    if degraded:
        print(f"[warning] 必要來源失敗：{', '.join(degraded)}", file=sys.stderr)
        if args.fail_on_degraded:
            raise SystemExit(2)
    if quality_failures:
        for failure in quality_failures:
            print(f"[quality] {failure['code']}: {failure['message']}", file=sys.stderr)
        raise SystemExit(3)


def _select_sources(
    sources: list[Source],
    countries: list[str] | None,
    source_ids: list[str] | None,
) -> list[Source]:
    country_set = set(countries or [])
    source_set = set(source_ids or [])
    unknown = source_set - {source.id for source in sources}
    if unknown:
        raise SystemExit(f"[error] 未知來源代碼：{', '.join(sorted(unknown))}")
    return [
        source
        for source in sources
        if (not country_set or source.country in country_set) and (not source_set or source.id in source_set)
    ]


def _validate_quality_options(args: argparse.Namespace) -> None:
    for name in ("min_source_success_rate", "min_critical_date_rate"):
        value = getattr(args, name, None)
        if value is not None and not 0 <= value <= 1:
            raise SystemExit(f"[error] --{name.replace('_', '-')} 必須介於 0 與 1。")
    future_limit = getattr(args, "max_unexplained_future_dates", None)
    if future_limit is not None and future_limit < 0:
        raise SystemExit("[error] --max-unexplained-future-dates 不可為負數。")


def _quality_failures(statuses: list[SourceStatus], args: argparse.Namespace) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    success_rate = sum(status.success for status in statuses) / len(statuses) if statuses else 0.0
    minimum_success = getattr(args, "min_source_success_rate", None)
    if minimum_success is not None and success_rate < minimum_success:
        failures.append(
            {
                "code": "SOURCE_SUCCESS_RATE_LOW",
                "message": f"來源成功率 {success_rate:.2%} 低於門檻 {minimum_success:.2%}。",
            }
        )

    critical = [status for status in statuses if status.critical]
    critical_date_rates = [
        status.dated_count / status.raw_count if status.raw_count else 0.0
        for status in critical
    ]
    critical_date_rate = sum(critical_date_rates) / len(critical_date_rates) if critical_date_rates else 1.0
    minimum_critical_dates = getattr(args, "min_critical_date_rate", None)
    if minimum_critical_dates is not None and critical_date_rate < minimum_critical_dates:
        failures.append(
            {
                "code": "CRITICAL_DATE_RATE_LOW",
                "message": f"必要來源平均日期完整率 {critical_date_rate:.2%} 低於門檻 {minimum_critical_dates:.2%}。",
            }
        )

    future_dates = sum(status.unexplained_future_date_count for status in statuses)
    maximum_future_dates = getattr(args, "max_unexplained_future_dates", None)
    if maximum_future_dates is not None and future_dates > maximum_future_dates:
        failures.append(
            {
                "code": "FUTURE_DATE_LIMIT_EXCEEDED",
                "message": f"未解釋未來日期 {future_dates} 筆，超過上限 {maximum_future_dates}。",
            }
        )
    return failures


def _state_write_eligible(statuses: list[SourceStatus], quality_failures: list[dict[str, str]]) -> bool:
    if quality_failures:
        return False
    return not any(
        status.critical and (not status.success or status.health_status == "degraded")
        for status in statuses
    )


def _health_observation_key(
    period: PeriodSelection | None,
    since: datetime,
    until: datetime,
    profile: dict[str, object],
) -> str:
    period_value = period.as_dict() if period else {
        "mode": "fixed",
        "period_start_utc": since.isoformat(),
        "period_end_exclusive_utc": until.isoformat(),
    }
    observation = {
        "period": period_value,
        "period_mode": profile.get("period_mode"),
        "fetch_details": profile.get("fetch_details"),
        "include_undated": profile.get("include_undated"),
        "include_unmatched": profile.get("include_unmatched"),
    }
    return health_profile_fingerprint(observation)


def _date_range(since_value: str | None, until_value: str | None, days: int) -> tuple[datetime, datetime]:
    try:
        period = resolve_period(since_value, until_value, None if since_value or until_value else days)
    except ValueError as exc:
        raise SystemExit(f"[error] {exc}") from exc
    return period.since, period.until


def _default_output(since: datetime, until: datetime) -> Path:
    start_date, end_date = _display_dates(since, until)
    filename = f"歐盟資安法制新聞_{start_date:%Y%m%d}-{end_date:%Y%m%d}.xlsx"
    return DEFAULT_OUTPUT_DIR / filename


def _display_dates(since: datetime, until: datetime) -> tuple[date, date]:
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    return since.astimezone(zone).date(), (until - timedelta(microseconds=1)).astimezone(zone).date()


def _print_sources(sources: list[Source]) -> None:
    for source in sources:
        marker = "*" if source.critical else " "
        print(f"{marker} {source.id:24} {source.country} {source.name_zh}｜{source.institution_type}")


if __name__ == "__main__":
    main()
