from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.listening_corpus import browse_listening_items, listening_categories
from ielts_coach.storage import connect
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


LAUNCH_TOKEN = "test-launch-token-that-is-long-enough"


def _client(home: Path, *, control_token: str | None = None) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token=LAUNCH_TOKEN),
        allowed_origin="http://testserver",
        test_mode=True,
        control_token=control_token,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    return client


def _authenticate(client: TestClient, token: str = LAUNCH_TOKEN) -> None:
    response = client.post("/api/auth/exchange", json={"token": token})
    assert response.status_code == 200


def test_listening_starter_corpus_and_attempt_round_trip(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    items = browse_listening_items(home, limit=1000)
    categories = listening_categories(home)
    assert len(items) == 50
    assert len(categories) == 10
    assert sum(category["total"] for category in categories) == 50
    assert all(item["source_type"] == "project_original" for item in items)

    client = _client(home)
    _authenticate(client)
    created = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": "create-listening-session"},
        json={"module": "listening", "mode": "high_frequency"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    item = client.get("/api/v1/listening/items?limit=1").json()[0]

    headers = {"Idempotency-Key": "listening-attempt-correct"}
    payload = {
        "item_id": item["item_id"],
        "user_answer": item["expression"],
        "expected_revision": 0,
    }
    submitted = client.post(
        f"/api/v1/listening/{session_id}/attempts", headers=headers, json=payload
    )
    replay = client.post(
        f"/api/v1/listening/{session_id}/attempts", headers=headers, json=payload
    )
    assert submitted.status_code == replay.status_code == 200
    assert submitted.json()["session"]["revision"] == replay.json()["session"]["revision"] == 1
    assert submitted.json()["attempt"]["is_correct"] is True

    wrong = client.post(
        f"/api/v1/listening/{session_id}/attempts",
        headers={"Idempotency-Key": "listening-attempt-wrong"},
        json={
            "item_id": item["item_id"],
            "user_answer": "deliberately wrong",
            "error_tags": ["listening_spelling"],
            "expected_revision": 1,
        },
    )
    assert wrong.status_code == 200
    assert wrong.json()["attempt"]["is_correct"] is False
    assert wrong.json()["session"]["score"] == {"correct": 1, "total": 2}
    assert client.post(f"/api/v1/sessions/{session_id}/finish").status_code == 200

    with connect(home) as conn:
        attempts = conn.execute(
            "SELECT COUNT(*) FROM question_attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0]
    assert attempts == 2


def test_speaking_voice_handoff_report_and_story_bank(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    _authenticate(client)

    handoff = client.post(
        "/api/v1/speaking/handoffs",
        headers={"Idempotency-Key": "speaking-handoff-full"},
        json={"mode": "full_mock", "provider": "external_voice_live", "seed": 7},
    )
    assert handoff.status_code == 200
    data = handoff.json()
    assert [question["part"] for question in data["speaking_handoff"]["questions"]].count(2) == 1
    prompt = data["speaking_handoff"]["prompt"]
    assert "Do not correct" in prompt
    assert "one minute to prepare" in prompt
    assert "up to two minutes" in prompt

    session_id = data["session_id"]
    imported = client.post(
        f"/api/v1/speaking/{session_id}/reports",
        headers={"Idempotency-Key": "speaking-report-import"},
        json={
            "provider": "external_voice_live",
            "mode": "full_mock",
            "transcript": "Examiner: Tell me about your home. Learner: I live in a busy city.",
            "expected_revision": 1,
        },
    )
    assert imported.status_code == 200
    assert imported.json()["status"] == "awaiting_feedback"
    assert imported.json()["band"] is None
    assert imported.json()["score_kind"] == "partial_profile"
    assert imported.json()["speaking_report"]["local_evaluation"]["status"] == "pending"
    replay = client.post(
        f"/api/v1/speaking/{session_id}/reports",
        headers={"Idempotency-Key": "speaking-report-import"},
        json={
            "provider": "external_voice_live",
            "mode": "full_mock",
            "transcript": "Examiner: Tell me about your home. Learner: I live in a busy city.",
            "expected_revision": 1,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["revision"] == imported.json()["revision"] == 2
    stale = client.post(
        f"/api/v1/speaking/{session_id}/reports",
        headers={"Idempotency-Key": "speaking-report-stale"},
        json={
            "provider": "external_voice_live",
            "mode": "full_mock",
            "transcript": "A conflicting second import.",
            "expected_revision": 1,
        },
    )
    assert stale.status_code == 409

    story = {
        "story_id": "first-day-campus",
        "title": "My first day on campus",
        "people": ["a classmate"],
        "places": ["the library"],
        "events": ["I got lost and asked for directions"],
        "feelings": ["nervous", "relieved"],
        "lessons": ["ask for help early"],
        "usable_topics": ["education", "a helpful person"],
        "expressions": ["find my way around"],
    }
    saved = client.post("/api/v1/speaking/stories", json=story)
    assert saved.status_code == 200
    assert client.get("/api/v1/speaking/stories").json() == [story]


def test_internal_launcher_issues_fresh_one_time_tokens(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home, control_token="private-control-token")

    assert client.get("/api/internal/launch").status_code == 404
    first = client.get(
        "/api/internal/launch",
        headers={"X-IELTS-Control-Token": "private-control-token"},
    )
    second = client.get(
        "/api/internal/launch",
        headers={"X-IELTS-Control-Token": "private-control-token"},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["launch_token"] != second.json()["launch_token"]

    first_token = first.json()["launch_token"]
    assert client.post("/api/auth/exchange", json={"token": first_token}).status_code == 200
    assert client.post("/api/auth/exchange", json={"token": first_token}).status_code == 401
    assert client.post(
        "/api/auth/exchange", json={"token": second.json()["launch_token"]}
    ).status_code == 200
