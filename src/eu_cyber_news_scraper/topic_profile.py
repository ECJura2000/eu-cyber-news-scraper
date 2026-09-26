"""Versioned user topic overlay; legacy matching remains the default baseline."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import Article
from .topics import OBSERVATION_TOPICS, confidence_level, normalize_text

SUPPORTED_LANGUAGES = frozenset({"en", "fr", "de", "es", "pt", "it", "pl", "da", "no", "sv", "et", "lv", "lt", "*"})


@dataclass(frozen=True)
class Profile:
    topics: tuple[dict[str, Any], ...]
    schedule: dict[str, Any]
    manual: dict[str, Any]
    hash: str

    @property
    def names(self) -> frozenset[str]:
        return frozenset(row["name"] for row in self.topics if row["enabled"])


def load_profile(path: str | Path | None = None) -> Profile:
    try:
        raw = Path(path).read_bytes() if path else files(__package__).joinpath("topic_profile.json").read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2} or not isinstance(payload.get("topics"), list):
            raise ValueError("schema_version 必須為 1 或 2，topics 必須為陣列")
        if payload.get("schema_version") == 2:
            mode = payload.get("mode", "replace")
            if mode not in {"replace", "merge"}:
                raise ValueError("mode 必須為 replace 或 merge")
            removed = payload.get("remove_topics", [])
            if not isinstance(removed, list) or any(not isinstance(name, str) or not name.strip() for name in removed) or len(set(removed)) != len(removed):
                raise ValueError("remove_topics 必須是不重複的主題名稱陣列")
            submitted_names = [row.get("name") for row in payload["topics"] if isinstance(row, dict)]
            if len(submitted_names) != len(set(submitted_names)):
                raise ValueError("同一 JSON 內不得重複主題")
            if mode == "replace" and removed:
                raise ValueError("replace 模式不可使用 remove_topics；直接從 topics 移除即可")
            if mode == "merge":
                base = load_profile()
                inherited = {row["name"]: row for row in base.topics}
                for name in removed:
                    if name not in inherited and name not in {row.get("name") for row in payload["topics"] if isinstance(row, dict)}:
                        raise ValueError(f"無法刪除不存在的主題：{name}")
                    inherited.pop(name, None)
                for row in payload["topics"]:
                    if isinstance(row, dict) and row.get("name") in removed:
                        raise ValueError("同一主題不可同時移除與增補")
                    if isinstance(row, dict) and isinstance(row.get("name"), str):
                        inherited[row["name"]] = row
                payload["topics"] = list(inherited.values())
                payload["schedule"] = {**base.schedule, **payload.get("schedule", {})}
                payload["manual"] = {**base.manual, **payload.get("manual", {})}
        elif payload.get("mode") is not None or payload.get("remove_topics") is not None:
            raise ValueError("mode/remove_topics 需要 schema_version 2")
        names: set[str] = set()
        for row in payload["topics"]:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
                raise ValueError("每個主題都需要非空 name")
            if row["name"] in names:
                raise ValueError(f"重複主題：{row['name']}")
            names.add(row["name"])
            if not isinstance(row.get("enabled", True), bool):
                raise ValueError(f"主題 {row['name']} 的 enabled 必須為布林值")
            for field in ("keywords", "synonyms", "penalties", "excludes"):
                value = row.get(field, [])
                valid = isinstance(value, list) and all(_valid_term(item, weighted=field == "keywords") for item in value)
                if not valid:
                    raise ValueError(f"主題 {row['name']} 的 {field} 格式不正確")
            if row.get("enabled", True) and row.get("inherit_legacy", True) is False and not row.get("keywords") and not row.get("synonyms"):
                raise ValueError(f"主題 {row['name']} 缺少正向詞")
            legacy_name = row.get("legacy_name", row["name"])
            if not isinstance(legacy_name, str):
                raise ValueError("legacy_name 必須是字串")
            if legacy_name not in OBSERVATION_TOPICS and not row.get("keywords") and not row.get("synonyms"):
                raise ValueError(f"新主題 {row['name']} 必須有 keywords 或 synonyms")
            if not isinstance(row.get("responsibility_owner", ""), str):
                raise ValueError("responsibility_owner 必須是字串")
        for section in ("schedule", "manual"):
            value = payload.get(section, {})
            if not isinstance(value, dict) or not isinstance(value.get("days", 14), int) or value.get("days", 14) < 1:
                raise ValueError(f"{section}.days 必須是正整數")
        if not any(row.get("enabled", True) for row in payload["topics"]):
            raise ValueError("至少需要一個啟用主題")
        digest = sha256(json.dumps({key: payload.get(key) for key in ("topics", "schedule", "manual")}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return Profile(tuple({"enabled": True, **row} for row in payload["topics"]), payload.get("schedule", {}), payload.get("manual", {}), digest)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"主題 JSON 無效：{exc}") from exc


def _valid_term(item: Any, *, weighted: bool) -> bool:
    if isinstance(item, str):
        return not weighted and bool(item.strip())
    if not isinstance(item, dict) or not isinstance(item.get("term"), str) or not item["term"].strip():
        return False
    if item.get("language", "*") not in SUPPORTED_LANGUAGES:
        return False
    if "concept" in item and (not isinstance(item["concept"], str) or not item["concept"].strip()):
        return False
    if weighted:
        return isinstance(item.get("weight"), (int, float)) and not isinstance(item["weight"], bool) and 0 < item["weight"] <= 100
    return True


def _term(item: str | dict[str, Any]) -> str:
    return item if isinstance(item, str) else str(item["term"])


def _eligible(item: str | dict[str, Any], language: str) -> bool:
    return isinstance(item, str) or item.get("language", "*") in {"*", language}


@lru_cache(maxsize=8192)
def _pattern(term: str) -> re.Pattern[str]:
    normalized = normalize_text(term)
    return re.compile(rf"(?<!\w){re.escape(normalized)}(?!\w)")


def _matches(text: str, item: str | dict[str, Any], language: str) -> bool:
    return _eligible(item, language) and bool(_pattern(_term(item)).search(text))


def apply_profile(article: Article, profile: Profile) -> Article:
    text = normalize_text(f"{article.title} {article.summary}")
    legacy = set(article.matched_topics)
    matches: list[str] = []
    keywords: list[str] = []
    scores: list[float] = []
    kept_legacy = False
    for row in profile.topics:
        if not row["enabled"]:
            continue
        name = row["name"]
        original = row.get("legacy_name", name)
        inherited = row.get("inherit_legacy", True) and original in OBSERVATION_TOPICS and original in legacy
        if any(_matches(text, term, article.language) for term in row.get("excludes", [])):
            continue
        concepts: dict[str, float] = {}
        hit_terms: list[str] = []
        for item in row.get("keywords", []):
            if _matches(text, item, article.language):
                key = item.get("concept", item["term"])
                concepts[key] = max(concepts.get(key, 0), float(item["weight"]))
                hit_terms.append(item["term"])
        for item in row.get("synonyms", []):
            if _matches(text, item, article.language):
                key = item.get("concept", _term(item)) if isinstance(item, dict) else item
                concepts[key] = max(concepts.get(key, 0), 1)
                hit_terms.append(_term(item))
        score = sum(concepts.values())
        score -= sum(1 for term in row.get("penalties", []) if _matches(text, term, article.language))
        if inherited:
            score += 1
        if score > 0:
            matches.append(name)
            scores.append(score)
            kept_legacy = kept_legacy or bool(inherited)
            keywords.extend(hit_terms)
    article.matched_topics = matches
    article.matched_keywords = list(dict.fromkeys([*article.matched_keywords, *keywords])) if matches else []
    article.relevance_score = int(max(1 if scores else 0, *scores, article.relevance_score if kept_legacy else 0))
    article.confidence_level = confidence_level(article.relevance_score)
    return article
