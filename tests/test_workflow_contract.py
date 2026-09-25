from pathlib import Path


def test_manual_source_probe_does_not_advance_schedule_state():
    workflow = Path(".github/workflows/scrape.yml").read_text(encoding="utf-8")
    assert "SOURCE: ${{ inputs.source }}" in workflow
    assert 'if [[ -n "$SOURCE" ]]; then args+=(--source "$SOURCE"); fi' in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "--require-complete-artifacts" in workflow
