import json
import queue
import time
from types import SimpleNamespace

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.translation import (
    _translate_with_fallback,
    _translation_circuit_failures,
    _translation_timeout,
    _translation_workers,
    load_translations,
    translate_article_titles,
)


def article(title: str) -> Article:
    return Article("source", "EU", "Agency", "official", "en", title, "https://example.eu/news")


def direct_runner(_name, provider, title):
    return provider(title)


def slow_provider(_title):
    time.sleep(2)
    return "遲到的翻譯"


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
    assert payload["schema_version"] == 3
    assert payload["translations"]["en\0Cybersicherheit"]["text"] == "網路安全"


def test_translation_cache_key_includes_source_language(monkeypatch, tmp_path):
    cache = tmp_path / "translations.json"
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(cache))
    monkeypatch.setattr(
        "eu_cyber_news_scraper.translation._translate_titles",
        lambda titles: {"Gift": "禮物"},
    )
    english = article("Gift")
    german = article("Gift")
    german.language = "de"
    report = translate_article_titles([english, german])
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert report.total == 2
    assert {"en\0Gift", "de\0Gift"} <= payload["translations"].keys()


def test_translation_falls_back_to_second_free_engine(monkeypatch):
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_googletrans", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translate_module", lambda title: "備援翻譯")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translatepy", lambda title: "不應呼叫")
    assert _translate_with_fallback("Cybersecurity guidance", runner=direct_runner) == "備援翻譯"


def test_translation_falls_back_to_third_free_engine(monkeypatch):
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_googletrans", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translate_module", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translatepy", lambda title: "第三引擎翻譯")
    assert _translate_with_fallback("Cybersecurity guidance", runner=direct_runner) == "第三引擎翻譯"


def test_translation_provider_circuit_breaker(monkeypatch):
    from eu_cyber_news_scraper.translation import _ProviderTracker

    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES", "1")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_googletrans", lambda title: "")
    monkeypatch.setattr("eu_cyber_news_scraper.translation._translate_translate_module", lambda title: "備援翻譯")
    tracker = _ProviderTracker()
    assert _translate_with_fallback("First title", tracker, direct_runner) == "備援翻譯"
    assert _translate_with_fallback("Second title", tracker, direct_runner) == "備援翻譯"
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

    monkeypatch.setattr("eu_cyber_news_scraper.translation._translation_timeout", lambda: 0.05)

    started = time.monotonic()
    assert _call_provider_with_timeout(slow_provider, "Cyber law") == ""
    assert time.monotonic() - started < 1.5


def test_translation_normalizes_taiwan_terminology():
    from eu_cyber_news_scraper.translation import _to_taiwan_traditional

    assert _to_taiwan_traditional("数字产品、人工智能、算法、数据和芯片") == "數位產品、人工智慧、演算法、資料和晶片"


def test_translation_configuration_falls_back_on_invalid_environment(monkeypatch):
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_WORKERS", "invalid")
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_TIMEOUT", "invalid")
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES", "invalid")
    assert _translation_workers() == 4
    assert _translation_timeout() == 10
    assert _translation_circuit_failures() == 3


def test_translation_configuration_accepts_valid_environment(monkeypatch):
    monkeypatch.delenv("EU_CYBER_NEWS_TRANSLATION_WORKERS", raising=False)
    assert _translation_workers() == 4
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_WORKERS", "0")
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_TIMEOUT", "2.5")
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES", "5")
    assert _translation_workers() == 1
    assert _translation_timeout() == 2.5
    assert _translation_circuit_failures() == 5


def test_translation_cache_rejects_invalid_payloads(monkeypatch, tmp_path):
    cache = tmp_path / "translations.json"
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(cache))
    cache.write_text("not json", encoding="utf-8")
    assert load_translations() == {}
    cache.write_text("[]", encoding="utf-8")
    assert load_translations() == {}
    cache.write_text(json.dumps({"translations": []}), encoding="utf-8")
    assert load_translations() == {}


def test_translation_cache_recovers_from_non_mapping_rows(monkeypatch, tmp_path):
    from eu_cyber_news_scraper.translation import save_translations

    cache = tmp_path / "translations.json"
    cache.write_text(json.dumps({"translations": []}), encoding="utf-8")
    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_CACHE", str(cache))
    save_translations({"en\0Cyber law": "網路法"})
    assert load_translations() == {"en\0Cyber law": "網路法"}


def test_empty_article_list_needs_no_translation():
    report = translate_article_titles([])
    assert report.total == 0


class FakeQueue:
    def __init__(self, values=()):
        self.values = list(values)
        self.puts = []
        self.closed = False

    def put(self, value):
        self.puts.append(value)

    def get(self, timeout=None):
        del timeout
        if not self.values:
            raise queue.Empty
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        self.closed = True

    def join_thread(self):
        return None


