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

