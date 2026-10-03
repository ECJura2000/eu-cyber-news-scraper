import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from eu_cyber_news_scraper.http import (
    HttpClient,
    HttpStats,
    RetryDeferredError,
    RobotsDeniedError,
    RobotsUnavailableError,
    _retry_delay,
)
from eu_cyber_news_scraper.http_cache import ResponseCache
from eu_cyber_news_scraper.robots import RobotsPolicy


@pytest.mark.parametrize("use_cache", [False, True])
def test_cookie_names_shared_across_sites_and_paths_do_not_conflict(tmp_path, use_cache):
    calls = []

    async def handler(request):
        calls.append((request.url.host, request.headers.get("cookie", "")))
        return httpx.Response(200, text="news", headers={
            "set-cookie": f"session={request.url.host}; Path=/",
        }, request=request)

    async def run():
        async with HttpClient(cache_dir=tmp_path if use_cache else None,
                              transport=httpx.MockTransport(handler)) as client:
            await client.get("https://one.eu/news")
            await client.get("https://two.eu/news")
            await client.get("https://one.eu/news")
            await client.get("https://two.eu/news")

    asyncio.run(run())
    assert calls == [("one.eu", ""), ("two.eu", ""),
                     ("one.eu", "session=one.eu"), ("two.eu", "session=two.eu")]


@pytest.mark.parametrize("url,allowed", [
    ("https://example.eu/private", False),
    ("https://example.eu/private/public", True),
    ("https://example.eu/public", True),
    ("https://example.eu/a/file.pdf", False),
    ("https://example.eu/a/file.pdf?x=1", True),
    ("https://example.eu/caf%C3%A9", False),
    ("https://example.eu/%70rivate", False),
    ("https://example.eu/robots.txt", True),
])
def test_robots_merges_groups_and_uses_longest_octet_match(url, allowed):
    policy = RobotsPolicy.parse("""User-agent: *
Disallow: /
User-agent: EU-CYBER-NEWS-SCRAPER
Disallow: /private
Allow: /private/public
Disallow: /*.pdf$
Crawl-delay: 1
User-agent: eu-cyber-news-scraper
Disallow: /café
Crawl-delay: invalid
""")
    assert policy.allows(url) is allowed
    assert policy.crawl_delay == 1


def test_robots_fallback_empty_records_and_allow_tie():
    policy = RobotsPolicy.parse("""broken
User-agent: *
Disallow:
Disallow: /same
Allow: /same
Crawl-delay: -1
Crawl-delay: inf
Sitemap: https://example.eu/sitemap.xml
User-agent: OtherBot
Disallow: /
""")
    assert policy.allows("https://example.eu/same")
    assert policy.allows("https://example.eu/")
    assert policy.crawl_delay == 0
    assert RobotsPolicy.parse("User-agent: OtherBot\nDisallow: /").allows("https://example.eu/")


def test_robots_is_fetched_once_and_disallowed_paths_never_downloaded():
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private", request=request)
        return httpx.Response(200, text="news", request=request)

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            await client.get("https://example.eu/news")
            await client.get("https://example.eu/news2")
            with pytest.raises(RobotsDeniedError):
                await client.get("https://example.eu/private")
    asyncio.run(run())
    assert calls == ["https://example.eu/robots.txt", "https://example.eu/news", "https://example.eu/news2"]


@pytest.mark.parametrize("status,html,exception", [
    (404, False, None), (403, False, RobotsDeniedError),
    (500, False, RobotsUnavailableError), (200, True, RobotsUnavailableError),
])
def test_robots_http_error_policy(status, html, exception, monkeypatch):
    async def no_sleep(_):
        pass
    monkeypatch.setattr("eu_cyber_news_scraper.http.asyncio.sleep", no_sleep)

    async def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(status, text="<html>challenge</html>" if html else "error",
                                  headers={"content-type": "text/html" if html else "text/plain"}, request=request)
        return httpx.Response(200, text="news", request=request)

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            return await client.get("https://example.eu/news")
    if exception:
        with pytest.raises(exception):
            asyncio.run(run())
    else:
        assert asyncio.run(run()).text == "news"


def test_retry_after_accepts_full_seconds_and_http_dates():
    response = httpx.Response(429, headers={"retry-after": "120"})
    assert _retry_delay(response) == 120
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    response = httpx.Response(503, headers={"retry-after": format_datetime(future, usegmt=True)})
    assert 118 < _retry_delay(response) <= 120
    assert .5 <= _retry_delay(httpx.Response(503, headers={"retry-after": "broken"})) <= .75
    assert .5 <= _retry_delay(None) <= .75


@pytest.mark.parametrize("content_type", ["text/plain", "text/html;charset=utf-8"])
def test_plain_robots_with_mislabelled_html_mime_keeps_disallowed_paths(content_type):
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="\ufeffUser-agent: *\nDisallow: /SiteGlobals\n",
                                  headers={"content-type": content_type}, request=request)
        return httpx.Response(200, text="news", request=request)

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            await client.get("https://agency.example/DE/Presse/news.html")
            with pytest.raises(RobotsDeniedError):
                await client.get("https://agency.example/SiteGlobals/feed.xml")

    asyncio.run(run())
    assert calls == ["/robots.txt", "/DE/Presse/news.html"]


@pytest.mark.parametrize("body", [
    "<html><pre>\nUser-agent: *\nAllow: /\n</pre></html>",
    "<!-- challenge -->\n<script>check()</script>\nUser-agent: *\nAllow: /",
    'User-agent: *\n<div class="cf-chl-container">Checking your browser</div>',
    'User-agent: *\n<span>Access denied</span>',
    'User-agent: *\n<!-- challenge with no visible markup -->',
    'User-agent: *\n<?xml version="1.0"?><response>Forbidden</response>',
    "Access denied", "",
])
def test_html_robot_documents_and_empty_html_fail_closed(body):
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"}, request=request)

    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RobotsUnavailableError):
                await client.get("https://agency.example/news")

    asyncio.run(run())
    assert calls == ["/robots.txt"]


