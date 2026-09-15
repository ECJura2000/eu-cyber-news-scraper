from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "src/eu_cyber_news_scraper/sources.toml"
COVERAGE_PATH = ROOT / "src/eu_cyber_news_scraper/authority_coverage.toml"
OUTPUT_DIR = ROOT / "organisation_registry"
SPECIAL_TOPICS = {
    "eu_parliament_press": [
        "AI法、模型評估、演算法問責、自動化決策、AI與著作權",
        "平台責任、內容審查、推薦演算法",
        "NIS2、關鍵基礎設施保護",
        "產品資安、漏洞揭露義務、SBOM",
    ],
    "fr_cybermalveillance": [
        "NIS2、關鍵基礎設施保護",
        "產品資安、漏洞揭露義務、SBOM",
        "供應鏈安全",
    ],
    "fr_arcep": [
        "跨境資料流通、資料主權、資料開放與再利用",
        "平台責任、內容審查、推薦演算法",
        "競爭規範面向（平台責任的市場結構面）",
        "NIS2、關鍵基礎設施保護",
    ],
}


def main() -> None:
    sources = tomllib.loads(SOURCES_PATH.read_text(encoding="utf-8"))["sources"]
    coverage = tomllib.loads(COVERAGE_PATH.read_text(encoding="utf-8"))["topics"]
    topics_by_source: dict[str, list[str]] = {}
    owners_by_source: dict[str, dict[str, str]] = {}
    for topic in coverage:
        topic_name = topic["name"]
        for country in ("EU", "FR", "DE", "IE"):
            owner = topic[country]["authorities"]
            for source_id in topic[country]["source_ids"]:
                topics_by_source.setdefault(source_id, []).append(topic_name)
                owners_by_source.setdefault(source_id, {})[topic_name] = owner
    topics_by_source.update(SPECIAL_TOPICS)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source in sources:
        source_id = source["id"]
        topics = list(dict.fromkeys(topics_by_source[source_id]))
        payload = {
            "schema_version": 2,
            "module_version": "2026-09-15.2",
            "canonical_id": source_id,
            "names": {
                "zh": source["name_zh"],
                "en": source["name"],
                "short": source_id,
                "publisher_aliases": [],
            },
            "sources": [source],
            "filter": {
                "topics": topics,
                "include_patterns": source.get("include_patterns", []),
                "exclude_patterns": source.get("exclude_patterns", []),
            },
            "health": {
                "required": bool(source.get("critical", False)),
                "minimum_items": 1,
                "maximum_age_days": int(source.get("freshness_days", 90)),
            },
            "history": {
                "effective_from": "2026-09-15",
                "predecessors": [],
                "successors": [],
                "transitional_sources": [],
            },
            "responsibility_by_topic": owners_by_source.get(source_id, {}),
        }
        path = OUTPUT_DIR / f"{source_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
