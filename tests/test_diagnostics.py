from pathlib import Path

import pytest

from ielts_coach.diagnostics import (
    attach_diagnostic_session,
    cancel_diagnostic,
    complete_diagnostic,
    diagnostic_status,
    start_diagnostic,
)
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import record_session


def test_quick_diagnostic_tracks_coverage_and_preserves_unknown_baselines(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    run = start_diagnostic(home, "quick")
    diagnostic_id = run["diagnostic_id"]

    sessions = [
        {
            "session_id": "L-DIAG", "module": "listening", "status": "completed",
            "band": 7.0, "score_kind": "official_result",
        },
        {
            "session_id": "R-DIAG", "module": "reading", "status": "completed",
            "mode": "timed-practice", "time_limit_minutes": 20,
            "started_at": "2026-07-22T10:00:00+00:00",
            "submitted_at": "2026-07-22T10:20:00+00:00",
            "questions": [{"question_type": "multiple_choice", "user_answer": "B"}],
        },
        {
            "session_id": "W-DIAG", "module": "writing", "status": "completed",
            "task": "task2", "mode": "timed-practice",
            "band": 7.0,
            "versions": [{"label": "v1", "content": "Diagnostic essay"}],
        },
        {
            "session_id": "S-DIAG", "module": "speaking", "status": "completed",
            "score_kind": "partial_profile", "errors": [{"tag": "FC_LONG_PAUSE"}],
            "speaking_report": {
                "mode": "full_mock",
                "parts": [{"part": 1}, {"part": 2}, {"part": 3}],
                "source_observations": {
                    "evidence_types": ["transcript"],
                    "transcript": "A short diagnostic transcript.",
                    "parts": [{"part": 1}, {"part": 2}, {"part": 3}],
                },
            },
        },
    ]
    for session in sessions:
        record_session(home, session)
        attach_diagnostic_session(home, diagnostic_id, session["session_id"])

    status = diagnostic_status(home, diagnostic_id)
    assert status["missing_requirements"] == []
    completed = complete_diagnostic(home, diagnostic_id)
    assert completed["result"]["baseline_scores"] == {"listening": 7.0}
    assert completed["result"]["baseline_status"] == "partial"


def test_full_diagnostic_requires_both_writing_tasks(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    diagnostic_id = start_diagnostic(home, "full")["diagnostic_id"]
    evidence = [
        {
            "session_id": "L-FULL", "module": "listening", "status": "completed",
            "band": 7.0, "score_kind": "official_result", "mode": "timed-practice",
            "score": {"correct": 30, "total": 40},
        },
        {
            "session_id": "R-FULL", "module": "reading", "status": "completed",
            "mode": "timed-practice", "time_limit_minutes": 60,
            "started_at": "2026-07-22T10:00:00+00:00",
            "submitted_at": "2026-07-22T11:00:00+00:00",
            "questions": [
                {"question_type": "multiple_choice", "user_answer": "A"}
                for _ in range(40)
            ],
        },
        {
            "session_id": "S-FULL", "module": "speaking", "status": "completed",
            "duration_minutes": 13,
            "speaking_report": {
                "mode": "full_mock",
                "parts": [{"part": 1}, {"part": 2}, {"part": 3}],
                "source_observations": {
                    "evidence_types": ["transcript"],
                    "transcript": "A full mock transcript.",
                    "parts": [{"part": 1}, {"part": 2}, {"part": 3}],
                },
            },
        },
    ]
    for data in evidence:
        record_session(home, data)
        attach_diagnostic_session(home, diagnostic_id, data["session_id"])
    writing = {
        "session_id": "W-FULL-T2", "module": "writing", "status": "completed",
        "task": "task2", "mode": "timed-practice",
        "versions": [{"label": "v1", "content": "Task 2"}],
    }
    record_session(home, writing)
    attach_diagnostic_session(home, diagnostic_id, writing["session_id"])
    with pytest.raises(ValueError, match="writing_task1"):
        complete_diagnostic(home, diagnostic_id)


def test_diagnostic_rejects_non_completed_session(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    diagnostic_id = start_diagnostic(home, "quick")["diagnostic_id"]
    record_session(home, {"session_id": "R-DRAFT", "module": "reading", "status": "draft"})
    with pytest.raises(ValueError, match="completed Session"):
        attach_diagnostic_session(home, diagnostic_id, "R-DRAFT")


def test_only_one_diagnostic_can_be_active_and_it_can_be_cancelled(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    first = start_diagnostic(home, "quick")["diagnostic_id"]
    with pytest.raises(ValueError, match="already active"):
        start_diagnostic(home, "full")
    assert cancel_diagnostic(home, first)["status"] == "cancelled"
    assert start_diagnostic(home, "full")["status"] == "active"
