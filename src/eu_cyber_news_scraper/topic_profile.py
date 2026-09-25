"""Versioned user topic overlay; legacy matching remains the default baseline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import Article
from .topics import OBSERVATION_TOPICS, _contains, confidence_level, normalize_text


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
        payload = json.loads(raw)
        if payload.get("schema_version") != 1 or not isinstance(payload.get("topics"), list):
            raise ValueError("schema_version 必須為 1，topics 必須為陣列")
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
                if field == "keywords":
                    valid = isinstance(value, list) and all(
                        isinstance(item, dict) and isinstance(item.get("term"), str)
                        and isinstance(item.get("weight"), (int, float)) and item["weight"] > 0
                        for item in value
                    )
                else:
                    valid = isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
                if not valid:
                    raise ValueError(f"主題 {row['name']} 的 {field} 格式不正確")
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
        digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return Profile(tuple({"enabled": True, **row} for row in payload["topics"]), payload.get("schedule", {}), payload.get("manual", {}), digest)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"主題 JSON 無效：{exc}") from exc


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
        if any(_contains(text, term) for term in row.get("excludes", [])):
            continue
        score = sum(item["weight"] for item in row.get("keywords", []) if _contains(text, item["term"]))
        score += sum(1 for term in row.get("synonyms", []) if _contains(text, term))
        score -= sum(1 for term in row.get("penalties", []) if _contains(text, term))
        if inherited:
            score += 1
        if score > 0:
            matches.append(name)
            scores.append(score)
            kept_legacy = kept_legacy or bool(inherited)
            keywords.extend(item["term"] for item in row.get("keywords", []) if _contains(text, item["term"]))
            keywords.extend(term for term in row.get("synonyms", []) if _contains(text, term))
    article.matched_topics = matches
    article.matched_keywords = list(dict.fromkeys([*article.matched_keywords, *keywords])) if matches else []
    article.relevance_score = int(max([*scores, article.relevance_score if kept_legacy else 0], default=0))
    article.confidence_level = confidence_level(article.relevance_score)
    return article
