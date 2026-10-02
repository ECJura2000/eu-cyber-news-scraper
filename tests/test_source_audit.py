import asyncio
import json
import socket
import ssl
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from eu_cyber_news_scraper import source_audit as audit
from eu_cyber_news_scraper.http import HttpClient, RetryDeferredError, RobotsDeniedError, RobotsUnavailableError
from eu_cyber_news_scraper.models import Article, Source, SourceResult, SourceStatus

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
HTML = b"<html><main><a href='/news/guidance'>Official news</a></main></html>"


@pytest.fixture
def source():
    return Source("audit_test", "EU", "測試機關", "Test agency", "official", "en",
                  "https://agency.example/", "https://agency.example/news/",
                  feed_urls=("https://agency.example/feed.xml",), allow_domains=("agency.example",),
                  detail_pages=0, schedule_enabled=False, paused_until="2026-12-01",
                  pause_reason="Observation", pause_evidence_url="https://agency.example/")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def public_dns(_host):
        return None

    async def no_pace(_self, _host):
        return None

    def unexpected_network(*_args, **_kwargs):
        pytest.fail("Tests must not access the network")

    monkeypatch.setattr(audit, "_validate_public_dns", public_dns)
    monkeypatch.setattr(HttpClient, "_pace", no_pace)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_network)


def mock_client(monkeypatch, handler):
    real = audit.AuditHttpClient
    clients = []

    def factory(**kwargs):
        client = real(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(audit, "AuditHttpClient", factory)
    return clients


def handler_for_feed(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
    if request.url.path == "/feed.xml":
        return httpx.Response(200, content=(Path(__file__).parent / "fixtures/source_audit_feed.xml").read_bytes(),
                              headers={"content-type": "application/rss+xml"})
    return httpx.Response(200, content=HTML, headers={"content-type": "text/html"})


def run_audit(source, tmp_path, **kwargs):
    return asyncio.run(audit.audit_sources([source], registry_hash="registry-hash", output_dir=tmp_path / "output",
                                          history_dir=tmp_path / "history", observed_at=NOW, **kwargs))


@pytest.mark.parametrize("url,code", [
    ("http://agency.example/", "https_required"),
    ("https://localhost/", "nonpublic_host"),
    ("https://127.0.0.1/", "nonpublic_host"),
    ("https://[::1]/", "nonpublic_host"),
    ("https://169.254.169.254/latest/meta-data", "nonpublic_host"),
    ("https://224.0.0.1/", "nonpublic_host"),
    ("https://agency.local/", "nonpublic_host"),
    ("https://user:password@agency.example/", "url_credentials"),
    ("https://agency.example:abc/", "malformed_url"),
    ("https://agency.example:8000/", "malformed_url"),
    ("https://agency.example\\@127.0.0.1/", "malformed_url"),
    ("https://agency.example/\n", "malformed_url"),
    ("https:///", "malformed_url"),
    ("https://agency.example.evil.example/", "unexpected_domain"),
])
def test_url_safeguards(url, code):
    with pytest.raises(audit.UnsafeUrlError, match=code):
        audit.validate_url(url, ("agency.example",))


def test_url_allows_https_expected_subdomain():
    assert audit.validate_url("https://WWW.AGENCY.EXAMPLE./news", ("agency.example",)) == "www.agency.example"


def test_dns_mixed_public_private_is_denied(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443)),
    ])
    with pytest.raises(audit.UnsafeUrlError, match="nonpublic_host"):
        asyncio.run(audit._validate_public_dns("agency.example"))


