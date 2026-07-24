from __future__ import annotations

import math
import threading
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

from .storage import connect, db_path, initialise_database


@dataclass(frozen=True)
class RequestSample:
    route: str
    method: str
    status: int
    duration_ms: float
    created_at: float


class RequestPerformanceMonitor:
    """Bounded, metadata-only request timing for the local application process."""

    def __init__(self, capacity: int = 1000) -> None:
        self._samples: deque[RequestSample] = deque(maxlen=max(100, capacity))
        self._lock = threading.Lock()

    def record(self, route: str, method: str, status: int, duration_ms: float) -> None:
        with self._lock:
            self._samples.append(
                RequestSample(route, method, status, duration_ms, time())
            )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
        durations = sorted(item.duration_ms for item in samples)
        route_groups: dict[str, list[float]] = {}
        for item in samples:
            route_groups.setdefault(f"{item.method} {item.route}", []).append(
                item.duration_ms
            )
        slowest = sorted(
            (
                {
                    "route": route,
                    "requests": len(values),
                    "average_ms": round(sum(values) / len(values), 1),
                    "p95_ms": round(_percentile(sorted(values), 0.95), 1),
                }
                for route, values in route_groups.items()
            ),
            key=lambda item: (item["p95_ms"], item["requests"]),
            reverse=True,
        )[:8]
        statuses = Counter(f"{item.status // 100}xx" for item in samples)
        return {
            "sample_capacity": self._samples.maxlen,
            "sample_count": len(samples),
            "window_started_at": min(
                (item.created_at for item in samples), default=None
            ),
            "average_ms": round(sum(durations) / len(durations), 1)
            if durations
            else None,
            "p50_ms": round(_percentile(durations, 0.5), 1) if durations else None,
            "p95_ms": round(_percentile(durations, 0.95), 1) if durations else None,
            "status_counts": dict(statuses),
            "slowest_routes": slowest,
        }


def database_performance_status(home: Path) -> dict[str, Any]:
    initialise_database(home)
    path = db_path(home)
    with connect(home) as conn:
        pragmas = {
            "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]),
            "synchronous": int(conn.execute("PRAGMA synchronous").fetchone()[0]),
            "busy_timeout_ms": int(conn.execute("PRAGMA busy_timeout").fetchone()[0]),
            "cache_size": int(conn.execute("PRAGMA cache_size").fetchone()[0]),
            "page_count": int(conn.execute("PRAGMA page_count").fetchone()[0]),
            "page_size": int(conn.execute("PRAGMA page_size").fetchone()[0]),
            "freelist_count": int(conn.execute("PRAGMA freelist_count").fetchone()[0]),
        }
        counts = {
            str(row["name"]): int(row["rows"])
            for row in conn.execute(
                """
                SELECT 'sessions' name,COUNT(*) rows FROM sessions
                UNION ALL SELECT 'questions',COUNT(*) FROM questions
                UNION ALL SELECT 'assessment_packs',COUNT(*) FROM assessment_packs
                UNION ALL SELECT 'agent_runs',COUNT(*) FROM agent_runs
                UNION ALL SELECT 'media_assets',COUNT(*) FROM media_assets
                """
            ).fetchall()
        }
    allocated = pragmas["page_count"] * pragmas["page_size"]
    reclaimable = pragmas["freelist_count"] * pragmas["page_size"]
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "allocated_bytes": allocated,
        "reclaimable_bytes": reclaimable,
        "pragmas": pragmas,
        "row_counts": counts,
        "native_acceleration": {
            "enabled": False,
            "decision": "not_needed",
            "reason": (
                "SQLite queries and Python orchestration remain the measured boundary; "
                "add a native worker only after a reproducible CPU profile identifies one."
            ),
        },
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return math.nan
    index = max(0, min(len(values) - 1, math.ceil(len(values) * fraction) - 1))
    return values[index]
