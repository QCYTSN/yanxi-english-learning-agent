from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.learning_orchestration import (
    bind_practice_unit,
    complete_review_task,
    list_review_tasks,
    materialise_today_unit,
    start_review_task,
)
from ielts_coach.session_manager import start_session
from ielts_coach.storage import SCHEMA_VERSION, connect, record_session
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    assert client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    ).status_code == 200
    return client


def test_current_schema_preserves_first_class_learning_objects(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert SCHEMA_VERSION == 34
    with connect(home) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"practice_units", "assessment_runs", "review_tasks"} <= tables
        assert "practice_unit_id" in {
            row[1] for row in conn.execute("PRAGMA table_info(assessment_runs)")
        }


def test_review_queue_is_derived_from_authoritative_records(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(
        home,
        {
            "session_id": "W-V12-001",
            "module": "writing",
            "status": "awaiting_revision",
            "versions": [{"label": "v1", "content": "My first response."}],
        },
    )
    record_session(
        home,
        {
            "session_id": "R-V12-001",
            "module": "reading",
            "status": "completed",
            "questions": [
                {
                    "question_id": None,
                    "question_number": "1",
                    "question_type": "multiple_choice",
                    "user_answer": "A",
                    "correct_answer": "B",
                    "is_correct": False,
                    "error_tags": ["R_DISTRACTOR"],
                }
            ],
            "errors": [{"tag": "R_DISTRACTOR", "count": 1}],
        },
    )
    tasks = list_review_tasks(home)
    kinds = {task["review_kind"] for task in tasks}
    assert {
        "writing_revision",
        "reading_wrong_answer",
        "error_review",
    } <= kinds
    assert {
        task["review_task_id"] for task in list_review_tasks(home)
    } == {task["review_task_id"] for task in tasks}

    writing = next(task for task in tasks if task["review_kind"] == "writing_revision")
    unit = start_review_task(home, writing["review_task_id"])
    assert unit["unit_kind"] == "review"
    assert unit["status"] == "in_progress"
    completed = complete_review_task(home, writing["review_task_id"])
    assert completed["status"] == "completed"


def test_today_unit_is_idempotent_and_binds_to_session(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    first = materialise_today_unit(home, "primary")
    second = materialise_today_unit(home, "primary")
    assert first["unit_id"] == second["unit_id"]
    assert first["unit_kind"] == "practice"
    path = start_session(home, str(first["module"]))
    bound = bind_practice_unit(home, first["unit_id"], session_id=path.stem)
    assert bound["status"] == "in_progress"
    assert bound["session_id"] == path.stem
    with connect(home) as conn:
        assert conn.execute(
            "SELECT practice_unit_id FROM sessions WHERE session_id=?", (path.stem,)
        ).fetchone()[0] == first["unit_id"]


def test_v12_http_materialises_today_and_exposes_review_queue(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    response = client.post("/api/v1/today/materialise", json={"slot": "primary"})
    assert response.status_code == 200
    assert response.json()["launch_url"].startswith("/practice")
    queue = client.get("/api/v1/review-tasks")
    assert queue.status_code == 200
    assert queue.json() == []
