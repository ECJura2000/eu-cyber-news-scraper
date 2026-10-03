import asyncio
import copy
import json
from datetime import date

import httpx
import pytest

from eu_cyber_news_scraper import ministry_inventory as inventory
from eu_cyber_news_scraper.organisation_registry import OrganisationModule, OrganisationRegistry


@pytest.fixture
def registry():
    module = OrganisationModule("at_department", "test", {
        "sources": [{"id": "at_department", "country": "AT"}],
        "verification": {"status": "smoke_healthy"},
    }, "test-fixture", False)
    return OrganisationRegistry((module,), (), "test")


@pytest.fixture
def country():
    return {
        "schema_version": 1, "country": "AT", "reviewed_on": "2026-09-30",
        "official_roster_urls": ["https://government.example.eu/ministries"],
        "roster_complete": True, "limitations": [], "ministries": [{
            "canonical_id": "at_department", "name_zh": "測試部", "name_local": "Testministerium",
            "name_en": "Test Ministry", "kind": "ministry", "language": "de",
            "homepage": "https://department.example.eu/", "news_url": "https://department.example.eu/news",
            "source_ids": ["at_department"], "status": "manual_verified",
            "reason": "Synthetic unit-test parser evidence, not an official roster.",
            "evidence_urls": ["https://department.example.eu/news"],
        }],
    }


def save(directory, value, name="AT.json"):
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


def test_manual_evidence_and_recorded_review_are_separate(country, registry, tmp_path):
    inventory.validate_country(country, registry, today=date(2026, 10, 1))
    save(tmp_path, country)
    records = inventory.load_inventory(tmp_path, registry)
    report = inventory.inventory_report(records)
    assert report["status"] == "attention"
    assert report["country_count"] == report["registered_ministries"] == 1
    assert report["new_manual_verified_ministries"] == 1
    assert "not_live_reverification" in report["evidence_check"]
    assert not report["automatic_schedule_changes"]
    assert len(report["missing_countries"]) == 26


@pytest.mark.parametrize("mutation,match", [
    (lambda c: c.update(schema_version=2), "invalid ministry"),
    (lambda c: c.update(reviewed_on="2999-01-01"), "future"),
    (lambda c: c.update(official_roster_urls=["http://government.example.eu/"]), "HTTPS"),
    (lambda c: c.update(roster_complete=False), "limitations"),
    (lambda c: c["ministries"].append(copy.deepcopy(c["ministries"][0])), "duplicate"),
    (lambda c: c["ministries"][0].update(canonical_id="de_other"), "mismatched"),
    (lambda c: c["ministries"][0].update(name_en=" "), "blank"),
    (lambda c: c["ministries"][0].update(homepage="https://127.0.0.1/"), "hostname"),
    (lambda c: c["ministries"][0].update(source_ids=[]), "requires source_ids"),
    (lambda c: c["ministries"][0].update(status="blocked"), "unresolved"),
    (lambda c: c["ministries"][0].update(homepage=None), "requires homepage"),
    (lambda c: c["ministries"][0].update(source_ids=["unknown"]), "missing"),
    (lambda c: c["ministries"][0].update(status="no_news_endpoint", source_ids=[]), "cannot declare"),
])
def test_invalid_claims_are_rejected(country, registry, mutation, match):
    mutation(country)
    with pytest.raises(ValueError, match=match):
        inventory.validate_country(country, registry)


def test_pending_and_blocked_remain_inventory_only(country, registry):
    row = country["ministries"][0]
    for status in ("parser_pending", "blocked", "needs_review", "no_news_endpoint"):
        row.update(status=status, source_ids=[], news_url=None)
        inventory.validate_country(country, registry)
        assert inventory.inventory_report([country])["registered_ministries"] == 0


def test_registered_does_not_imply_new_live_verification(country, registry):
    row = country["ministries"][0]
    registry.modules[0].payload["verification"]["status"] = "parser_pending"
    with pytest.raises(ValueError, match="successful live"):
        inventory.validate_country(country, registry)
    row["status"] = "existing_source"
    inventory.validate_country(country, registry)
    assert inventory.inventory_report([country])["new_manual_verified_ministries"] == 0
    registry.modules[0].payload["sources"][0]["country"] = "DE"
    with pytest.raises(ValueError, match="cross-country"):
        inventory.validate_country(country, registry)


def test_complete_rosters_can_have_no_searchable_endpoints(country):
    records = []
    for code in sorted(inventory.EU27):
        item = copy.deepcopy(country)
        item.update(country=code)
        item["ministries"][0].update(canonical_id=code.lower()+"_department", status="blocked", source_ids=[])
        records.append(item)
    report = inventory.inventory_report(records)
    assert report["status"] == "complete"
    assert report["ministry_count"] == 27 and report["registered_ministries"] == 0
    assert report["unresolved_ministries"] == 27
    assert report["searchable_inventory_complete"] is False
    for record in records:
        record["ministries"][0].update(status="existing_source", source_ids=["registered"])
    assert inventory.inventory_report(records)["searchable_inventory_complete"] is True
    records[0].update(roster_complete=False, limitations=["Official roster unavailable"])
    report = inventory.inventory_report(records)
    assert report["status"] == "attention" and report["incomplete_rosters"] == [records[0]["country"]]


