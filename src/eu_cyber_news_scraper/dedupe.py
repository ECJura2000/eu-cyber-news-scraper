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


def article_title_key(article: Article) -> tuple[str, ...] | None:
    if not article.title or not article.published_at:
        return None
    return ("title-date", normalize_text(article.title), article.published_at.date().isoformat())


def dedupe_articles(articles: list[Article]) -> list[Article]:
    seen_urls: dict[str, Article] = {}
    seen_titles: dict[tuple[str, ...], Article] = {}
    result: list[Article] = []
    for article in articles:
        if not article.discovered_by:
            article.discovered_by = [article.source_id]
        url_key = canonical_url(article.url) if article.url else ""
        title_key = article_title_key(article)
        existing = seen_urls.get(url_key) if url_key else None
        if existing is None and title_key is not None:
            existing = seen_titles.get(title_key)
        if existing is not None:
            _merge_article(existing, article)
            if url_key:
                seen_urls[url_key] = existing
            if title_key is not None:
                seen_titles[title_key] = existing
            continue
        if url_key:
            seen_urls[url_key] = article
        if title_key is not None:
            seen_titles[title_key] = article
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
    alternate_urls = [*target.alternate_urls, *candidate.alternate_urls]
    if candidate.url and canonical_url(candidate.url) != canonical_url(target.url):
        alternate_urls.append(candidate.url)
    target.alternate_urls = list(dict.fromkeys(url for url in alternate_urls if url and url != target.url))
