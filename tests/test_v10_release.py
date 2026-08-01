from __future__ import annotations

import json
import errno
import time
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.agent_contracts import CONTRACT_SCHEMAS, validate_agent_contract
from ielts_coach.agent_gateway import adapter_descriptors
from ielts_coach.agent_gateway.manual import ManualAdapter
from ielts_coach.agent_gateway.process import (
    ClaudeProcessAdapter,
    OpenCodeProcessAdapter,
    _normalise_opencode_result,
    _process_environment,
    _proxy_environment_from_windows_value,
    _remove_temporary_paths,
)
from ielts_coach.agent_jobs import AgentJobManager
from ielts_coach.init_home import initialise_home
from ielts_coach.media import import_image_bytes
from ielts_coach.session_manager import show_session, start_session
from ielts_coach.study_runtime import submit_writing_version
from ielts_coach.score_results import build_score_result
from ielts_coach.storage import (
    SCHEMA_VERSION,
    connect,
    create_agent_run,
    create_provider_attempt,
    get_agent_run,
    list_provider_attempts,
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


def test_writing_agent_cannot_invent_authoritative_rubric_id():
    result = json.loads(
        (FIXTURES / "writing-review.valid.json").read_text(encoding="utf-8")
    )
    result["rubric"]["rubric_id"] = "model-invented-rubric"
    with pytest.raises(Exception):
        validate_agent_contract("writing-review@1", result)


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
        "test_passed",
    }
    assert response.json()["capability_id"] == "writing_review"
    assert response.json()["execution_profile_id"] == "pipeline-test"
    assert response.json()["backend_kind"] == "mock"
    assert response.json()["privacy_receipt"]["authorization_kind"] == "local_processing"
    assert response.json()["privacy_receipt"]["reusable"] is False
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 5
    run = response.json()
    while run["status"] not in {"test_passed", "failed"} and time.monotonic() < deadline:
        time.sleep(0.03)
        run = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert run["status"] == "test_passed"
    assert run["result"]["score_kind"] == "mock_fixture"
    canonical = client.get(f"/api/v1/sessions/{session['session_id']}").json()
    assert canonical["status"] == "awaiting_feedback"
    assert "writing_review" not in canonical
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


def test_current_schema_and_restart_recovery(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert SCHEMA_VERSION == 23
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
    create_provider_attempt(
        home,
        run_id="run_interrupted",
        provider_id="provider-before-restart",
        provider_kind="openai_compatible",
        model_id="model-before-restart",
        fallback_index=0,
    )
    manager = AgentJobManager(home)
    try:
        result = manager.recover()
        assert result["interrupted"] == 1
        run = get_agent_run(home, "run_interrupted")
        assert run and run["status"] == "failed"
        assert run["recovery_action"] == "retry"
        attempts = list_provider_attempts(home, "run_interrupted")
        assert attempts[0]["status"] == "interrupted"
        assert attempts[0]["failure_stage"] == "recovery"
    finally:
        manager.shutdown()
    with connect(home) as conn:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()["value"]
        agent_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)")
        }
        session_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sessions)")
        }
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert version == "23"
    assert {
        "timeout_seconds",
        "attempt_count",
        "cancel_requested",
        "checkpoint",
        "input_hash",
        "lease_owner",
        "lease_expires_at",
        "resume_count",
        "persistence_json",
    }.issubset(
        agent_columns
    )
    assert {"payload_hash", "mirror_status", "mirror_checked_at"}.issubset(
        session_columns
    )
    assert "privacy_receipts" in tables


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
                "modelUsage": {"\u001b[1mclaude-sonnet-explicit[1m]\u001b[0m": {"inputTokens": 20}},
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


def test_process_adapters_keep_large_prompts_out_of_windows_command_line(
    tmp_path: Path,
):
    prompt = "REQUEST\n" + ("x" * 50000)
    claude = ClaudeProcessAdapter()
    claude_command, claude_stdin, _, claude_cleanup = claude._prepare_invocation(
        tmp_path,
        "claude.exe",
        prompt,
        "writing-review@1",
    )
    assert prompt not in claude_command
    assert claude_stdin == prompt
    assert claude_cleanup == []

    opencode = OpenCodeProcessAdapter()
    command, stdin_text, environment, cleanup = opencode._prepare_invocation(
        tmp_path,
        "opencode.exe",
        prompt,
        "writing-review@1",
    )
    try:
        assert prompt not in command
        assert stdin_text is None
        assert Path(environment["OPENCODE_CONFIG"]).is_file()
        request_path = next(path for path in cleanup if path.suffix == ".txt")
        assert request_path.read_text(encoding="utf-8") == prompt
        assert "--file" in command
    finally:
        _remove_temporary_paths(cleanup)
    assert all(not path.exists() for path in cleanup)


