from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.errors import (
    InvalidTeachingTransitionError,
    LearningRevisionConflictError,
)
from ielts_coach.init_home import initialise_home
from ielts_coach.learning_model import create_learning_activity
from ielts_coach.pedagogy import (
    get_active_teaching_cycle,
    start_teaching_cycle,
    transition_teaching_cycle,
)
from ielts_coach.storage import (
    connect,
    create_learner_memory,
    get_learner_memory,
    list_learner_memories,
    list_learner_memory_conflicts,
    list_learner_memory_revisions,
    record_session,
    resolve_learner_memory_conflict,
    update_learner_memory,
)
from ielts_coach.study_threads import create_study_thread
from ielts_coach.teaching_quality import (
    list_teaching_quality_evaluations,
    run_teaching_quality_evaluation,
)
from ielts_coach.tutor_orchestrator import DomainToolRegistry, TutorOrchestrator
from ielts_coach.tutor_state import get_thread_learning_state
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="v32-test-launch-token-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    assert client.post(
        "/api/auth/exchange",
        json={"token": "v32-test-launch-token-long-enough"},
    ).status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf
    client.headers.update({CSRF_HEADER_NAME: csrf})
    return client


def test_versioned_memory_detects_conflicts_expires_and_resolves(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    first = create_learner_memory(
        home,
        memory_type="feedback_language",
        memory_key="preference:feedback-language",
        statement="Use Chinese for explanations.",
        confidence=1,
    )
    second = create_learner_memory(
        home,
        memory_type="feedback_language",
        memory_key="preference:feedback-language",
        statement="Use English for explanations.",
        confidence=1,
    )
    assert get_learner_memory(home, first["memory_id"])["effective"] is False
    assert get_learner_memory(home, second["memory_id"])["effective"] is False
    assert list_learner_memories(home) == []

    conflicts = list_learner_memory_conflicts(home)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    keep_second = (
        "keep_left"
        if conflict["left_memory_id"] == second["memory_id"]
        else "keep_right"
    )
    resolved = resolve_learner_memory_conflict(
        home,
        conflict["conflict_id"],
        resolution=keep_second,
    )
    selected = (
        resolved["left_memory"]
        if resolved["left_memory_id"] == second["memory_id"]
        else resolved["right_memory"]
    )
    assert selected["effective"] is True
    assert selected["revision"] >= 2
    assert len(list_learner_memory_revisions(home, second["memory_id"])) >= 2
    duplicate = create_learner_memory(
        home,
        memory_type="feedback_language",
        memory_key="preference:feedback-language",
        statement="Use English for explanations.",
        confidence=0.8,
    )
    assert duplicate["memory_id"] == second["memory_id"]

    changed = create_learner_memory(
        home,
        memory_type="feedback_language",
        memory_key="preference:feedback-language",
        statement="Use bilingual explanations.",
        confidence=1,
    )
    assert list_learner_memory_conflicts(home)
    changed = update_learner_memory(
        home,
        changed["memory_id"],
        memory_key="preference:bilingual-explanations",
        expected_revision=changed["revision"],
    )
    assert changed["effective"] is True
    assert get_learner_memory(home, second["memory_id"])["effective"] is True
    assert list_learner_memory_conflicts(home) == []

    with pytest.raises(LearningRevisionConflictError):
        update_learner_memory(
            home,
            second["memory_id"],
            statement="Use bilingual feedback.",
            expected_revision=1,
        )
    expired = create_learner_memory(
        home,
        memory_type="temporary_goal",
        statement="Review this topic today.",
        confidence=0.8,
        expires_at="2020-01-01T00:00:00+00:00",
    )
    assert expired["effective_validity_status"] == "expired"
    assert all(
        item["memory_id"] != expired["memory_id"]
        for item in list_learner_memories(home)
    )
    assert any(
        item["memory_id"] == expired["memory_id"]
        for item in list_learner_memories(
            home,
            validity_status="expired",
            include_expired=True,
        )
    )
    expired_conflict = create_learner_memory(
        home,
        memory_type="feedback_language",
        memory_key="preference:feedback-language",
        statement="Use Japanese for explanations.",
        confidence=1,
        expires_at="2020-01-01T00:00:00+00:00",
    )
    assert expired_conflict["effective_validity_status"] == "expired"
    assert get_learner_memory(home, second["memory_id"])["effective"] is True
    assert list_learner_memory_conflicts(home) == []


def test_tutor_only_reads_effective_memory_and_records_access(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    active = create_learner_memory(
        home,
        memory_type="teaching_preference",
        statement="Ask me to explain my reasoning before giving feedback.",
        confidence=0.9,
    )
    create_learner_memory(
        home,
        memory_type="temporary_goal",
        statement="An expired temporary preference.",
        confidence=0.9,
        expires_at="2020-01-01T00:00:00+00:00",
    )
    memories = DomainToolRegistry(home).execute("get_learner_memories", limit=10)
    assert [item["memory_id"] for item in memories] == [active["memory_id"]]
    assert memories[0]["access_count"] == 1
    assert memories[0]["last_accessed_at"] is not None
    thread = create_study_thread(home, title="Memory continuity", module="mixed")
    context = TutorOrchestrator(home).initial_context(
        "hallo",
        thread_id=thread["thread_id"],
    )
    assert [item["memory_id"] for item in context["learner_memories"]] == [
        active["memory_id"]
    ]
    assert get_learner_memory(home, active["memory_id"])["access_count"] == 2


def test_teaching_cycle_enforces_graph_revision_and_runtime_projection(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Reading inference", module="reading")
    activity = create_learning_activity(
        home,
        activity_type="independent_practice",
        title="Evidence-based inference practice",
        dimension_id="reading",
        thread_id=thread["thread_id"],
        source_type="test",
        status="in_progress",
    )
    cycle = start_teaching_cycle(
        home,
        title="Inference teaching cycle",
        dimension_id="reading",
        skill_id="reading.inference",
        activity_id=activity["activity_id"],
        phase="diagnose",
    )
    assert cycle["recommendation"]["target_phase"] == "teach"
    with pytest.raises(InvalidTeachingTransitionError):
        transition_teaching_cycle(
            home,
            cycle["cycle_id"],
            to_phase="consolidate",
            expected_revision=0,
        )
    cycle = transition_teaching_cycle(
        home,
        cycle["cycle_id"],
        to_phase="independent_practice",
        expected_revision=0,
    )
    with pytest.raises(LearningRevisionConflictError):
        transition_teaching_cycle(
            home,
            cycle["cycle_id"],
            to_phase="assess",
            expected_revision=0,
        )

    session = {
        "session_id": "R-20260809-cycle",
        "module": "reading",
        "status": "completed",
        "occurred_at": "2026-08-09T12:00:00+00:00",
        "learning_activity_id": activity["activity_id"],
        "questions": [
            {
                "question_number": "1",
                "question_type": "multiple_choice",
                "user_answer": "A",
                "correct_answer": "A",
                "is_correct": True,
            }
        ],
    }
    record_session(home, session)
    projected = get_active_teaching_cycle(home, thread["thread_id"])
    assert projected is not None
    assert projected["phase"] == "assess"
    first_revision = projected["revision"]
    record_session(home, session)
    assert get_active_teaching_cycle(home, thread["thread_id"])["revision"] == first_revision
    state = get_thread_learning_state(home, thread["thread_id"])
    assert state["teaching_cycle"]["cycle_id"] == cycle["cycle_id"]


def test_teaching_quality_suite_is_privacy_safe_and_dimension_complete(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    result = run_teaching_quality_evaluation(home)
    assert result["status"] == "passed"
    assert result["case_count"] == 14
    assert set(result["dimension_scores"]) == {
        "instructional_fit",
        "answer_integrity",
        "evidence_grounding",
        "active_learning",
        "memory_continuity",
        "pedagogy_control",
        "recovery",
    }
    assert list_teaching_quality_evaluations(home)[0]["report_hash"] == result["report_hash"]
    with connect(home) as conn:
        stored = conn.execute(
            "SELECT report_json FROM teaching_quality_evaluation_runs"
        ).fetchone()[0]
    assert "A short anchored excerpt" not in stored
    assert "Ask me to explain" not in stored


def test_v32_memory_and_teaching_cycle_api(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="API cycle", module="writing")
    with _client(home) as client:
        first = client.post(
            "/api/v1/learner-memories",
            json={
                "memory_type": "feedback_language",
                "memory_key": "preference:feedback-language",
                "statement": "Chinese",
                "confidence": 1,
            },
        )
        second = client.post(
            "/api/v1/learner-memories",
            json={
                "memory_type": "feedback_language",
                "memory_key": "preference:feedback-language",
                "statement": "English",
                "confidence": 1,
            },
        )
        assert first.status_code == second.status_code == 200
        conflicts = client.get("/api/v1/learner-memory-conflicts")
        assert conflicts.status_code == 200
        assert len(conflicts.json()) == 1
        revisions = client.get(
            f"/api/v1/learner-memories/{first.json()['memory_id']}/revisions"
        )
        assert revisions.status_code == 200
        assert len(revisions.json()) >= 2

        cycle = client.post(
            "/api/v1/teaching-cycles",
            json={
                "title": "Writing revision cycle",
                "dimension_id": "writing",
                "thread_id": thread["thread_id"],
            },
        )
        assert cycle.status_code == 200
        moved = client.post(
            f"/api/v1/teaching-cycles/{cycle.json()['cycle_id']}/transition",
            json={"to_phase": "teach", "expected_revision": 0},
        )
        assert moved.status_code == 200
        assert moved.json()["phase"] == "teach"
        stale = client.post(
            f"/api/v1/teaching-cycles/{cycle.json()['cycle_id']}/transition",
            json={"to_phase": "guided_practice", "expected_revision": 0},
        )
        assert stale.status_code == 409
        quality = client.get("/api/v1/system/teaching-evaluations")
        assert quality.status_code == 200
