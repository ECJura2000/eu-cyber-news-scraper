import json
from collections import Counter

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.topics import classify_article


def test_gold_topic_set_meets_precision_and_recall_floor(fixture_dir):
    rows = json.loads((fixture_dir / "topic_evaluation.json").read_text(encoding="utf-8"))
    assert len(rows) >= 120
    assert len({(row["title"], row["summary"]) for row in rows}) == len(rows)
    true_positive = false_positive = false_negative = 0
    topic_true_positive = Counter()
    topic_false_negative = Counter()
    for index, row in enumerate(rows):
        article = Article("gold", "EU", "Gold", "test", "en", row["title"], f"https://example.eu/{index}", summary=row["summary"])
        classify_article(article)
        actual = set(article.matched_topics)
        expected = set(row["topics"])
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        topic_true_positive.update(actual & expected)
        topic_false_negative.update(expected - actual)
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert precision >= 0.90
    assert recall >= 0.90
    for topic in {topic for row in rows for topic in row["topics"]}:
        topic_recall = topic_true_positive[topic] / (topic_true_positive[topic] + topic_false_negative[topic])
        assert topic_recall >= 0.75, topic
