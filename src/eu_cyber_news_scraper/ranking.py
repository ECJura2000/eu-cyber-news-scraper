from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .models import Article
from .organisation_registry import OrganisationRegistry
from .topics import OBSERVATION_TOPICS, TOPIC_RULES, _output_topics, normalize_text

BM25_K1 = 1.2
BM25_B = 0.75
BM25_MINIMUM_SCORE = 0.15
TITLE_WEIGHT = 2
SUMMARY_WEIGHT = 1
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "de", "des", "die", "der", "das",
        "en", "et", "for", "from", "für", "in", "is", "la", "le", "les", "of", "on", "or",
        "the", "to", "und", "von", "with", "zu",
    }
)
TOKEN_PATTERN = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)


def rank_articles(
    articles: list[Article],
    registry: OrganisationRegistry,
    *,
    minimum_score: float = BM25_MINIMUM_SCORE,
) -> list[Article]:
    if not articles:
        return articles
    documents = [_document_tokens(article) for article in articles]
    document_frequency: Counter[str] = Counter()
    for tokens in documents:
        document_frequency.update(set(tokens))
    average_length = sum(len(tokens) for tokens in documents) / len(documents)
    queries = _topic_queries()

    for article, tokens in zip(articles, documents, strict=True):
        module = registry.module_for_source(article.source_id)
        allowed = module.topics if module else frozenset(OBSERVATION_TOPICS)
        article.matched_topics = [topic for topic in article.matched_topics if topic in allowed]
        article.matched_synonyms = list(dict.fromkeys(article.matched_keywords))
        article.boolean_score = article.relevance_score if article.matched_topics else 0
        article.publisher_organisation = article.source_name
        scores: dict[str, float] = {}
        for topic in article.matched_topics:
            score = _bm25_score(
                tokens,
                queries[topic],
                document_frequency,
                len(documents),
                average_length,
            )
            scores[topic] = round(score, 4)
        article.bm25_topic_scores = scores
        article.bm25_score = round(max(scores.values(), default=0.0), 4)
        if module:
            article.responsibility_owner = list(
                dict.fromkeys(
                    owner
                    for topic in article.matched_topics
                    if (owner := module.responsibility_owner(topic))
                )
            )
        if article.bm25_score < minimum_score:
            article.confidence_level = "未命中"
    return articles


def is_hybrid_relevant(article: Article, *, minimum_score: float = BM25_MINIMUM_SCORE) -> bool:
    return article.boolean_score > 0 and article.bm25_score >= minimum_score


def _document_tokens(article: Article) -> list[str]:
    return [*_tokens(article.title)] * TITLE_WEIGHT + _tokens(article.summary) * SUMMARY_WEIGHT


def _tokens(value: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(normalize_text(value)) if token not in STOPWORDS]


def _topic_queries() -> dict[str, tuple[str, ...]]:
    terms: dict[str, set[str]] = defaultdict(set)
    for topic in OBSERVATION_TOPICS:
        terms[topic].update(_tokens(topic))
    for rule in TOPIC_RULES:
        for keyword in rule.keywords:
            for topic in _output_topics(rule.name, [keyword], normalize_text(keyword)):
                terms[topic].update(_tokens(keyword))
    return {topic: tuple(sorted(values)) for topic, values in terms.items()}


def _bm25_score(
    tokens: list[str],
    query: tuple[str, ...],
    document_frequency: Counter[str],
    document_count: int,
    average_length: float,
) -> float:
    frequencies = Counter(tokens)
    length_ratio = len(tokens) / average_length if average_length else 0.0
    score = 0.0
    for term in query:
        frequency = frequencies[term]
        if not frequency:
            continue
        frequency_in_documents = document_frequency[term]
        inverse_frequency = math.log(
            1.0 + (document_count - frequency_in_documents + 0.5) / (frequency_in_documents + 0.5)
        )
        denominator = frequency + BM25_K1 * (1.0 - BM25_B + BM25_B * length_ratio)
        score += inverse_frequency * (frequency * (BM25_K1 + 1.0)) / denominator
    return score
