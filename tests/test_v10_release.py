from __future__ import annotations

import json
import errno
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.agent_contracts import CONTRACT_SCHEMAS, validate_agent_contract
from ielts_coach.agent_gateway import adapter_descriptors
from ielts_coach.agent_gateway.process import (
    ClaudeProcessAdapter,
    OpenCodeProcessAdapter,
)
from ielts_coach.agent_jobs import AgentJobManager
from ielts_coach.init_home import initialise_home
from ielts_coach.session_manager import show_session, start_session
from ielts_coach.study_runtime import submit_writing_version
from ielts_coach.score_results import build_score_result
from ielts_coach.storage import (
    SCHEMA_VERSION,
    connect,
    create_agent_run,
    get_agent_run,
)
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


FIXTURES = Path(__file__).parent / "fixtures" / "agent_contracts"


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    assert (
        client.post(
            "/api/auth/exchange",
            json={"token": "test-launch-token-that-is-long-enough"},
        ).status_code
        == 200
    )
    return client


def test_score_result_has_one_progress_admission_policy():
    objective = build_score_result(
        {
            "session_id": "R-full",
            "module": "reading",
            "status": "completed",
            "practice_mode": "full_mock",
            "conformance_status": "verified",
            "raw_score": 32,
            "score": {"correct": 32, "total": 40},
            "band": 7,
            "score_kind": "answer_key_estimate",
            "answer_key_source": "reviewed-pack",
            "band_conversion_source": "published-conversion",
        }
    )
    assert objective["eligible_for_progress"] is True
    assert objective["eligibility_reason"] == "verified_answer_key_full_mock"

    partial = build_score_result(
        {
            "session_id": "R-partial",
            "module": "reading",
            "status": "completed",
            "practice_mode": "section_practice",
            "conformance_status": "verified",
            "raw_score": 10,
            "score": {"correct": 10, "total": 13},
            "band": 7,
            "score_kind": "answer_key_estimate",
            "band_conversion_source": "source",
        }
    )
    assert partial["eligible_for_progress"] is False
    assert partial["eligibility_reason"] == "not_verified_full_mock"

    ai = build_score_result(
        {
            "session_id": "W-ai",
            "module": "writing",
            "status": "completed",
            "task": "task2",
            "scored_version": "v1",
            "criterion_scores": [
                {"criterion": name, "version": "v1", "score": 6.5}
                for name in ("TR", "CC", "LR", "GRA")
            ],
            "band": 6.5,
            "score_kind": "ai_training_estimate",
            "score_confidence": "high",
            "calibration_status": "unknown",
        }
    )
    assert ai["eligible_for_progress"] is False
    assert ai["eligibility_reason"] == "uncalibrated_ai_estimate"


@pytest.mark.parametrize("contract", sorted(CONTRACT_SCHEMAS))
def test_agent_contract_golden_and_failure_samples(contract: str):
    stem = contract.partition("@")[0]
    valid = json.loads((FIXTURES / f"{stem}.valid.json").read_text(encoding="utf-8"))
    invalid = json.loads(
        (FIXTURES / f"{stem}.invalid.json").read_text(encoding="utf-8")
    )
    assert validate_agent_contract(contract, valid)
    with pytest.raises(Exception):
        validate_agent_contract(contract, invalid)


