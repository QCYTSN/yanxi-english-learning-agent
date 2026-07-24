from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from ielts_coach.init_home import initialise_home
from ielts_coach import init_home
from ielts_coach.media import import_image_bytes
from ielts_coach.performance import RequestPerformanceMonitor, database_performance_status
from ielts_coach.question_bank import show_reading_set
from ielts_coach.session_manager import start_session
from ielts_coach.storage import connect, list_media_assets
from ielts_coach.study_runtime import record_reading_hint


def test_managed_connection_closes_its_windows_file_handle(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    with connect(home) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_duplicate_media_can_bind_to_multiple_sessions(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    image = io.BytesIO()
    Image.new("RGB", (10, 8), "white").save(image, format="PNG")
    content = image.getvalue()

    first = import_image_bytes(
        home,
        content,
        alt_text="Task 1 evidence",
        owner_type="session",
        owner_id="W-FIRST",
    )
    second = import_image_bytes(
        home,
        content,
        alt_text="Task 1 evidence",
        owner_type="session",
        owner_id="W-SECOND",
    )

    assert first["media_id"] == second["media_id"]
    assert list_media_assets(
        home, owner_type="session", owner_id="W-FIRST"
    )[0]["media_id"] == first["media_id"]
    assert list_media_assets(
        home, owner_type="session", owner_id="W-SECOND"
    )[0]["media_id"] == first["media_id"]


def test_reading_batch_view_and_progressive_hint_never_reveal_answer(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    reading_set = show_reading_set(home, "START-RP-001")
    assert reading_set is not None
    assert len(reading_set["questions"]) == 4
    assert all("correct_answer" not in item for item in reading_set["questions"])

    path = start_session(
        home,
        "reading",
        passage_id="START-RP-001",
        mode="guided-solving",
    )
    result = record_reading_hint(
        home,
        path.stem,
        level=1,
        question_id="START-R-001",
    )
    assert result["latest_hint"]["question_id"] == "START-R-001"
    assert result["latest_hint"]["answer_revealed"] is False
    assert "TRUE" not in result["latest_hint"]["message"]


def test_bounded_performance_monitor_and_database_snapshot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    monitor = RequestPerformanceMonitor(capacity=100)
    for duration in (5.0, 10.0, 20.0, 40.0):
        monitor.record("/api/v1/questions", "GET", 200, duration)
    summary = monitor.summary()
    assert summary["sample_count"] == 4
    assert summary["p50_ms"] == 10.0
    assert summary["p95_ms"] == 40.0

    database = database_performance_status(home)
    assert database["pragmas"]["journal_mode"] == "wal"
    assert database["pragmas"]["busy_timeout_ms"] == 10000
    assert database["row_counts"]["questions"] > 0
    assert database["native_acceleration"]["decision"] == "not_needed"


def test_unchanged_starter_corpus_is_not_reindexed_on_every_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)

    def unexpected_reindex(*args: object, **kwargs: object) -> None:
        raise AssertionError("unchanged managed corpus should use the fast launch guard")

    monkeypatch.setattr(init_home, "import_manifest", unexpected_reindex)
    initialise_home(home)
