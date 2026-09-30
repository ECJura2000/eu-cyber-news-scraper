import asyncio
import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from eu_cyber_news_scraper import source_catalog as catalog


@pytest.fixture
def data():
    return catalog.load_catalog(catalog.catalog_directory() / "eu27.seed.json")


@pytest.fixture(autouse=True)
def fast_pacing(monkeypatch):
    async def no_pace(_self, _host):
        pass
    monkeypatch.setattr(catalog.HttpClient, "_pace", no_pace)


def test_builtin_catalog_has_evidence_and_keeps_parser_gaps(data):
    assert not catalog.validate_catalog(data)
    report = catalog.check_report(data)
    assert report["institution_count"] == 12
    assert report["searchable_count"] == report["auto_enrolled"] == 0
    assert len(report["parser_gaps"]) == 12
    assert report["coverage"]["completeness"] == "partial"
    assert report["coverage"]["countries_without_catalog_entries"]


@pytest.mark.parametrize("value", [
    "http://example.eu/", "https://user:pass@example.eu/", "https://example.eu:444/",
    "https://127.0.0.1/", "https://foo.local/", "https://foo.test/",
    "https://example.eu/a b", "https://example.eu/../secret", "https://example.eu/%252e%252e/",
    "https://example.eu/\\secret", "https://example.eu/%00", "https://example.eu:wrong/",
])
def test_catalog_rejects_malformed_or_nonpublic_url(value):
    with pytest.raises(ValueError):
        catalog.https_url(value)


def test_link_identity_removes_tracking_and_fragment():
    assert catalog._url_key("https://www.example.eu/news/?utm_source=mail#anchor") == ("example.eu", "/news")


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(schema_version=999),
    lambda c: c["institutions"][0].update(searchable=True),
    lambda c: c["institutions"][0].update(topics=["unknown"]),
    lambda c: c["institutions"][0].update(canonical_id="fr_imec"),
    lambda c: c["institutions"].append(copy.deepcopy(c["institutions"][0])),
    lambda c: c["institutions"][0]["verification"].update(verified_on="2999-01-01"),
    lambda c: c["institutions"][0]["verification"].update(urls=["https://www.imec-int.com/en"]),
    lambda c: c["institutions"][0].update(news_url="https://unrelated.eu/news"),
    lambda c: c["institutions"][0].update(official_domains=["other.eu"]),
    lambda c: c["discovery"]["directory_seeds"].append(copy.deepcopy(c["discovery"]["directory_seeds"][0])),
    lambda c: c["discovery"]["directory_seeds"][0]["verification"].update(verified_on="2999-01-01"),
    lambda c: c["discovery"]["directory_seeds"][0]["verification"].update(urls=["https://other.eu/"]),
    lambda c: c["discovery"]["directory_seeds"][0]["candidate_domains"][0].update(country="FI"),
    lambda c: c["discovery"]["directory_seeds"][0]["candidate_domains"].append(
        copy.deepcopy(c["discovery"]["directory_seeds"][0]["candidate_domains"][0])),
])
def test_catalog_invalid_metadata_is_not_called_verified(data, mutation):
    mutation(data)
    report = catalog.check_report(data)
    assert report["status"] == "invalid"
    assert report["validation_errors"]


def test_registry_collision_and_unavailable_registry(data, tmp_path):
    directory = tmp_path / "registry"
    directory.mkdir()
    row = data["institutions"][0]
    (directory / "known.json").write_text(json.dumps({"canonical_id": row["canonical_id"],
       "sources": [{"id": row["canonical_id"], "homepage": row["homepage"], "listing_url": row["news_url"]}]}))
    assert any("duplicate" in value for value in catalog.validate_catalog(data, registry_dir=directory))
    assert catalog.check_report(data, registry_dir=tmp_path / "absent")["status"] == "invalid"


def test_load_rejects_duplicate_keys_large_files_and_nonobjects(tmp_path):
    path = tmp_path / "catalog.json"
    for value in ('{"schema_version":1,"schema_version":2}', '[]', "x" * (catalog.MAX_CATALOG_BYTES + 1)):
        path.write_text(value)
        with pytest.raises(ValueError):
            catalog.load_catalog(path)


def discover_mock(data, html, status=200, redirect=None, robots="User-agent: *\nAllow: /"):
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots, headers={"content-type": "text/plain"}, request=request)
        if redirect:
            return httpx.Response(302, headers={"location": redirect}, request=request)
        return httpx.Response(status, text=html, headers={"content-type": "text/html"}, request=request)
    result = asyncio.run(catalog.discover(data, transport=httpx.MockTransport(handler)))
    return result, calls


