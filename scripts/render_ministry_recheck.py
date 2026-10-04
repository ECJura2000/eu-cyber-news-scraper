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
          "parser_pending": "待解析／歸屬驗證", "needs_review": "待查證", "no_news_endpoint": "未確認新聞入口",
          "user_excluded": "使用者排除（不宣稱網站失效）"}


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
             f"起始剩餘 {baseline['remaining_count']} 個；歷次累計檢查 {len(checks)} 個。觀察日期：{'、'.join(dates)}。",
             f"累計新增可手動查詢 {counts['manual_verified']} 個；仍未完成新聞入口驗證 {len(checks)-counts['manual_verified']} 個。",
             f"其中依使用者指示排除 {counts['user_excluded']} 個；仍待處理 {len(checks)-counts['manual_verified']-counts['user_excluded']} 個。被排除的部會不計入可搜尋來源。",
             f"最新第 {latest['number']} 輪涵蓋當輪起始全部 {latest['baseline']['remaining_count']} 個未完成入口。各輪紀錄保留，不覆寫過往觀察。",
             "全部檢查過不代表全部可以搜尋，也不代表正式排程已通過來源、日期、翻譯、artifact 與 state 驗收。",
             "robots、TLS、網站阻擋及需要認證的入口不繞過；未建立發布機關歸屬或日期證據的入口不登錄。", "",
             "逐項原始檢查紀錄：" + '、'.join(f"[第 {r['number']} 輪／{p.rsplit('_',1)[-1][:-5]}](tests/fixtures/{p})"
                                                  for r in rounds for p in r['reports']) + "。",
             "完整 460 筆名錄見 [MINISTRIES.md](MINISTRIES.md)。2026-10-04 後續清理另見 [SOURCE_CLEANUP.md](SOURCE_CLEANUP.md)；上方累計數是歷次觀察，不覆寫歷史成功，目前狀態以下表與部會名錄為準。", "",
             "維基百科只用於尋找官方網址線索；條目可能過時，不作為新聞發布機關、日期或可抓取性的合格證據。第五輪確認失效／非新聞的候選網址才清理；第六輪依使用者指示，當地語言重查仍未通過者移除候選新聞入口，標示為使用者排除而非網站失效，部會官網與歷史證據保留。", "",
             "百科短摘錄的來源署名與授權見 [WIKIPEDIA_ATTRIBUTION.md](tests/fixtures/WIKIPEDIA_ATTRIBUTION.md)。", "",
             "| 國家 | 部會 | 最新結果 | 嘗試入口數 | 維基百科線索 | 後續處理 |", "| --- | --- | --- | --- | --- | --- |"]
    for identifier in sorted(checks):
        check = checks[identifier]
        row = rows[identifier]
        removed_after_recheck = row.get('user_exclusion', {}).get('policy') == 'exclude_unreadable_registered_source'
        if check["result"] != row["status"] and not removed_after_recheck:
            raise ValueError(f"Recheck/inventory status mismatch: {identifier}")
        review = check.get('wikipedia', {})
        pages = review.get('pages', [])
        wiki = '、'.join(f"[條目 {i+1}]({page['url']})" for i, page in enumerate(pages))
        if not wiki:
            wiki = {'not_found': '未找到可匹配條目', 'ambiguous': '條目／機關歸屬待匹配',
                    'blocked': '百科查詢受阻'}.get(review.get('status'), '先前已完成官網驗證')
        cleanup = f"已清理 {len(check['removed_news_urls'])} 個候選網址；" if check.get('removed_news_urls') else ''
        if check['result'] == 'user_excluded':
            cleanup += '已依使用者指示移除候選新聞入口；'
        if removed_after_recheck:
            cleanup += '後續抓取複查失敗，已移除；詳見 SOURCE_CLEANUP.md。'
        lines.append(f"| {check['country']} | {cell(row['name_zh'])}（`{identifier}`） | "
                     f"{LABELS[row['status']]} | {len(check['attempts'])} | {wiki} | {cell(cleanup+check['next_action'])} |")
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
