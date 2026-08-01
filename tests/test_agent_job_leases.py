from __future__ import annotations

import time
from pathlib import Path

from ielts_coach.agent_jobs import AgentJobManager
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import (
    claim_agent_run,
    connect,
    create_agent_run,
    get_agent_run,
    update_agent_run,
)
from ielts_coach.study_threads import add_assistant_message, create_study_thread


def _study_plan() -> dict:
    return {
        "contract_version": 1,
        "period": "2026-W31",
        "allocation": {
            "listening": 0.25,
            "reading": 0.25,
            "writing": 0.25,
            "speaking": 0.25,
        },
        "tasks": [
            {
                "module": "reading",
                "title": "Evidence review",
                "minutes": 30,
                "reason": "Highest-priority verified gap",
            }
        ],
        "evidence_summary": ["One verified Reading error pattern."],
    }


def _wait_for_status(home: Path, run_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 5
    run = get_agent_run(home, run_id) or {}
    while run.get("status") != expected and time.monotonic() < deadline:
        time.sleep(0.03)
        run = get_agent_run(home, run_id) or {}
    return run


def test_agent_run_lease_is_claimed_atomically(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    create_agent_run(
        home,
        {
            "run_id": "run-lease",
            "adapter_id": "model-provider-chain",
            "action": "plan",
            "output_contract": "study-plan@1",
            "status": "queued",
        },
    )

    first = claim_agent_run(
        home,
        "run-lease",
        lease_owner="worker-a",
        lease_seconds=30,
    )
    second = claim_agent_run(
        home,
        "run-lease",
        lease_owner="worker-b",
        lease_seconds=30,
    )
    assert first and first["lease_owner"] == "worker-a"
    assert second is None

    update_agent_run(
        home,
        "run-lease",
        lease_expires_at="2000-01-01T00:00:00+00:00",
    )
    reclaimed = claim_agent_run(
        home,
        "run-lease",
        lease_owner="worker-b",
        lease_seconds=30,
    )
    assert reclaimed and reclaimed["lease_owner"] == "worker-b"


def test_recovery_resumes_saved_candidate_without_model_call(
    tmp_path: Path,
):
    home = tmp_path / "home"
    initialise_home(home)
    create_agent_run(
        home,
        {
            "run_id": "run-resume",
            "adapter_id": "model-provider-chain",
            "backend_kind": "model_provider",
            "action": "plan",
            "output_contract": "study-plan@1",
            "status": "validating",
            "checkpoint": "candidate_received",
            "result": _study_plan(),
            "lease_owner": "dead-worker",
            "lease_expires_at": "2000-01-01T00:00:00+00:00",
        },
    )
    manager = AgentJobManager(home)
    manager.broker.for_run = lambda run: (_ for _ in ()).throw(
        AssertionError("checkpoint recovery must not invoke a model")
    )
    try:
        recovery = manager._recover_stale_runs()
        assert recovery == {"recovered": 1, "interrupted": 0}
        run = _wait_for_status(home, "run-resume", "persisted")
        assert run["status"] == "persisted"
        assert run["checkpoint"] == "persisted"
        assert run["resume_count"] == 1
        assert run["persistence"]["artifact_id"] == "artifact:run-resume"
    finally:
        manager.shutdown()


def test_active_lease_is_not_recovered_by_another_manager(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    create_agent_run(
        home,
        {
            "run_id": "run-active",
            "adapter_id": "model-provider-chain",
            "action": "plan",
            "output_contract": "study-plan@1",
            "status": "queued",
        },
    )
    assert claim_agent_run(
        home,
        "run-active",
        lease_owner="live-worker",
        lease_seconds=30,
    )
    manager = AgentJobManager(home)
    try:
        assert manager._recover_stale_runs() == {"recovered": 0, "interrupted": 0}
        run = get_agent_run(home, "run-active")
        assert run and run["lease_owner"] == "live-worker"
    finally:
        manager.shutdown()


def test_study_help_persistence_is_idempotent_per_agent_run(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Reading question")
    result = {"summary": "This sentence describes the author's contrast."}
    create_agent_run(
        home,
        {
            "run_id": "run-study-help",
            "adapter_id": "model-provider-chain",
            "action": "explain",
            "output_contract": "study-help@1",
            "status": "persisting",
        },
    )

    first = add_assistant_message(
        home,
        thread_id=thread["thread_id"],
        result=result,
        agent_run_id="run-study-help",
    )
    second = add_assistant_message(
        home,
        thread_id=thread["thread_id"],
        result=result,
        agent_run_id="run-study-help",
    )
    assert second["message_id"] == first["message_id"]
    with connect(home) as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM study_messages WHERE agent_run_id=?",
            ("run-study-help",),
        ).fetchone()["count"]
    assert count == 1
