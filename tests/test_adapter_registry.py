"""Registration policy and runtime fallback contracts for parser adapters."""
import json
import subprocess
import sys
from dataclasses import replace

import pytest

from eu_cyber_news_scraper import adapter_registry as adapters
from eu_cyber_news_scraper import parsers
from eu_cyber_news_scraper.models import Source


def source(adapter=""):
    return Source(
        id="test", country="EU", name_zh="測試", name="Test",
        institution_type="official", language="en", timezone="Europe/Brussels",
        homepage="https://agency.example/", listing_url="https://agency.example/news/",
        allow_domains=("agency.example",), include_patterns=(r"/news/.+",),
        card_selectors=("article",), title_selectors=("h2",),
        date_selectors=("time",), summary_selectors=("p",), parser_adapter=adapter,
    )


HTML = ('<article><h2><a href="/news/one">Official cybersecurity news</a></h2>'
        '<time datetime="2026-10-02">2 October 2026</time><p>Official summary</p></article>')
RSS = ('<rss version="2.0"><channel><title>News</title><item>'
       '<title>Official cybersecurity news</title><link>https://agency.example/news/one</link>'
       '<pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate>'
       '<description>Official summary</description></item></channel></rss>')


@pytest.mark.parametrize("capability", ["listing", "feed"])
def test_duplicate_registration_is_atomic(capability):
    registry = adapters.AdapterRegistry()
    register = getattr(registry, f"register_{capability}")
    lookup = getattr(registry, capability)
    def handler(*args):
        return []

    register(("existing",), handler)
    with pytest.raises(ValueError, match=f"Duplicate {capability} adapter: existing"):
        register(("new", "existing"), handler)
    assert lookup("existing") is handler
    assert lookup("new") is None
    with pytest.raises(ValueError, match="Duplicate"):
        register(("repeated", "repeated"), handler)
    assert lookup("repeated") is None


@pytest.mark.parametrize("name", ["", " ", None, 42])
def test_invalid_names_do_not_partially_register(name):
    registry = adapters.AdapterRegistry()
    with pytest.raises(ValueError, match="non-empty strings"):
        registry.register_listing(("valid", name), lambda *args: [])
    assert registry.listing("valid") is None


def test_listing_and_feed_are_independent_capabilities():
    registry = adapters.AdapterRegistry()
    def listing(*args):
        return []

    def feed(*args):
        return []

    registry.register_listing(("shared",), listing)
    registry.register_feed(("shared",), feed)
    assert registry.listing("shared") is listing
    assert registry.feed("shared") is feed
    assert registry.listing("unknown") is registry.feed("unknown") is None
    assert registry.listing("") is registry.feed("") is None


@pytest.mark.parametrize("names,handler,capability", [
    (adapters.MINISTRY_LISTING_ADAPTERS, adapters.parse_ministry_listing, "listing"),
    (adapters.MINISTRY_FEED_ADAPTERS, adapters.parse_ministry_feed, "feed"),
    (adapters.NORTH_ADAPTERS, adapters.parse_north_listing, "listing"),
    (adapters.NORTH_ADAPTERS, adapters.parse_north_feed, "feed"),
    (adapters.ROUND4_NORTH_ADAPTERS, adapters.parse_round4_listing, "listing"),
    (adapters.ROUND4_SOUTH_FEED_ADAPTERS, adapters.parse_round4_south_feed, "feed"),
    (adapters.FINLAND_LISTING_ADAPTERS, adapters.parse_finland_listing, "listing"),
    (adapters.FINLAND_FEED_ADAPTERS, adapters.parse_finland_feed, "feed"),
])
def test_existing_adapter_capabilities(names, handler, capability):
    lookup = getattr(adapters.PARSER_ADAPTERS, capability)
    assert names
    assert all(lookup(name) is handler for name in names)


@pytest.mark.parametrize("capability,payload", [("listing", HTML), ("feed", RSS.encode())])
@pytest.mark.parametrize("result", [[], [object()]])
def test_dispatch_preserves_arguments_and_result(monkeypatch, capability, payload, result):
    registry = adapters.AdapterRegistry()
    s = source("registered")
    calls = []

    def handler(*args):
        calls.append(args)
        return result

    getattr(registry, f"register_{capability}")((s.parser_adapter,), handler)
    monkeypatch.setattr(parsers, "PARSER_ADAPTERS", registry)
    assert getattr(parsers, f"parse_{capability}")(payload, s, s.listing_url) is result
    assert calls == [(payload, s, s.listing_url)]


@pytest.mark.parametrize("capability,payload", [("listing", HTML), ("feed", RSS)])
def test_registered_errors_propagate_without_generic_fallback(monkeypatch, capability, payload):
    registry = adapters.AdapterRegistry()
    error = ValueError("Publisher scope mismatch")

    def handler(*args):
        raise error

    getattr(registry, f"register_{capability}")(("registered",), handler)
    monkeypatch.setattr(parsers, "PARSER_ADAPTERS", registry)
    with pytest.raises(ValueError) as raised:
        getattr(parsers, f"parse_{capability}")(payload, source("registered"), "fixture")
    assert raised.value is error


@pytest.mark.parametrize("name", ["unknown", "sitecore_public", "bg_defence_onclick"])
def test_unregistered_feed_capability_preserves_generic_rss(name):
    s = source()
    expected = parsers.parse_feed(RSS, s, "fixture")
    actual = parsers.parse_feed(RSS, replace(s, parser_adapter=name), "fixture")
    assert actual == expected
    assert actual[0].date_source == "feed-published"
    assert actual[0].published_at.isoformat() == "2026-10-02T10:00:00+00:00"