def test_long_retry_after_defers_all_requests_to_same_host():
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "120"}, request=request)
    async def run():
        async with HttpClient(transport=httpx.MockTransport(handler)) as client:
            for path in ("/one", "/two"):
                with pytest.raises(RetryDeferredError):
                    await client.get("https://example.eu" + path)
    asyncio.run(run())
    assert len(calls) == 1


def test_retry_exhaustion_keeps_fresh_retry_after_for_other_host_requests():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "0" if len(calls) == 1 else "120"}, request=request)

    async def run():
        async with HttpClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get("https://example.eu/one")
            with pytest.raises(RetryDeferredError):
                await client.get("https://example.eu/two")

    asyncio.run(run())
    assert len(calls) == 2


def test_conditional_cache_revalidates_across_clients_and_keeps_body(tmp_path):
    headers_seen = []
    async def handler(request):
        headers_seen.append(dict(request.headers))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'}, request=request)
        return httpx.Response(200, content=b"official news", headers={"etag": '"v1"'}, request=request)
    async def run():
        transport = httpx.MockTransport(handler)
        stats = HttpStats()
        async with HttpClient(cache_dir=tmp_path, transport=transport) as client:
            first = await client.get("https://example.eu/news", stats=stats)
        async with HttpClient(cache_dir=tmp_path, transport=transport) as client:
            second = await client.get("https://example.eu/news", stats=stats)
        return first, second, stats
    first, second, stats = asyncio.run(run())
    assert first.content == second.content == b"official news"
    assert second.extensions["cache_revalidated"] is True
    assert stats.cache_hits == 1
    assert stats.statuses == ["200", "304"]
    assert stats.bytes_downloaded == len(first.content)
    assert headers_seen[1]["if-none-match"] == '"v1"'


def test_last_modified_and_changed_content_refresh_cache(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, text=str(len(calls)), headers={"last-modified": "Mon, 28 Sep 2026 12:00:00 GMT"},
                              request=request)
    async def run():
        async with HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)) as client:
            await client.get("https://example.eu/news")
            return await client.get("https://example.eu/news")
    assert asyncio.run(run()).text == "2"
    assert "if-modified-since" in calls[1].headers


def test_uncached_304_is_error():
    async def handler(request):
        return httpx.Response(304, request=request)
    async def run():
        async with HttpClient(transport=httpx.MockTransport(handler)) as client:
            await client.get("https://example.eu/news")
    with pytest.raises(httpx.HTTPStatusError, match="304 without"):
        asyncio.run(run())


def test_redirect_checks_destination_robots_before_fetch():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if request.url.host == "blocked.eu":
            assert request.url.path == "/robots.txt"
            return httpx.Response(200, text="User-agent: *\nDisallow: /", request=request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, request=request)
        return httpx.Response(302, headers={"location": "https://blocked.eu/news"}, request=request)
    async def run():
        async with HttpClient(obey_robots=True, transport=httpx.MockTransport(handler)) as client:
            await client.get("https://example.eu/news")
    with pytest.raises(RobotsDeniedError):
        asyncio.run(run())
    assert calls[-1] == "https://blocked.eu/robots.txt"


@pytest.mark.parametrize("destination,error", [("http://example.eu/next", httpx.InvalidURL),
                                                ("https://example.eu/loop", httpx.TooManyRedirects)])
def test_https_downgrade_and_redirect_loop_are_rejected(destination, error):
    async def handler(request):
        return httpx.Response(302, headers={"location": destination}, request=request)
    async def run():
        async with HttpClient(transport=httpx.MockTransport(handler)) as client:
            await client.get("https://example.eu/news")
    with pytest.raises(error):
        asyncio.run(run())


def test_same_host_request_starts_are_spaced():
    times = []
    async def handler(request):
        times.append(asyncio.get_running_loop().time())
        return httpx.Response(200, request=request)
    async def run():
        async with HttpClient(min_interval=.02, transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(*(client.get(f"https://example.eu/{i}") for i in range(3)))
    asyncio.run(run())
    assert all(right - left >= .018 for left, right in zip(times, times[1:]))


def test_cache_prunes_and_rejects_corruption_and_unstoreable_responses(tmp_path):
    cache = ResponseCache(tmp_path, max_bytes=10)
    def response(url, **headers):
        return httpx.Response(200, content=b"12345678", headers={"etag": '"v1"', **headers},
                              request=httpx.Request("GET", url))
    cache.save(response("https://example.eu/one"), "variant")
    cache.save(response("https://example.eu/two"), "variant")
    assert cache.load("https://example.eu/one", "variant") is None
    assert cache.load("https://example.eu/two", "variant") is not None
    cache.connection.execute("UPDATE responses SET body = ?", (b"tampered",))
    cache.connection.commit()
    assert cache.load("https://example.eu/two", "variant") is None
    for headers in ({"cache-control": "no-store"}, {"vary": "*"}, {"set-cookie": "a=b"}, {"vary": "X-Private"}):
        cache.save(response("https://example.eu/private", **headers), "variant")
        assert cache.load("https://example.eu/private", "variant") is None
    cache.save(response("https://example.eu/corrupt"), "variant")
    cache.connection.execute("UPDATE responses SET headers = ?", ("[]",))
    cache.connection.commit()
    assert cache.load("https://example.eu/corrupt", "variant") is None
    cache.close()