def test_audit_uses_shared_options_and_keeps_source_paused(source, tmp_path, monkeypatch):
    clients = mock_client(monkeypatch, handler_for_feed)
    original = audit.config_hash(source)
    report = run_audit(source, tmp_path)
    assert report["healthy"]
    assert clients[0].obey_robots and clients[0].min_interval == 0.5
    observation = report["sources"][0]
    assert observation["registry_hash"] == "registry-hash"
    assert observation["country"] == "EU"
    assert len(observation["endpoints"]) == 3
    assert not observation["promotion"]["promotion_eligible"]
    assert source.schedule_enabled is False and source.is_paused(NOW.date())
    assert audit.config_hash(source) == original
    assert json.loads(Path(report["report_path"]).read_text())["run_id"] == report["run_id"]


@pytest.mark.parametrize("reverse_order", [False, True])
def test_client_context_isolates_concurrent_domains_and_failures(source, reverse_order):
    other = replace(source, id="other", homepage="https://other.example/",
                    listing_url="https://other.example/news/", feed_urls=(), allow_domains=("other.example",))
    requested = []

    async def handler(request):
        requested.append(str(request.url))
        await asyncio.sleep(0)
        return handler_for_feed(request)

    async def exercise():
        async with audit.AuditHttpClient(transport=httpx.MockTransport(handler)) as client:
            client.source = source
            parent_failures = client.failures
            ready = {item.id: asyncio.Event() for item in (source, other)}

            async def check(item, foreign_url, code):
                client.source = item
                failures = client.failures
                ready[item.id].set()
                await asyncio.gather(*(event.wait() for event in ready.values()))
                response = await client.get(item.listing_url)
                assert response.status_code == 200
                with pytest.raises(audit.UnsafeUrlError, match=code):
                    await client.get(foreign_url)
                await asyncio.sleep(0)
                assert client.source is item
                assert client.failures is failures
                assert failures == [{"url": foreign_url, "error_code": code, "error_type": "UnsafeUrlError"}]
                return failures

            checks = [(source, other.listing_url, "unexpected_domain"),
                      (other, "http://other.example/blocked", "https_required")]
            if reverse_order:
                checks.reverse()
            failures = await asyncio.wait_for(asyncio.gather(*(check(*args) for args in checks)), timeout=5)
            assert failures[0] is not failures[1]
            assert client.source is source
            assert client.failures is parent_failures
            assert parent_failures == []

    asyncio.run(exercise())
    assert sorted(requested) == sorted([
        source.listing_url, other.listing_url,
        "https://agency.example/robots.txt", "https://other.example/robots.txt",
    ])


def test_concurrent_audit_keeps_parse_diagnostics_with_their_source(source, tmp_path, monkeypatch):
    sources = [replace(source, id=f"source{i}", homepage=f"https://agency{i}.example/",
                       listing_url=f"https://agency{i}.example/news/", feed_urls=(),
                       allow_domains=(f"agency{i}.example",)) for i in range(3)]
    mock_client(monkeypatch, handler_for_feed)
    entered = set()
    all_parsing = asyncio.Event()

    async def parse(item, client, **_kwargs):
        entered.add(item.id)
        if len(entered) == len(sources):
            all_parsing.set()
        await asyncio.wait_for(all_parsing.wait(), timeout=5)
        if item.id != "source2":
            url, code = ((sources[1].listing_url, "unexpected_domain") if item.id == "source0"
                         else ("http://agency1.example/blocked", "https_required"))
            with pytest.raises(audit.UnsafeUrlError, match=code):
                await client.get(url)
        await asyncio.sleep(0)
        article = Article(item.id, item.country, item.name, "official", "en", "Guidance",
                          item.listing_url + "guidance", published_at=NOW - timedelta(days=1),
                          date_confidence="high")
        status = SourceStatus(item.id, item.name, item.country, False, True, "feed", 1, 1, 0, dated_count=1)
        return SourceResult(item, [article], status, parsed_articles=[article])

    monkeypatch.setattr(audit, "scrape_source", parse)
    report = asyncio.run(audit.audit_sources(
        sources, registry_hash="registry-hash", output_dir=tmp_path / "output",
        history_dir=tmp_path / "history", observed_at=NOW, parse=True, workers=3,
    ))
    assert not report["healthy"]
    for observation, (url, code) in zip(report["sources"], [
        (sources[1].listing_url, "unexpected_domain"), ("http://agency1.example/blocked", "https_required"),
        (None, None),
    ], strict=True):
        expected = [] if code is None else [{"url": url, "error_code": code, "error_type": "UnsafeUrlError"}]
        assert observation["parse_request_failures"] == expected
        assert observation["healthy"] is (code is None)
        assert observation["promotion"]["successful_parse_executions"] == (1 if code is None else 0)


