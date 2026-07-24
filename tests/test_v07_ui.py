from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ielts_coach.init_home import initialise_home
from ielts_coach.session_manager import start_session
from ielts_coach.study_runtime import submit_writing_version
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
    return client


def _authenticate(client: TestClient) -> None:
    response = client.post(
        "/api/auth/exchange", json={"token": "test-launch-token-that-is-long-enough"}
    )
    assert response.status_code == 200


def _wait_agent(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/agent-runs/{run_id}").json()
        if run["status"] in {
            "persisted",
            "test_passed",
            "failed",
            "cancelled",
            "awaiting_import",
        }:
            return run
        time.sleep(0.03)
    raise AssertionError("Agent run did not reach a terminal state")


def test_health_bootstrap_auth_and_origin(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)

    health = client.get("/api/health")
    assert health.json()["status"] == "ok"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert client.get("/api/v1/bootstrap").status_code == 401
    _authenticate(client)
    bootstrap = client.get("/api/v1/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["setup_required"] is False
    assert bootstrap.json()["core_version"] == "1.2.0"
    assert bootstrap.json()["storage"]["data_home"] == str(home.resolve())

    blocked = client.get(
        "/api/v1/bootstrap", headers={"Origin": "http://attacker.invalid"}
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "INVALID_ORIGIN"


def test_backup_api_create_verify_and_restore_confirmation(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    _authenticate(client)

    created = client.post("/api/v1/backups")
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]
    rows = client.get("/api/v1/backups")
    assert rows.status_code == 200
    assert rows.json()[0]["backup_id"] == backup_id

    verified = client.post(f"/api/v1/backups/{backup_id}/verify")
    assert verified.status_code == 200
    assert verified.json()["database_integrity"] == "ok"

    refused = client.post(
        f"/api/v1/backups/{backup_id}/restore", json={"confirmed": False}
    )
    assert refused.status_code == 422
    restored = client.post(
        f"/api/v1/backups/{backup_id}/restore", json={"confirmed": True}
    )
    assert restored.status_code == 200
    assert restored.json()["restored"] is True


def test_content_readiness_and_private_upload_queue(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    _authenticate(client)

    readiness = client.get("/api/v1/content/readiness")
    assert readiness.status_code == 200
    assert set(readiness.json()["modules"]) == {"listening", "reading", "writing", "speaking"}

    upload = client.post(
        "/api/v1/content/imports",
        data={
            "title": "Owned PDF",
            "source_type": "licensed_private",
            "authenticity": "official_practice_book",
            "rights_status": "local_private",
        },
        files=[("files", ("owned.pdf", b"%PDF-1.4\ntest", "application/pdf"))],
    )
    assert upload.status_code == 200
    assert upload.json()["status"] == "needs_structuring"
    jobs = client.get("/api/v1/content/imports")
    assert jobs.status_code == 200
    assert jobs.json()[0]["files"][0]["original_name"] == "owned.pdf"

    pack = client.post("/api/v1/assessment-packs", json={
        "module": "writing",
        "title": "Starter writing pair",
        "question_ids": ["START-WT1-001", "START-WT2-001"],
    })
    assert pack.status_code == 200
    assert pack.json()["conformance_status"] == "provisional"
    review_target = client.get(
        f"/api/v1/content-reviews/targets/assessment_pack/{pack.json()['pack_id']}"
    )
    assert review_target.status_code == 200
    checklist = {
        key: True for key in review_target.json()["required_checklist"]
    }
    reviewed_pack = client.post(
        f"/api/v1/content-reviews/targets/assessment_pack/{pack.json()['pack_id']}",
        json={
            "reviewer": "UI test reviewer",
            "decision": "approved",
            "checklist": checklist,
            "notes": "Structure and dependencies checked.",
        },
    )
    assert reviewed_pack.status_code == 200
    assert reviewed_pack.json()["local_review_status"] == "approved"
    assert client.get(
        f"/api/v1/assessment-packs/{pack.json()['pack_id']}"
    ).json()["conformance_status"] == "verified"


def test_session_creation_draft_and_idempotent_writing_submission(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    _authenticate(client)

    headers = {"Idempotency-Key": "create-writing-001"}
    first = client.post("/api/v1/sessions", headers=headers, json={"module": "writing"})
    second = client.post("/api/v1/sessions", headers=headers, json={"module": "writing"})
    assert first.status_code == second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    session_id = first.json()["session_id"]

    draft = client.put(
        f"/api/v1/sessions/{session_id}/draft",
        json={"draft_kind": "writing", "expected_revision": 0, "payload": {"content": "draft"}},
    )
    assert draft.status_code == 200
    conflict = client.put(
        f"/api/v1/sessions/{session_id}/draft",
        json={"draft_kind": "writing", "expected_revision": 0, "payload": {"content": "stale"}},
    )
    assert conflict.status_code == 409

    submit_headers = {"Idempotency-Key": "writing-version-001"}
    payload = {"label": "v1", "content": "A learner response for UI testing.", "expected_revision": 0}
    submitted = client.post(
        f"/api/v1/writing/{session_id}/versions", headers=submit_headers, json=payload
    )
    replay = client.post(
        f"/api/v1/writing/{session_id}/versions", headers=submit_headers, json=payload
    )
    assert submitted.status_code == replay.status_code == 200
    assert submitted.json()["revision"] == replay.json()["revision"] == 1


def test_cross_process_lock_allows_only_one_revision_winner(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    session_id = start_session(home, "writing").stem

    def submit(key: str):
        return submit_writing_version(
            home,
            session_id,
            label="v1",
            content=f"response {key}",
            expected_revision=0,
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, key) for key in ("concurrent-a", "concurrent-b")]
    successes = [future.result() for future in futures if future.exception() is None]
    failures = [future.exception() for future in futures if future.exception() is not None]
    assert len(successes) == 1
    assert len(failures) == 1
    assert "Stale Session revision" in str(failures[0])


def test_media_registry_and_mock_agent_round_trip(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    _authenticate(client)

    session = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": "create-writing-mock"},
        json={"module": "writing"},
    ).json()
    session_id = session["session_id"]
    client.post(
        f"/api/v1/writing/{session_id}/versions",
        headers={"Idempotency-Key": "submit-writing-mock"},
        json={"label": "v1", "content": "This response needs evidence based feedback.", "expected_revision": 0},
    )

    run = client.post(
        "/api/v1/agent-runs",
        headers={"Idempotency-Key": "create-writing-agent"},
        json={
            "adapter_id": "mock",
            "study_session_id": session_id,
            "action": "first_review",
            "output_contract": "writing-review@1",
        },
    )
    assert run.status_code == 200
    persisted = _wait_agent(client, run.json()["run_id"])
    assert persisted["status"] == "test_passed"
    assert persisted["result"]["score_kind"] == "mock_fixture"
    canonical = client.get(f"/api/v1/sessions/{session_id}").json()
    assert canonical["status"] == "awaiting_feedback"
    assert "writing_review" not in canonical

    buffer = io.BytesIO()
    Image.new("RGB", (24, 16), "white").save(buffer, format="PNG")
    media = client.post(
        "/api/v1/media",
        files={"image": ("task.png", buffer.getvalue(), "image/png")},
        data={"alt_text": "A simple Task 1 chart"},
    )
    assert media.status_code == 200
    assert "local_path" not in media.json()
    content = client.get(f"/api/v1/media/{media.json()['media_id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
