"""Read-only source diagnostics and independently persisted promotion evidence.

Run with ``python -m eu_cyber_news_scraper.source_audit --help``. Observations
are immutable atomic JSON files, never production health or scheduling state.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import tempfile
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from .config import DEFAULT_DAYS, DEFAULT_TIMEOUT, load_sources_and_registry
from .http import HttpClient
from .models import Source, SourceResult
from .scraper import scrape_source

SCHEMA_VERSION = 1
MAX_FIXTURE_BYTES = 32768
_SENSITIVE = re.compile(r"token|secret|password|passwd|api[-_]?key|authorization|cookie|session|nonce|signature", re.I)
_CHALLENGE = re.compile(
    r"cf-chl-|/cdn-cgi/challenge-platform/|challenge-form|anubis_challenge|"
    r"<title[^>]*>\s*(?:just a moment|access denied|checking your browser|attention required|"
    r"verify you are human|captcha)", re.I,
)


class UnsafeUrlError(ValueError):
    """A request is unsafe or outside the source's expected domains."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical_host(host: str) -> str:
    return host.rstrip(".").encode("idna").decode("ascii").casefold()


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast and not address.is_reserved


def validate_url(url: str, expected_domains: Sequence[str] = ()) -> str:
    """Validate syntax and literal hosts before any HTTP/DNS operation."""
    try:
        if not url or re.search(r"[\s\x00-\x1f\x7f\\]", url):
            raise UnsafeUrlError("malformed_url")
        parts = urlsplit(url)
        if parts.scheme.casefold() != "https":
            raise UnsafeUrlError("https_required")
        if parts.username is not None or parts.password is not None:
            raise UnsafeUrlError("url_credentials")
        if not parts.hostname or parts.port not in {None, 443}:
            raise UnsafeUrlError("malformed_url")
        host = _canonical_host(parts.hostname)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (
                "." not in host or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
                or host == "localhost" or not re.fullmatch(r"[a-z0-9.-]+", host)
                or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                       for label in host.split("."))
            ):
                raise UnsafeUrlError("nonpublic_host") from None
        else:
            if not _public_address(host) or getattr(address, "ipv4_mapped", None) is not None:
                raise UnsafeUrlError("nonpublic_host")
        if expected_domains and not any(
            host == _canonical_host(domain) or host.endswith("." + _canonical_host(domain))
            for domain in expected_domains if domain
        ):
            raise UnsafeUrlError("unexpected_domain")
        return host
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, UnsafeUrlError):
            raise
        raise UnsafeUrlError("malformed_url") from exc


async def _validate_public_dns(host: str) -> None:
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not _public_address(str(item[4][0])) for item in addresses):
        raise UnsafeUrlError("nonpublic_host")


def expected_domains(source: Source) -> tuple[str, ...]:
    """Configured endpoint hosts are explicit; allow_domains permits redirects."""
    hosts = [*source.allow_domains]
    for url in (source.homepage, source.listing_url, *source.feed_urls):
        try:
            host = urlsplit(url).hostname
        except ValueError:
            continue
        if host:
            hosts.append(host)
    return tuple(dict.fromkeys(hosts))