@pytest.mark.parametrize("destination,code", [
    ("https://outside.example/news", "unexpected_domain"),
    ("https://127.0.0.1/news", "nonpublic_host"),
    ("http://agency.example/news", "https_required"),
])
def test_redirect_target_is_blocked_before_request(source, tmp_path, monkeypatch, destination, code):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/news/":
            return httpx.Response(302, headers={"location": destination})
        return handler_for_feed(request)

    mock_client(monkeypatch, handler)
    report = run_audit(source, tmp_path)
    listing = report["sources"][0]["endpoints"][1]
    assert not report["healthy"]
    assert listing["error_code"] == code
    assert destination not in requested
    assert not any("outside.example" in url or "127.0.0.1" in url for url in requested)


def test_successful_redirect_is_reported(source, tmp_path, monkeypatch):
    def handler(request):
        if request.url.path == "/news/":
            return httpx.Response(301, headers={"location": "/archive/"})
        return handler_for_feed(request)

    mock_client(monkeypatch, handler)
    endpoint = run_audit(source, tmp_path)["sources"][0]["endpoints"][1]
    assert endpoint["healthy"]
    assert endpoint["final_url"] == "https://agency.example/archive/"
    assert endpoint["redirects"][0]["http_status"] == 301
    assert endpoint["redirects"][0]["location"] == "https://agency.example/archive/"
    assert endpoint["duration_seconds"] >= 0


@pytest.mark.parametrize("body,kind,content_type,code", [
    (b"<html><title>Just a moment...</title></html>", "listing", "text/html", "challenge_page"),
    (b"<html><script src='/cdn-cgi/challenge-platform/test'></script></html>", "feed", "application/xml", "challenge_page"),
    (HTML, "feed", "text/html", "feed_received_html"),
    (b"not xml", "feed", "application/xml", "invalid_feed"),
    (b"<error>Oops</error>", "feed", "application/xml", "invalid_feed"),
    (b"", "listing", "text/html", "empty_response"),
    (b"%PDF-1.0", "listing", "application/pdf", "expected_html"),
])
def test_challenges_and_expected_content(source, body, kind, content_type, code):
    response = httpx.Response(200, content=body, headers={"content-type": content_type},
                              request=httpx.Request("GET", source.listing_url))
    assert audit._content_error(response, kind, source) == code


def test_official_feed_can_be_the_primary_listing_without_relaxing_xml_checks(source):
    from dataclasses import replace
    rss = replace(source, listing_url="https://agency.example/feed/", feed_urls=("https://agency.example/feed/",))
    for body, content_type, expected in [
        (b"<rss version='2.0'><channel><title>News</title></channel></rss>", "application/rss+xml", ""),
        (HTML, "text/html", "feed_received_html"),
        (b"<error>not RSS</error>", "application/xml", "invalid_feed"),
        (b"<!DOCTYPE rss><rss/>", "application/xml", "invalid_feed"),
    ]:
        response = httpx.Response(200, content=body, headers={"content-type": content_type},
                                  request=httpx.Request("GET", rss.listing_url))
        assert audit._content_error(response, "listing", rss) == expected


