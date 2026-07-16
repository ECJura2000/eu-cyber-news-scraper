from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, cast
from uuid import uuid4

from googletrans import Translator as GoogleTranslator
from opencc import OpenCC

from .config import DEFAULT_TRANSLATION_WORKERS
from .models import Article
from .state_lock import state_lock

_CACHE_LOCK = Lock()
_OPENCC = OpenCC("s2twp")
_TAIWAN_TERMS = {
    "數字產品": "數位產品",
    "數字身分": "數位身分",
}


@dataclass(frozen=True)
class TranslationReport:
    total: int
    translated: int
    failed_titles: tuple[str, ...] = ()
    provider_stats: tuple[ProviderTranslationStats, ...] = ()
    enabled: bool = True
    cache_hits: int = 0

    @property
    def success_rate(self) -> float:
        if not self.enabled:
            return 1.0
        return 1.0 if self.total == 0 else self.translated / self.total


@dataclass(frozen=True)
class ProviderTranslationStats:
    name: str
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    duration_seconds: float
    disabled: bool


class TranslationResults(dict[str, str]):
    provider_stats: tuple[ProviderTranslationStats, ...] = ()
    providers_by_title: dict[str, str]


class _ProviderTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows = {
            name: {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0, "duration": 0.0, "disabled": False}
            for name in ("googletrans", "translate", "translatepy")
        }
        self.providers_by_title: dict[str, str] = {}

    def available(self, name: str) -> bool:
        with self._lock:
            row = self._rows[name]
            if row["disabled"]:
                row["skipped"] += 1
                return False
            return True

    def record(self, name: str, *, title: str, succeeded: bool, duration: float) -> None:
        with self._lock:
            row = self._rows[name]
            row["attempted"] += 1
            row["duration"] += duration
            row["succeeded" if succeeded else "failed"] += 1
            if succeeded:
                self.providers_by_title[title] = name
            elif row["failed"] >= _translation_circuit_failures() and row["succeeded"] == 0:
                row["disabled"] = True

    def report(self) -> tuple[ProviderTranslationStats, ...]:
        with self._lock:
            return tuple(
                ProviderTranslationStats(
                    name=name,
                    attempted=int(row["attempted"]),
                    succeeded=int(row["succeeded"]),
                    failed=int(row["failed"]),
                    skipped=int(row["skipped"]),
                    duration_seconds=round(float(row["duration"]), 3),
                    disabled=bool(row["disabled"]),
                )
                for name, row in self._rows.items()
            )


def translation_cache_path() -> Path:
    configured = os.environ.get("EU_CYBER_NEWS_TRANSLATION_CACHE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "eu_cyber_news_scraper" / "translations.json"


def load_translations() -> dict[str, str]:
    path = translation_cache_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("translations", payload)
    if not isinstance(rows, dict):
        return {}
    result = {}
    for source, target in rows.items():
        value = target.get("text") if isinstance(target, dict) else target
        if source and value:
            result[str(source)] = str(value)
    return result


def save_translations(translations: dict[str, str], providers: dict[str, str] | None = None) -> None:
    if not translations:
        return
    path = translation_cache_path()
    with _CACHE_LOCK:
        with state_lock(path, f"translation-{uuid4().hex}"):
            now = datetime.now(timezone.utc).isoformat()
            existing_payload = _load_cache_payload(path)
            rows = existing_payload.get("translations", {})
            if not isinstance(rows, dict):
                rows = {}
            providers = providers or {}
            for source, target in translations.items():
                prior = rows.get(source, {})
                created_at = prior.get("created_at", prior.get("cached_at", now)) if isinstance(prior, dict) else now
                rows[source] = {
                    "text": target,
                    "provider": providers.get(source, "legacy-cache"),
                    "created_at": created_at,
                    "last_accessed_at": now,
                }
            ordered = sorted(
                rows.items(),
                key=lambda item: str(item[1].get("last_accessed_at", item[1].get("created_at", "")))
                if isinstance(item[1], dict)
                else "",
                reverse=True,
            )[:10000]
            payload = {"schema_version": 3, "translations": dict(ordered)}
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)


