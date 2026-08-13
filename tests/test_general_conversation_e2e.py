from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="general-e2e-token-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    response = client.post(
        "/api/auth/exchange",
        json={"token": "general-e2e-token-long-enough"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    client.headers.update({CSRF_HEADER_NAME: csrf})
    return client


def _wait_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/agent-runs/{run_id}").json()
        if run["status"] in {"persisted", "test_passed", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("Agent run did not reach a terminal state")


def test_general_study_help_end_to_end_pipeline(tmp_path: Path) -> None:
    """The conversation-first general track works end to end without a model:
    thread -> agent run (mock) -> contract validation -> persisted message."""
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)

    # new users default to the general track
    bootstrap = client.get("/api/v1/bootstrap").json()
    assert bootstrap["active_learning_track_id"] == "general-english"
    assert [c["capability_id"] for c in bootstrap["capabilities"]] == [
        "study_help", "writing_feedback", "speaking_prompt",
        "vocabulary_lesson", "reading_coach", "grammar_lesson",
    ]

    thread = client.post(
        "/api/v1/study-threads",
        json={
            "module": "mixed",
            "title": "Daily English check",
        },
    )
    assert thread.status_code == 200, thread.text
    thread_id = thread.json()["thread_id"]
    message = client.post(
        f"/api/v1/study-threads/{thread_id}/messages",
        data={"content": "Hi teacher, how do I say '我下周要出差' in English?"},
    )
    assert message.status_code == 200, message.text
    message_id = message.json()["message_id"]

    run = client.post(
        "/api/v1/agent-runs",
        headers={"Idempotency-Key": "general-e2e-run"},
        json={
            "adapter_id": "mock",
            "study_thread_id": thread_id,
            "user_message_id": message_id,
            "action": "study_help",
            "output_contract": "general-study-help@1",
        },
    )
    assert run.status_code == 200, run.text
    terminal = _wait_run(client, run.json()["run_id"])
    assert terminal["status"] == "test_passed"

    # The deterministic pipeline test validates the contract and the run
    # lifecycle without writing an authoritative learning record.
    assert terminal["result"]["contract_version"] == 1
    assert terminal["result"]["check_question"]


def test_general_contracts_all_pass_pipeline_mock(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)

    thread = client.post(
        "/api/v1/study-threads",
        json={"module": "mixed", "title": "All contracts"},
    ).json()
    thread_id = thread["thread_id"]
    message = client.post(
        f"/api/v1/study-threads/{thread_id}/messages",
        data={"content": "hello"},
    ).json()
    message_id = message["message_id"]

    for contract in (
        "general-writing-feedback@1",
        "general-speaking-prompt@1",
        "general-vocabulary@1",
        "general-reading-coach@1",
        "general-grammar@1",
    ):
        run = client.post(
            "/api/v1/agent-runs",
            headers={"Idempotency-Key": f"general-e2e-{contract}"},
            json={
                "adapter_id": "mock",
                "study_thread_id": thread_id,
                "user_message_id": message_id,
                "action": contract.partition("@")[0],
                "output_contract": contract,
            },
        )
        assert run.status_code == 200, (contract, run.text)
        terminal = _wait_run(client, run.json()["run_id"])
        assert terminal["status"] == "test_passed", (contract, terminal)
