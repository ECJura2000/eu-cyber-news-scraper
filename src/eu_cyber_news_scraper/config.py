from __future__ import annotations

import re
import tomllib
from datetime import date
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__
from .models import Source

DEFAULT_DAYS = 14
DEFAULT_WORKERS = 8
DEFAULT_TIMEOUT = 25
DEFAULT_SOURCE_BUDGET = 60
DEFAULT_TIMEZONE = "Asia/Taipei"
DEFAULT_OUTPUT_DIR = Path.cwd() / "新聞放置區"
DEFAULT_TRANSLATION_WORKERS = 4
DEFAULT_HTTP_CONCURRENCY = 16
USER_AGENT = (
    f"Mozilla/5.0 (compatible; eu-cyber-news-scraper/{__version__}; "
    "+https://github.com/ECJura2000/eu-cyber-news-scraper)"
)

COUNTRY_TIMEZONES = {
    "EU": "Europe/Brussels",
    "FR": "Europe/Paris",
    "DE": "Europe/Berlin",
    "IE": "Europe/Dublin",
}


def default_sources_path() -> Path:
    return Path(str(files("eu_cyber_news_scraper").joinpath("sources.toml")))


def load_sources(path: str | Path | None = None) -> tuple[Source, ...]:
    source_path = Path(path) if path else default_sources_path()
    with source_path.open("rb") as stream:
        data = tomllib.load(stream)
    sources = []
    for row in data.get("sources", []):
        sources.append(
            Source(
                id=row["id"],
                country=row["country"],
                name_zh=row["name_zh"],
                name=row["name"],
                institution_type=row["institution_type"],
                language=row["language"],
                homepage=row["homepage"],
                listing_url=row["listing_url"],
                feed_urls=tuple(row.get("feed_urls", [])),
                allow_domains=tuple(row.get("allow_domains", [])),
                include_patterns=tuple(row.get("include_patterns", [])),
                exclude_patterns=tuple(row.get("exclude_patterns", [])),
                critical=bool(row.get("critical", False)),
                detail_pages=int(row.get("detail_pages", 12)),
                yearly_listing_url=str(row.get("yearly_listing_url", "")),
                pagination_url=str(row.get("pagination_url", "")),
                max_pages=int(row.get("max_pages", 1)),
                observation_runs=int(row.get("observation_runs", 3)),
                freshness_days=int(row.get("freshness_days", 45 if row.get("critical", False) else 90)),
                timezone=str(row.get("timezone", COUNTRY_TIMEZONES.get(row["country"], "UTC"))),
                card_selectors=tuple(row.get("card_selectors", [])),
                link_selectors=tuple(row.get("link_selectors", [])),
                title_selectors=tuple(row.get("title_selectors", [])),
                date_selectors=tuple(row.get("date_selectors", [])),
                summary_selectors=tuple(row.get("summary_selectors", [])),
                parser_adapter=str(row.get("parser_adapter", "")),
                date_policy=str(
                    row.get("date_policy", "best_effort" if row.get("date_optional", False) else "required")
                ),
                date_exception_reason=str(row.get("date_exception_reason", "")),
                date_evidence_url=str(row.get("date_evidence_url", "")),
                date_reviewed_on=str(row.get("date_reviewed_on", "")),
                date_review_due=str(row.get("date_review_due", "")),
                tls_intermediate_bundle=str(row.get("tls_intermediate_bundle", "")),
                paused_until=str(row.get("paused_until", "")),
                pause_reason=str(row.get("pause_reason", "")),
                pause_evidence_url=str(row.get("pause_evidence_url", "")),
            )
        )
    _validate_sources(sources)
    return tuple(sources)


def _validate_sources(sources: list[Source]) -> None:
    ids = [source.id for source in sources]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate source ids: {', '.join(duplicates)}")
    invalid_countries = sorted({source.country for source in sources} - {"EU", "FR", "DE", "IE"})
    if invalid_countries:
        raise ValueError(f"Unsupported country codes: {', '.join(invalid_countries)}")
    if not sources:
        raise ValueError("No sources configured")
    for source in sources:
        if not source.id.strip() or not source.name.strip() or not source.name_zh.strip():
            raise ValueError("Source id and names must not be blank")
        if source.detail_pages < 0:
            raise ValueError(f"{source.id}: detail_pages must be non-negative")
        if source.max_pages < 1 or source.observation_runs < 0 or source.freshness_days < 1:
            raise ValueError(f"{source.id}: max_pages must be positive and observation_runs non-negative")
        if source.date_policy not in {"required", "best_effort", "unavailable"}:
            raise ValueError(f"{source.id}: invalid date_policy: {source.date_policy}")
        if source.date_policy != "required":
            missing = [
                name
                for name, value in (
                    ("date_exception_reason", source.date_exception_reason),
                    ("date_evidence_url", source.date_evidence_url),
                    ("date_reviewed_on", source.date_reviewed_on),
                    ("date_review_due", source.date_review_due),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"{source.id}: {source.date_policy} date policy requires {', '.join(missing)}")
        if source.tls_intermediate_bundle:
            bundle = Path(__file__).with_name("certificates") / source.tls_intermediate_bundle
            if Path(source.tls_intermediate_bundle).name != source.tls_intermediate_bundle or not bundle.is_file():
                raise ValueError(f"{source.id}: unknown TLS intermediate bundle: {source.tls_intermediate_bundle}")
        pause_values = (source.paused_until, source.pause_reason, source.pause_evidence_url)
        if any(pause_values):
            if not all(pause_values):
                raise ValueError(f"{source.id}: paused source requires paused_until, pause_reason and pause_evidence_url")
            try:
                date.fromisoformat(source.paused_until)
            except ValueError as exc:
                raise ValueError(f"{source.id}: invalid paused_until: {source.paused_until}") from exc
            evidence = urlsplit(source.pause_evidence_url)
            if evidence.scheme not in {"http", "https"} or not evidence.netloc:
                raise ValueError(f"{source.id}: invalid pause_evidence_url: {source.pause_evidence_url}")
        try:
            ZoneInfo(source.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"{source.id}: invalid timezone: {source.timezone}") from exc
        urls_to_validate = [
            ("homepage", source.homepage),
            ("listing_url", source.listing_url),
            *(("feed_url", url) for url in source.feed_urls),
        ]
        if source.yearly_listing_url:
            urls_to_validate.append(("yearly_listing_url", source.yearly_listing_url))
        if source.pagination_url:
            urls_to_validate.append(("pagination_url", source.pagination_url))
        for label, url in urls_to_validate:
            parts = urlsplit(url.replace("{year}", "2026").replace("{page}", "1"))
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise ValueError(f"{source.id}: invalid {label}: {url}")
        listing_domain = urlsplit(source.listing_url).hostname or ""
        if source.allow_domains and not any(
            listing_domain == domain or listing_domain.endswith(f".{domain}") for domain in source.allow_domains
        ):
            raise ValueError(f"{source.id}: listing_url is outside allow_domains")
        for label, template in (("yearly_listing_url", source.yearly_listing_url), ("pagination_url", source.pagination_url)):
            if not template:
                continue
            template_domain = urlsplit(template.replace("{year}", "2026").replace("{page}", "1")).hostname or ""
            if source.allow_domains and not any(
                template_domain == domain or template_domain.endswith(f".{domain}") for domain in source.allow_domains
            ):
                raise ValueError(f"{source.id}: {label} is outside allow_domains")
        for pattern in (*source.include_patterns, *source.exclude_patterns):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"{source.id}: invalid URL regex {pattern!r}: {exc}") from exc