def test_directory_load_errors(country, registry, tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        inventory.load_inventory(tmp_path / "missing", registry)
    with pytest.raises(ValueError, match="no country"):
        inventory.load_inventory(tmp_path, registry)
    save(tmp_path, country, "wrong.json")
    with pytest.raises(ValueError, match="filename"):
        inventory.load_inventory(tmp_path, registry)
    with pytest.raises(ValueError, match="registry is invalid"):
        inventory.load_inventory(tmp_path, OrganisationRegistry((), ("invalid module",), "test"))
    (tmp_path / "wrong.json").unlink()
    (tmp_path / "AT.json").write_text('{"country":"AT","country":"DE"}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        inventory.load_inventory(tmp_path, registry)


def test_size_limit(country, registry, tmp_path, monkeypatch):
    save(tmp_path, country)
    monkeypatch.setattr(inventory, "MAX_CATALOG_BYTES", 5)
    with pytest.raises(ValueError, match="size limit"):
        inventory.load_inventory(tmp_path, registry)


def test_cli_reports_errors_gaps_and_country_selection(country, registry, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(inventory, "load_organisation_registry", lambda: registry)
    args = ["--inventory-dir", str(tmp_path)]
    assert inventory.main(args+ ["--check"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"
    save(tmp_path, country)
    original = (tmp_path / "AT.json").read_bytes()
    assert inventory.main(args+["--json", "--country", "AT"]) == 1
    assert json.loads(capsys.readouterr().out)["countries"][0]["country"] == "AT"
    assert inventory.main(args+["--country", "DE"]) == 2
    assert "尚無" in capsys.readouterr().err
    assert inventory.main(args) == 1
    assert "測試部" in capsys.readouterr().out
    assert (tmp_path / "AT.json").read_bytes() == original
    monkeypatch.setattr(inventory, "EU27", frozenset({"AT"}))
    assert inventory.main(args+["--check"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "complete"


def test_inventory_location_install_and_frozen(tmp_path, monkeypatch):
    packaged = tmp_path / "ministry_inventory"
    packaged.mkdir()
    monkeypatch.setattr(inventory.sys, "frozen", True, raising=False)
    monkeypatch.setattr(inventory.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert inventory.inventory_directory() == packaged


def test_cli_dispatch(monkeypatch):
    from eu_cyber_news_scraper import cli
    monkeypatch.setattr(cli.sys, "argv", ["eu-cyber-news", "ministries", "--check"])
    monkeypatch.setattr(inventory, "main", lambda argv: 0 if argv == ["--check"] else 2)
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0


def test_url_audit_deduplicates_shared_urls_and_does_not_claim_parser_success(country, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from eu_cyber_news_scraper import source_audit
    monkeypatch.setattr(source_audit, "_validate_public_dns", AsyncMock())
    monkeypatch.setattr(inventory.AuditHttpClient, "_pace", AsyncMock())
    calls = []
    def handler(request):
        calls.append(str(request.url))
        text = "User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else "<html><body>Official news</body></html>"
        return httpx.Response(200, text=text, headers={"content-type": "text/plain" if request.url.path == "/robots.txt" else "text/html"})
    row = country["ministries"][0]
    row.update(status="parser_pending", source_ids=[])
    other = copy.deepcopy(row)
    other["canonical_id"] = "at_other"
    country["ministries"].append(other)
    report = asyncio.run(inventory.audit_inventory_urls([country], tmp_path, transport=httpx.MockTransport(handler)))
    assert report["status"] == "complete"
    assert not report["parser_validation_performed"] and not report["automatic_schedule_changes"]
    assert len(report["endpoints"]) == 2
    assert all(row["ministry_ids"] == ["at_department", "at_other"] for row in report["endpoints"])
    assert calls.count("https://department.example.eu/news") == 1
    assert (tmp_path / "ministry-urls.json").is_file()


def test_url_audit_missing_or_blocked_urls_keep_gaps(country, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from eu_cyber_news_scraper import source_audit
    monkeypatch.setattr(source_audit, "_validate_public_dns", AsyncMock())
    monkeypatch.setattr(inventory.AuditHttpClient, "_pace", AsyncMock())
    row = country["ministries"][0]
    row.update(status="blocked", source_ids=[], news_url=None)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /",
                                                           headers={"content-type": "text/plain"}))
    report = asyncio.run(inventory.audit_inventory_urls([country], tmp_path, transport=transport))
    assert report["status"] == "attention"
    assert report["unresolved_endpoint_ministries"] == ["at_department"]
    assert report["endpoints"][0]["error_code"] == "robots_denied"
    row.update(status="existing_source", source_ids=["at_department"])
    report = asyncio.run(inventory.audit_inventory_urls([country], tmp_path, transport=transport))
    assert not report["endpoints"]


def test_url_audit_cli_cannot_overwrite_inventory(country, registry, tmp_path, monkeypatch, capsys):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(inventory, "load_organisation_registry", lambda: registry)
    save(tmp_path, country)
    with pytest.raises(SystemExit):
        inventory.main(["--inventory-dir", str(tmp_path), "--audit-urls", "--output-dir", str(tmp_path)])
    monkeypatch.setattr(inventory, "audit_inventory_urls", AsyncMock(return_value={"status": "attention"}))
    assert inventory.main(["--inventory-dir", str(tmp_path), "--audit-urls", "--output-dir", str(tmp_path.parent)]) == 1
    assert json.loads(capsys.readouterr().out)["url_audit"]["status"] == "attention"
    monkeypatch.setattr(inventory, "audit_inventory_urls", AsyncMock(side_effect=OSError("diagnostic output failed")))
    assert inventory.main(["--inventory-dir", str(tmp_path), "--audit-urls", "--output-dir", str(tmp_path.parent)]) == 2
    assert "diagnostic output failed" in capsys.readouterr().out