@pytest.mark.parametrize("error,code", [
    (httpx.ReadTimeout("timed out"), "timeout"),
    (ssl.SSLCertVerificationError("certificate verify failed"), "tls_failure"),
    (httpx.ConnectError("TLS handshake failed"), "tls_failure"),
    (RobotsDeniedError("disallowed"), "robots_denied"),
    (RobotsUnavailableError("unavailable"), "robots_unavailable"),
    (RetryDeferredError("retry later"), "retry_deferred"),
])
def test_endpoint_failures_are_structured(source, error, code):
    class Client:
        async def get(self, *_args, **_kwargs):
            raise error

    endpoint = asyncio.run(audit.check_endpoint(Client(), source, "listing", source.listing_url))
    assert not endpoint["healthy"] and endpoint["error_code"] == code
    assert endpoint["duration_seconds"] >= 0


@pytest.mark.parametrize("scheme", ["https", "HTTPS"])
def test_endpoint_error_redacts_url_credentials_and_query_tokens(source, scheme):
    sensitive_url = (f"{scheme}://audit-user:password-secret@agency.example/news/"
                     "?access_token=token-secret&api_key=key-secret&session=session-secret&page=2#fragment-secret")

    class Client:
        async def get(self, *_args, **_kwargs):
            raise httpx.ReadTimeout(f"Request failed for '{sensitive_url}': " + "x" * 1000)

    endpoint = asyncio.run(audit.check_endpoint(Client(), source, "listing", source.listing_url))
    assert not endpoint["healthy"]
    assert endpoint["error_code"] == "timeout"
    assert endpoint["error_type"] == "ReadTimeout"
    assert endpoint["duration_seconds"] >= 0
    assert endpoint["error"].startswith(
        "Request failed for 'https://agency.example/news/?access_token=%5Bredacted%5D"
        "&api_key=%5Bredacted%5D&session=%5Bredacted%5D&page=2': "
    )
    assert len(endpoint["error"]) == 500
    serialized = json.dumps(endpoint)
    for secret in ("audit-user", "password-secret", "token-secret", "key-secret", "session-secret", "fragment-secret"):
        assert secret not in serialized


def test_http_failure_collects_other_endpoints(source, tmp_path, monkeypatch):
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/news/":
            return httpx.Response(404)
        return handler_for_feed(request)

    mock_client(monkeypatch, handler)
    report = run_audit(source, tmp_path)
    assert not report["healthy"]
    assert "/feed.xml" in requested
    assert report["sources"][0]["endpoints"][1]["http_status"] == 404
    assert report["sources"][0]["endpoints"][1]["error_code"] == "http_error"


@pytest.mark.parametrize("robots,code", [
    ("User-agent: *\nDisallow: /", "robots_denied"),
    ("<html><title>Checking your browser</title></html>", "robots_unavailable"),
])
def test_robots_policy_failure(source, tmp_path, monkeypatch, robots, code):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return handler_for_feed(request)

    mock_client(monkeypatch, handler)
    report = run_audit(source, tmp_path)
    assert not report["healthy"]
    assert all(item["error_code"] == code for item in report["sources"][0]["endpoints"])
    assert requests == ["/robots.txt"]


def test_required_date_gates(source):
    article = Article(source.id, source.country, source.name, "official", "en", "Guidance",
                      "https://agency.example/news/guidance", published_at=NOW - timedelta(days=1),
                      date_confidence="high")
    status = SourceStatus(source.id, source.name, source.country, False, True, "feed", 1, 1, 0, dated_count=1)
    result = SourceResult(source, [article], status)
    assessment = audit.assess_parse(result, observed_at=NOW)
    assert assessment["high_confidence_date_rate"] == 1
    assert assessment["assessment_complete"]
    article.published_at = None
    assert audit.assess_parse(result, observed_at=NOW)["missing_required_count"] == 1
    article.published_at = NOW + timedelta(hours=1)
    assert audit.assess_parse(result, observed_at=NOW)["future_count"] == 1
    article.date_conflict = True
    assert audit.assess_parse(result, observed_at=NOW)["conflict_rate"] == 1
    result.status = replace(status, raw_count=2, dated_count=2)
    assert not audit.assess_parse(result, observed_at=NOW)["assessment_complete"]


