from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .runtime_lock import acquire_run_lock, release_run_lock


@contextmanager
def state_lock(path: str | Path, run_id: str, wait_seconds: float = 30.0) -> Iterator[None]:
    state_anchor = Path(path).expanduser().resolve().parent / ".state"
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        try:
            lock_path = acquire_run_lock(state_anchor, run_id)
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"健康狀態正由其他程序更新：{state_anchor}.lock") from None
            time.sleep(0.1)
    try:
        yield
    finally:
        release_run_lock(lock_path, run_id)