class FakeProcess:
    def __init__(self, *, alive=True, stop_on_terminate=True):
        self.alive = alive
        self.stop_on_terminate = stop_on_terminate
        self.started = False
        self.terminated = False
        self.killed = False
        self.joined = []

    def start(self):
        self.started = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.joined.append(timeout)

    def terminate(self):
        self.terminated = True
        if self.stop_on_terminate:
            self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False


def _bare_worker(results=(), *, process=None):
    from eu_cyber_news_scraper.translation import _ProviderWorker

    worker = _ProviderWorker.__new__(_ProviderWorker)
    worker._requests = FakeQueue()
    worker._results = FakeQueue(results)
    worker._process = process or FakeProcess()
    worker._context = None
    return worker


def test_provider_worker_returns_matching_result(monkeypatch):
    monkeypatch.setattr(
        "eu_cyber_news_scraper.translation.uuid4",
        lambda: SimpleNamespace(hex="task-1"),
    )
    worker = _bare_worker([("task-1", "翻譯結果")])
    assert worker.call("googletrans", "Cyber law") == "翻譯結果"
    assert worker._requests.puts == [("task-1", "googletrans", "Cyber law")]


def test_provider_worker_restarts_after_timeout_or_mismatched_result(monkeypatch):
    monkeypatch.setattr(
        "eu_cyber_news_scraper.translation.uuid4",
        lambda: SimpleNamespace(hex="expected"),
    )
    for results in ((), (("other", "錯誤回應"),)):
        worker = _bare_worker(results)
        restarted = []
        monkeypatch.setattr(worker, "_restart", lambda: restarted.append(True))
        assert worker.call("translate", "Cyber law") == ""
        assert restarted == [True]


def test_provider_worker_start_restart_stop_and_close():
    from eu_cyber_news_scraper.translation import _ProviderWorker

    requests = FakeQueue()
    results = FakeQueue()
    process = FakeProcess()

    class Context:
        queues = [requests, results]

        def Queue(self):
            return self.queues.pop(0)

        def Process(self, *, target, args):
            assert callable(target)
            assert args == (requests, results)
            return process

    worker = _ProviderWorker.__new__(_ProviderWorker)
    worker._context = Context()
    worker._requests = None
    worker._results = None
    worker._process = None
    worker._start()
    assert process.started

    stubborn = FakeProcess(stop_on_terminate=False)
    worker._process = stubborn
    worker._stop()
    assert stubborn.terminated and stubborn.killed
    assert requests.closed and results.closed

    worker = _bare_worker(process=FakeProcess())
    stopped = []
    started = []
    worker._stop = lambda: stopped.append(True)
    worker._start = lambda: started.append(True)
    worker._restart()
    assert stopped == [True] and started == [True]

    worker = _bare_worker(process=FakeProcess())
    stopped = []
    worker._stop = lambda: stopped.append(True)
    worker.close()
    assert worker._requests.puts == [None]
    assert stopped == [True]


def test_provider_worker_pool_reuses_and_closes_workers(monkeypatch):
    from eu_cyber_news_scraper import translation

    class Worker:
        def __init__(self):
            self.closed = False
            self.calls = []

        def call(self, provider_name, title):
            self.calls.append((provider_name, title))
            return "池內翻譯"

        def close(self):
            self.closed = True

    monkeypatch.setattr(translation, "_ProviderWorker", Worker)
    with translation._ProviderWorkerPool(2) as pool:
        assert pool.call("googletrans", lambda title: title, "Cyber law") == "池內翻譯"
    assert all(worker.closed for worker in pool._workers)
    assert sum(len(worker.calls) for worker in pool._workers) == 1


def test_provider_worker_target_dispatches_success_failure_and_shutdown(monkeypatch):
    from eu_cyber_news_scraper import translation

    monkeypatch.setattr(translation, "_translate_googletrans", lambda title: "谷歌翻譯")
    monkeypatch.setattr(
        translation,
        "_translate_translate_module",
        lambda title: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    requests = FakeQueue(
        [
            ("one", "googletrans", "First"),
            ("two", "translate", "Second"),
            None,
        ]
    )
    results = FakeQueue()
    translation._provider_worker_target(requests, results)
    assert results.puts == [("one", "谷歌翻譯"), ("two", "")]


def test_translate_titles_uses_configured_pool(monkeypatch):
    from eu_cyber_news_scraper import translation

    calls = []

    class Pool:
        def __init__(self, size):
            calls.append(("size", size))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append(("closed", True))

        def call(self, name, provider, title):
            del provider
            calls.append((name, title))
            return "繁體翻譯"

    monkeypatch.setenv("EU_CYBER_NEWS_TRANSLATION_WORKERS", "2")
    monkeypatch.setattr(translation, "_ProviderWorkerPool", Pool)
    translated = translation._translate_titles(["First", "Second"])
    assert translated == {"First": "繁體翻譯", "Second": "繁體翻譯"}
    assert translated.providers_by_title == {"First": "googletrans", "Second": "googletrans"}
    assert calls[0] == ("size", 2)
    assert calls[-1] == ("closed", True)
