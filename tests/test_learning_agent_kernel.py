from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.capabilities import capability_descriptors
from ielts_coach.domain_packs import (
    DEFAULT_TRACK_ID,
    domain_pack_descriptors,
    get_domain_pack,
)
from ielts_coach.errors import LearningRevisionConflictError
from ielts_coach.init_home import initialise_home
from ielts_coach.learning_model import (
    complete_learning_review,
    create_learning_activity,
    create_learning_objective,
    get_learning_model_snapshot,
    list_learning_reviews,
    list_mastery_evidence,
    record_mastery_evidence,
    update_learning_activity,
    update_learning_objective,
    update_learning_review_status,
)
from ielts_coach.storage import connect, record_session
from ielts_coach.study_threads import create_study_thread
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    response = client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf
    client.headers.update({CSRF_HEADER_NAME: csrf})
    return client


def test_ielts_is_registered_as_the_first_domain_pack() -> None:
    descriptors = domain_pack_descriptors(include_skills=True)
    assert [item["track_id"] for item in descriptors] == [
        DEFAULT_TRACK_ID,
        "general-english",
    ]
    pack = get_domain_pack(DEFAULT_TRACK_ID)
    assert {item.dimension_id for item in pack.dimensions} == {
        "listening",
        "reading",
        "writing",
        "speaking",
    }
    assert len(pack.skills) == 21
    assert len(pack.capabilities) == 9

    general = get_domain_pack("general-english")
    assert {item.dimension_id for item in general.dimensions} == {
        "listening",
        "reading",
        "writing",
        "speaking",
        "vocabulary",
        "grammar",
    }
    assert general.assessment_scale.scale_id == "cefr"
    assert {item["track_id"] for item in capability_descriptors()} == {
        DEFAULT_TRACK_ID,
        "general-english",
    }


