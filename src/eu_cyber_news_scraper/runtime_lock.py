from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path


def acquire_run_lock(output_path: str | Path, run_id: str, stale_after_seconds: int = 21600) -> Path:
    output = Path(output_path).expanduser().resolve()
    lock_path = output.with_suffix(f"{output.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists() and not _lock_is_active(lock_path, stale_after_seconds):
        lock_path.unlink(missing_ok=True)
    created_at = datetime.now(timezone.utc)
    payload = json.dumps(
        {
            "run_id": run_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": created_at.isoformat(),
            "created_at_epoch": created_at.timestamp(),
        },
        ensure_ascii=False,
    )
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"相同輸出已有執行中的工作：{lock_path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload + "\n")
    return lock_path


def _lock_is_active(path: Path, stale_after_seconds: int) -> bool:
    age = time.time() - path.stat().st_mtime
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return age <= stale_after_seconds
    if payload.get("hostname") not in {None, socket.gethostname()}:
        return age <= stale_after_seconds
    try:
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError):
        return age <= stale_after_seconds
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def release_run_lock(lock_path: str | Path, run_id: str) -> None:
    path = Path(lock_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if payload.get("run_id") == run_id:
        path.unlink(missing_ok=True)