class AuditHttpClient(HttpClient):
    """Use shared robots/TLS/rate limits with checks on every redirect request.

    httpx request hooks also guard discovered feeds and detail URLs during parse.
    DNS is checked before each request; this is not a DNS-pinning transport.
    """

    def __init__(self, *, timeout: int = DEFAULT_TIMEOUT, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._source: ContextVar[Source | None] = ContextVar("audit_source", default=None)
        self._failures: ContextVar[list[dict[str, Any]] | None] = ContextVar("audit_failures", default=None)
        super().__init__(timeout=timeout, transport=transport, obey_robots=True, min_interval=0.5)

    @property
    def source(self) -> Source | None:
        return self._source.get()

    @source.setter
    def source(self, value: Source) -> None:
        self._source.set(value)
        self._failures.set([])

    @property
    def failures(self) -> list[dict[str, Any]]:
        values = self._failures.get()
        if values is None:
            values = []
            self._failures.set(values)
        return values

    def _new_client(self, verify: ssl.SSLContext) -> httpx.AsyncClient:
        client = super()._new_client(verify)
        client.event_hooks["request"].append(self._guard_request)
        return client

    async def _guard_request(self, request: httpx.Request) -> None:
        host = validate_url(str(request.url), expected_domains(self.source) if self.source else ())
        await asyncio.wait_for(_validate_public_dns(host), timeout=self.timeout)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            validate_url(url, expected_domains(self.source) if self.source else ())
            response = await super().get(url, **kwargs)
            validate_url(str(response.url), expected_domains(self.source) if self.source else ())
            return response
        except Exception as exc:
            if kwargs.get("_check_robots", True):
                self.failures.append({"url": _safe_url(url), "error_code": _error_code(exc),
                                      "error_type": type(exc).__name__})
            raise


def _safe_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        query = urlencode([(key, "[redacted]" if _SENSITIVE.search(key) else value)
                           for key, value in parse_qsl(parts.query, keep_blank_values=True)])
        return urlunsplit((parts.scheme, host, parts.path, query, ""))
    except ValueError:
        return "[invalid URL]"


def _error_code(exc: Exception) -> str:
    if isinstance(exc, UnsafeUrlError):
        return exc.code
    names = {item.__name__ for item in type(exc).__mro__}
    if "RobotsDeniedError" in names:
        return "robots_denied"
    if "RobotsUnavailableError" in names:
        return "robots_unavailable"
    if "RetryDeferredError" in names:
        return "retry_deferred"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    cause: BaseException | None = exc
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, ssl.SSLError) or re.search(r"certificate|\bssl\b|\btls\b", str(cause), re.I):
            return "tls_failure"
        cause = cause.__cause__ or cause.__context__
    if isinstance(exc, socket.gaierror):
        return "dns_failure"
    if isinstance(exc, httpx.TooManyRedirects):
        return "redirect_loop"
    if isinstance(exc, httpx.InvalidURL):
        return "https_required" if "downgrade" in str(exc).casefold() else "malformed_url"
    if isinstance(exc, httpx.TransportError):
        return "transport_failure"
    return "request_failure"


def _error_detail(exc: Exception) -> str:
    """Bounded explanation with credentials and sensitive URL query values removed."""
    return re.sub(r"https?://[^\s\"']+", lambda match: _safe_url(match.group()), str(exc), flags=re.I)[:500]


def _content_error(response: httpx.Response, kind: str, source: Source) -> str:
    body = response.content
    sample = response.text[:131072]
    content_type = response.headers.get("content-type", "").casefold()
    if _CHALLENGE.search(sample):
        return "challenge_page"
    if not body.strip():
        return "empty_response"
    if kind == "feed":
        if "html" in content_type or re.search(r"<(?:!doctype\s+html|html)\b", sample, re.I):
            return "feed_received_html"
        # ElementTree never fetches external entities; reject all DTDs explicitly.
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            return "invalid_feed"
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return "invalid_feed"
        if root.tag.rsplit("}", 1)[-1].casefold() not in {"rss", "feed", "rdf"}:
            return "invalid_feed"
    else:
        if content_type and "html" not in content_type:
            return "expected_html"
        if not re.search(r"<(?:html|!doctype\s+html|head|body|main|a|div)\b", sample, re.I):
            return "expected_html"
        if kind == "listing" and len(body) < source.min_listing_bytes:
            return "undersized_listing"
    return ""


