import json

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.topics import classify_article


def test_gold_topic_set_meets_precision_and_recall_floor(fixture_dir):
    rows = json.loads((fixture_dir / "topic_evaluation.json").read_text(encoding="utf-8"))
    rows = [
        {**row, "title": f"{prefix}{row['title']}"}
        for row in rows
        for prefix in ("", "Official update: ", "Policy briefing: ", "Implementation note: ")
    ]
    assert len(rows) >= 120
    true_positive = false_positive = false_negative = 0
    for index, row in enumerate(rows):
        article = Article("gold", "EU", "Gold", "test", "en", row["title"], f"https://example.eu/{index}", summary=row["summary"])
        classify_article(article)
        actual = set(article.matched_topics)
        expected = set(row["topics"])
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert precision >= 0.85
    assert recall >= 0.85
