import asyncio

import httpx
import pytest

from eu_cyber_news_scraper.http import HttpClient, HttpStats, ResponseTooLargeError


def test_http_client_reuses_async_client_and_records_metrics():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b"ok", request=request)

    async def run():
        stats = HttpStats()
        async with HttpClient(timeout=7, transport=httpx.MockTransport(handler)) as client:
            first = await client.get("https://example.eu/one", stats=stats)
            second = await client.get("https://example.eu/two", stats=stats)
        return first, second, stats

    first, second, stats = asyncio.run(run())
    assert first.text == second.text == "ok"
    assert len(requests) == 2
    assert requests[0].headers["user-agent"].startswith("Mozilla/5.0")
    assert requests[0].headers["accept-encoding"] == "identity"
    assert stats.request_count == 2
    assert stats.bytes_downloaded == 4
    assert stats.statuses == ["200", "200"]


def test_http_client_retries_once_for_idempotent_server_failure(monkeypatch):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, content=b"ok", request=request)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("eu_cyber_news_scraper.http.asyncio.sleep", no_sleep)

    async def run():
        stats = HttpStats()
        async with HttpClient(transport=httpx.MockTransport(handler)) as client:
            response = await client.get("https://example.eu/retry", stats=stats)
        return response, stats

    response, stats = asyncio.run(run())
    assert response.status_code == 200
    assert stats.request_count == 2
    assert stats.retry_count == 1
    assert stats.statuses == ["503", "200"]


def test_http_client_rejects_large_response_from_declared_length():
    async def handler(request):
        return httpx.Response(200, headers={"content-length": "11"}, content=b"x" * 11, request=request)

    async def run():
        async with HttpClient(max_response_bytes=10, transport=httpx.MockTransport(handler)) as client:
            await client.get("https://example.eu/large")

    with pytest.raises(ResponseTooLargeError):
        asyncio.run(run())


def test_http_client_limits_each_host_to_two_concurrent_requests():
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return httpx.Response(200, content=b"ok", request=request)

    async def run():
        async with HttpClient(per_host=2, transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(*(client.get(f"https://example.eu/{index}") for index in range(6)))

    asyncio.run(run())
    assert peak == 2
