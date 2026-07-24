from __future__ import annotations

import time
import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ielts_coach.backups import create_backup, restore_backup
from ielts_coach.health import audit_data_home
from ielts_coach.init_home import initialise_home
from ielts_coach.media import import_image_bytes, resolve_media_file
from ielts_coach.session_manager import start_session
from ielts_coach.session_io import load_session_file
from ielts_coach.storage import get_study_draft, list_sessions, save_study_draft
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def _wait_agent(client: TestClient, run_id: str, expected: set[str]) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/agent-runs/{run_id}").json()
        if run["status"] in expected or run["status"] == "failed":
            return run
        time.sleep(0.03)
    raise AssertionError("Agent run did not reach the expected state")


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


def test_cross_home_restore_preserves_four_skills_drafts_media_and_health(
    tmp_path: Path,
):
    source = tmp_path / "source-home"
    target = tmp_path / "target-home"
    initialise_home(source)
    initialise_home(target)

    session_ids: list[str] = []
    for module in ("listening", "reading", "writing", "speaking"):
        session_path = start_session(source, module)
        session_ids.append(str(load_session_file(session_path)["session_id"]))
    save_study_draft(
        source,
        session_ids[2],
        "writing-editor",
        {"content": "A recoverable learner draft."},
    )
    image_buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(image_buffer, format="PNG")
    media = import_image_bytes(
        source,
        image_buffer.getvalue(),
        alt_text="Task 1 restore fixture",
        owner_type="session",
        owner_id=session_ids[2],
    )
    created = create_backup(source, kind="v08-four-skill")

    restored = restore_backup(
        target,
        created["path"],
        confirmed=True,
        allow_external_path=True,
    )
    assert restored["post_restore_health"]["status"] != "failed"
    assert {row["module"] for row in list_sessions(target, limit=20)} == {
        "listening",
        "reading",
        "writing",
        "speaking",
    }
    assert get_study_draft(target, session_ids[2], "writing-editor")["payload"] == {
        "content": "A recoverable learner draft."
    }
    asset, path = resolve_media_file(target, media["media_id"])
    assert target.resolve() in path.parents
    assert source.resolve() not in path.parents
    assert asset["content_hash"] == media["content_hash"]
    assert audit_data_home(target)["status"] != "failed"


def test_onboarding_diagnostics_settings_and_agent_provenance_api(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)

    before = client.get("/api/v1/bootstrap").json()
    assert before["onboarding"]["status"] == "pending"
    updated = client.put(
        "/api/v1/profile",
        json={
            "complete_onboarding": True,
            "updates": {
                "exam": {"type": "academic", "test_date": "2026-12-12"},
                "target": {
                    "overall": 7.0,
                    "listening": 7.5,
                    "reading": 7.5,
                    "writing": 6.5,
                    "speaking": 6.5,
                },
                "privacy": {"remote_processing": "ask"},
            },
        },
    )
    assert updated.status_code == 200
    assert updated.json()["onboarding"]["status"] == "ready"
    assert client.get("/api/v1/system/health").json()["status"] != "failed"
    assert len(client.get("/api/v1/rubrics").json()) >= 2
    assert isinstance(client.get("/api/v1/telemetry/summary").json(), list)

    diagnostic = client.post("/api/v1/diagnostics", json={"mode": "quick"})
    assert diagnostic.status_code == 200
    diagnostic_id = diagnostic.json()["diagnostic_id"]
    assert "reading_timed_passage" in diagnostic.json()["missing_requirements"]
    cancelled = client.post(f"/api/v1/diagnostics/{diagnostic_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    session = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": "v08-agent-session"},
        json={"module": "writing"},
    ).json()
    session_id = session["session_id"]
    submitted = client.post(
        f"/api/v1/writing/{session_id}/versions",
        headers={"Idempotency-Key": "v08-agent-writing"},
        json={
            "label": "v1",
            "content": "This response needs evidence based feedback.",
            "expected_revision": 0,
        },
    )
    assert submitted.status_code == 200
    run = client.post(
        "/api/v1/agent-runs",
        headers={"Idempotency-Key": "v08-mock-agent"},
        json={
            "adapter_id": "mock",
            "study_session_id": session_id,
            "action": "first_review",
            "output_contract": "writing-review@1",
        },
    )
    assert run.status_code == 200
    provenance = _wait_agent(client, run.json()["run_id"], {"test_passed"})
    assert provenance["status"] == "test_passed"
    assert provenance["agent_provider"] == "ielts-ai-coach"
    assert provenance["model_id"] is None
    assert provenance["launcher_kind"] == "deterministic_local"
    assert provenance["calibration_status"] == "not_applicable"
    assert provenance["capabilities"]["structured_output"] is True
    history = client.get(
        "/api/v1/agent-runs",
        params={"study_session_id": session_id},
    ).json()
    assert history[0]["run_id"] == provenance["run_id"]
    assert history[0]["agent_provider"] == "ielts-ai-coach"

    manual_session = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": "v08-manual-session"},
        json={"module": "writing"},
    ).json()
    manual_session_id = manual_session["session_id"]
    client.post(
        f"/api/v1/writing/{manual_session_id}/versions",
        headers={"Idempotency-Key": "v08-manual-writing"},
        json={
            "label": "v1",
            "content": "A second response for a declared external reviewer.",
            "expected_revision": 0,
        },
    )
    manual = client.post(
        "/api/v1/agent-runs",
        headers={"Idempotency-Key": "v08-manual-agent"},
        json={
            "adapter_id": "manual",
            "study_session_id": manual_session_id,
            "action": "first_review",
            "output_contract": "writing-review@1",
            "agent_provider": "OpenCode",
            "agent_version": "declared",
            "model_id": "user-declared-model",
            "model_display_name": "User-declared model",
            "agent_session_id": "external-session-1",
            "source_type": "personal",
            "explicit_consent": True,
        },
    )
    assert manual.status_code == 200
    manual_run = _wait_agent(client, manual.json()["run_id"], {"awaiting_import"})
    assert manual_run["status"] == "awaiting_import"
    assert manual_run["agent_provider"] == "OpenCode"
    assert manual_run["model_id"] == "user-declared-model"
    assert manual_run["launcher_kind"] == "manual_handoff"
