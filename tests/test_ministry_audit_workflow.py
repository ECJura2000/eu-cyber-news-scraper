import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

from eu_cyber_news_scraper.source_catalog import EU27

ROOT = Path(__file__).resolve().parents[1]


def workflow():
    return (ROOT / ".github/workflows/ministry-audit.yml").read_text()


def test_country_partition_never_accepts_shell_input(tmp_path):
    text = workflow()
    body = re.search(r"python3 - <<'PY'\n(.*?)\n          PY", text, re.S).group(1)
    for value in ("", "at", "NO", '$(touch injected); DE'):
        output = tmp_path / "outputs"
        output.write_text("")
        result = subprocess.run(["python3", "-c", textwrap.dedent(body)], env={
            **os.environ, "COUNTRY": value, "GITHUB_OUTPUT": str(output),
        }, capture_output=True, text=True, check=False)
        if value in {"", "at"}:
            assert result.returncode == 0
            selected = json.loads(output.read_text().split("=", 1)[1])
            assert set(selected) == (EU27 if not value else {"AT"})
        else:
            assert result.returncode != 0 and not output.read_text()
    assert not (tmp_path / "injected").exists()


def test_country_audit_is_read_only_bounded_and_preserves_history():
    text = workflow()
    assert "max-parallel: 4" in text and "--workers 8" in text
    assert "fail-fast: false" in text and "timeout-minutes: 40" in text
    assert "contents: read" in text and "actions: read" in text
    assert 'cron: "15 1 * * 3"' in text
    for forbidden in ("ref: state", "--health-write", ".source-health.json", "git push", "contents: write"):
        assert forbidden not in text
    assert "ministry-inventory-state-$COUNTRY" in text
    assert "source-inventory-state" in text and "starting a new diagnostic baseline" in text
    assert "--audit-urls" in text and '"$COUNTRY"' in text
    assert text.count("retention-days: 90") == 2
    assert "--allow-unhealthy" in text
    actions = re.findall(r"(?m)^\s*- uses:\s*(\S+)", text)
    assert actions and all(re.fullmatch(r"actions/[a-z-]+@[a-f0-9]{40}", item) for item in actions)
    old = (ROOT / ".github/workflows/source-audit.yml").read_text()
    assert "--country EU --country NO" in old
