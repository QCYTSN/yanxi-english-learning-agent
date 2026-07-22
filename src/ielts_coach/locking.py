from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock, Timeout


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:160]


@contextmanager
def runtime_lock(home: Path, key: str, *, timeout: float = 15.0) -> Iterator[None]:
    """Cross-process lock for a Session or ID-generation scope."""

    folder = home / "runtime" / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(folder / f"{_safe_key(key)}.lock"), timeout=timeout)
    try:
        with lock:
            yield
    except Timeout as exc:
        raise TimeoutError(f"Timed out waiting for runtime lock: {key}") from exc

