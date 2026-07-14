import json
import time

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.translation import _translate_with_fallback, load_translations, translate_article_titles


def article(title: str) -> Article:
    return Article("source", "EU", "Agency", "official", "en", title, "https://example.eu/news")


def test_title_translation_uses_cache(monkeypatch, tmp_path):
    cache = tmp_path / "translations.json"
    cache.write_text(json.dumps({"Cyber law": "網路法"}), encoding="utf-8")
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(cache))
    item = article("Cyber law")
    report = translate_article_titles([item])
    assert item.title_zh_tw == "網路法"
    assert report.success_rate == 1
    assert load_translations() == {"Cyber law": "網路法"}


def test_missing_translation_falls_back_without_losing_output(monkeypatch, tmp_path):
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(tmp_path / "missing.json"))
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_titles", lambda titles: {})
    item = article("Cyber law")
    report = translate_article_titles([item])
    assert item.title_zh_tw == "Cyber law"
    assert report.failed_titles == ("Cyber law",)


def test_server_error_page_is_not_accepted_as_translation(monkeypatch, tmp_path):
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(tmp_path / "missing.json"))
    monkeypatch.setattr(
        "eu_cyber_news_scraper.translation._translate_titles",
        lambda titles: {"Cyber law": "Error 500 (Server Error). Please try again later."},
    )
    item = article("Cyber law")
    report = translate_article_titles([item])
    assert item.title_zh_tw == "Cyber law"
    assert report.success_rate == 0


def test_new_translation_is_saved(monkeypatch, tmp_path):
    cache = tmp_path / "translations.json"
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(cache))
    monkeypatch.setattr(
        "eu_cyber_news_scraper.translation._translate_titles",
        lambda titles: {"Cybersicherheit": "網路安全"},
    )
    item = article("Cybersicherheit")
    translate_article_titles([item])
    assert item.title_zh_tw == "網路安全"
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["translations"]["Cybersicherheit"]["text"] == "網路安全"


def test_translation_falls_back_to_second_free_engine(monkeypatch):
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_googletrans", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translate_module", lambda title: "備援翻譯")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translatepy", lambda title: "不應呼叫")
    assert _translate_with_fallback("Cybersecurity guidance") == "備援翻譯"


def test_translation_falls_back_to_third_free_engine(monkeypatch):
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_googletrans", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translate_module", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translatepy", lambda title: "第三引擎翻譯")
    assert _translate_with_fallback("Cybersecurity guidance") == "第三引擎翻譯"


def test_translation_provider_circuit_breaker(monkeypatch):
    from eu_cyber_news_scraper.translation import _ProviderTracker

    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES", "1")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_googletrans", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translate_module", lambda title: "備援翻譯")
    tracker = _ProviderTracker()
    assert _translate_with_fallback("First title", tracker) == "備援翻譯"
    assert _translate_with_fallback("Second title", tracker) == "備援翻譯"
    google = tracker.report()[0]
    assert google.disabled
    assert google.skipped == 1


def test_skip_translation_preserves_titles():
    from eu_cyber_news_scraper.translation import skip_article_title_translation

    item = article("Cyber law")
    report = skip_article_title_translation([item])
    assert item.title_zh_tw == "Cyber law"
    assert not report.enabled
    assert report.success_rate == 1


def test_provider_call_has_a_hard_timeout(monkeypatch):
    from eu_cyber_news_scraper.translation import _call_provider_with_timeout

    monkeypatch.setattr("eu_cyber_news_scraper.translation._translation_timeout", lambda: 0.01)

    def slow_provider(title):
        time.sleep(0.1)
        return "遲到的翻譯"

    started = time.monotonic()
    assert _call_provider_with_timeout(slow_provider, "Cyber law") == ""
    assert time.monotonic() - started < 0.08


def test_translation_normalizes_taiwan_terminology():
    from eu_cyber_news_scraper.translation import _to_taiwan_traditional

    assert _to_taiwan_traditional("数字产品、人工智能、算法、数据和芯片") == "數位產品、人工智慧、演算法、資料和晶片"
