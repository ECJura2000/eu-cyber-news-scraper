"""Render the human-readable ministry roster from canonical country JSON."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eu_cyber_news_scraper.ministry_inventory import inventory_report, load_inventory  # noqa: E402
from eu_cyber_news_scraper.organisation_registry import OrganisationRegistry, _load_directory  # noqa: E402

LABELS = {
    "existing_source": "既有來源（未重新宣稱合格）", "manual_verified": "新增手動查詢已驗證",
    "parser_pending": "待解析驗證", "blocked": "網站存取受阻",
    "no_news_endpoint": "未找到獨立新聞入口", "needs_review": "待查證入口",
    "user_excluded": "依使用者指示排除候選入口（非網站失效）",
}


def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render() -> str:
    modules, errors = _load_directory(ROOT / "organisation_registry", False)
    registry = OrganisationRegistry(tuple(modules), tuple(errors), "canonical-inventory-docs")
    records = load_inventory(ROOT / "ministry_inventory", registry)
    report = inventory_report(records)
    lines = ["# 歐盟中央部會追蹤名錄", "",
        f"共 {report['country_count']} 國、{report['ministry_count']} 個中央部會與政府首長辦公室。",
        "名錄以逐國官方名單為依據。已列入名錄不代表新聞可抓取；既有來源、已驗證新增來源與待驗證入口分別標示。",
        f"已登錄新聞查詢：{report['registered_ministries']} 個（新增手動驗證 {report['new_manual_verified_ministries']} 個）；尚未完成新聞入口驗證：{report['unresolved_ministries']} 個。這不是正式排程驗收結果。",
        f"其中使用者排除 {report['user_excluded_ministries']} 個；仍待處理 {report['pending_ministries']} 個。排除不代表網站不存在，也不計入可搜尋來源。",
        "", "```console", "python -m eu_cyber_news_scraper ministries --country AT",
        "python -m eu_cyber_news_scraper ministries --check", "```", "",
        "新增來源僅供手動查詢，正式每週來源與品質門檻維持原設定。", ""]
    for record in records:
        lines.extend([f"## {record['country']}", "",
            f"查核日：{record['reviewed_on']}；{len(record['ministries'])} 個部會；官方名錄盤點完整：{'是' if record['roster_complete'] else '否'}。",
            "", "官方名錄：" + "、".join(f"[來源 {i+1}]({url})" for i, url in enumerate(record['official_roster_urls'])), ""])
        lines.extend(record["limitations"])
        lines.extend(["", "| 部會／原文名稱 | 新聞入口 | 查詢與驗證狀態 |", "| --- | --- | --- |"])
        for row in record["ministries"]:
            name = cell(row["name_zh"] + "／" + row["name_local"])
            absent = "已移除候選新聞入口" if row['status'] == 'user_excluded' else "未確認新聞入口"
            url = f"[官方入口]({row['news_url']})" if row["news_url"] else absent
            sources = ", ".join(f"`{value}`" for value in row["source_ids"])
            status = cell(LABELS[row["status"]] + ("；"+sources if sources else "") + "；"+row["reason"])
            lines.append(f"| {name} | {url} | {status} |")
        lines.append("")
    return "\n".join(lines).rstrip()+"\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "MINISTRIES.md")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != text:
            print("Ministry document differs from canonical inventory; regenerate explicitly.", file=sys.stderr)
            return 1
        return 0
    args.output.write_text(text, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
