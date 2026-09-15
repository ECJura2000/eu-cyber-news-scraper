from __future__ import annotations

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.ranking import is_hybrid_relevant, rank_articles
from eu_cyber_news_scraper.topics import classify_article


def article(source_id: str, title: str, summary: str = "") -> Article:
    return Article(source_id, "EU", "Publisher", "official", "en", title, "https://example.eu/news", summary=summary)


def test_bm25_scores_are_quantized_and_preserve_publisher_and_owner():
    item = classify_article(article("eu_dg_connect", "AI Act model evaluation guidance", "artificial intelligence governance"))
    rank_articles([item], load_organisation_registry())
    assert item.boolean_score > 0
    assert item.bm25_score > 0
    assert item.bm25_score == round(item.bm25_score, 4)
    assert item.publisher_organisation == "Publisher"
    assert item.responsibility_owner
    assert item.matched_synonyms
    assert is_hybrid_relevant(item)


def test_registry_topic_allowlist_removes_out_of_scope_topic():
    item = classify_article(article("eu_enisa_certification", "AI Act model evaluation guidance"))
    rank_articles([item], load_organisation_registry())
    assert item.matched_topics == []
    assert not is_hybrid_relevant(item)


def test_stable_order_does_not_change_equal_score_articles():
    first = classify_article(article("eu_dg_connect", "NIS2 cybersecurity guidance"))
    second = classify_article(article("eu_dg_connect", "NIS2 cybersecurity guidance"))
    items = rank_articles([first, second], load_organisation_registry())
    assert items == [first, second]
    assert first.bm25_score == second.bm25_score


def test_empty_corpus_is_unchanged():
    assert rank_articles([], load_organisation_registry()) == []