def test_initialisation_seeds_generic_learning_model_without_user_content(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    with connect(home) as conn:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        skill_count = conn.execute(
            "SELECT COUNT(*) FROM learning_skill_nodes WHERE track_id=?",
            (DEFAULT_TRACK_ID,),
        ).fetchone()[0]
        learner_rows = conn.execute("SELECT COUNT(*) FROM learning_objectives").fetchone()[0]
    assert version == "32"
    assert {
        "learning_skill_nodes",
        "learning_objectives",
        "learning_activities",
        "mastery_evidence",
        "skill_mastery",
        "learning_review_schedules",
    } <= tables
    assert skill_count == 21
    assert learner_rows == 0


def test_objective_activity_mastery_and_spaced_review_are_revision_safe(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    objective = create_learning_objective(
        home,
        title="Improve passage evidence location",
        dimension_id="reading",
        skill_id="reading.locate_evidence",
        target_value=0.8,
    )
    activity = create_learning_activity(
        home,
        activity_type="guided_practice",
        title="Locate evidence in one passage",
        dimension_id="reading",
        objective_id=objective["objective_id"],
        source_type="test",
    )
    activity = update_learning_activity(
        home,
        activity["activity_id"],
        updates={"status": "in_progress"},
        expected_revision=0,
    )
    assert activity["revision"] == 1
    assert activity["started_at"] is not None
    with pytest.raises(LearningRevisionConflictError):
        update_learning_activity(
            home,
            activity["activity_id"],
            updates={"status": "completed"},
            expected_revision=0,
        )
    first = record_mastery_evidence(
        home,
        track_id=DEFAULT_TRACK_ID,
        skill_id="reading.locate_evidence",
        score=0.35,
        confidence=0.9,
        evidence_kind="attempt",
        source_type="test_attempt",
        source_id="attempt-1",
        objective_id=objective["objective_id"],
        activity_id=activity["activity_id"],
        rationale="The learner selected evidence from the wrong paragraph.",
    )
    assert first["mastery"]["estimate"] == pytest.approx(0.35)
    assert first["mastery"]["status"] == "needs_support"
    assert first["review"]["interval_days"] == 1

    # Replaying the same authoritative evidence updates it instead of double counting.
    replay = record_mastery_evidence(
        home,
        track_id=DEFAULT_TRACK_ID,
        skill_id="reading.locate_evidence",
        score=0.75,
        confidence=0.9,
        evidence_kind="attempt",
        source_type="test_attempt",
        source_id="attempt-1",
        objective_id=objective["objective_id"],
        activity_id=activity["activity_id"],
    )
    assert replay["mastery"]["evidence_count"] == 1
    assert replay["mastery"]["estimate"] == pytest.approx(0.75)
    replay_due_at = replay["review"]["due_at"]
    identical_replay = record_mastery_evidence(
        home,
        track_id=DEFAULT_TRACK_ID,
        skill_id="reading.locate_evidence",
        score=0.75,
        confidence=0.9,
        evidence_kind="attempt",
        source_type="test_attempt",
        source_id="attempt-1",
        objective_id=objective["objective_id"],
        activity_id=activity["activity_id"],
    )
    assert identical_replay["review"]["due_at"] == replay_due_at

    updated = update_learning_objective(
        home,
        objective["objective_id"],
        updates={"priority": 80},
        expected_revision=0,
    )
    assert updated["revision"] == 1
    with pytest.raises(LearningRevisionConflictError):
        update_learning_objective(
            home,
            objective["objective_id"],
            updates={"priority": 10},
            expected_revision=0,
        )

    reviews = list_learning_reviews(home, status="pending")
    completed = complete_learning_review(
        home,
        reviews[0]["review_id"],
        score=0.9,
        rationale="Independent delayed retrieval was correct.",
    )
    assert completed["review"]["status"] == "pending"
    assert completed["review"]["repetition_count"] == 1
    assert completed["mastery"]["evidence_count"] == 2
    update_learning_review_status(home, reviews[0]["review_id"], "dismissed")
    snapshot = get_learning_model_snapshot(home, dimension_id="reading")
    skill = next(
        item
        for item in snapshot["skills"]
        if item["skill_id"] == "reading.locate_evidence"
    )
    assert skill["mastery"]["next_review_at"] is None


def test_authoritative_ielts_session_projects_idempotent_skill_evidence(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    session = {
        "session_id": "R-20260809-001",
        "module": "reading",
        "status": "completed",
        "occurred_at": "2026-08-09T12:00:00+08:00",
        "questions": [
            {
                "question_number": "1",
                "question_type": "true_false_not_given",
                "user_answer": "TRUE",
                "correct_answer": "FALSE",
                "is_correct": False,
            }
        ],
        "score": {"correct": 0, "total": 1},
        "raw_score": 0,
        "answer_key_source": "test-answer-key",
        "band_conversion_source": "test-conversion",
        "score_kind": "answer_key_estimate",
        "score_confidence": "high",
        "band": 6.5,
    }
    record_session(home, session)
    first_due_at = list_learning_reviews(home, status="pending")[0]["due_at"]
    record_session(home, session)
    second_due_at = list_learning_reviews(home, status="pending")[0]["due_at"]
    evidence = list_mastery_evidence(home)
    assert len(evidence) == 1
    assert second_due_at == first_due_at
    assert evidence[0]["skill_id"] == "reading.inference"
    assert evidence[0]["score"] == 0
    snapshot = get_learning_model_snapshot(home, dimension_id="reading")
    assert snapshot["summary"]["observed_skill_count"] == 1

    cleared = dict(session)
    cleared["questions"] = []
    cleared["band"] = None
    cleared["score_kind"] = None
    record_session(home, cleared)
    assert list_mastery_evidence(home) == []
    assert list_learning_reviews(home, status="pending") == []
    cleared_snapshot = get_learning_model_snapshot(home, dimension_id="reading")
    assert cleared_snapshot["summary"]["observed_skill_count"] == 0


def test_threads_and_http_bootstrap_expose_learning_track_boundary(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Track aware")
    assert thread["track_id"] == DEFAULT_TRACK_ID

    with _client(home) as client:
        bootstrap = client.get("/api/v1/bootstrap")
        tracks = client.get("/api/v1/learning-tracks")
        objective = client.post(
            "/api/v1/learning-objectives",
            json={
                "title": "Strengthen writer position questions",
                "dimension_id": "reading",
                "skill_id": "reading.writer_position",
            },
        )
        evidence = client.post(
            "/api/v1/mastery-evidence",
            json={
                "skill_id": "reading.writer_position",
                "score": 0.5,
                "confidence": 0.8,
                "evidence_kind": "tutor_observation",
                "source_type": "api-test",
                "source_id": "observation-1",
                "objective_id": objective.json()["objective_id"],
            },
        )
        updated = client.patch(
            f"/api/v1/learning-objectives/{objective.json()['objective_id']}",
            json={"priority": 80, "expected_revision": 0},
        )
        stale = client.patch(
            f"/api/v1/learning-objectives/{objective.json()['objective_id']}",
            json={"priority": 10, "expected_revision": 0},
        )
        snapshot = client.get("/api/v1/learning-model?dimension_id=reading")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["active_learning_track_id"] == DEFAULT_TRACK_ID
    assert bootstrap.json()["learning_tracks"][0]["track_id"] == DEFAULT_TRACK_ID
    assert tracks.status_code == 200
    assert objective.status_code == 200
    assert evidence.status_code == 200
    assert updated.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "LEARNING_REVISION_CONFLICT"
    assert snapshot.status_code == 200
    assert snapshot.json()["summary"]["active_objective_count"] == 1