def test_v10_today_progress_and_background_agent_lifecycle(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)

    session = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": "v10-writing-session"},
        json={"module": "writing"},
    ).json()
    submitted = client.post(
        f"/api/v1/writing/{session['session_id']}/versions",
        headers={"Idempotency-Key": "v10-writing-version"},
        json={
            "label": "v1",
            "content": "This response needs evidence based feedback.",
            "expected_revision": 0,
        },
    )
    assert submitted.status_code == 200
    response = client.post(
        "/api/v1/agent-runs",
        headers={"Idempotency-Key": "v10-agent-run"},
        json={
            "adapter_id": "mock",
            "study_session_id": session["session_id"],
            "action": "first_review",
            "output_contract": "writing-review@1",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] in {
        "queued",
        "running",
        "validating",
        "persisting",
        "persisted",
    }
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 5
    run = response.json()
    while run["status"] not in {"persisted", "failed"} and time.monotonic() < deadline:
        time.sleep(0.03)
        run = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert run["status"] == "persisted"
    events = client.get(f"/api/v1/agent-runs/{run_id}/events?after=999")
    assert events.status_code == 200

    today = client.get("/api/v1/today")
    assert today.status_code == 200
    assert today.json()["context_version"] == 2
    assert set(today.json()["today_plan"]) >= {"primary", "consolidation"}
    progress = client.get("/api/v1/progress/dashboard")
    assert progress.status_code == 200
    assert set(progress.json()["modules"]) == {
        "listening",
        "reading",
        "writing",
        "speaking",
    }


def test_schema13_and_restart_recovery(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert SCHEMA_VERSION == 13
    create_agent_run(
        home,
        {
            "run_id": "run_interrupted",
            "adapter_id": "mock",
            "action": "review",
            "output_contract": "weekly-coaching@1",
            "status": "running",
        },
    )
    manager = AgentJobManager(home)
    try:
        result = manager.recover()
        assert result["interrupted"] == 1
        run = get_agent_run(home, "run_interrupted")
        assert run and run["status"] == "failed"
        assert run["recovery_action"] == "retry"
    finally:
        manager.shutdown()
    with connect(home) as conn:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()["value"]
        agent_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)")
        }
    assert version == "13"
    assert {"timeout_seconds", "attempt_count", "cancel_requested"}.issubset(
        agent_columns
    )


def test_process_adapters_disclose_identity_without_guessing_model():
    descriptors = {item["id"]: item for item in adapter_descriptors()}
    for adapter_id in ("claude", "opencode"):
        assert adapter_id in descriptors
        assert descriptors[adapter_id]["identity"]["launcher_kind"] == "local_process"
        assert descriptors[adapter_id]["identity"]["model_id"] is None


def test_process_adapters_extract_only_explicit_runtime_identity():
    claude = ClaudeProcessAdapter()
    claude_identity = claude._extract_runtime_identity(
        json.dumps(
            {
                "modelUsage": {"claude-sonnet-explicit": {"inputTokens": 20}},
                "session_id": "claude-session",
            }
        )
    )
    assert claude_identity["agent_provider"] == "claude"
    assert claude_identity["model_id"] == "claude-sonnet-explicit"
    assert claude_identity["agent_session_id"] == "claude-session"

    opencode = OpenCodeProcessAdapter()
    opencode_identity = opencode._extract_runtime_identity(
        json.dumps(
            {
                "type": "step_finish",
                "properties": {
                    "modelID": "model-returned-by-cli",
                    "providerID": "provider-returned-by-cli",
                    "sessionID": "opencode-session",
                },
            }
        )
    )
    assert opencode_identity["agent_provider"] == "opencode"
    assert opencode_identity["model_id"] == "model-returned-by-cli"
    assert opencode_identity["agent_session_id"] == "opencode-session"


def test_agent_timeout_has_a_recoverable_failure(tmp_path: Path):
    class SlowAdapter:
        def start(self, home: Path, request: dict) -> dict:
            time.sleep(0.1)
            return {}

        def cancel(self, home: Path, execution_ref: str) -> bool:
            return True

    home = tmp_path / "home"
    initialise_home(home)
    manager = AgentJobManager(home)
    try:
        with pytest.raises(TimeoutError, match="timeout"):
            manager._run_with_timeout(
                SlowAdapter(),
                {"request_id": "slow"},
                timeout_seconds=0.02,
                execution_ref="slow",
            )
    finally:
        manager.shutdown()


def test_disk_full_does_not_partially_update_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "writing")
    before_file = path.read_text(encoding="utf-8")
    before_db = show_session(home, path.stem)

    def disk_full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "simulated disk full")

    monkeypatch.setattr(
        "ielts_coach.session_manager._write_session_document_atomic", disk_full
    )
    with pytest.raises(OSError) as error:
        submit_writing_version(home, path.stem, label="v1", content="Draft text")
    assert error.value.errno == errno.ENOSPC
    assert path.read_text(encoding="utf-8") == before_file
    assert show_session(home, path.stem) == before_db
