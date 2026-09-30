"""Offline evidence checks and bounded, non-enrolling official-directory discovery.

The catalog is a partial inventory, not a source configuration. Its evidence was
reviewed by a human/agent through first-party web pages; --check validates those
records, never claims to have reverified a website or validated a news parser.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import re
import ssl
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx
import truststore
from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator, FormatChecker

from .http import HttpClient, HttpStats, ResponseTooLargeError
from .models import Source
from .organisation_registry import builtin_registry_dir
from .source_audit import _atomic_json_or_bytes, audit_sources
from .topics import OBSERVATION_TOPICS

EU27 = frozenset("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
MAX_CATALOG_BYTES = 2 * 1024 * 1024


def catalog_directory() -> Path:
    candidates = [Path(__file__).resolve().parents[2] / "source_catalog", Path(sys.prefix) / "source_catalog"]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / "source_catalog")
    return next((path for path in candidates if (path / "catalog.schema.json").is_file()), candidates[0])


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_catalog(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError("catalog exceeds 2 MiB limit")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    if not isinstance(value, dict):
        raise ValueError("catalog must be a JSON object")
    return value


def https_url(value: str) -> str:
    """Validate a public DNS HTTPS URL and remove fragments for link identity."""
    if not isinstance(value, str) or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise ValueError("URL contains whitespace, controls or backslash")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL authority") from exc
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or port not in {None, 443}:
        raise ValueError("URL must use HTTPS, no credentials, and port 443 only")
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", host):
        raise ValueError("URL must use a public DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP literal URLs are forbidden")
    if host.endswith((".localhost", ".local", ".internal", ".invalid", ".test")):
        raise ValueError("local or reserved URL hostname")
    decoded = unquote(unquote(parsed.path))
    if re.search(r"[\\\x00-\x1f\x7f]", decoded) or any(part in {".", ".."} for part in decoded.split("/")):
        raise ValueError("URL path contains controls or traversal")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _allowed(url: str, domains: list[str]) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _url_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(https_url(url))
    host = (parsed.hostname or "").removeprefix("www.")
    # Fragments, query tracking and trailing slashes do not create a new source.
    return host, unquote(parsed.path).rstrip("/") or "/"


def existing_registry_snapshot(directory: Path | None = None) -> tuple[set[str], set[tuple[str, str]]]:
    """Read identity/URL fields only; registry schema/owner consistency is separate."""
    directory = directory or builtin_registry_dir()
    if not directory.is_dir():
        raise ValueError(f"registry directory unavailable: {directory}")
    ids: set[str] = set()
    urls: set[tuple[str, str]] = set()
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".example.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        ids.add(data["canonical_id"].casefold())
        for row in data.get("sources", []):
            ids.add(row["id"].casefold())
            for field in ("listing_url", "homepage"):
                if row.get(field):
                    urls.add(_url_key(row[field]))
    return ids, urls


def validate_catalog(
    catalog: dict[str, Any], *, registry_dir: Path | None = None,
) -> list[str]:
    schema = json.loads((catalog_directory() / "catalog.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = [
        f"{'/'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog)
    ]
    if errors:
        return sorted(errors)
    try:
        existing_ids, existing_urls = existing_registry_snapshot(registry_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"registry identity snapshot unavailable: {exc}"]
    seen_ids: set[str] = set()
    seen_news: set[tuple[str, str]] = set()
    for row in catalog["institutions"]:
        label = row["canonical_id"]
        canonical = label.casefold()
        if not label.startswith(row["country"].lower() + "_"):
            errors.append(f"{label}: id country prefix mismatch")
        if canonical in seen_ids or canonical in existing_ids:
            errors.append(f"{label}: duplicate catalog/registry id")
        seen_ids.add(canonical)
        if set(row["topics"]) - set(OBSERVATION_TOPICS):
            errors.append(f"{label}: unknown observation topic")
        verification = row["verification"]
        if date.fromisoformat(verification["verified_on"]) > date.today():
            errors.append(f"{label}: evidence date is in the future")
        required_urls = {row["homepage"], row["news_url"], row["mandate_evidence_url"]}
        if not required_urls.issubset(verification["urls"]):
            errors.append(f"{label}: homepage/news/mandate evidence review missing")
        for value in required_urls | set(verification["urls"]):
            try:
                clean = https_url(value)
                if urlsplit(value).fragment or not _allowed(clean, row["official_domains"]):
                    raise ValueError("URL outside declared first-party domains or includes fragment")
            except ValueError as exc:
                errors.append(f"{label}: {exc}: {value}")
        try:
            key = _url_key(row["news_url"])
            if key in seen_news or key in existing_urls:
                errors.append(f"{label}: duplicate catalog/registry news host/path")
            seen_news.add(key)
        except ValueError:
            pass
    seen_seeds: set[str] = set()
    seen_seed_urls: set[str] = set()
    for seed in catalog["discovery"]["directory_seeds"]:
        label = seed["id"]
        if label in seen_seeds or seed["url"] in seen_seed_urls:
            errors.append(f"{label}: duplicate directory seed")
        seen_seeds.add(label)
        seen_seed_urls.add(seed["url"])
        if seed["url"] not in seed["verification"]["urls"]:
            errors.append(f"{label}: directory evidence review missing")
        if date.fromisoformat(seed["verification"]["verified_on"]) > date.today():
            errors.append(f"{label}: directory evidence date is in the future")
        for value in [seed["url"], *seed["verification"]["urls"]]:
            try:
                if not _allowed(https_url(value), seed["official_domains"]) or urlsplit(value).fragment:
                    raise ValueError("directory URL outside declared official domains or includes fragment")
            except ValueError as exc:
                errors.append(f"{label}: {exc}")
        domains = [item["domain"] for item in seed["candidate_domains"]]
        if len(set(domains)) != len(domains):
            errors.append(f"{label}: duplicate candidate domain declarations")
        if any(item["country"] != seed["country"] for item in seed["candidate_domains"]):
            errors.append(f"{label}: candidate country outside directory country")
        for domain in [*seed["official_domains"], *domains]:
            try:
                https_url("https://" + domain + "/")
            except ValueError as exc:
                errors.append(f"{label}: invalid declared domain: {exc}")
    return sorted(errors)


def check_report(catalog: dict[str, Any], *, registry_dir: Path | None = None) -> dict[str, Any]:
    errors = validate_catalog(catalog, registry_dir=registry_dir)
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_kind": "source_catalog_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "invalid" if errors else "complete",
        "validation_errors": errors,
        "evidence_check": "recorded_first_party_reviews_only_not_live_reverification",
        "parser_validation_performed": False,
        "auto_enrolled": 0,
        "discovery": {"status": "not_requested", "candidates": []},
    }
    if errors:
        return report
    rows = catalog["institutions"]
    covered_countries = {row["country"] for row in rows}
    covered_topics = {topic for row in rows for topic in row["topics"]}
    report.update({
        "catalog_version": catalog["catalog_version"],
        "catalog_sha256": hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "institution_count": len(rows),
        "searchable_count": 0,
        "parser_gaps": [{"canonical_id": row["canonical_id"], "reason": "parser_not_validated"} for row in rows],
        "coverage": {
            "basis": "verified_catalog_metadata_only",
            "completeness": "partial",
            "countries_present": sorted(covered_countries),
            "countries_without_catalog_entries": sorted(EU27 - covered_countries),
            "topics_without_catalog_entries": [topic for topic in OBSERVATION_TOPICS if topic not in covered_topics],
            "gap_semantics": "Inventory gaps are not proof of institution absence or production coverage gaps.",
        },
    })
    return report


def maintain_candidates(discovery: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Keep previously discovered URLs and mark which ones were seen this run."""
    now = datetime.now(timezone.utc).isoformat()
    inventory: dict[tuple[str, str], dict[str, Any]] = {}
    old = (previous or {}).get("discovery", {}).get("candidates", [])
    if not isinstance(old, list) or len(old) > 1000:
        raise ValueError("invalid previous candidate inventory")
    for row in old:
        if (not isinstance(row, dict) or row.get("verification_status") != "unverified"
                or row.get("searchable") is not False or row.get("country_scope") not in EU27):
            raise ValueError("previous candidates must remain unverified EU27 directory entries")
        key = _url_key(row["url"])
        inventory[key] = {**row, "seen_this_run": False}
    added = 0
    for row in discovery["candidates"]:
        key = _url_key(row["url"])
        prior = inventory.get(key, {})
        if not prior and len(inventory) >= 1000:
            discovery["status"] = "attention"
            discovery["inventory_limit_reached"] = True
            continue
        added += not bool(prior)
        inventory[key] = {**row, "first_seen_at": prior.get("first_seen_at", now), "last_seen_at": now,
                          "seen_this_run": True,
                          "discovered_from": sorted(set(row["discovered_from"]) | set(prior.get("discovered_from", [])))}
    return {**discovery, "candidates": list(inventory.values()), "candidate_count": len(inventory),
            "new_candidate_count": added, "prior_inventory_restored": previous is not None}