@pytest.mark.parametrize("name", ["unknown", "wordpress_rest", "bg_justice_json"])
def test_unregistered_listing_capability_preserves_configured_html(name):
    s = source()
    expected = parsers.parse_listing(HTML, s, s.listing_url)
    actual = parsers.parse_listing(HTML, replace(s, parser_adapter=name), s.listing_url)
    assert actual == expected
    assert actual[0].date_source == "source-selector"
    assert actual[0].published_date_local == "2026-10-02"
    assert actual[0].date_candidates[0].selected


@pytest.mark.parametrize("payload", [RSS, RSS.encode()])
def test_wordpress_non_json_keeps_generic_feed(payload):
    assert parsers.parse_feed(payload, source("wordpress_rest"), "fixture") == parsers.parse_feed(
        payload, source(), "fixture",
    )


def test_generic_json_and_wordpress_json_routes_remain_available():
    wp = json.dumps([{"title": {"rendered": "Official cybersecurity news"},
                      "link": "https://agency.example/news/one", "date_gmt": "2026-10-02T10:00:00"}])
    items = parsers.parse_feed(wp.encode(), source("wordpress_rest"), "fixture")
    assert items[0].date_source == "json-api"
    assert items[0].published_at.isoformat() == "2026-10-02T10:00:00+00:00"
    s = replace(source(), allow_domains=("ec.europa.eu",), include_patterns=(r"/commission/presscorner/detail/",))
    payload = json.dumps({"docuLanguageListResources": [
        {"title": "Official cybersecurity news", "refCode": "IP/26/123", "eventDate": "2026-10-02"},
    ]})
    expected = parsers.parse_feed(payload, s, "fixture")
    assert len(expected) == 1
    assert parsers.parse_feed(payload.encode(), replace(s, parser_adapter="unknown"), "fixture") == expected


def test_sitecore_registration_preserves_legacy_signature(monkeypatch):
    s = source("sitecore_public")
    result = [object()]
    calls = []

    def legacy(html, configured_source):
        calls.append((html, configured_source))
        return result

    monkeypatch.setattr(parsers, "_parse_sitecore_public", legacy)
    assert parsers.parse_listing("payload", s, "ignored-by-legacy") is result
    assert calls == [("payload", s)]


def test_finland_registers_only_supplied_capabilities(monkeypatch):
    def listing(*args):
        return []

    def feed(*args):
        return []

    monkeypatch.setattr(adapters, "FINLAND_LISTING_ADAPTERS", {"test_fi_listing"})
    monkeypatch.setattr(adapters, "FINLAND_FEED_ADAPTERS", {"test_fi_feed"})
    monkeypatch.setattr(adapters, "parse_finland_listing", listing)
    monkeypatch.setattr(adapters, "parse_finland_feed", feed)
    registry = adapters.build_adapter_registry()
    assert registry.listing("test_fi_listing") is listing
    assert registry.feed("test_fi_feed") is feed
    assert registry.feed("test_fi_listing") is registry.listing("test_fi_feed") is None


def test_finland_duplicate_does_not_override_existing_handler(monkeypatch):
    monkeypatch.setattr(adapters, "FINLAND_LISTING_ADAPTERS", {"sitecore_public"})
    with pytest.raises(ValueError, match="Duplicate listing adapter: sitecore_public"):
        adapters.build_adapter_registry()


@pytest.mark.parametrize("capability", ["listing", "feed"])
def test_finland_runtime_dispatch_preserves_article_and_publisher(capability):
    if capability == "listing":
        url = "https://www.oph.fi/fi/tiedotteet"
        s = replace(source("fi_oph_listing"), id="fi_education_agency", country="FI",
                    language="fi", timezone="Europe/Helsinki", homepage="https://www.oph.fi/",
                    listing_url=url, allow_domains=("www.oph.fi",), include_patterns=(r"/fi/uutiset/",))
        payload = '''<main><div class="listing-item node--type-news">
          <h3 class="listing-title"><a class="listing-title__link" href="/fi/uutiset/2026/test">
          Official education publication</a></h3><div class="listing-item-bundle">Tiedote</div>
          <div class="listing-item-footer"><span class="node-post-date">2.10.2026</span></div>
          </div></main>'''
        expected = adapters.parse_finland_listing(payload, s, url)
    else:
        url = "https://www.oikeus.fi/feed/rss-feed?post_type=ajankohtaiset"
        s = replace(source("fi_oikeus_aggregate_rss"), id="fi_judicial_administration_portal",
                    country="FI", language="fi", timezone="Europe/Helsinki", listing_url=url,
                    homepage="https://www.oikeus.fi/", feed_urls=(url,),
                    allow_domains=("www.kho.fi",), include_patterns=(r"/ajankohtaiset/",))
        payload = RSS.replace("agency.example/news/one", "www.kho.fi/ajankohtaiset/test")
        expected = adapters.parse_finland_feed(payload, s, url)
    actual = getattr(parsers, f"parse_{capability}")(payload, s, url)
    assert len(expected) == 1
    assert actual == expected
    assert actual[0].source_id == s.id
    assert actual[0].publisher_organisation
    assert actual[0].published_date_local == "2026-10-02"


def test_missing_finland_module_fails_import_instead_of_generic_fallback():
    code = """
import importlib.abc
import sys

class MissingFinland(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'eu_cyber_news_scraper.finland_adapters':
            raise ModuleNotFoundError('Missing required Finland adapter', name=fullname)

sys.meta_path.insert(0, MissingFinland())
from eu_cyber_news_scraper.parsers import parse_listing
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "ModuleNotFoundError: Missing required Finland adapter" in result.stderr
