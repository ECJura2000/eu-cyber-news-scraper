from __future__ import annotations

import asyncio
import random
import re
import ssl
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
import truststore

from .config import DEFAULT_HTTP_CONCURRENCY, DEFAULT_TIMEOUT, USER_AGENT
from .http_cache import ResponseCache
from .robots import RobotsPolicy

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ResponseTooLargeError(RuntimeError):
    pass


class RobotsDeniedError(RuntimeError):
    pass


class RobotsUnavailableError(RuntimeError):
    pass


class RetryDeferredError(RuntimeError):
    """The server requires a delay longer than this run's bounded retry wait."""


class _Decoder(Protocol):
    @property
    def unconsumed_tail(self) -> bytes: ...

    def decompress(self, data: bytes, max_length: int = 0) -> bytes: ...

    def flush(self, length: int = ...) -> bytes: ...


@dataclass
class HttpStats:
    request_count: int = 0
    bytes_downloaded: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    cache_hits: int = 0
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
        obey_robots: bool = False,
        min_interval: float = 0.0,
        cache_dir: Path | None = None,
        max_retry_wait: float = 30.0,
    ) -> None:
        self.timeout = max(1, timeout)
        self.max_response_bytes = max_response_bytes
        self._global_limiter = asyncio.Semaphore(max_connections)
        self._per_host_limit = per_host
        self._host_limiters: dict[str, asyncio.Semaphore] = {}
        self.obey_robots = obey_robots
        self.min_interval = max(0.0, min_interval)
        self.max_retry_wait = max(0.0, max_retry_wait)
        self._host_clocks: dict[str, float] = {}
        self._host_delays: dict[str, float] = {}
        self._host_cooldowns: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, tuple[float, RobotsPolicy | str]] = {}
        self._cache = ResponseCache(cache_dir) if cache_dir is not None else None
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,fr,de;q=0.9",
            # Several public-sector CDNs mislabel compressed payloads.
            # Requesting identity encoding keeps streaming size checks reliable.
            "Accept-Encoding": "identity",
        }
        self._limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
        self._transport = transport
        self._client = self._new_client(truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
        self._special_clients: dict[str, httpx.AsyncClient] = {}

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()
        await asyncio.gather(*(client.aclose() for client in self._special_clients.values()))
        if self._cache:
            self._cache.close()

    async def get(
        self,
        url: str,
        *,
        stats: HttpStats | None = None,
        ssl_bundle: str = "",
        user_agent: str = "",
        _check_robots: bool = True,
        redirect_guard: Callable[[str], bool] | None = None,
    ) -> httpx.Response:
        metrics = stats or HttpStats()
        original_https = urlsplit(url).scheme == "https"
        history: list[httpx.Response] = []
        for _hop in range(11):
            if redirect_guard is not None and not redirect_guard(url):
                raise httpx.InvalidURL("Request or redirect target is outside source scope")
            if urlsplit(url).scheme not in {"http", "https"}:
                raise httpx.InvalidURL(f"unsupported redirect scheme: {url}")
            if self.obey_robots and _check_robots:
                await self._ensure_robots(url, metrics, ssl_bundle, user_agent, redirect_guard)
            response = await self._get_with_retry(url, metrics, ssl_bundle, user_agent)
            if response.has_redirect_location:
                history.append(response)
                url = str(response.url.join(response.headers["location"]))
                if original_https and urlsplit(url).scheme != "https":
                    raise httpx.InvalidURL(f"HTTPS redirect downgrade: {url}")
                continue
            response.history = history
            return response
        raise httpx.TooManyRedirects("too many redirects", request=httpx.Request("GET", url))

    async def _get_with_retry(
        self, url: str, metrics: HttpStats, ssl_bundle: str, user_agent: str,
    ) -> httpx.Response:
        host = (urlsplit(url).hostname or "").casefold()
        host_limiter = self._host_limiters.setdefault(host, asyncio.Semaphore(self._per_host_limit))
        # Cookie names need not be unique across domains or paths. Cookies.items()
        # raises CookieConflict in that normal case for a multi-site crawler.
        cookies = repr(sorted(
            (cookie.domain, cookie.path, cookie.name, cookie.value)
            for cookie in self._client_for_bundle(ssl_bundle).cookies.jar
        )) if self._cache else ""
        variant = (user_agent or USER_AGENT) + "\n" + ssl_bundle + "\n" + self._headers["Accept-Language"] + cookies
        cached = self._cache.load(url, variant) if self._cache else None
        conditional: dict[str, str] = {}
        if cached is not None:
            if cached.headers.get("etag"):
                conditional["If-None-Match"] = cached.headers["etag"]
            elif cached.headers.get("last-modified"):
                conditional["If-Modified-Since"] = cached.headers["last-modified"]
        last_error: Exception | None = None
        for attempt in range(2):
            response: httpx.Response | None = None
            try:
                async with host_limiter:
                    await self._pace(host)
                    async with self._global_limiter:
                        metrics.request_count += 1
                        response = await self._read_response(
                            url,
                            self._client_for_bundle(ssl_bundle),
                            user_agent=user_agent,
                            headers=conditional,
                        )
                metrics.statuses.append(str(response.status_code))
                metrics.bytes_downloaded += len(response.content)
                if response.status_code == 304:
                    if cached is None:
                        raise httpx.HTTPStatusError("304 without cached content", request=response.request,
                                                    response=response)
                    merged = httpx.Headers(cached.headers)
                    merged.update(response.headers)
                    response = httpx.Response(200, headers=merged, content=cached.content,
                                              request=response.request, extensions={"cache_revalidated": True})
                    metrics.cache_hits += 1
                if self._cache and response.status_code == 200:
                    self._cache.save(response, variant)
                if attempt == 1 and response.status_code in RETRYABLE_STATUSES and response.headers.get("retry-after"):
                    # Exhausting this request's retries does not release other
                    # requests from a fresh server-specified origin cooldown.
                    delay = _retry_delay(response, attempt)
                    self._host_cooldowns[host] = max(self._host_cooldowns.get(host, 0.0), time.monotonic() + delay)
                if response.status_code not in RETRYABLE_STATUSES or attempt == 1:
                    if not response.has_redirect_location:
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
            delay = _retry_delay(response, attempt)
            self._host_cooldowns[host] = max(self._host_cooldowns.get(host, 0.0), time.monotonic() + delay)
            if delay > self.max_retry_wait:
                raise RetryDeferredError(f"{host}: Retry-After requires {delay:.1f}s; request deferred")
            await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    async def _pace(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            cooldown = self._host_cooldowns.get(host, 0.0) - time.monotonic()
            if cooldown > self.max_retry_wait:
                raise RetryDeferredError(f"{host}: origin is cooling down for {cooldown:.1f}s")
            ready = max(self._host_clocks.get(host, 0.0), self._host_cooldowns.get(host, 0.0))
            remaining = ready - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._host_clocks[host] = time.monotonic() + max(self.min_interval, self._host_delays.get(host, 0.0))

    async def _ensure_robots(self, url: str, stats: HttpStats, bundle: str, user_agent: str,
                             redirect_guard: Callable[[str], bool] | None = None) -> None:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        key = origin + "\n" + user_agent + "\n" + bundle
        lock = self._robots_locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._robots.get(key)
            if entry is None or time.monotonic() - entry[0] >= 86400:
                policy: RobotsPolicy | str
                try:
                    response = await self.get(origin + "/robots.txt", stats=stats, ssl_bundle=bundle,
                                              user_agent=user_agent, _check_robots=False,
                                              redirect_guard=redirect_guard)
                    content_type = response.headers.get("content-type", "").casefold()
                    text = response.text.lstrip("\ufeff")
                    # Some official servers label plain robots rules text/html.
                    # A MIME mismatch must not hide valid Disallow rules, while
                    # actual HTML/challenges still fail closed, even if they
                    # contain a robots-looking line inside their document.
                    has_agent = re.search(r"(?im)^\s*user-agent\s*:\s*\S+", text) is not None
                    has_markup = (text.lstrip().startswith("<")
                                  or re.search(r"<\s*(?:/?[a-z][\w:-]*\b|[!?])", text, re.I) is not None)
                    if has_markup or ("html" in content_type and not has_agent):
                        policy = "robots.txt returned HTML/challenge content"
                    else:
                        policy = RobotsPolicy.parse(text)
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    if 400 <= code < 500 and code != 429:
                        policy = RobotsPolicy(((False, "/"),)) if code in {401, 403} else RobotsPolicy()
                    else:
                        policy = f"robots.txt unreachable: HTTP {code}"
                except (httpx.HTTPError, ResponseTooLargeError, RetryDeferredError) as exc:
                    policy = f"robots.txt unreachable: {type(exc).__name__}: {exc}"
                entry = (time.monotonic(), policy)
                self._robots[key] = entry
            selected = entry[1]
            if isinstance(selected, str):
                raise RobotsUnavailableError(f"{origin}: {selected}")
            self._host_delays[parsed.hostname or ""] = max(self.min_interval, selected.crawl_delay)
            if not selected.allows(url):
                raise RobotsDeniedError(f"robots.txt disallows: {url}")

    def _new_client(self, verify: ssl.SSLContext) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers,
            follow_redirects=False,
            verify=verify,
            limits=self._limits,
            transport=self._transport,
        )

    def _client_for_bundle(self, bundle: str) -> httpx.AsyncClient:
        if not bundle:
            return self._client
        if bundle not in self._special_clients:
            self._special_clients[bundle] = self._new_client(_ssl_context_with_intermediate(bundle))
        return self._special_clients[bundle]

    async def _read_response(
        self,
        url: str,
        client: httpx.AsyncClient,
        *,
        user_agent: str = "",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        timeout = httpx.Timeout(self.timeout, connect=min(8, self.timeout))
        request_headers = dict(headers or {})
        if user_agent:
            request_headers["User-Agent"] = user_agent
        async with client.stream("GET", url, timeout=timeout, headers=request_headers) as streamed:
            content_length = streamed.headers.get("content-length")
            try:
                declared_size = int(content_length) if content_length else 0
            except ValueError:
                declared_size = 0
            if declared_size > self.max_response_bytes:
                raise ResponseTooLargeError(f"response exceeds {self.max_response_bytes} bytes: {url}")
            decoder = _content_decoder(streamed.headers.get("content-encoding", ""))
            chunks: list[bytes] = []
            size = 0
            encoded_size = 0

            def append_chunk(raw_chunk: bytes) -> None:
                nonlocal encoded_size, size
                encoded_size += len(raw_chunk)
                if encoded_size > self.max_response_bytes:
                    raise ResponseTooLargeError(f"response exceeds {self.max_response_bytes} bytes: {url}")
                chunk = _decompress_limited(decoder, raw_chunk, self.max_response_bytes - size, url)
                size += len(chunk)
                chunks.append(chunk)

            if streamed.is_stream_consumed:
                # Mock/custom transports may hand httpx an already-decoded body
                # while retaining the original Content-Encoding header.
                decoder = None
                append_chunk(streamed.content)
            else:
                async for raw_chunk in streamed.aiter_raw():
                    append_chunk(raw_chunk)
            if decoder is not None:
                tail = decoder.flush(self.max_response_bytes - size + 1)
                size += len(tail)
                if size > self.max_response_bytes:
                    raise ResponseTooLargeError(f"response exceeds {self.max_response_bytes} bytes: {url}")
                chunks.append(tail)
            response_headers = httpx.Headers(streamed.headers)
            response_headers.pop("content-encoding", None)
            response_headers.pop("content-length", None)
            return httpx.Response(
                streamed.status_code,
                headers=response_headers,
                content=b"".join(chunks),
                request=streamed.request,
            )


def _ssl_context_with_intermediate(bundle: str) -> ssl.SSLContext:
    if Path(bundle).name != bundle:
        raise ValueError(f"invalid TLS intermediate bundle: {bundle}")
    certificate = Path(__file__).with_name("certificates") / bundle
    if not certificate.is_file():
        raise ValueError(f"unknown TLS intermediate bundle: {bundle}")
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(certificate))
    return context


def _content_decoder(encoding: str) -> _Decoder | None:
    normalized = encoding.casefold().strip()
    if not normalized or normalized == "identity":
        return None
    if normalized == "gzip":
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if normalized == "deflate":
        return zlib.decompressobj()
    raise httpx.DecodingError(f"unsupported content encoding: {encoding}")


def _decompress_limited(
    decoder: _Decoder | None,
    chunk: bytes,
    remaining: int,
    url: str,
) -> bytes:
    if decoder is None:
        if len(chunk) > remaining:
            raise ResponseTooLargeError(f"response exceeds limit: {url}")
        return chunk
    try:
        decoded = decoder.decompress(chunk, remaining + 1)
    except zlib.error as exc:
        raise httpx.DecodingError(f"invalid compressed response from {url}: {exc}") from exc
    if len(decoded) > remaining or decoder.unconsumed_tail:
        raise ResponseTooLargeError(f"decompressed response exceeds limit: {url}")
    return decoded


def _retry_delay(response: httpx.Response | None, attempt: int = 0) -> float:
    if response is not None:
        value = response.headers.get("retry-after", "")
        try:
            if value.strip().isdigit():
                return max(0.0, float(value))
            if value:
                moment = parsedate_to_datetime(value)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=timezone.utc)
                return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
        except ValueError:
            pass
    return float(0.5 * (2 ** attempt) + random.uniform(0.0, 0.25))
