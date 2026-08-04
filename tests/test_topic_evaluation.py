import json
from collections import Counter

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.topics import classify_article


def test_assisted_topic_regression_set_meets_precision_and_recall_floor(fixture_dir):
    rows = json.loads((fixture_dir / "topic_evaluation.json").read_text(encoding="utf-8"))
    assert len(rows) >= 240
    assert len({(row["title"], row["summary"]) for row in rows}) == len(rows)
    assert len({row["title"].casefold().strip() for row in rows}) == len(rows)
    assert Counter(row["language"] for row in rows) == {"en": 80, "fr": 80, "de": 80}
    assert Counter(row["split"] for row in rows) == {"dev": 80, "locked_test": 160}
    assert all(row["url"].startswith("https://") and row["source_id"] for row in rows)
    assert all(row["captured_at"] and row["reviewer"] for row in rows)
    assert all(row["review_status"] == "assisted" for row in rows)
    assert all(row["title"].casefold().strip() not in {"meldung lesen", "s'abonner à ma recherche"} for row in rows)
    true_positive = false_positive = false_negative = 0
    topic_true_positive = Counter()
    topic_false_negative = Counter()
    language_true_positive = Counter()
    language_false_positive = Counter()
    language_false_negative = Counter()
    for row in rows:
        article = Article(
            row["source_id"], "EU", "Gold", "test", row["language"],
            row["title"], row["url"], summary=row["summary"],
        )
        classify_article(article)
        actual = set(article.matched_topics)
        expected = set(row["topics"])
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        topic_true_positive.update(actual & expected)
        topic_false_negative.update(expected - actual)
        language_true_positive[row["language"]] += len(actual & expected)
        language_false_positive[row["language"]] += len(actual - expected)
        language_false_negative[row["language"]] += len(expected - actual)
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert precision >= 0.90
    assert recall >= 0.90
    for topic in {topic for row in rows for topic in row["topics"]}:
        topic_recall = topic_true_positive[topic] / (topic_true_positive[topic] + topic_false_negative[topic])
        assert topic_recall >= 0.75, topic
    for language in ("en", "fr", "de"):
        language_precision = language_true_positive[language] / (
            language_true_positive[language] + language_false_positive[language]
        )
        language_recall = language_true_positive[language] / (
            language_true_positive[language] + language_false_negative[language]
        )
        assert language_precision >= 0.90, language
        assert language_recall >= 0.75, language
