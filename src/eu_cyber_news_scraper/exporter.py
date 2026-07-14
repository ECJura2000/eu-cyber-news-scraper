from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .coverage import load_coverage
from .models import Article, Source, SourceStatus
from .periods import PeriodSelection
from .translation import TranslationReport

ARTICLE_HEADERS = (
    "編號",
    "國家／區域",
    "發布機關",
    "機關屬性",
    "規範權威層級",
    "內容性質",
    "發布日期",
    "原文語言",
    "新聞標題",
    "繁體中文標題",
    "摘要",
    "觀測主題",
    "命中關鍵字",
    "關聯分數",
    "可信度",
    "官方原文",
    "其他官方連結",
    "抓取方式",
    "發現來源",
)

FORMULA_PREFIXES = ("=", "+", "-", "@")
HIGH_CONFIDENCE_FILL = PatternFill("solid", fgColor="FFC000")
MEDIUM_CONFIDENCE_FILL = PatternFill("solid", fgColor="FFF2CC")
LOW_CONFIDENCE_FILL = PatternFill("solid", fgColor="FFFCE6")
EXCEL_SUMMARY_LIMIT = 500


def safe_excel_text(value: str) -> str:
    """Prevent externally supplied text from being interpreted as a formula."""
    if value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def export_workbook(
    articles: list[Article],
    statuses: list[SourceStatus],
    sources: list[Source],
    output_path: str | Path,
) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws_all = wb.active
    ws_all.title = "全部命中新聞"
    _write_articles(ws_all, articles, highlight_matches=True)

    ws_law = wb.create_sheet("CRA_CSA_NIS2_CER")
    legal_topics = {
        "產品資安、漏洞揭露義務、SBOM",
        "資安產品認證",
        "NIS2、關鍵基礎設施保護",
        "關鍵基礎設施的實體與數位融合保護",
    }
    _write_articles(ws_law, [item for item in articles if legal_topics.intersection(item.matched_topics)])

    ws_authority = wb.create_sheet("官方規範與執法")
    _write_articles(
        ws_authority,
        [item for item in articles if item.authority_level in {"立法機關", "主管／監理機關", "法定機構／行政法人"}],
    )

    ws_research = wb.create_sheet("研究智庫與公私協力")
    _write_articles(
        ws_research,
        [item for item in articles if item.authority_level in {"公私協力／產學平台", "政策智庫", "研究／支援機構"}],
    )

    ws_status = wb.create_sheet("來源健康狀態")
    _write_statuses(ws_status, statuses)

    ws_sources = wb.create_sheet("官方來源清單")
    _write_sources(ws_sources, sources)

    ws_coverage = wb.create_sheet("議題主管機關覆蓋")
    _write_coverage(ws_coverage, sources)

    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    try:
        wb.save(temporary)
        _verify_workbook(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def write_jsonl(articles: list[Article], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for article in articles:
        lines.append(
            json.dumps(
                {
                    "source_id": article.source_id,
                    "country": article.country,
                    "source_name": article.source_name,
                    "institution_type": article.institution_type,
                    "language": article.language,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                    "title": article.title,
                    "title_zh_tw": article.title_zh_tw,
                    "summary": article.summary,
                    "url": article.url,
                    "alternate_urls": article.alternate_urls,
                    "matched_topics": article.matched_topics,
                    "matched_keywords": article.matched_keywords,
                    "relevance_score": article.relevance_score,
                    "confidence_level": article.confidence_level,
                    "fetched_via": article.fetched_via,
                    "discovered_by": article.discovered_by,
                    "authority_level": article.authority_level,
                    "content_kind": article.content_kind,
                },
                ensure_ascii=False,
            )
        )
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    return path


def _write_articles(ws, articles: list[Article], *, highlight_matches: bool = False) -> None:
    ws.append(ARTICLE_HEADERS)
    for index, article in enumerate(articles, 1):
        ws.append(
            (
                index,
                article.country,
                safe_excel_text(article.source_name),
                safe_excel_text(article.institution_type),
                article.authority_level,
                article.content_kind,
                article.published_at.date().isoformat() if article.published_at else "未辨識",
                article.language,
                safe_excel_text(article.title),
                safe_excel_text(article.title_zh_tw),
                safe_excel_text(_excel_summary(article.summary)),
                "；".join(article.matched_topics),
                "；".join(article.matched_keywords),
                article.relevance_score,
                article.confidence_level,
                article.url,
                "\n".join(article.alternate_urls),
                article.fetched_via,
                "；".join(article.discovered_by or [article.source_id]),
            )
        )
        ws.cell(ws.max_row, 16).hyperlink = article.url
        ws.cell(ws.max_row, 16).style = "Hyperlink"
        if highlight_matches and article.matched_keywords:
            fill = {
                "高": HIGH_CONFIDENCE_FILL,
                "中": MEDIUM_CONFIDENCE_FILL,
                "低": LOW_CONFIDENCE_FILL,
            }.get(article.confidence_level, LOW_CONFIDENCE_FILL)
            for cell in ws[ws.max_row]:
                cell.fill = fill
    _style_table(ws, widths=(8, 12, 28, 18, 18, 18, 14, 12, 56, 56, 72, 36, 44, 12, 12, 64, 64, 28, 32))


def _write_statuses(ws, statuses: list[SourceStatus]) -> None:
    ws.append(("來源代碼", "國家", "機關", "必要來源", "抓取狀態", "健康狀態", "抓取方式", "抓取頁數", "原始筆數", "期間內筆數", "有日期筆數", "無效未來日期", "逾時次數", "無日期比例", "唯一標題比例", "歷史中位數", "命中筆數", "秒數", "最新日期", "新鮮度落後天數", "健康警示", "抓取警示", "內容結果", "錯誤"))
    for status in statuses:
        ws.append(
            (
                status.source_id,
                status.country,
                safe_excel_text(status.source_name),
                "是" if status.critical else "否",
                status.fetch_status,
                status.health_status,
                status.fetched_via,
                status.pages_fetched,
                status.raw_count,
                status.in_range_count,
                status.dated_count,
                status.invalid_date_count,
                status.timeout_count,
                status.undated_ratio,
                status.unique_title_ratio,
                status.historical_median_count,
                status.relevant_count,
                status.duration_seconds,
                status.newest_published_at,
                status.freshness_lag_days,
                " ".join(status.health_alerts),
                safe_excel_text(status.warning),
                safe_excel_text(status.content_warning),
                safe_excel_text(status.error),
            )
        )
    _style_table(ws, widths=(22, 10, 30, 12, 14, 14, 20, 12, 12, 12, 12, 16, 12, 14, 14, 14, 12, 10, 26, 16, 52, 52, 52, 72))


def _write_sources(ws, sources: list[Source]) -> None:
    ws.append(("來源代碼", "國家", "中文名稱", "原文名稱", "機關屬性", "語言", "首頁", "新聞入口", "RSS／Atom", "必要來源", "健康基線觀察次數", "新鮮度門檻天數"))
    for source in sources:
        ws.append(
            (
                source.id,
                source.country,
                safe_excel_text(source.name_zh),
                safe_excel_text(source.name),
                safe_excel_text(source.institution_type),
                source.language,
                source.homepage,
                source.listing_url,
                "\n".join(source.feed_urls),
                "是" if source.critical else "否",
                source.observation_runs,
                source.freshness_days,
            )
        )
        for column in (7, 8):
            ws.cell(ws.max_row, column).hyperlink = ws.cell(ws.max_row, column).value
            ws.cell(ws.max_row, column).style = "Hyperlink"
    _style_table(ws, widths=(22, 10, 28, 42, 18, 10, 50, 64, 64, 12, 18, 18))


def _write_coverage(ws, sources: list[Source]) -> None:
    source_names = {source.id: source.name_zh for source in sources}
    ws.append(("觀測議題", "法域", "主管／主要執行機關與研究生態系", "本程式監測來源代碼", "監測機關", "角色／機構性質", "官方機構／職掌證據網址", "最後查核日期"))
    for row in load_coverage(sources, validate_source_ids=False):
        ws.append(
            (
                row.topic,
                row.country,
                row.authorities,
                "；".join(row.source_ids),
                "；".join(source_names.get(source_id, source_id) for source_id in row.source_ids),
                row.roles,
                "\n".join(row.evidence_urls),
                row.verified_on,
            )
        )
        ws.cell(ws.max_row, 7).hyperlink = row.evidence_urls[0]
        ws.cell(ws.max_row, 7).style = "Hyperlink"
    _style_table(ws, widths=(48, 10, 76, 62, 76, 76, 76, 16))


def _style_table(ws, widths: tuple[int, ...], max_row_height: float = 90) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws.iter_rows(min_row=2):
        estimated_lines = 1
        for cell, width in zip(row, widths):
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            text = str(cell.value or "")
            estimated_lines = max(
                estimated_lines,
                sum(max(1, math.ceil(len(part) / max(8, width))) for part in text.splitlines() or [""]),
            )
        ws.row_dimensions[row[0].row].height = min(max_row_height, max(18, estimated_lines * 15))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _verify_workbook(path: Path) -> None:
    workbook = load_workbook(path, read_only=True, data_only=True)
    required = {
        "全部命中新聞", "CRA_CSA_NIS2_CER", "官方規範與執法", "研究智庫與公私協力",
        "來源健康狀態", "官方來源清單", "議題主管機關覆蓋",
    }
    missing = required - set(workbook.sheetnames)
    if missing:
        raise ValueError(f"Workbook is missing sheets: {', '.join(sorted(missing))}")


def write_run_summary(
    output_path: str | Path,
    *,
    started_at: datetime,
    finished_at: datetime,
    since: datetime,
    until: datetime,
    articles: list[Article],
    statuses: list[SourceStatus],
    run_id: str = "",
    translation_report: TranslationReport | None = None,
    period: PeriodSelection | None = None,
    discovered_article_count: int | None = None,
) -> Path:
    workbook_path = Path(output_path).expanduser().resolve()
    summary_path = workbook_path.with_suffix(".run.json")
    translation = translation_report or TranslationReport(0, 0)
    hard_failure = any(
        item.critical and (item.fetch_status == "failed" or item.health_status == "degraded")
        for item in statuses
    )
    attention = any(
        item.fetch_status == "failed" or item.health_status in {"attention", "degraded"}
        for item in statuses
    ) or translation.success_rate < 0.95
    period_payload = period.as_dict() if period else {
        "mode": "fixed",
        "timezone": "UTC",
        "normalized_since": since.date().isoformat(),
        "normalized_until": (until - timedelta(microseconds=1)).date().isoformat(),
        "period_start_utc": since.isoformat(),
        "period_end_exclusive_utc": until.isoformat(),
    }
    discovered_count = len(articles) if discovered_article_count is None else discovered_article_count
    payload = {
        "schema_version": 4,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "period_start": since.isoformat(),
        "period_end_exclusive": until.isoformat(),
        "period": period_payload,
        "output_file": str(workbook_path),
        "article_count": len(articles),
        "discovered_article_count": discovered_count,
        "deduplicated_article_count": discovered_count - len(articles),
        "status": "degraded" if hard_failure else ("attention" if attention else "complete"),
        "translation": {
            "enabled": translation.enabled,
            "total": translation.total,
            "translated": translation.translated,
            "success_rate": round(translation.success_rate, 4),
            "failed_titles": list(translation.failed_titles),
            "providers": [item.__dict__ for item in translation.provider_stats],
        },
        "source_summary": {
            "total": len(statuses),
            "fetch_ok": sum(item.fetch_status == "ok" for item in statuses),
            "fetch_failed": sum(item.fetch_status == "failed" for item in statuses),
            "healthy": sum(item.health_status == "healthy" for item in statuses),
            "attention": sum(item.health_status == "attention" for item in statuses),
            "degraded": sum(item.health_status == "degraded" for item in statuses),
            "critical_degraded": sum(item.critical and item.health_status == "degraded" for item in statuses),
            "with_health_alerts": sum(bool(item.health_alerts) for item in statuses),
            "with_content_hits": sum(item.relevant_count > 0 for item in statuses),
            "invalid_date_count": sum(item.invalid_date_count for item in statuses),
            "timeout_count": sum(item.timeout_count for item in statuses),
        },
        "sources": [status.__dict__ for status in statuses],
    }
    _atomic_write_text(summary_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return summary_path


def _excel_summary(value: str) -> str:
    if len(value) <= EXCEL_SUMMARY_LIMIT:
        return value
    return value[: EXCEL_SUMMARY_LIMIT - 1].rstrip() + "…"


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
