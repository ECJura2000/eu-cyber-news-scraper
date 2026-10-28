import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from playwright.async_api import Error, TimeoutError

from eu_cyber_news_scraper.browser_http import (
    BrowserHttpTransport,
    BrowserResponseTooLargeError,
    system_chrome,
)
from eu_cyber_news_scraper.config import _validate_sources, load_sources
from eu_cyber_news_scraper.http import HttpClient, HttpStats, RobotsDeniedError, RobotsUnavailableError


@pytest.fixture
def chrome(monkeypatch):
    """Replay browser network events, keeping the production route/HTTP policy code."""
    specs = {}
    calls = []
    contexts = []
    routes = []

    class Page:
        def __init__(self):
            self.main_frame = object()
            self.events = {}
            self.network = {}
            self.close = AsyncMock()

        async def evaluate(self, _expression):
            return "Chrome/Test"

        async def route(self, _pattern, handler):
            self.guard = handler

        def on(self, event, callback):
            self.events[event] = callback

        async def goto(self, url, **_kwargs):
            spec = specs[url]
            calls.append(url)
            initial = SimpleNamespace(is_navigation_request=lambda: True, frame=self.main_frame,
                                      redirected_from=None, url=url)
            asset = SimpleNamespace(is_navigation_request=lambda: False)
            frame = SimpleNamespace(is_navigation_request=lambda: True, frame=object())
            redirect = SimpleNamespace(is_navigation_request=lambda: True, frame=self.main_frame,
                                       redirected_from=initial, url=url + "/redirect")
            for incoming in (initial, asset, frame, redirect):
                route = SimpleNamespace(request=incoming, continue_=AsyncMock(), abort=AsyncMock())
                await self.guard(route)
                routes.append((incoming, route.continue_.await_count, route.abort.await_count))
            if "error" in spec:
                raise spec.get("exception", Error)(spec["error"])
            response = SimpleNamespace(status=spec.get("status", 200), request=initial,
                                       all_headers=AsyncMock(return_value=spec.get("headers", {})),
                                       body=AsyncMock(return_value=spec.get("body", b"news")))
            self.events["response"](response)
            if "data_size" in spec:
                await self.network["Network.dataReceived"]({"dataLength": spec["data_size"]})
            if 300 <= response.status < 400:
                raise Error("redirect aborted by policy")

    class Context:
        def __init__(self, options):
            self.options = options
            self.close = AsyncMock()
            self.set_extra_http_headers = AsyncMock()
            contexts.append(self)

        async def new_page(self):
            return Page()

        async def new_cdp_session(self, page):
            return SimpleNamespace(send=AsyncMock(), on=lambda event, cb: page.network.update({event: cb}))

    async def new_context(**kwargs):
        return Context(kwargs)

    browser = SimpleNamespace(new_context=new_context, close=AsyncMock())
    engine = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)), stop=AsyncMock())
    monkeypatch.setattr("eu_cyber_news_scraper.browser_http.system_chrome", lambda: "/system/chrome")
    monkeypatch.setattr("eu_cyber_news_scraper.browser_http.async_playwright",
                        lambda: SimpleNamespace(start=AsyncMock(return_value=engine)))
    return SimpleNamespace(specs=specs, calls=calls, contexts=contexts, routes=routes, engine=engine, browser=browser)


def test_browser_checks_robots_and_blocks_page_resources(chrome):
    chrome.specs.update({
        "https://example.eu/robots.txt": {"body": b"User-agent: *\nDisallow: /private"},
        "https://example.eu/news": {"body": b"official news", "headers": {"content-type": "text/html"}},
    })
    stats = HttpStats()

    async def run():
        async with HttpClient(obey_robots=True) as client:
            response = await client.get("https://example.eu/news", browser_transport=True, stats=stats)
            assert response.text == "official news"
            with pytest.raises(RobotsDeniedError):
                await client.get("https://example.eu/private", browser_transport=True, stats=stats)

    asyncio.run(run())
    assert chrome.calls == ["https://example.eu/robots.txt", "https://example.eu/news"]
    assert stats.browser_requests == stats.request_count == 2
    for incoming, continued, aborted in chrome.routes:
        assert continued + aborted == 1
        if continued:
            assert incoming.url in chrome.calls and incoming.redirected_from is None
    assert sum(row[1] for row in chrome.routes) == 2
    options = chrome.contexts[1].options
    assert options["java_script_enabled"] is False
    assert options["service_workers"] == "block"
    assert options["accept_downloads"] is False
    assert "ignore_https_errors" not in options
    assert options["user_agent"].startswith("Chrome/Test eu-cyber-news-scraper/")
    chrome.browser.close.assert_awaited_once()
    chrome.engine.stop.assert_awaited_once()