def test_discovery_only_fetches_directories_and_deduplicates_known_hosts(data):
    html = """<html><a href='https://networks.imdea.org/'>New institute</a>
    <a href='https://networks.imdea.org/#two'>Duplicate institute</a>
    <a href='https://software.imdea.org/'>Already registered</a>
    <a href='https://ceps.eu/'>Known</a><a href='javascript:void(0)'>Bad</a>
    <a href='#anchor'>Navigation</a><a href='https://unrelated.eu/'>Not declared</a></html>"""
    result, calls = discover_mock(data, html)
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["verification_status"] == "unverified"
    assert result["candidate_pages_fetched"] == result["auto_enrolled"] == 0
    assert not any("networks.imdea.org" in url for url in calls)
    assert result["seed_results"][0]["duplicates"] >= 2


def test_discovery_reports_bounds_and_fetch_failure_without_claiming_absence(data):
    data["discovery"]["max_seed_pages"] = 1
    data["discovery"]["max_links_per_page"] = 1
    result, _ = discover_mock(data, "<html><a href='https://networks.imdea.org/'>one</a><a href='#a'>two</a></html>")
    assert result["status"] == "attention"
    assert result["skipped_seed_ids"]
    assert result["seed_results"][0]["bounds_reached"]
    result, _ = discover_mock(data, "<html>blocked</html>", robots="User-agent: *\nDisallow: /")
    assert result["status"] == "attention"
    assert result["candidate_count"] == 0
    assert result["seed_results"][0]["error_type"] == "RobotsDeniedError"


def test_discovery_rejects_redirect_off_directory_domain(data):
    result, calls = discover_mock(data, "", redirect="https://attacker.eu/news")
    assert result["status"] == "attention"
    assert not any(url.startswith("https://attacker.eu/") for url in calls)


def test_candidate_history_survives_missing_directory_and_remains_unverified(data):
    result, _ = discover_mock(data, "<a href='https://networks.imdea.org/'>Institute</a>")
    first = catalog.maintain_candidates(result, None)
    assert first["new_candidate_count"] == 1
    second = catalog.maintain_candidates({"status": "complete", "candidates": []}, {"discovery": first})
    assert second["candidate_count"] == 1
    assert second["candidates"][0]["seen_this_run"] is False
    assert second["candidates"][0]["verification_status"] == "unverified"
    third = catalog.maintain_candidates(result, {"discovery": first})
    assert third["new_candidate_count"] == 0
    assert third["candidates"][0]["first_seen_at"] == first["candidates"][0]["first_seen_at"]
    first["candidates"][0]["searchable"] = True
    with pytest.raises(ValueError, match="unverified"):
        catalog.maintain_candidates(result, {"discovery": first})
    with pytest.raises(ValueError, match="invalid previous"):
        catalog.maintain_candidates(result, {"discovery": {"candidates": "bad"}})


def test_catalog_cli_check_and_output_do_not_mutate_seed(data, tmp_path, capsys):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert catalog.main(["--check", "--catalog", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["institution_count"] == 12
    output = tmp_path / "report.json"
    assert catalog.main(["--check", "--catalog", str(path), "--output", str(output)]) == 0
    assert output.exists() and path.read_bytes() == before
    with pytest.raises(SystemExit):
        catalog.main(["--check", "--catalog", str(path), "--output", str(path)])
    path.write_text("{}")
    assert catalog.main(["--check", "--catalog", str(path)]) == 2


def test_catalog_cli_reports_attention_and_preserves_previous(data, tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"discovery": {"candidates": []}}))
    monkeypatch.setattr(catalog, "discover", AsyncMock(return_value={"status": "attention", "candidates": []}))
    monkeypatch.setattr(catalog, "audit_catalog_urls", AsyncMock(return_value={"healthy": False}))
    assert catalog.main(["--check", "--discover", "--audit-urls", "--previous", str(previous),
                         "--output", str(output)]) == 1
    value = json.loads(output.read_text())
    assert value["discovery"]["prior_inventory_restored"] is True
    assert value["url_audit"]["healthy"] is False


def test_catalog_url_audit_uses_shared_source_checker(data, tmp_path, monkeypatch):
    mock = AsyncMock(return_value={"healthy": True})
    monkeypatch.setattr(catalog, "audit_sources", mock)
    assert asyncio.run(catalog.audit_catalog_urls(data, tmp_path))["healthy"]
    rows = mock.call_args.args[0]
    assert len(rows) == 12 and all(not row.schedule_enabled for row in rows)
    assert mock.call_args.kwargs["workers"] == 4


def test_invalid_catalog_cannot_discover(data):
    data["schema_version"] = -1
    with pytest.raises(ValueError, match="invalid catalog"):
        asyncio.run(catalog.discover(data))
