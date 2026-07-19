from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Source:
    id: str
    country: str
    name_zh: str
    name: str
    institution_type: str
    language: str
    homepage: str
    listing_url: str
    feed_urls: tuple[str, ...] = ()
    allow_domains: tuple[str, ...] = ()
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    critical: bool = False
    detail_pages: int = 12
    yearly_listing_url: str = ""
    pagination_url: str = ""
    max_pages: int = 1
    observation_runs: int = 3
    freshness_days: int = 45
    timezone: str = "Europe/Brussels"
    card_selectors: tuple[str, ...] = ()
    link_selectors: tuple[str, ...] = ()
    title_selectors: tuple[str, ...] = ()
    date_selectors: tuple[str, ...] = ()
    summary_selectors: tuple[str, ...] = ()
    parser_adapter: str = ""
    date_policy: str = "required"
    date_exception_reason: str = ""
    date_evidence_url: str = ""
    date_reviewed_on: str = ""
    date_review_due: str = ""
    @property
    def display_name(self) -> str:
        return f"{self.name_zh}（{self.name}）"


@dataclass
class Article:
    source_id: str
    country: str
    source_name: str
    institution_type: str
    language: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str = ""
    fetched_via: str = ""
    matched_topics: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    relevance_score: int = 0
    discovered_by: list[str] = field(default_factory=list)
    title_zh_tw: str = ""
    authority_level: str = ""
    content_kind: str = ""
    confidence_level: str = ""
    alternate_urls: list[str] = field(default_factory=list)
    published_at_raw: str = ""
    published_date_local: str = ""
    published_timezone: str = "UTC"
    date_precision: str = "unknown"
    date_source: str = ""
    date_confidence: str = ""
    date_conflict: bool = False


@dataclass(frozen=True)
class SourceStatus:
    source_id: str
    source_name: str
    country: str
    critical: bool
    success: bool
    fetched_via: str
    raw_count: int
    relevant_count: int
    duration_seconds: float
    newest_published_at: str = ""
    warning: str = ""
    error: str = ""
    pages_fetched: int = 0
    historical_median_count: float = 0.0
    health_alerts: tuple[str, ...] = ()
    dated_count: int = 0
    undated_ratio: float = 0.0
    unique_title_ratio: float = 1.0
    in_range_count: int = 0
    freshness_lag_days: float = 0.0
    content_warning: str = ""
    fetch_status: str = "ok"
    health_status: str = "healthy"
    invalid_date_count: int = 0
    unexplained_future_date_count: int = 0
    timeout_count: int = 0
    parse_status: str = "healthy"
    freshness_status: str = "fresh"
    content_status: str = "hits"
    request_count: int = 0
    bytes_downloaded: int = 0
    retry_count: int = 0
    budget_exhausted: bool = False
    http_statuses: tuple[str, ...] = ()
    error_code: str = ""


@dataclass
class SourceResult:
    source: Source
    articles: list[Article]
    status: SourceStatus
