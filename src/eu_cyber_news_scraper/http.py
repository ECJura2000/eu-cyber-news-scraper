from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
import truststore

from .config import DEFAULT_HTTP_CONCURRENCY, DEFAULT_TIMEOUT, USER_AGENT

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ResponseTooLargeError(RuntimeError):
    pass


@dataclass
class HttpStats:
    request_count: int = 0
    bytes_downloaded: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    statuses: list[str] = field(default_factory=list)


class HttpClient:
    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        *,
        max_connections: int = DEFAULT_HTTP_CONCURRENCY,
        per_host: int = 2,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout = max(1, timeout)
        self.max_response_bytes = max_response_bytes
        self._global_limiter = asyncio.Semaphore(max_connections)
        self._per_host_limit = per_host
        self._host_limiters: dict[str, asyncio.Semaphore] = {}
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en,fr,de;q=0.9",
                # Several public-sector CDNs mislabel compressed payloads.
                # Requesting identity encoding keeps streaming size checks reliable.
                "Accept-Encoding": "identity",
            },
            follow_redirects=True,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
            transport=transport,
        )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, stats: HttpStats | None = None) -> httpx.Response:
        metrics = stats or HttpStats()
        host = (urlsplit(url).hostname or "").casefold()
        host_limiter = self._host_limiters.setdefault(host, asyncio.Semaphore(self._per_host_limit))
        last_error: Exception | None = None
        for attempt in range(2):
            response: httpx.Response | None = None
            metrics.request_count += 1
            try:
                async with self._global_limiter, host_limiter:
                    response = await self._read_response(url)
                metrics.statuses.append(str(response.status_code))
                metrics.bytes_downloaded += len(response.content)
                if response.status_code not in RETRYABLE_STATUSES or attempt == 1:
                    response.raise_for_status()
                    return response
                last_error = httpx.HTTPStatusError(
                    f"retryable HTTP status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if isinstance(exc, httpx.TimeoutException):
                    metrics.timeout_count += 1
                if attempt == 1:
                    raise
            metrics.retry_count += 1
            await asyncio.sleep(_retry_delay(response))
        assert last_error is not None
        raise last_error

    async def _read_response(self, url: str) -> httpx.Response:
        timeout = httpx.Timeout(self.timeout, connect=min(8, self.timeout))
        async with self._client.stream("GET", url, timeout=timeout) as streamed:
            content_length = streamed.headers.get("content-length")
            try:
                declared_size = int(content_length) if content_length else 0
            except ValueError:
                declared_size = 0
            if declared_size > self.max_response_bytes:
                raise ResponseTooLargeError(f"response exceeds {self.max_response_bytes} bytes: {url}")
            chunks: list[bytes] = []
            size = 0
            async for chunk in streamed.aiter_bytes():
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise ResponseTooLargeError(f"response exceeds {self.max_response_bytes} bytes: {url}")
                chunks.append(chunk)
            return httpx.Response(
                streamed.status_code,
                headers=streamed.headers,
                content=b"".join(chunks),
                request=streamed.request,
            )


def _retry_delay(response: httpx.Response | None) -> float:
    if response is not None:
        value = response.headers.get("retry-after", "")
        try:
            return min(2.0, max(0.0, float(value)))
        except ValueError:
            pass
    return 0.5
