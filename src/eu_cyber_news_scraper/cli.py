from __future__ import annotations

import argparse
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
from .exporter import export_workbook, write_jsonl, write_run_summary
from .health import assess_and_record_health
from .http import HttpClient
from .models import SourceResult, SourceStatus
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
    parser.add_argument("--output", help="Excel 輸出路徑。")
    parser.add_argument("--jsonl", action="store_true", help="另輸出同名 JSONL。")
    parser.add_argument("--config", help="自訂 sources.toml 路徑。")
    parser.add_argument("--list-sources", action="store_true", help="列出來源後結束。")
    parser.add_argument("--fail-on-degraded", action="store_true", help="必要來源失敗時回傳非零結束碼。")
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
    args,
    selected,
    since,
    until,
    output: Path,
    run_id: str,
    *,
    period: PeriodSelection | None = None,
) -> None:
    started_at = datetime.now(timezone.utc)
    client = HttpClient(timeout=max(1, args.timeout))
    results = []
    worker_count = max(1, min(args.workers, len(selected)))

    display_since, display_until = _display_dates(since, until)
    print(f"期間：{display_since} 至 {display_until}；來源：{len(selected)}；run_id：{run_id}")
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(
                scrape_source,
                source,
                client,
                since=since,
                until=until,
                include_unmatched=args.all,
                include_undated=args.include_undated,
                fetch_details=not args.no_detail,
                source_budget_seconds=max(1, getattr(args, "source_budget", DEFAULT_SOURCE_BUDGET)),
                observed_at=started_at,
            ): source
            for source in selected
        }
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # defensive boundary around every source job
                print(f"[failed] {source.id}: {type(exc).__name__}: {exc}", file=sys.stderr)
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
                    ),
                )
            results.append(result)
            label = "ok" if result.status.success else "failed"
            print(f"[{label}] {source.id}: 原始 {result.status.raw_count}，命中 {result.status.relevant_count}")

    order = {source.id: index for index, source in enumerate(selected)}
    results.sort(key=lambda result: order[result.source.id])
    discovered_articles = [article for result in results for article in result.articles]
    articles = dedupe_articles(discovered_articles)
    if args.topic:
        wanted = {TOPIC_ALIASES[value] for value in args.topic}
        articles = [article for article in articles if wanted.intersection(article.matched_topics)]
    articles.sort(key=lambda item: item.published_at or since, reverse=True)
    state_dir_value = getattr(args, "state_dir", None)
    state_dir = Path(state_dir_value).expanduser() if state_dir_value else output.parent
    state_dir.mkdir(parents=True, exist_ok=True)
    if state_dir_value and "EU_CYBER_NEWS_TRANSLATION_CACHE" not in os.environ:
        os.environ["EU_CYBER_NEWS_TRANSLATION_CACHE"] = str(state_dir / "translations.json")
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
    statuses = assess_and_record_health(
        statuses,
        selected,
        state_dir / ".source-health.json",
        run_id=run_id,
        recorded_at=datetime.now(timezone.utc),
    )

    workbook = export_workbook(articles, statuses, selected, output)
    finished_at = datetime.now(timezone.utc)
    summary = write_run_summary(
        workbook,
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
    )
    print(f"Excel：{workbook}")
    print(f"執行摘要：{summary}")
    if args.jsonl:
        print(f"JSONL：{write_jsonl(articles, workbook.with_suffix('.jsonl'))}")

    degraded = [
        status.source_id
        for status in statuses
        if status.critical and (not status.success or status.health_status == "degraded")
    ]
    if translation.success_rate < 0.95:
        print(f"[warning] 標題翻譯成功率：{translation.success_rate:.1%}", file=sys.stderr)
    if degraded:
        print(f"[warning] 必要來源失敗：{', '.join(degraded)}", file=sys.stderr)
        if args.fail_on_degraded:
            raise SystemExit(2)


def _select_sources(sources, countries, source_ids):
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


def _print_sources(sources) -> None:
    for source in sources:
        marker = "*" if source.critical else " "
        print(f"{marker} {source.id:24} {source.country} {source.name_zh}｜{source.institution_type}")


if __name__ == "__main__":
    main()