def translate_article_titles(articles: list[Article]) -> TranslationReport:
    title_languages = list(dict.fromkeys((article.title, article.language or "auto") for article in articles if article.title))
    if not title_languages:
        return TranslationReport(0, 0)
    cached = load_translations()
    translations: dict[tuple[str, str], str] = {}
    cache_hits = 0
    for title, language in title_languages:
        key = _cache_key(title, language)
        value = cached.get(key, cached.get(title, ""))
        if _is_translated(title, value):
            translations[(title, language)] = value
            cache_hits += 1
    missing = [(title, language) for title, language in title_languages if (title, language) not in translations]
    if missing:
        missing_titles = list(dict.fromkeys(title for title, _language in missing))
        batch = _translate_titles(missing_titles)
        translated = {
            (title, language): batch[title]
            for title, language in missing
            if title in batch and _is_translated(title, batch[title])
        }
        translations.update(translated)
        cache_rows = {_cache_key(title, language): value for (title, language), value in translated.items()}
        cache_providers = {
            _cache_key(title, language): getattr(batch, "providers_by_title", {}).get(title, "unknown")
            for title, language in translated
        }
        save_translations(cache_rows, cache_providers)
    else:
        batch = TranslationResults()

    failed = [
        title
        for title, language in title_languages
        if not _is_translated(title, translations.get((title, language), ""))
    ]
    for article in articles:
        # Preserve a usable workbook even when the external translation service
        # is temporarily unavailable. The run summary records every fallback.
        article.title_zh_tw = translations.get((article.title, article.language or "auto"), article.title)
    return TranslationReport(
        len(title_languages),
        len(title_languages) - len(failed),
        tuple(failed),
        getattr(batch, "provider_stats", ()),
        cache_hits=cache_hits,
    )


def skip_article_title_translation(articles: list[Article]) -> TranslationReport:
    titles = tuple(dict.fromkeys(article.title for article in articles if article.title))
    for article in articles:
        article.title_zh_tw = article.title
    return TranslationReport(len(titles), 0, titles, enabled=False)


def _translate_titles(titles: list[str]) -> TranslationResults:
    tracker = _ProviderTracker()

    translations = TranslationResults()
    for title in titles:
        value = _translate_with_fallback(title, tracker)
        if _is_translated(title, value):
            translations[title] = value
    translations.provider_stats = tracker.report()
    translations.providers_by_title = tracker.providers_by_title
    return translations


def _translate_with_fallback(title: str, tracker: _ProviderTracker | None = None) -> str:
    providers = (
        ("googletrans", _translate_googletrans),
        ("translate", _translate_translate_module),
        ("translatepy", _translate_translatepy),
    )
    for name, provider in providers:
        if tracker and not tracker.available(name):
            continue
        for attempt in range(2):
            started = time.monotonic()
            try:
                value = _to_taiwan_traditional(_call_provider_with_timeout(provider, title) or "")
            except Exception:
                value = ""
            succeeded = _is_translated(title, value)
            if tracker:
                tracker.record(name, title=title, succeeded=succeeded, duration=time.monotonic() - started)
            if succeeded:
                return value
            if attempt == 0:
                time.sleep(0.2)
    return ""


def _translate_googletrans(title: str) -> str:
    translated = asyncio.run(GoogleTranslator(timeout=_translation_timeout()).translate(title, dest="zh-tw"))
    return str(translated.text or "")


def _translate_translate_module(title: str) -> str:
    from translate import Translator

    return Translator(from_lang="autodetect", to_lang="zh-TW", timeout=_translation_timeout()).translate(title) or ""


def _translate_translatepy(title: str) -> str:
    from translatepy import Translator

    return str(Translator().translate(title, "zh", "auto").result or "")


def _call_provider_with_timeout(provider: Callable[[str], str], title: str) -> str:
    method = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    context: Any = mp.get_context(method)
    result = context.Queue(maxsize=1)
    process = context.Process(target=_provider_process_target, args=(provider, title, result))
    process.start()
    process.join(_translation_timeout())
    try:
        if process.is_alive():
            process.terminate()
            process.join(1)
            return ""
        return str(result.get(timeout=0.2) or "")
    except Exception:
        return ""
    finally:
        if process.is_alive():
            process.kill()
            process.join(1)
        result.close()
        result.join_thread()


def _provider_process_target(provider: Callable[[str], str], title: str, result: Any) -> None:
    try:
        result.put(str(provider(title) or ""))
    except Exception:
        result.put("")


def _cache_key(title: str, language: str) -> str:
    return f"{language.casefold()}\0{title}"


def _load_cache_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _translation_workers() -> int:
    configured = os.environ.get("EU_CYBER_NEWS_TRANSLATION_WORKERS")
    if not configured:
        return DEFAULT_TRANSLATION_WORKERS
    try:
        return max(1, int(configured))
    except ValueError:
        return DEFAULT_TRANSLATION_WORKERS


def _translation_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("EU_CYBER_NEWS_TRANSLATION_TIMEOUT", "10")))
    except ValueError:
        return 10.0


def _translation_circuit_failures() -> int:
    try:
        return max(1, int(os.environ.get("EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES", "3")))
    except ValueError:
        return 3


def _is_translated(source: str, target: str) -> bool:
    return (
        bool(target.strip())
        and _normalize(source) != _normalize(target)
        and bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", target))
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _to_taiwan_traditional(value: str) -> str:
    converted = _OPENCC.convert(value)
    for source, target in _TAIWAN_TERMS.items():
        converted = converted.replace(source, target)
    return cast(str, converted)