async def audit_catalog_urls(catalog: dict[str, Any], directory: Path) -> dict[str, Any]:
    sources = [Source(
        id=row["canonical_id"], country=row["country"], name_zh=row["full_names"]["local"],
        name=row["full_names"]["en"], institution_type=row["institution_type"], language=row["language"],
        homepage=row["homepage"], listing_url=row["news_url"], allow_domains=tuple(row["official_domains"]),
        detail_pages=0, schedule_enabled=False,
    ) for row in catalog["institutions"]]
    digest = hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return await audit_sources(sources, registry_hash=digest, output_dir=directory / "url-checks",
                               history_dir=directory / "catalog-history", workers=4, timeout=15)


class DirectoryTransport(httpx.AsyncBaseTransport):
    """Enforce HTTPS/domain boundaries before every request, including redirects/robots."""

    def __init__(self, domains: list[str], inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.domains = domains
        self.inner = inner or httpx.AsyncHTTPTransport(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            if not _allowed(https_url(str(request.url)), self.domains):
                raise ValueError("request outside declared directory domains")
        except ValueError as exc:
            raise httpx.InvalidURL(str(exc)) from exc
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


async def discover(
    catalog: dict[str, Any], *, registry_dir: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """One hop of HTML links; no candidate fetching, recursion, search API or enrollment."""
    errors = validate_catalog(catalog, registry_dir=registry_dir)
    if errors:
        raise ValueError("invalid catalog: " + "; ".join(errors))
    limits = catalog["discovery"]
    seeds = limits["directory_seeds"]
    _, known_urls = existing_registry_snapshot(registry_dir)
    for row in catalog["institutions"]:
        known_urls.update(_url_key(row[field]) for field in ("homepage", "news_url"))
    known_hosts = {host for host, _path in known_urls}
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    stats = HttpStats()
    domains = sorted({domain for seed in seeds for domain in seed["official_domains"]})
    async with HttpClient(
        obey_robots=True, min_interval=0.5, max_connections=1, per_host=1,
        max_response_bytes=1024 * 1024, max_retry_wait=2.0,
        transport=DirectoryTransport(domains, transport),
    ) as client:
        for seed in seeds[:limits["max_seed_pages"]]:
            result: dict[str, Any] = {
                "seed_id": seed["id"], "url": seed["url"], "status": "complete",
                "links_examined": 0, "excluded_links": 0, "duplicates": 0, "bounds_reached": [],
            }
            results.append(result)
            try:
                response = await client.get(seed["url"], stats=stats)
                if not _allowed(https_url(str(response.url)), seed["official_domains"]):
                    raise ValueError("directory redirected outside its declared domains")
                if "html" not in response.headers.get("content-type", "").lower():
                    raise ValueError("directory response is not HTML")
                soup = BeautifulSoup(response.content, "html.parser")
                anchors = soup.find_all("a", href=True, limit=limits["max_links_per_page"] + 1)
                if len(anchors) > limits["max_links_per_page"]:
                    result["bounds_reached"].append("max_links_per_page")
                for anchor in anchors[:limits["max_links_per_page"]]:
                    result["links_examined"] += 1
                    href = str(anchor["href"])
                    if not href or href.startswith("#"):
                        result["excluded_links"] += 1
                        continue
                    try:
                        link = https_url(urljoin(str(response.url), href))
                        declared = next((
                            item for item in seed["candidate_domains"] if _allowed(link, [item["domain"]])
                        ), None)
                        if declared is None:
                            raise ValueError("undeclared institution domain")
                        key = _url_key(link)
                    except ValueError:
                        result["excluded_links"] += 1
                        continue
                    # Institutional hosts already known are suppressed; shared institutional
                    # news hosts are still compared by path during catalog validation.
                    if key[0] in known_hosts:
                        result["duplicates"] += 1
                        continue
                    if key in candidates:
                        result["duplicates"] += 1
                        if seed["url"] not in candidates[key]["discovered_from"]:
                            candidates[key]["discovered_from"].append(seed["url"])
                        continue
                    if len(candidates) >= limits["max_candidates"]:
                        if "max_candidates" not in result["bounds_reached"]:
                            result["bounds_reached"].append("max_candidates")
                        continue
                    candidates[key] = {
                        "url": link, "label": anchor.get_text(" ", strip=True)[:240],
                        "country_scope": declared["country"], "discovered_from": [seed["url"]],
                        "verification_status": "unverified", "status": "candidate_only", "searchable": False,
                        "note": "Directory link only; identity, mandate, country and parser require review.",
                    }
            except (httpx.HTTPError, httpx.InvalidURL, RuntimeError, ValueError, ResponseTooLargeError) as exc:
                result.update(status="attention", error_type=type(exc).__name__, error=str(exc)[:500])
    skipped = [seed["id"] for seed in seeds[limits["max_seed_pages"]:]]
    incomplete = bool(skipped) or any(row["status"] != "complete" or row["bounds_reached"] for row in results)
    return {
        "status": "attention" if incomplete else "complete",
        "completeness": "partial_inventory_even_when_seed_fetches_complete",
        "limits": {key: limits[key] for key in ("max_seed_pages", "max_links_per_page", "max_candidates")},
        "seed_results": results, "skipped_seed_ids": skipped,
        "request_count": stats.request_count, "bytes_downloaded": stats.bytes_downloaded,
        "candidate_count": len(candidates), "candidates": list(candidates.values()),
        "auto_enrolled": 0, "candidate_pages_fetched": 0,
        "gap_semantics": "Zero candidates can mean duplicates, exclusions, bounds, robots or fetch failure; not absence.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=catalog_directory() / "eu27.seed.json")
    parser.add_argument("--check", action="store_true", required=True, help="validate recorded evidence offline")
    parser.add_argument("--discover", action="store_true", help="read declared directory pages; do not fetch candidates")
    parser.add_argument("--audit-urls", action="store_true", help="live-check catalog homepages and news URLs")
    parser.add_argument("--previous", type=Path, help="previous discovery report to preserve accumulated candidates")
    parser.add_argument("--output", type=Path, help="optional separate JSON audit/discovery report")
    args = parser.parse_args(argv)
    if args.output and args.output.resolve() in {args.catalog.resolve(),
                                                (catalog_directory() / "catalog.schema.json").resolve()}:
        parser.error("output must not overwrite catalog or schema")
    try:
        catalog = load_catalog(args.catalog)
        report = check_report(catalog)
        if args.discover and not report["validation_errors"]:
            previous = load_catalog(args.previous) if args.previous and args.previous.exists() else None
            report["discovery"] = maintain_candidates(asyncio.run(discover(catalog)), previous)
            if report["discovery"]["status"] == "attention":
                report["status"] = "attention"
        if args.audit_urls and not report["validation_errors"]:
            report["url_audit"] = asyncio.run(audit_catalog_urls(catalog, args.output.parent if args.output
                                                               else Path("source-audit")))
            if not report["url_audit"]["healthy"]:
                report["status"] = "attention"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {"schema_version": 1, "report_kind": "source_catalog_audit", "status": "invalid",
                  "validation_errors": [str(exc)], "auto_enrolled": 0,
                  "discovery": {"status": "not_run", "candidates": []}}
    if args.output:
        _atomic_json_or_bytes(args.output, report)
    print(json.dumps(report, ensure_ascii=False))
    return 2 if report["status"] == "invalid" else 1 if report["status"] == "attention" else 0


if __name__ == "__main__":
    raise SystemExit(main())
