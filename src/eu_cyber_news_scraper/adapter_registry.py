"""Explicit parser capabilities; missing capabilities use the generic parser.

Listing and feed registrations are independent. Duplicate names within a
capability are errors, including attempts to register the same handler twice.
Handlers own validation: empty results and exceptions never trigger fallback.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from .finland_adapters import (
    FINLAND_FEED_ADAPTERS,
    FINLAND_LISTING_ADAPTERS,
    parse_finland_feed,
    parse_finland_listing,
)
from .ministry_adapters import (
    MINISTRY_FEED_ADAPTERS,
    MINISTRY_LISTING_ADAPTERS,
    parse_ministry_feed,
    parse_ministry_listing,
)
from .models import Article, Source
from .north_adapters import NORTH_ADAPTERS, parse_north_feed, parse_north_listing
from .round4_north_adapters import ROUND4_NORTH_ADAPTERS, parse_round4_listing
from .round4_south_adapters import ROUND4_SOUTH_FEED_ADAPTERS, parse_round4_south_feed

ListingParser = Callable[[str, Source, str], list[Article]]
FeedParser = Callable[[bytes | str, Source, str], list[Article]]
Handler = TypeVar("Handler")


class AdapterRegistry:
    def __init__(self) -> None:
        self._listing: dict[str, ListingParser] = {}
        self._feed: dict[str, FeedParser] = {}

    @staticmethod
    def _register(
        handlers: dict[str, Handler], names: Iterable[str], handler: Handler, capability: str,
    ) -> None:
        # Validate the whole group before mutating the registry.
        names = tuple(names)
        seen: set[str] = set()
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Adapter names must be non-empty strings")
            if name in handlers or name in seen:
                raise ValueError(f"Duplicate {capability} adapter: {name}")
            seen.add(name)
        handlers.update(dict.fromkeys(names, handler))

    def register_listing(self, names: Iterable[str], handler: ListingParser) -> None:
        self._register(self._listing, names, handler, "listing")

    def register_feed(self, names: Iterable[str], handler: FeedParser) -> None:
        self._register(self._feed, names, handler, "feed")

    def listing(self, name: str) -> ListingParser | None:
        return self._listing.get(name)

    def feed(self, name: str) -> FeedParser | None:
        return self._feed.get(name)


def _sitecore_listing(html: str, source: Source, base_url: str) -> list[Article]:
    # The existing implementation lives in parsers; defer to avoid an import cycle.
    from .parsers import _parse_sitecore_public

    return _parse_sitecore_public(html, source)


def build_adapter_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register_listing(ROUND4_NORTH_ADAPTERS, parse_round4_listing)
    registry.register_listing(NORTH_ADAPTERS, parse_north_listing)
    registry.register_listing(MINISTRY_LISTING_ADAPTERS, parse_ministry_listing)
    registry.register_listing(("sitecore_public",), _sitecore_listing)
    registry.register_feed(ROUND4_SOUTH_FEED_ADAPTERS, parse_round4_south_feed)
    registry.register_feed(NORTH_ADAPTERS, parse_north_feed)
    registry.register_feed(MINISTRY_FEED_ADAPTERS, parse_ministry_feed)
    registry.register_listing(FINLAND_LISTING_ADAPTERS, parse_finland_listing)
    registry.register_feed(FINLAND_FEED_ADAPTERS, parse_finland_feed)
    return registry


PARSER_ADAPTERS = build_adapter_registry()
