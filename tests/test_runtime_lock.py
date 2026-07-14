import json
import os
import socket
import time

import pytest

from eu_cyber_news_scraper.runtime_lock import acquire_run_lock, release_run_lock


def test_run_lock_prevents_overlapping_output_and_can_be_released(tmp_path):
    output = tmp_path / "result.xlsx"
    lock = acquire_run_lock(output, "first")
    with pytest.raises(RuntimeError, match="執行中"):
        acquire_run_lock(output, "second")
    release_run_lock(lock, "first")
    second = acquire_run_lock(output, "second")
    release_run_lock(second, "second")


def test_dead_process_lock_is_recovered_without_waiting_for_age(tmp_path):
    output = tmp_path / "result.xlsx"
    lock = output.with_suffix(".xlsx.lock")
    lock.write_text(
        json.dumps({"run_id": "dead", "pid": 99999999, "hostname": socket.gethostname()}),
        encoding="utf-8",
    )
    recovered = acquire_run_lock(output, "new")
    assert json.loads(recovered.read_text(encoding="utf-8"))["run_id"] == "new"
    release_run_lock(recovered, "new")


def test_live_process_lock_is_not_removed_even_when_old(tmp_path):
    output = tmp_path / "result.xlsx"
    lock = output.with_suffix(".xlsx.lock")
    lock.write_text(
        json.dumps({"run_id": "live", "pid": os.getpid(), "hostname": socket.gethostname()}),
        encoding="utf-8",
    )
    old = time.time() - 86400
    os.utime(lock, (old, old))
    with pytest.raises(RuntimeError, match="執行中"):
        acquire_run_lock(output, "new", stale_after_seconds=1)


def test_release_ignores_missing_or_corrupt_lock(tmp_path):
    missing = tmp_path / "missing.lock"
    release_run_lock(missing, "run")
    missing.write_text("not json", encoding="utf-8")
    release_run_lock(missing, "run")
    assert missing.exists()
