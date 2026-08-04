from __future__ import annotations

import asyncio
import ssl
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
import truststore

from .config import DEFAULT_HTTP_CONCURRENCY, DEFAULT_TIMEOUT, USER_AGENT

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ResponseTooLargeError(RuntimeError):
    pass


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

    async def get(
        self,
        url: str,
        *,
        stats: HttpStats | None = None,
        ssl_bundle: str = "",
        user_agent: str = "",
    ) -> httpx.Response:
        metrics = stats or HttpStats()
        host = (urlsplit(url).hostname or "").casefold()
        host_limiter = self._host_limiters.setdefault(host, asyncio.Semaphore(self._per_host_limit))
        last_error: Exception | None = None
        for attempt in range(2):
            response: httpx.Response | None = None
            metrics.request_count += 1
            try:
                async with self._global_limiter, host_limiter:
                    response = await self._read_response(
                        url,
                        self._client_for_bundle(ssl_bundle),
                        user_agent=user_agent,
                    )
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

    def _new_client(self, verify: ssl.SSLContext) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers,
            follow_redirects=True,
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
    ) -> httpx.Response:
        timeout = httpx.Timeout(self.timeout, connect=min(8, self.timeout))
        request_headers = {"User-Agent": user_agent} if user_agent else None
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


def _retry_delay(response: httpx.Response | None) -> float:
    if response is not None:
        value = response.headers.get("retry-after", "")
        try:
            return min(2.0, max(0.0, float(value)))
        except ValueError:
            pass
    return 0.5
