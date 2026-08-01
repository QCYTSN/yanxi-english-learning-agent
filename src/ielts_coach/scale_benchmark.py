from __future__ import annotations

import gc
import json
import statistics
import tempfile
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .config import DEFAULT_SETTINGS, write_yaml
from .performance import database_performance_status
from .question_bank import draw_question
from .storage import (
    connect,
    initialise_database,
    list_questions,
    list_sessions,
)

DEFAULT_SESSION_COUNT = 10_000
DEFAULT_QUESTION_COUNT = 100_000

# These are interaction budgets, not claims about every possible machine.
DEFAULT_THRESHOLDS_MS = {
    "sessions_first_page": 250.0,
    "sessions_deep_page": 500.0,
    "questions_first_page": 250.0,
    "questions_filtered_page": 250.0,
    "questions_deep_page": 500.0,
    "questions_text_search": 750.0,
    "question_random_draw": 500.0,
    "database_status": 750.0,
}


def seed_scale_fixture(
    home: Path,
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
    question_count: int = DEFAULT_QUESTION_COUNT,
    batch_size: int = 5_000,
) -> dict[str, Any]:
    """Create a synthetic, non-copyrighted scale fixture in an empty data home."""
    session_count = max(1, int(session_count))
    question_count = max(1, int(question_count))
    batch_size = max(100, min(int(batch_size), 20_000))
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    write_yaml(home / "config" / "settings.yaml", DEFAULT_SETTINGS)
    initialise_database(home)
    with connect(home) as conn:
        existing_sessions = int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        existing_questions = int(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0])
    if existing_sessions or existing_questions:
        raise ValueError(
            "Scale fixtures may only be seeded into a database with no sessions or questions"
        )

    started = perf_counter()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    modules = ("listening", "reading", "writing", "speaking")
    question_types = (
        "multiple_choice",
        "matching_headings",
        "sentence_completion",
        "short_answer",
    )
    question_sql = """
        INSERT INTO questions(
            question_id,corpus_id,module,task,part,question_number,question_type,
            title,content,passage_id,topics_text,source_type,authenticity,
            review_status,practice_mode,standard_profile,conformance_status,
            content_hash,payload_json,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    session_sql = """
        INSERT INTO sessions(
            session_id,module,occurred_at,question_id,mode,status,band,score_kind,
            score_confidence,duration_minutes,payload_json,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    with connect(home) as conn:
        for start in range(0, question_count, batch_size):
            stop = min(start + batch_size, question_count)
            rows = []
            for index in range(start, stop):
                module = modules[index % len(modules)]
                question_id = f"BENCH-Q-{index:07d}"
                question_type = question_types[index % len(question_types)]
                content = (
                    f"Synthetic benchmark question {index}. "
                    f"benchmark phrase {index % 97}."
                )
                payload = {
                    "question_id": question_id,
                    "module": module,
                    "question_type": question_type,
                    "content": content,
                    "source_type": "synthetic_benchmark",
                }
                created_at = (now + timedelta(seconds=index)).isoformat()
                rows.append(
                    (
                        question_id,
                        None,
                        module,
                        "task2" if module == "writing" else None,
                        str((index % 3) + 1),
                        str((index % 40) + 1),
                        question_type,
                        f"Benchmark {index}",
                        content,
                        None,
                        f"benchmark topic-{index % 32}",
                        "synthetic_benchmark",
                        "synthetic",
                        "benchmark_only",
                        "practice",
                        "ielts-academic-benchmark",
                        "benchmark_only",
                        f"benchmark-hash-{index:07d}",
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        created_at,
                        created_at,
                    )
                )
            conn.executemany(question_sql, rows)

        for start in range(0, session_count, batch_size):
            stop = min(start + batch_size, session_count)
            rows = []
            for index in range(start, stop):
                module = modules[index % len(modules)]
                occurred_at = (now + timedelta(minutes=index)).isoformat()
                rows.append(
                    (
                        f"BENCH-S-{index:06d}",
                        module,
                        occurred_at,
                        f"BENCH-Q-{index % question_count:07d}",
                        "benchmark",
                        "completed",
                        5.0 + ((index % 5) * 0.5),
                        "ai_estimate",
                        "benchmark",
                        20.0 + (index % 40),
                        "{}",
                        occurred_at,
                        occurred_at,
                    )
                )
            conn.executemany(session_sql, rows)
        conn.execute("ANALYZE")
    return {
        "home": str(home),
        "session_count": session_count,
        "question_count": question_count,
        "seed_duration_seconds": round(perf_counter() - started, 3),
    }


def benchmark_scale_fixture(
    home: Path,
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
    question_count: int = DEFAULT_QUESTION_COUNT,
    repeats: int = 5,
    thresholds_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Measure the user-visible SQLite paths against a prepared scale fixture."""
    repeats = max(1, min(int(repeats), 20))
    budgets = dict(DEFAULT_THRESHOLDS_MS)
    budgets.update(thresholds_ms or {})
    measurements: dict[str, float] = {}
    operations: dict[str, Callable[[], Any]] = {
        "sessions_first_page": lambda: list_sessions(home, limit=50),
        "sessions_deep_page": lambda: list_sessions(
            home, limit=50, offset=max(0, session_count - 50)
        ),
        "questions_first_page": lambda: list_questions(home, limit=50),
        "questions_filtered_page": lambda: list_questions(
            home,
            module="reading",
            question_type="matching_headings",
            limit=50,
        ),
        "questions_deep_page": lambda: list_questions(
            home, limit=50, offset=max(0, question_count - 50)
        ),
        "questions_text_search": lambda: list_questions(
            home, query="benchmark phrase 42", limit=50
        ),
        "question_random_draw": lambda: draw_question(
            home, module="reading", seed=20260729
        ),
        "database_status": lambda: database_performance_status(home),
    }
    for name, operation in operations.items():
        measurements[name] = _median_duration_ms(operation, repeats=repeats)

    gc.collect()
    tracemalloc.start()
    draw_question(home, module="reading", seed=20260729)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    with connect(home) as conn:
        actual_counts = {
            "sessions": int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
            "questions": int(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]),
        }
        query_plans = {
            "sessions_first_page": _query_plan(
                conn,
                "SELECT session_id FROM sessions ORDER BY occurred_at DESC LIMIT 50",
            ),
            "questions_filtered_page": _query_plan(
                conn,
                "SELECT question_id FROM questions "
                "WHERE module='reading' AND question_type='matching_headings' "
                "ORDER BY question_id LIMIT 50",
            ),
        }
    query_plan_checks = {
        "sessions_order_uses_index": (
            any("idx_sessions_occurred" in item for item in query_plans["sessions_first_page"])
            and not any("TEMP B-TREE" in item for item in query_plans["sessions_first_page"])
        ),
        "question_filter_uses_composite_index": any(
            "idx_questions_module_type_id" in item
            for item in query_plans["questions_filtered_page"]
        ),
    }

    checks = {
        name: {
            "median_ms": duration,
            "budget_ms": budgets[name],
            "passed": duration <= budgets[name],
        }
        for name, duration in measurements.items()
    }
    return {
        "fixture": {
            "home": str(home.resolve()),
            "expected_counts": {
                "sessions": session_count,
                "questions": question_count,
            },
            "actual_counts": actual_counts,
        },
        "measurements": checks,
        "question_random_draw_peak_kib": round(peak_bytes / 1024, 1),
        "query_plans": query_plans,
        "query_plan_checks": query_plan_checks,
        "passed": (
            actual_counts
            == {"sessions": int(session_count), "questions": int(question_count)}
            and all(item["passed"] for item in checks.values())
            and all(query_plan_checks.values())
        ),
    }


def run_temporary_scale_benchmark(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
    question_count: int = DEFAULT_QUESTION_COUNT,
    repeats: int = 5,
) -> dict[str, Any]:
    """Seed, measure and remove a dedicated temporary benchmark data home."""
    with tempfile.TemporaryDirectory(prefix="ielts-scale-benchmark-") as directory:
        home = Path(directory)
        fixture = seed_scale_fixture(
            home,
            session_count=session_count,
            question_count=question_count,
        )
        report = benchmark_scale_fixture(
            home,
            session_count=session_count,
            question_count=question_count,
            repeats=repeats,
        )
        report["fixture"]["seed_duration_seconds"] = fixture[
            "seed_duration_seconds"
        ]
        report["fixture"]["temporary_home_removed"] = True
        return report


def _median_duration_ms(operation: Callable[[], Any], *, repeats: int) -> float:
    operation()
    durations = []
    for _ in range(repeats):
        started = perf_counter()
        operation()
        durations.append((perf_counter() - started) * 1000)
    return round(statistics.median(durations), 3)


def _query_plan(conn: Any, sql: str) -> list[str]:
    return [
        str(row[3])
        for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    ]