def test_manual_and_opencode_packages_copy_registered_images_without_source_path(
    tmp_path: Path,
):
    home = tmp_path / "home"
    initialise_home(home)
    image = import_image_bytes(
        home,
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        ),
        alt_text="Synthetic Task 1 visual",
    )
    request = {
        "request_id": "run_attachment_test",
        "study_session_id": "S-example",
        "output_contract": "writing-mock-review@1",
        "media_refs": [
            {
                "media_id": image["media_id"],
                "media_type": "image",
                "mime_type": image["mime_type"],
                "content_hash": image["content_hash"],
                "available_to_agent": True,
            }
        ],
    }
    manual = ManualAdapter().start(home, request)
    package_path = Path(manual["package_path"])
    package_text = package_path.read_text(encoding="utf-8")
    assert package_path.is_file()
    assert len(manual["attachments"]) == 1
    assert (package_path.parent / manual["attachments"][0]["file"]).is_file()
    assert str(image["local_path"]) not in package_text

    adapter = OpenCodeProcessAdapter()
    command, _, _, cleanup = adapter._prepare_invocation(
        home,
        "opencode.exe",
        "synthetic prompt",
        "writing-mock-review@1",
        request,
    )
    attached = [
        Path(command[index + 1])
        for index, value in enumerate(command[:-1])
        if value == "--file"
    ]
    try:
        assert len(attached) == 2
        assert any(path.suffix.lower() == ".png" for path in attached)
        assert all(str(image["local_path"]) != str(path) for path in attached)
    finally:
        _remove_temporary_paths(cleanup)


def test_windows_system_proxy_is_translated_for_cli_adapters():
    assert _proxy_environment_from_windows_value("127.0.0.1:7890") == {
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "HTTPS_PROXY": "http://127.0.0.1:7890",
        "http_proxy": "http://127.0.0.1:7890",
        "https_proxy": "http://127.0.0.1:7890",
    }
    assert _proxy_environment_from_windows_value(
        "http=proxy.local:8080;https=secure.local:8443;socks=127.0.0.1:1080"
    ) == {
        "HTTP_PROXY": "http://proxy.local:8080",
        "HTTPS_PROXY": "http://secure.local:8443",
        "ALL_PROXY": "socks5://127.0.0.1:1080",
        "http_proxy": "http://proxy.local:8080",
        "https_proxy": "http://secure.local:8443",
        "all_proxy": "socks5://127.0.0.1:1080",
    }


def test_explicit_proxy_environment_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://explicit.local:9000")
    monkeypatch.setattr(
        "ielts_coach.agent_gateway.process._windows_system_proxy_environment",
        lambda: {
            "HTTP_PROXY": "http://system.local:8080",
            "HTTPS_PROXY": "http://system.local:8080",
        },
    )
    environment = _process_environment({})
    assert environment["HTTP_PROXY"] == "http://system.local:8080"
    assert environment["HTTPS_PROXY"] == "http://explicit.local:9000"


def test_opencode_adapter_normalises_provider_aliases_before_strict_validation():
    result = _normalise_opencode_result(
        {
            "criteria": [
                {
                    "criterion": "grammatical_range_and_accuracy",
                    "score": 0,
                    "feedback": "There is no sentence-level evidence.",
                }
            ],
            "priority_issues": [
                {
                    "issue_id": "insufficient_response",
                    "issue": "The response does not address the task.",
                    "recommendation": "Write a complete response.",
                },
                "Use complete grammatical sentences.",
                "Use task-relevant vocabulary.",
                "This fourth priority must be truncated.",
            ]
        }
    )
    assert result["priority_issues"][0] | {
        "tag": "insufficient_response",
        "evidence": "The response does not address the task.",
        "learner_action": "Write a complete response.",
    } == result["priority_issues"][0]
    assert result["criteria"][0] | {
        "criterion": "GRA",
        "score_low": 0,
        "score_high": 0,
        "evidence_support": ["There is no sentence-level evidence."],
        "evidence_limit": ["There is no sentence-level evidence."],
    } == result["criteria"][0]
    assert result["priority_issues"][1] == {
        "tag": "AGENT_PRIORITY_2",
        "evidence": "Use complete grammatical sentences.",
        "learner_action": "Use complete grammatical sentences.",
    }
    assert len(result["priority_issues"]) == 3


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