@pytest.mark.parametrize("retained_count", [0, 1])
def test_parse_assessment_uses_all_parsed_articles_outside_date_window(source, retained_count):
    recent = Article(source.id, source.country, source.name, "official", "en", "Recent guidance",
                     source.listing_url + "recent", published_at=NOW - timedelta(days=1), date_confidence="high")
    old = replace(recent, title="Old guidance", url=source.listing_url + "old",
                  published_at=NOW - timedelta(days=90), date_conflict=True)
    future = replace(recent, title="Future guidance", url=source.listing_url + "future",
                     published_at=NOW + timedelta(hours=1))
    undated = replace(recent, title="Undated guidance", url=source.listing_url + "undated",
                      published_at=None, date_confidence="")
    status = SourceStatus(source.id, source.name, source.country, False, True, "feed", 4, retained_count, 0,
                          dated_count=3, in_range_count=retained_count)
    result = SourceResult(source, [recent][:retained_count], status, parsed_articles=[recent, old, future, undated])
    assessment = audit.assess_parse(result, observed_at=NOW)
    assert assessment["assessed_count"] == 4
    assert assessment["assessment_complete"]
    assert assessment["high_confidence_date_rate"] == 0.75
    assert assessment["conflict_rate"] == 0.25
    assert assessment["future_count"] == 1
    assert assessment["undated_count"] == assessment["missing_required_count"] == 1


def test_explicit_empty_parsed_articles_do_not_fall_back_to_filtered_articles(source):
    article = Article(source.id, source.country, source.name, "official", "en", "Guidance",
                      source.listing_url + "guidance", published_at=NOW - timedelta(days=1), date_confidence="high")
    status = SourceStatus(source.id, source.name, source.country, False, True, "feed", 1, 1, 0, dated_count=1)
    assessment = audit.assess_parse(SourceResult(source, [article], status, parsed_articles=[]), observed_at=NOW)
    assert assessment["assessed_count"] == 0
    assert not assessment["assessment_complete"]
    assert assessment["high_confidence_date_rate"] == 0


def qualifying_observation(source, run="run1", config=None):
    return {"source_id": source.id, "run_id": run, "timestamp": NOW.isoformat(),
            "config_hash": config or audit.config_hash(source), "healthy": True,
            "endpoints": [{"healthy": True}], "parse_request_failures": [],
            "parse": {"executed": True, "success": True, "fresh": True, "raw_count": 10,
                      "assessment_complete": True, "high_confidence_date_rate": 0.8,
                      "conflict_rate": 0.0, "future_count": 0, "missing_required_count": 0}}


def test_distinct_runs_and_immutable_history(source, tmp_path):
    observation = qualifying_observation(source)
    for _ in range(4):
        history = audit.persist_observation(tmp_path, observation)
    assert len(history) == 1
    assert not audit.promotion_evidence(observation, history)["promotion_eligible"]
    overwritten = {**observation, "healthy": False}
    assert audit.persist_observation(tmp_path, overwritten)[0]["healthy"] is True
    for run in ("run2", "run3"):
        observation = qualifying_observation(source, run)
        history = audit.persist_observation(tmp_path, observation)
    promotion = audit.promotion_evidence(observation, history)
    assert promotion["promotion_eligible"]
    assert promotion["successful_parse_executions"] == 3
    assert promotion["automatic_schedule_changes"] is False


@pytest.mark.parametrize("field,value", [
    ("raw_count", 0), ("assessment_complete", False), ("high_confidence_date_rate", 0.749),
    ("conflict_rate", 0.051), ("future_count", 1), ("missing_required_count", 1),
    ("success", False), ("executed", False),
    ("fresh", False),
])
def test_no_empty_or_low_quality_promotion(source, field, value):
    history = [qualifying_observation(source, f"run{i}") for i in range(3)]
    for item in history:
        item["parse"][field] = value
    assert not audit.promotion_evidence(history[-1], history)["promotion_eligible"]