def test_browser_redirect_does_not_download_disallowed_destination(chrome):
    chrome.specs.update({
        "https://example.eu/robots.txt": {"body": b"User-agent: *\nDisallow:"},
        "https://example.eu/news": {"status": 302, "headers": {"location": "https://other.eu/private"}},
        "https://other.eu/robots.txt": {"body": b"User-agent: *\nDisallow: /private"},
    })

    async def run():
        async with HttpClient(obey_robots=True) as client:
            with pytest.raises(RobotsDeniedError):
                await client.get("https://example.eu/news", browser_transport=True)

    asyncio.run(run())
    assert chrome.calls == ["https://example.eu/robots.txt", "https://example.eu/news", "https://other.eu/robots.txt"]
    assert len(chrome.contexts) == 3  # startup context plus isolated contexts for both origins


@pytest.mark.parametrize("status,body", [(403, b"blocked"), (200, b"<html>Browser Validation Page</html>")])
def test_browser_still_stops_when_robots_unreadable(chrome, status, body):
    chrome.specs["https://example.eu/robots.txt"] = {"status": status, "body": body}

    async def run():
        async with HttpClient(obey_robots=True) as client:
            with pytest.raises(RobotsUnavailableError):
                await client.get("https://example.eu/news", browser_transport=True)

    asyncio.run(run())
    assert chrome.calls == ["https://example.eu/robots.txt"]


@pytest.mark.parametrize("spec", [
    {"body": b"too large"}, {"headers": {"content-length": "100"}}, {"data_size": 100},
])
def test_browser_enforces_byte_limit(chrome, spec):
    chrome.specs["https://example.eu/news"] = spec

    async def run():
        async with httpx.AsyncClient(transport=BrowserHttpTransport(4)) as client:
            with pytest.raises(BrowserResponseTooLargeError):
                await client.get("https://example.eu/news")

    asyncio.run(run())


def test_browser_reports_certificate_failure_without_changing_tls_policy(chrome):
    chrome.specs["https://example.eu/news"] = {"error": "net::ERR_CERT_AUTHORITY_INVALID"}

    async def run():
        async with httpx.AsyncClient(transport=BrowserHttpTransport(100)) as client:
            with pytest.raises(httpx.ConnectError, match="ERR_CERT_AUTHORITY_INVALID"):
                await client.get("https://example.eu/news")

    asyncio.run(run())


def test_browser_timeout_remains_a_timeout_for_metrics_and_retry(chrome):
    chrome.specs["https://example.eu/news"] = {"error": "Timeout exceeded", "exception": TimeoutError}

    async def run():
        async with httpx.AsyncClient(transport=BrowserHttpTransport(100)) as client:
            with pytest.raises(httpx.ReadTimeout):
                await client.get("https://example.eu/news")

    asyncio.run(run())


@pytest.mark.parametrize("method,url", [("POST", "https://example.eu/"), ("GET", "http://example.eu/")])
def test_browser_rejects_unsupported_requests(chrome, method, url):
    async def run():
        async with httpx.AsyncClient(transport=BrowserHttpTransport(100)) as client:
            with pytest.raises(httpx.UnsupportedProtocol):
                await client.request(method, url)

    asyncio.run(run())
    assert not chrome.calls


def test_system_chrome_missing_has_actionable_error(monkeypatch):
    monkeypatch.setattr("eu_cyber_news_scraper.browser_http.Path.is_file", lambda _self: False)
    with pytest.raises(RuntimeError, match="CHROME_PATH"):
        system_chrome()


def test_browser_policy_is_declared_only_for_the_four_affected_sources():
    sources = load_sources()
    assert {source.id for source in sources if source.browser_transport} == {
        "de_bmi", "eu_dg_connect", "eu_eeas", "fr_viginum",
    }
    for changes, message in [({"browser_transport": "yes"}, "must be boolean"),
                             ({"browser_transport": True, "tls_intermediate_bundle": "custom.pem"}, "custom TLS")]:
        with pytest.raises(ValueError, match=message):
            _validate_sources([replace(sources[0], **changes)])
