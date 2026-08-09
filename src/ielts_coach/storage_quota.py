from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .config import load_settings


DEFAULT_LOCAL_STORAGE_QUOTA = 25 * 1024 * 1024 * 1024
MIN_FREE_DISK_RESERVE = 512 * 1024 * 1024
_CACHE_LOCK = threading.Lock()
_USAGE_CACHE: dict[Path, tuple[float, int]] = {}


def local_storage_status(home: Path, *, refresh: bool = False) -> dict[str, Any]:
    root = home.resolve()
    settings = load_settings(root)
    quota = max(
        1024 * 1024 * 1024,
        int(settings.get("local_storage_quota_bytes") or DEFAULT_LOCAL_STORAGE_QUOTA),
    )
    used = _cached_managed_size(root, refresh=refresh)
    disk = shutil.disk_usage(root)
    quota_remaining = max(0, quota - used)
    disk_remaining = max(0, int(disk.free) - MIN_FREE_DISK_RESERVE)
    return {
        "quota_bytes": quota,
        "used_bytes": used,
        "quota_remaining_bytes": quota_remaining,
        "disk_free_bytes": int(disk.free),
        "disk_reserve_bytes": MIN_FREE_DISK_RESERVE,
        "writable_bytes": min(quota_remaining, disk_remaining),
        "over_quota": used > quota,
    }


def assert_local_storage_capacity(home: Path, incoming_bytes: int) -> None:
    required = max(0, int(incoming_bytes))
    status = local_storage_status(home)
    if required > int(status["writable_bytes"]):
        raise ValueError(
            "Not enough managed local storage is available for this upload. "
            "Delete unused imports or attachments, or increase the local storage quota."
        )


def invalidate_storage_usage(home: Path) -> None:
    with _CACHE_LOCK:
        _USAGE_CACHE.pop(home.resolve(), None)


def _cached_managed_size(home: Path, *, refresh: bool) -> int:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _USAGE_CACHE.get(home)
        if not refresh and cached and now - cached[0] <= 5.0:
            return cached[1]
    total = 0
    for relative in (
        Path("media"),
        Path("study-threads"),
        Path("corpus") / "inbox",
        Path("corpus") / "private",
    ):
        root = home / relative
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    with _CACHE_LOCK:
        _USAGE_CACHE[home] = (now, total)
    return total