def test_failed_endpoint_or_parse_request_blocks_promotion(source):
    history = [qualifying_observation(source, f"run{i}") for i in range(3)]
    history[-1]["endpoints"][0]["healthy"] = False
    assert not audit.promotion_evidence(history[-1], history)["promotion_eligible"]
    history[-1]["endpoints"][0]["healthy"] = True
    history[-1]["parse_request_failures"] = [{"error_code": "robots_denied"}]
    assert not audit.promotion_evidence(history[-1], history)["promotion_eligible"]


def test_config_change_and_reverting_do_not_reuse_old_evidence(source):
    old = audit.config_hash(source)
    changed = audit.config_hash(replace(source, listing_url="https://agency.example/updates/"))
    assert old != changed
    history = [qualifying_observation(source, f"run{i}", old) for i in range(3)]
    history.append(qualifying_observation(source, "run3", changed))
    assert audit.promotion_evidence(history[-1], history)["successful_parse_executions"] == 1
    history.append(qualifying_observation(source, "run4", old))
    assert audit.promotion_evidence(history[-1], history)["successful_parse_executions"] == 1


@pytest.mark.parametrize("reset", ["freshness", "failure", "config_change", "config_revert"])
def test_persisted_promotion_history_requires_three_new_runs_after_reset(source, tmp_path, reset):
    current = audit.config_hash(source)
    changed = audit.config_hash(replace(source, listing_url="https://agency.example/updates/"))
    initial = changed if reset == "config_revert" else current
    for index in range(3):
        observation = qualifying_observation(source, f"run{index}", initial)
        history = audit.persist_observation(tmp_path, observation)
    assert audit.promotion_evidence(observation, history)["promotion_eligible"]

    if reset in {"freshness", "failure"}:
        observation = qualifying_observation(source, "run3", current)
        observation["parse"]["fresh" if reset == "freshness" else "success"] = False
        history = audit.persist_observation(tmp_path, observation)
        promotion = audit.promotion_evidence(observation, history)
        assert not promotion["promotion_eligible"]
        assert promotion["successful_parse_executions"] == 0
        assert promotion["evidence_run_ids"] == []
    elif reset == "config_change":
        current = changed

    first_run = 4 if reset in {"freshness", "failure"} else 3
    new_runs = []
    for index in range(3):
        observation = qualifying_observation(source, f"run{first_run + index}", current)
        new_runs.append(observation["run_id"])
        history = audit.persist_observation(tmp_path, observation)
        promotion = audit.promotion_evidence(observation, list(reversed(history)))
        assert promotion["successful_parse_executions"] == index + 1
        assert promotion["evidence_run_ids"] == new_runs
        assert promotion["promotion_eligible"] is (index == 2)
        assert promotion["automatic_schedule_changes"] is False


@pytest.mark.parametrize("days", [1, audit.DEFAULT_DAYS])
def test_full_parse_accumulates_three_real_executions(source, tmp_path, monkeypatch, days):
    mock_client(monkeypatch, handler_for_feed)
    for run in range(3):
        report = run_audit(source, tmp_path, parse=True, run_id=f"real{run}", days=days)
        observation = report["sources"][0]
        assert observation["parse"]["raw_count"] == 1
        assert observation["parse"]["assessed_count"] == 1
        assert observation["parse"]["source_status"]["in_range_count"] == (0 if days == 1 else 1)
        assert observation["parse"]["source_status"]["relevant_count"] == (0 if days == 1 else 1)
        assert observation["parse"]["high_confidence_date_rate"] == 1
        assert observation["parse"]["assessment_complete"]
        assert observation["promotion"]["promotion_eligible"] is (run == 2)


