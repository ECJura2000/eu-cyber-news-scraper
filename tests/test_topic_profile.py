import json
from datetime import datetime, timezone

import pytest

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry
from eu_cyber_news_scraper.ranking import is_hybrid_relevant, rank_articles
from eu_cyber_news_scraper.topic_profile import apply_profile, load_profile
from eu_cyber_news_scraper.topics import classify_article


def _article(title: str) -> Article:
    return Article(
        source_id="ie_comreg", country="IE", source_name="ComReg", institution_type="監理機關",
        language="en", title=title, url="https://www.comreg.ie/example/",
        published_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )


def test_profile_add_remove_rename_and_local_exclusion(tmp_path):
    payload = {
        "schema_version": 1, "schedule": {"days": 14}, "manual": {"days": 30},
        "topics": [
            {"name": "量子技術", "enabled": False},
            {"name": "新議題", "keywords": [{"term": "quantum", "weight": 2}], "excludes": ["laboratory"]},
            {"name": "改名主題", "legacy_name": "半導體", "enabled": True},
        ],
    }
    path = tmp_path / "topics.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    profile = load_profile(path)
    assert profile.manual["days"] == 30
    assert profile.hash == load_profile(path).hash
    article = _article("Quantum chips laboratory")
    classify_article(article)
    apply_profile(article, profile)
    assert "新議題" not in article.matched_topics
    assert "量子技術" not in article.matched_topics
    payload["topics"][1]["excludes"] = []
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    changed = load_profile(path)
    assert changed.hash != profile.hash
    apply_profile(article, changed)
    assert "新議題" in article.matched_topics


def test_invalid_profile_fails_before_scrape(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":1,"topics":[{"name":"new"}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="新主題"):
        load_profile(path)


@pytest.mark.parametrize("payload", [
    "not JSON", "{}", '{"schema_version":1,"topics":[{"name":"x","keywords":"bad"}]}',
    '{"schema_version":1,"topics":[{"name":"半導體","enabled":"yes"}]}',
    '{"schema_version":1,"topics":[{"name":"半導體"},{"name":"半導體"}]}',
    '{"schema_version":1,"topics":[],"manual":{"days":0}}',
    '{"schema_version":1,"topics":[{"name":"半導體","legacy_name":42}]}',
    '{"schema_version":1,"topics":[{"name":"半導體","responsibility_owner":42}]}',
])
def test_profile_rejects_invalid_json(tmp_path, payload):
    path = tmp_path / "topics.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_profile(path)


def test_profile_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError, match="主題 JSON 無效"):
        load_profile(tmp_path / "missing.json")


def test_penalty_removes_only_its_topic(tmp_path):
    payload = {
        "schema_version": 1,
        "topics": [
            {"name": "NIS2、關鍵基礎設施保護", "penalties": ["conference"]},
            {"name": "會議追蹤", "keywords": [{"term": "conference", "weight": 2}],
             "responsibility_owner": "未設定"},
        ],
    }
    path = tmp_path / "topics.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    article = _article("NIS2 cybersecurity conference")
    classify_article(article)
    apply_profile(article, load_profile(path))
    assert article.matched_topics == ["會議追蹤"]


def test_new_topic_is_not_limited_by_existing_source_whitelist(tmp_path):
    payload = {"schema_version": 1, "topics": [
        {"name": "新量子政策", "keywords": [{"term": "quantum", "weight": 2}]}
    ]}
    path = tmp_path / "topics.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    article = _article("Quantum regulation announced")
    classify_article(article)
    profile = load_profile(path)
    apply_profile(article, profile)
    rank_articles([article], load_organisation_registry(), profile=profile)
    assert is_hybrid_relevant(article)
    assert article.matched_topics == ["新量子政策"]
    assert article.responsibility_owner == ["未設定"]
