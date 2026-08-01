from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.storage import (
    append_agent_run_event,
    connect,
    create_agent_run,
    list_agent_run_events,
    list_audit_events,
)
from ielts_coach.web import auth as auth_module
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import (
    AuthState,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
)


def test_agent_events_are_canonical_and_audited(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    create_agent_run(
        home,
        {
            "run_id": "run-audit",
            "adapter_id": "mock",
            "action": "teacher_dialogue",
            "output_contract": "study-help@1",
            "status": "queued",
            "request": {"private_text": "must not enter audit metadata"},
        },
    )

    queued = append_agent_run_event(
        home,
        "run-audit",
        "status",
        {"stage": "queued", "label": "Preparing feedback"},
    )
    fallback = append_agent_run_event(
        home,
        "run-audit",
        "progress",
        {
            "stage": "fallback_started",
            "provider_id": "fallback-provider",
            "private_text": "not copied into audit metadata",
        },
    )
    failed = append_agent_run_event(
        home,
        "run-audit",
        "failed",
        {"code": "MODEL_ROUTE_FAILED", "recovery_action": "retry"},
    )

    assert queued["type"] == "job_queued"
    assert fallback["type"] == "fallback_started"
    assert failed["type"] == "job_failed"
    assert failed["recoverable"] is True
    events = list_agent_run_events(home, "run-audit")
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert all(event["payload_hash"] for event in events)
    assert all(event["display_message"] for event in events)

    audit = list_audit_events(home, category="agent_job", run_id="run-audit")
    assert len(audit) == 3
    assert audit[1]["metadata"]["provider_id"] == "fallback-provider"
    assert "private_text" not in audit[1]["metadata"]
    with connect(home) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE audit_events SET outcome='changed' WHERE audit_id=?",
                (audit[0]["audit_id"],),
            )


def test_local_mutations_require_session_bound_csrf(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    origin = "http://127.0.0.1"
    state = AuthState(launch_token="launch-token-that-is-long-enough")
    app = create_app(
        home=home,
        auth=state,
        allowed_origin=origin,
        test_mode=False,
    )
    with TestClient(app, base_url=origin) as client:
        client.headers.update({"Origin": origin})
        exchanged = client.post(
            "/api/auth/exchange",
            json={"token": "launch-token-that-is-long-enough"},
        )
        assert exchanged.status_code == 200
        csrf = client.cookies.get(CSRF_COOKIE_NAME)
        assert csrf

        blocked = client.post("/api/v1/backups")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "CSRF_TOKEN_REQUIRED"

        wrong = client.post(
            "/api/v1/backups",
            headers={CSRF_HEADER_NAME: "wrong-token"},
        )
        assert wrong.status_code == 403

        allowed = client.post(
            "/api/v1/backups",
            headers={CSRF_HEADER_NAME: csrf},
        )
        assert allowed.status_code == 200


def test_launch_tokens_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"value": 100.0}
    monkeypatch.setattr(auth_module.time, "monotonic", lambda: clock["value"])
    state = AuthState(launch_token="launch-token-that-is-long-enough")
    clock["value"] += auth_module.LAUNCH_TOKEN_TTL_SECONDS + 1
    with pytest.raises(HTTPException, match="Invalid or expired"):
        state.exchange("launch-token-that-is-long-enough")