def test_capture_is_bounded_and_refuses_tokens(source, tmp_path):
    def response(body):
        return httpx.Response(200, content=body, headers={"content-type": "text/html"},
                              request=httpx.Request("GET", source.homepage))

    endpoint = {"url": source.homepage}
    audit._capture(response(HTML + b"x" * 100000), endpoint, tmp_path)
    assert endpoint["fixture"]["bytes"] <= audit.MAX_FIXTURE_BYTES
    assert endpoint["fixture"]["truncated"]
    sensitive = {"url": source.homepage}
    audit._capture(response(b"<html><input name='csrf_token' value='secret123'></html>"), sensitive, tmp_path)
    assert sensitive["fixture_skipped"] == "sensitive_content"
    assert "fixture" not in sensitive
    secret_url = {"url": source.homepage + "?access_token=abc"}
    audit._capture(response(HTML), secret_url, tmp_path)
    assert "fixture" not in secret_url


def test_cli_filters_exit_and_allow_unhealthy(source, tmp_path, monkeypatch, capsys):
    def handler(request):
        if request.url.path == "/news/":
            return httpx.Response(404)
        return handler_for_feed(request)

    mock_client(monkeypatch, handler)
    monkeypatch.setattr(audit, "load_sources_and_registry", lambda: (
        (source, replace(source, id="not-selected", country="FR")),
        SimpleNamespace(registry_hash="registry-hash", errors=()),
    ))
    argv = ["--source", source.id, "--source", source.id, "--country", "eu", "--limit", "1",
            "--timeout", "2", "--days", "10", "--output-dir", str(tmp_path / "output"),
            "--history-dir", str(tmp_path / "history")]
    assert audit.main(argv) == 1
    assert len(json.loads(capsys.readouterr().out)["sources"]) == 1
    assert audit.main([*argv, "--allow-unhealthy"]) == 0
    assert json.loads(capsys.readouterr().out)["healthy"] is False
    with pytest.raises(SystemExit):
        audit.main(["--source", "unknown"])
    with pytest.raises(SystemExit):
        audit.main(["--limit", "0"])


@pytest.mark.parametrize("selection,selected_ids,skipped_ids", [
    ([], ["active", "expired"], ["audit_test"]),
    (["--country", "eu"], ["active", "expired"], ["audit_test"]),
    (["--limit", "1"], ["active"], ["audit_test"]),
    (["--source", "audit_test"], ["audit_test"], []),
    (["--country", "EU", "--source", "audit_test", "--source", "active"], ["audit_test", "active"], []),
])
def test_bulk_cli_skips_paused_sources_unless_explicitly_selected(
    source, tmp_path, monkeypatch, capsys, selection, selected_ids, skipped_ids,
):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(audit, "datetime", FrozenDatetime)
    sources = (source, replace(source, id="active", paused_until="", schedule_enabled=True),
               replace(source, id="expired", paused_until="2026-09-29"))
    monkeypatch.setattr(audit, "load_sources_and_registry", lambda: (
        sources, SimpleNamespace(registry_hash="registry-hash", errors=()),
    ))
    mock_client(monkeypatch, handler_for_feed)
    assert audit.main([*selection, "--output-dir", str(tmp_path / "output"),
                       "--history-dir", str(tmp_path / "history")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [item["source_id"] for item in report["sources"]] == selected_ids
    assert report["paused_sources_skipped"] == skipped_ids
    assert json.loads(Path(report["report_path"]).read_text())["paused_sources_skipped"] == skipped_ids
    assert source.is_paused(NOW.date()) and not source.schedule_enabled


def test_invalid_history_is_not_counted(source, tmp_path):
    observation = qualifying_observation(source)
    audit.persist_observation(tmp_path, observation)
    directory = next(tmp_path.iterdir())
    (directory / "corrupt.json").write_text("{not JSON")
    with pytest.raises(ValueError):
        audit.persist_observation(tmp_path, qualifying_observation(source, "new"))
