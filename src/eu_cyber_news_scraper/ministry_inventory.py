"""Evidence-backed central ministry inventory, separate from runnable sources."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from jsonschema.exceptions import ValidationError

from .models import Source
from .organisation_registry import OrganisationRegistry, load_organisation_registry
from .schema_validation import validate_schema_payload
from .source_audit import AuditHttpClient, check_endpoint
from .source_catalog import EU27, MAX_CATALOG_BYTES, https_url, load_catalog


def inventory_directory() -> Path:
    candidates = [Path(__file__).resolve().parents[2] / "ministry_inventory", Path(sys.prefix) / "ministry_inventory"]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / "ministry_inventory")
    return next((path for path in candidates if path.is_dir()), candidates[0])


def validate_country(
    payload: dict[str, Any], registry: OrganisationRegistry, *, today: date | None = None,
) -> None:
    try:
        validate_schema_payload(payload, "ministry-inventory-v1.schema.json")
    except ValidationError as exc:
        raise ValueError(f"invalid ministry inventory: {exc.message}") from exc
    country = payload["country"]
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if date.fromisoformat(payload["reviewed_on"]) > today:
        raise ValueError(f"{country}: roster review date is in the future")
    for url in payload["official_roster_urls"]:
        https_url(url)
    if not payload["roster_complete"] and not payload["limitations"]:
        raise ValueError(f"{country}: incomplete roster requires limitations")
    source_rows = {row["id"]: row for row in registry.source_rows}
    seen: set[str] = set()
    for row in payload["ministries"]:
        ministry_id = row["canonical_id"]
        if not ministry_id.startswith(country.lower() + "_") or ministry_id in seen:
            raise ValueError(f"{country}: duplicate or mismatched ministry id: {ministry_id}")
        seen.add(ministry_id)
        for key in ("name_zh", "name_local", "name_en", "reason"):
            if not row[key].strip():
                raise ValueError(f"{ministry_id}: blank {key}")
        for url in [*row["evidence_urls"], row["homepage"], row["news_url"]]:
            if url is not None:
                https_url(url)
        status = row["status"]
        if status in {"existing_source", "manual_verified"} and not row["source_ids"]:
            raise ValueError(f"{ministry_id}: registered status requires source_ids")
        if status in {"blocked", "no_news_endpoint", "parser_pending", "needs_review"} and row["source_ids"]:
            raise ValueError(f"{ministry_id}: unresolved endpoint must not claim registered sources")
        if status == "manual_verified" and (not row["homepage"] or not row["news_url"]):
            raise ValueError(f"{ministry_id}: verified endpoint requires homepage and news URL")
        if status == "no_news_endpoint" and row["news_url"] is not None:
            raise ValueError(f"{ministry_id}: no_news_endpoint cannot declare a news URL")
        for source_id in row["source_ids"]:
            source = source_rows.get(source_id)
            if source is None or source["country"] != country:
                raise ValueError(f"{ministry_id}: missing or cross-country source: {source_id}")
            if status == "manual_verified":
                module = registry.module_for_source(source_id)
                if module is None or module.payload.get("verification", {}).get("status") != "smoke_healthy":
                    raise ValueError(f"{ministry_id}: source lacks successful live parser evidence")


def load_inventory(directory: Path, registry: OrganisationRegistry) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise ValueError(f"ministry inventory directory unavailable: {directory}")
    if registry.errors:
        raise ValueError("organisation registry is invalid: " + "; ".join(registry.errors))
    result = []
    countries: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        if path.stat().st_size > MAX_CATALOG_BYTES:
            raise ValueError(f"{path.name}: ministry inventory exceeds size limit")
        payload = load_catalog(path)
        validate_country(payload, registry)
        country = payload["country"]
        if path.stem != country or country in countries:
            raise ValueError(f"{path.name}: duplicate country or filename/country mismatch")
        countries.add(country)
        result.append(payload)
    if not result:
        raise ValueError("ministry inventory has no country records")
    return result


def inventory_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    present = {record["country"] for record in records}
    missing = sorted(EU27 - present)
    incomplete = sorted(record["country"] for record in records if not record["roster_complete"])
    statuses = Counter(row["status"] for record in records for row in record["ministries"])
    registered = statuses["existing_source"] + statuses["manual_verified"]
    unresolved = sum(statuses.values()) - registered
    return {
        "schema_version": 1, "report_kind": "central_ministry_inventory",
        "evidence_check": "recorded_first_party_roster_reviews_not_live_reverification",
        "status": "complete" if not missing and not incomplete else "attention",
        "country_count": len(present), "ministry_count": sum(statuses.values()),
        "missing_countries": missing, "incomplete_rosters": incomplete,
        "status_counts": dict(sorted(statuses.items())),
        "registered_ministries": registered,
        "unresolved_ministries": unresolved,
        "searchable_inventory_complete": not missing and not incomplete and unresolved == 0,
        "new_manual_verified_ministries": statuses["manual_verified"],
        "automatic_schedule_changes": False, "countries": records,
    }


async def audit_inventory_urls(
    records: list[dict[str, Any]], output_dir: Path, *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Inspect unresolved ministry URLs without registering them or running parsers."""
    requests: dict[str, tuple[Source, str, list[str]]] = {}
    missing: list[str] = []
    for record in records:
        for row in record["ministries"]:
            if row["status"] in {"existing_source", "manual_verified"}:
                continue  # Registered endpoints are checked by the full source audit.
            if not row["homepage"] or not row["news_url"]:
                missing.append(row["canonical_id"])
            urls = [url for url in (row["homepage"], row["news_url"]) if url]
            source = Source(
                id=row["canonical_id"], country=record["country"], name_zh=row["name_zh"],
                name=row["name_local"], institution_type=row["kind"], language=row["language"],
                homepage=row["homepage"] or "", listing_url=row["news_url"] or "",
                allow_domains=tuple(sorted({urlsplit(url).hostname or "" for url in urls})),
                schedule_enabled=False,
            )
            for kind, url in (("homepage", row["homepage"]), ("listing", row["news_url"])):
                if not url:
                    continue
                clean = https_url(url)
                if clean in requests:
                    requests[clean][2].append(row["canonical_id"])
                else:
                    requests[clean] = source, kind, [row["canonical_id"]]
    semaphore = asyncio.Semaphore(8)
    client = AuditHttpClient(timeout=15, transport=transport)
    async with client:
        async def check(url: str, source: Source, kind: str, owners: list[str]) -> dict[str, Any]:
            async with semaphore:
                client.source = source
                result = await check_endpoint(client, source, kind, url)
                result["ministry_ids"] = sorted(set(owners))
                return result
        endpoints = await asyncio.gather(*(check(url, *values) for url, values in requests.items()))
    result = {
        "schema_version": 1, "report_kind": "ministry_url_audit",
        "observed_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "status": "complete" if not missing and all(row["healthy"] for row in endpoints) else "attention",
        "parser_validation_performed": False, "automatic_schedule_changes": False,
        "unresolved_endpoint_ministries": sorted(missing), "endpoints": endpoints,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "ministry-urls.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="列出 EU27 中央部會名錄、新聞入口與驗證缺口。")
    parser.add_argument("--inventory-dir", type=Path, default=inventory_directory())
    parser.add_argument("--country", action="append", choices=sorted(EU27))
    parser.add_argument("--check", action="store_true", help="驗證全部名錄與來源參照；不重新抓取網站。")
    parser.add_argument("--json", action="store_true", help="輸出可稽核的完整 JSON。")
    parser.add_argument("--audit-urls", action="store_true", help="檢查未登錄部會網址；不驗證解析器或啟用來源。")
    parser.add_argument("--output-dir", type=Path, default=Path("source-audit/ministry-urls"))
    args = parser.parse_args(argv)
    try:
        records = load_inventory(args.inventory_dir, load_organisation_registry())
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    report = inventory_report(records)
    if args.country:
        selected = [record for record in records if record["country"] in args.country]
        if len(selected) != len(set(args.country)):
            print("[error] 指定國家尚無部會名錄。", file=sys.stderr)
            return 2
        report["countries"] = selected
    if args.audit_urls:
        if args.output_dir.resolve().is_relative_to(args.inventory_dir.resolve()):
            parser.error("URL audit output must be outside the ministry inventory directory")
        try:
            report["url_audit"] = asyncio.run(audit_inventory_urls(report["countries"], args.output_dir))
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
            return 2
        if report["url_audit"]["status"] != "complete":
            report["status"] = "attention"
    if args.check or args.json or args.audit_urls:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for record in report["countries"]:
            print(f"{record['country']}：{len(record['ministries'])} 個部會；查核 {record['reviewed_on']}")
            for row in record["ministries"]:
                print(f"  {row['canonical_id']} | {row['name_zh']} | {row['status']} | {row['news_url'] or '未找到新聞入口'}")
                print(f"    {row['reason']}")
        print(f"名錄完整性：{report['status']}；登錄與解析驗證請分別檢視，不代表全部可抓取。")
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
