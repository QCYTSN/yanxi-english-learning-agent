from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ielts_coach.init_home import initialise_home
from ielts_coach.privacy import check_processing_permission
from ielts_coach.rubrics import list_rubrics
from ielts_coach.session_manager import start_session
from ielts_coach.storage import connect, record_runtime_telemetry, record_session, telemetry_summary
from ielts_coach.study_context import build_study_context
from ielts_coach.study_runtime import (
    apply_reading_review,
    apply_writing_review,
    record_reading_hint,
    resume_session,
    submit_reading_answers,
    submit_writing_version,
)
from ielts_coach.validation import validate_data


def _writing_review(session_id: str) -> dict:
    criteria = []
    for name in ("TR", "CC", "LR", "GRA"):
        criteria.append(
            {
                "criterion": name,
                "score_low": 6.0,
                "score_high": 6.0,
                "evidence_support": [f"Learner evidence for {name}"],
                "evidence_limit": [f"Current limit for {name}"],
            }
        )
    criteria[0]["score_low"] = 7.0
    criteria[0]["score_high"] = 7.0
    return {
        "review_version": 1,
        "session_id": session_id,
        "stage": "first_review",
        "task": "task2",
        "version_label": "v1",
        "score_kind": "ai_training_estimate",
        "confidence": "medium",
        "estimated_band": {"low": 6.0, "high": 6.5},
        "rubric": {
            "rubric_id": "ielts-writing-public-descriptors",
            "publisher": "IELTS",
            "standard": "IELTS Writing Band Descriptors",
            "version": "updated-2023",
            "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf",
        },
        "criteria": criteria,
        "priority_issues": [
            {"tag": "TR_UNDERDEVELOPED_IDEA", "evidence": "Paragraph 2 stops at a claim.", "learner_action": "Add a reason and example."}
        ],
        "full_model_answer": None,
    }


def test_writing_runtime_is_revisioned_validated_and_resumable(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "writing")
    session_id = path.stem

    submitted = submit_writing_version(home, session_id, label="v1", content="A learner response with enough words to test storage.")
    assert submitted["revision"] == 1
    assert submitted["status"] == "awaiting_feedback"
    assert resume_session(home, "writing")["session_id"] == session_id

    review = _writing_review(session_id)
    review["rubric"]["source_reference"] = "https://model-invented.invalid/rubric"
    reviewed = apply_writing_review(home, session_id, review, expected_revision=1)
    assert reviewed["revision"] == 2
    assert reviewed["status"] == "awaiting_revision"
    assert reviewed["band"] == 6.5
    assert reviewed["rubric"]["rubric_id"] == "ielts-writing-public-descriptors"
    assert "model-invented.invalid" not in reviewed["rubric"]["source_reference"]
    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM writing_versions WHERE session_id=?", (session_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM criterion_scores WHERE session_id=?", (session_id,)).fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM runtime_events WHERE session_id=?", (session_id,)).fetchone()[0] == 2

    with pytest.raises(ValueError, match="Stale Session revision"):
        submit_writing_version(home, session_id, label="v2", content="revision", expected_revision=1)


def test_writing_first_review_cannot_leak_full_answer():
    review = _writing_review("W-20260722-001")
    review["full_model_answer"] = "A complete model essay must be blocked here."
    with pytest.raises(ValueError, match="must not reveal"):
        validate_data(review, "writing-review")


def test_reading_runtime_preserves_hint_and_answer_integrity(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "reading", mode="guided-solving")
    session_id = path.stem
    hint = record_reading_hint(home, session_id, level=1)
    assert hint["hints_used"] == 1
    assert hint["latest_hint"]["answer_revealed"] is False
    assert hint["latest_hint"]["message"]

    answers = [{"question_number": 1, "question_type": "multiple_choice", "user_answer": "B"}]
    submitted = submit_reading_answers(home, session_id, answers, expected_revision=1)
    review = {
        "review_version": 1,
        "session_id": session_id,
        "mode": "wrong_answer_review",
        "answer_revealed": True,
        "items": [
            {
                "question_number": 1,
                "question_type": "multiple_choice",
                "user_answer": "B",
                "correct_answer": "C",
                "evidence_location": "Paragraph C",
                "evidence": "The passage states the causal relationship directly.",
                "reasoning": "C preserves the cause and effect; B reverses it.",
                "distractors": [{"option": "B", "reason": "reversed logic"}],
                "error_tags": ["R_DISTRACTOR_KEYWORD"],
                "next_rule": "Check the logical relation, not only matching words.",
            }
        ],
    }
    reviewed = apply_reading_review(home, session_id, review, expected_revision=submitted["revision"])
    assert reviewed["score"] == {"correct": 0, "total": 1}
    assert reviewed["answer_revealed_at"]

    timed = start_session(home, "reading", mode="timed-practice")
    with pytest.raises(ValueError, match="cannot use hints"):
        record_reading_hint(home, timed.stem)


def test_reading_guided_contract_rejects_answer_reveal():
    with pytest.raises(ValueError, match="must not reveal"):
        validate_data(
            {
                "review_version": 1,
                "session_id": "R-20260722-001",
                "mode": "guided_hint",
                "hint_level": 1,
                "answer_revealed": True,
                "items": [{"question_type": "tfng", "correct_answer": "Not Given"}],
            },
            "reading-review",
        )


def test_rubric_privacy_and_metadata_only_telemetry(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert {row["module"] for row in list_rubrics(home)} == {"writing", "speaking"}

    blocked = check_processing_permission(
        home, remote_processing=True, source_type="licensed_private"
    )
    assert blocked["allowed"] is False
    assert check_processing_permission(
        home, remote_processing=True, source_type="licensed_private", explicit_consent=True
    )["allowed"] is True
    assert check_processing_permission(
        home, remote_processing=True, source_type="project_original"
    )["allowed"] is True
    assert check_processing_permission(
        home, remote_processing=True, question_id="missing-question"
    )["allowed"] is False

    event = {
        "event_type": "writing_review",
        "module": "writing",
        "model_label": "test-model",
        "input_tokens": 500,
        "output_tokens": 200,
        "latency_ms": 1200,
        "tool_calls": 2,
    }
    record_runtime_telemetry(home, event)
    summary = telemetry_summary(home)
    assert dict(summary[0])["output_tokens"] == 200
    with pytest.raises(Exception):
        record_runtime_telemetry(home, {**event, "prompt": "raw learner text"})


def test_atomic_session_write_rolls_back_file_when_database_write_fails(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "writing")
    original = path.read_text(encoding="utf-8")

    def fail(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr("ielts_coach.session_manager.record_session", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        submit_writing_version(home, path.stem, label="v1", content="must roll back")
    assert path.read_text(encoding="utf-8") == original


def test_study_context_error_window_is_really_bounded(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(
        home,
        {
            "session_id": "W-OLD-CONTEXT",
            "module": "writing",
            "status": "completed",
            "occurred_at": "2020-01-01T00:00:00+00:00",
            "versions": [{"label": "v1", "content": "old response"}],
            "errors": [{"tag": "OLD_ONLY", "count": 9}],
        },
    )
    record_session(
        home,
        {
            "session_id": "W-RECENT-CONTEXT",
            "module": "writing",
            "status": "completed",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "versions": [{"label": "v1", "content": "recent response"}],
            "errors": [{"tag": "RECENT_ONLY", "count": 1}],
        },
    )
    context = build_study_context(home, module="writing", days=14)
    tags = {item["tag"] for item in context["history"]["active_errors"]}
    assert tags == {"RECENT_ONLY"}
    assert context["history"]["scope_days"] == 14
