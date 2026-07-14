from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Article
from .topics import normalize_text

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_KEYS
    ]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, urlencode(query), ""))


def article_key(article: Article) -> tuple[str, ...]:
    if article.url:
        return ("url", canonical_url(article.url))
    date_text = article.published_at.date().isoformat() if article.published_at else ""
    return ("title", normalize_text(article.title), date_text)


def dedupe_articles(articles: list[Article]) -> list[Article]:
    seen: dict[tuple[str, ...], Article] = {}
    result: list[Article] = []
    for article in articles:
        if not article.discovered_by:
            article.discovered_by = [article.source_id]
        key = article_key(article)
        existing = seen.get(key)
        if existing is not None:
            _merge_article(existing, article)
            continue
        seen[key] = article
        result.append(article)
    return result


def _merge_article(target: Article, candidate: Article) -> None:
    """Preserve the best metadata and every source that discovered a duplicate."""
    if not target.published_at and candidate.published_at:
        target.published_at = candidate.published_at
    if len(candidate.title) > len(target.title):
        target.title = candidate.title
    if len(candidate.summary) > len(target.summary):
        target.summary = candidate.summary
    if candidate.relevance_score > target.relevance_score:
        target.relevance_score = candidate.relevance_score
    target.matched_topics = list(dict.fromkeys([*target.matched_topics, *candidate.matched_topics]))
    target.matched_keywords = list(dict.fromkeys([*target.matched_keywords, *candidate.matched_keywords]))
    target.discovered_by = list(
        dict.fromkeys([*target.discovered_by, *(candidate.discovered_by or [candidate.source_id])])
    )
