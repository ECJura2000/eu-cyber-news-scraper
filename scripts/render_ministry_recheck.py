"""Publish a readable disposition for every ministry in the remaining-work snapshot."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eu_cyber_news_scraper.ministry_inventory import inventory_directory, load_inventory  # noqa: E402
from eu_cyber_news_scraper.ministry_rechecks import latest_checks, load_rechecks  # noqa: E402
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry  # noqa: E402

LABELS = {"manual_verified": "已驗證手動來源", "blocked": "存取受阻",
          "parser_pending": "待解析／歸屬驗證", "needs_review": "待查證", "no_news_endpoint": "未確認新聞入口"}


def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render() -> str:
    fixtures = ROOT / "tests/fixtures"
    rounds = load_rechecks(fixtures)
    checks = latest_checks(rounds)
    baseline = rounds[0]['baseline']
    latest = rounds[-1]
    rows = {row["canonical_id"]: row
            for country in load_inventory(inventory_directory(), load_organisation_registry())
            for row in country["ministries"]}
    counts = Counter(c["result"] for c in checks.values())
    dates = sorted({a["observed_at"][:10] for c in checks.values() for a in c["attempts"]})
    lines = ["# 剩餘中央部會入口逐項複查", "",
             f"起始剩餘 {baseline['remaining_count']} 個；本批檢查 {len(checks)} 個。觀察日期：{'、'.join(dates)}。",
             f"累計新增可手動查詢 {counts['manual_verified']} 個；仍未完成新聞入口驗證 {len(checks)-counts['manual_verified']} 個。",
             f"最新第 {latest['number']} 輪涵蓋當輪起始全部 {latest['baseline']['remaining_count']} 個未完成入口。各輪紀錄保留，不覆寫過往觀察。",
             "全部檢查過不代表全部可以搜尋，也不代表正式排程已通過來源、日期、翻譯、artifact 與 state 驗收。",
             "robots、TLS、網站阻擋及需要認證的入口不繞過；未建立發布機關歸屬或日期證據的入口不登錄。", "",
             "逐項原始檢查紀錄：" + '、'.join(f"[第 {r['number']} 輪／{p.rsplit('_',1)[-1][:-5]}](tests/fixtures/{p})"
                                                  for r in rounds for p in r['reports']) + "。",
             "完整 460 筆名錄見 [MINISTRIES.md](MINISTRIES.md)。", "",
             "| 國家 | 部會 | 本批結果 | 嘗試入口數 | 後續處理 |", "| --- | --- | --- | --- | --- |"]
    for identifier in sorted(checks):
        check = checks[identifier]
        row = rows[identifier]
        if check["result"] != row["status"]:
            raise ValueError(f"Recheck/inventory status mismatch: {identifier}")
        lines.append(f"| {check['country']} | {cell(row['name_zh'])}（`{identifier}`） | "
                     f"{LABELS[check['result']]} | {len(check['attempts'])} | {cell(check['next_action'])} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT / "REMAINING_MINISTRIES.md"
    content = render()
    if args.check:
        if not output.is_file() or output.read_text() != content:
            print("Remaining-ministry document differs from canonical evidence.", file=sys.stderr)
            return 1
    else:
        output.write_text(content, encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