def config_hash(source: Source) -> str:
    encoded = json.dumps(asdict(source), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _capture(response: httpx.Response, endpoint: dict[str, Any], directory: Path) -> None:
    urls = [endpoint["url"], *(str(item.url) for item in response.history), str(response.url)]
    if any(urlsplit(url).scheme != "https" or _SENSITIVE.search(url) for url in urls):
        endpoint["fixture_skipped"] = "unsafe_or_sensitive_url"
        return
    # Do not persist request headers, cookies, credentials or token-bearing pages.
    text = response.text
    if _SENSITIVE.search(text) or re.search(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.", text):
        endpoint["fixture_skipped"] = "sensitive_content"
        return
    if not any(value in response.headers.get("content-type", "").casefold() for value in ("html", "xml")):
        endpoint["fixture_skipped"] = "unsupported_content_type"
        return
    content = text.encode("utf-8")[:MAX_FIXTURE_BYTES].decode("utf-8", errors="ignore").encode("utf-8")
    filename = hashlib.sha256(endpoint["url"].encode()).hexdigest() + ".txt"
    path = directory / filename
    _atomic_json_or_bytes(path, content)
    endpoint["fixture"] = {"path": str(path), "bytes": len(content), "truncated": len(content) < len(text.encode()),
                           "sha256": hashlib.sha256(content).hexdigest()}


async def check_endpoint(
    client: HttpClient, source: Source, kind: str, url: str, *, fixture_dir: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    endpoint: dict[str, Any] = {"kind": kind, "url": _safe_url(url), "healthy": False, "http_status": None,
                                "final_url": "", "redirects": [], "error_code": "", "error_type": ""}
    try:
        validate_url(url, expected_domains(source))
        response = await client.get(url, ssl_bundle=source.tls_intermediate_bundle, user_agent=source.user_agent)
        endpoint.update(http_status=response.status_code, final_url=_safe_url(str(response.url)),
                        content_type=response.headers.get("content-type", ""), bytes=len(response.content),
                        redirects=[{"url": _safe_url(str(item.url)), "http_status": item.status_code,
                                    "location": _safe_url(str(item.url.join(item.headers["location"])))
                                    if item.has_redirect_location else ""}
                                   for item in response.history])
        for redirected in (*response.history, response):
            validate_url(str(redirected.url), expected_domains(source))
        response.raise_for_status()
        endpoint["error_code"] = _content_error(response, kind, source)
        endpoint["healthy"] = not endpoint["error_code"]
        if fixture_dir is not None:
            _capture(response, endpoint, fixture_dir)
    except Exception as exc:
        endpoint.update(error_code=_error_code(exc), error_type=type(exc).__name__, error=_error_detail(exc))
        if isinstance(exc, httpx.HTTPStatusError):
            endpoint.update(http_status=exc.response.status_code, final_url=_safe_url(str(exc.response.url)))
    finally:
        endpoint["duration_seconds"] = round(time.monotonic() - started, 6)
    return endpoint


def assess_parse(result: SourceResult, *, observed_at: datetime) -> dict[str, Any]:
    raw = result.status.raw_count
    articles = result.parsed_articles if result.parsed_articles is not None else result.articles
    count = len(articles)
    high = sum(item.published_at is not None and item.date_confidence == "high" for item in articles)
    conflicts = sum(item.date_conflict for item in articles)
    future = max(result.status.invalid_date_count, result.status.unexplained_future_date_count,
                 sum(item.published_at is not None and item.published_at > observed_at for item in articles))
    undated = max(raw - result.status.dated_count, sum(item.published_at is None for item in articles))
    complete = raw > 0 and count == raw
    return {"executed": True, "source_status": asdict(result.status), "success": result.status.success,
            "fresh": result.status.freshness_status == "fresh",
            "raw_count": raw, "assessed_count": count, "assessment_complete": complete,
            "high_confidence_date_rate": high / raw if raw > 0 else 0.0,
            "conflict_rate": conflicts / raw if raw > 0 else 0.0,
            "future_count": future, "undated_count": undated,
            "missing_required_count": undated if result.source.date_policy == "required" else 0}


def _qualifies(observation: dict[str, Any]) -> bool:
    assessment = observation.get("parse") or {}
    endpoints = observation.get("endpoints") or []
    return bool(
        observation.get("healthy") is True and endpoints and all(item.get("healthy") is True for item in endpoints)
        and assessment.get("executed") is True and assessment.get("success") is True
        and assessment.get("fresh") is True
        and assessment.get("raw_count", 0) > 0 and assessment.get("assessment_complete") is True
        and assessment.get("high_confidence_date_rate", 0) >= 0.75
        and assessment.get("conflict_rate", 1) <= 0.05
        and assessment.get("future_count", 1) == 0 and assessment.get("missing_required_count", 1) == 0
        and not observation.get("parse_request_failures")
    )


def promotion_evidence(observation: dict[str, Any], history: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Count distinct qualifying executions in the current uninterrupted config era."""
    source_id = observation["source_id"]
    current_hash = observation["config_hash"]
    by_run = {item["run_id"]: item for item in history if item.get("source_id") == source_id}
    by_run.setdefault(observation["run_id"], observation)
    ordered = sorted(by_run.values(), key=lambda item: (item["timestamp"], item["run_id"]))
    successes: list[str] = []
    for item in ordered:
        if item.get("config_hash") != current_hash:
            successes.clear()
        elif _qualifies(item):
            successes.append(item["run_id"])
        else:
            successes.clear()
    eligible = _qualifies(observation) and len(successes) >= 3
    return {"promotion_eligible": eligible, "successful_parse_executions": len(successes),
            "required_executions": 3, "evidence_run_ids": successes,
            "suggestion": "review_for_promotion" if eligible else "continue_observation",
            "automatic_schedule_changes": False,
            "remaining_checks": ["complete_workflow_quality", "translation", "artifacts", "same_run_state_observation"]}


def _atomic_json_or_bytes(path: Path, payload: dict[str, Any] | bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = payload if isinstance(payload, bytes) else (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".audit-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                pass
        else:
            os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def persist_observation(history_dir: Path, observation: dict[str, Any]) -> list[dict[str, Any]]:
    # Hash both keys, so user-supplied source/run identifiers cannot traverse paths.
    directory = history_dir / hashlib.sha256(observation["source_id"].encode()).hexdigest()
    path = directory / (hashlib.sha256(observation["run_id"].encode()).hexdigest() + ".json")
    _atomic_json_or_bytes(path, observation, immutable=True)
    history: list[dict[str, Any]] = []
    for candidate in sorted(directory.glob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not all(key in payload for key in ("source_id", "run_id", "timestamp", "config_hash")):
            raise ValueError(f"Invalid source audit history: {candidate}")
        history.append(payload)
    return history


async def audit_sources(
    sources: Sequence[Source], *, registry_hash: str, output_dir: Path, history_dir: Path,
    parse: bool = False, days: int = DEFAULT_DAYS, timeout: int = DEFAULT_TIMEOUT,
    capture_fixtures: bool = False, run_id: str | None = None, observed_at: datetime | None = None,
    workers: int = 4,
) -> dict[str, Any]:
    run_id = run_id or uuid.uuid4().hex
    now = observed_at or datetime.now(timezone.utc)
    report: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "timestamp": now.isoformat(),
                              "registry_hash": registry_hash, "healthy": True, "sources": [],
                              "registry_errors": [], "suggestions_only": True}
    fixture_dir = output_dir / "fixtures" / hashlib.sha256(run_id.encode()).hexdigest() if capture_fixtures else None
    limiter = asyncio.Semaphore(max(1, workers))
    client = AuditHttpClient(timeout=timeout)
    async with client:
        async def run_one(source: Source) -> dict[str, Any]:
            async with limiter:
                return await check_source(source)

        async def check_source(source: Source) -> dict[str, Any]:
            client.source = source
            client.failures.clear()
            endpoints = [("homepage", source.homepage), ("listing", source.listing_url),
                         *(("feed", url) for url in source.feed_urls)]
            checked = [await check_endpoint(client, source, kind, url, fixture_dir=fixture_dir)
                       for kind, url in endpoints]
            observation: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "run_id": run_id,
                "timestamp": now.isoformat(), "source_id": source.id, "country": source.country,
                "registry_hash": registry_hash, "config_hash": config_hash(source), "endpoints": checked,
                "healthy": all(item["healthy"] for item in checked), "parse": None, "parse_request_failures": []}
            if parse:
                client.failures.clear()
                try:
                    result = await scrape_source(source, client, since=now - timedelta(days=days), until=now,
                                                 include_unmatched=True, include_undated=True, observed_at=now,
                                                 source_budget_seconds=max(60, timeout))
                    observation["parse"] = assess_parse(result, observed_at=now)
                    observation["parse_request_failures"] = list(client.failures)
                    # Failed optional/discovered/detail requests must also block promotion.
                    observation["healthy"] &= result.status.success and not client.failures
                except Exception as exc:
                    observation["parse"] = {"executed": True, "success": False, "error_code": _error_code(exc),
                                             "error_type": type(exc).__name__}
                    observation["healthy"] = False
            history = persist_observation(history_dir, observation)
            observation["promotion"] = promotion_evidence(observation, history)
            return observation

        report["sources"] = await asyncio.gather(*(run_one(source) for source in sources))
        report["healthy"] = all(item["healthy"] for item in report["sources"])
    report_path = output_dir / ("source-audit-" + hashlib.sha256(run_id.encode()).hexdigest() + ".json")
    report["report_path"] = str(report_path)
    _atomic_json_or_bytes(report_path, report)
    return report


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", default=[], help="Source ID; repeat to select multiple")
    parser.add_argument("--country", action="append", default=[], help="Country code; repeat to select multiple")
    parser.add_argument("--output-dir", type=Path, default=Path("source-audit"))
    parser.add_argument("--history-dir", type=Path, default=Path("source-audit-history"))
    parser.add_argument("--parse", action="store_true", help="Run full scrape and assess date quality")
    parser.add_argument("--capture-fixtures", action="store_true", help="Capture bounded HTTPS evidence without tokens")
    parser.add_argument("--limit", type=_positive_int, help="Maximum number of selected sources")
    parser.add_argument("--days", type=_positive_int, default=DEFAULT_DAYS)
    parser.add_argument("--timeout", type=_positive_int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--workers", type=_positive_int, default=4, help="Concurrent source checks; per-host limits shared")
    parser.add_argument("--allow-unhealthy", action="store_true", help="Exit zero for unhealthy diagnostics; keep failures in JSON")
    args = parser.parse_args(argv)
    try:
        sources, registry = load_sources_and_registry()
        ids, countries = set(args.source), {item.upper() for item in args.country}
        unknown_ids = ids - {item.id for item in sources}
        unknown_countries = countries - {item.country for item in sources}
        if unknown_ids or unknown_countries:
            parser.error(f"Unknown source/country: {', '.join(sorted(unknown_ids | unknown_countries))}")
        selected = [item for item in sources if (not ids or item.id in ids) and (not countries or item.country in countries)]
        paused = [item.id for item in selected if item.is_paused(datetime.now(timezone.utc).date()) and item.id not in ids]
        selected = [item for item in selected if item.id not in paused]
        if not selected:
            parser.error("No sources match the selected source/country filters")
        if args.limit:
            selected = selected[:args.limit]
        report = asyncio.run(audit_sources(selected, registry_hash=registry.registry_hash, output_dir=args.output_dir,
                                          history_dir=args.history_dir, parse=args.parse, days=args.days,
                                          timeout=args.timeout, capture_fixtures=args.capture_fixtures, workers=args.workers))
        report["paused_sources_skipped"] = paused
        if registry.errors:
            report["registry_errors"] = list(registry.errors)
            report["healthy"] = False
        _atomic_json_or_bytes(Path(report["report_path"]), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["healthy"] or args.allow_unhealthy else 1
    except (OSError, ValueError) as exc:
        parser.exit(2, f"source audit failed: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
