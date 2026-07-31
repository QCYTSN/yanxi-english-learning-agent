from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.storage import connect
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
    response = client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    )
    assert response.status_code == 200
    return client


def test_unreviewed_questions_are_visible_only_in_review_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        with connect(home) as conn:
            row = conn.execute(
                "SELECT question_id,module FROM questions ORDER BY question_id LIMIT 1"
            ).fetchone()
            assert row is not None
            question_id, module = str(row["question_id"]), str(row["module"])
            conn.execute(
                "UPDATE questions SET review_status='unreviewed',conformance_status='provisional' "
                "WHERE question_id=?",
                (question_id,),
            )

        learner = client.get("/api/v1/questions?limit=500")
        assert learner.status_code == 200
        assert question_id not in {item["question_id"] for item in learner.json()}

        reviewer = client.get("/api/v1/questions?review_mode=true&limit=500")
        assert reviewer.status_code == 200
        assert question_id in {item["question_id"] for item in reviewer.json()}

        session = client.post(
            "/api/v1/sessions",
            json={"module": module, "question_id": question_id},
            headers={"Idempotency-Key": "public-boundary-test"},
        )
        assert session.status_code == 422
        assert "local review" in session.json()["error"]["message"]


def test_app_lifespan_initialises_a_completely_fresh_home(tmp_path: Path) -> None:
    home = tmp_path / "never-initialised"
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    with TestClient(app) as client:
        client.headers.update({"Origin": "http://testserver"})
        response = client.get("/health")
        assert response.status_code == 200
    with connect(home) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_runs'"
        ).fetchone()
