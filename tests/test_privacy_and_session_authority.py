from __future__ import annotations

import json
from pathlib import Path

import pytest

from ielts_coach.errors import SessionMirrorConflictError
from ielts_coach.health import audit_data_home
from ielts_coach.init_home import initialise_home
from ielts_coach.privacy import build_privacy_receipt, check_processing_permission
from ielts_coach.session_io import load_session_file
from ielts_coach.session_manager import _write_session_document_atomic, start_session
from ielts_coach.storage import connect, create_agent_run, get_agent_run
from ielts_coach.study_runtime import reconcile_session, resume_session, submit_writing_version


def _rewrite_session(path: Path, **changes) -> None:
    data = load_session_file(path)
    body = str(data.pop("document_body", ""))
    data.update(changes)
    _write_session_document_atomic(path, data, body)


def test_one_time_privacy_receipt_is_consumed_and_not_reusable(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    decision = check_processing_permission(
        home,
        remote_processing=True,
        source_type="personal",
        explicit_consent=True,
    )
    assert decision["authorization_kind"] == "one_time_consent"
    receipt = build_privacy_receipt(
        run_id="run-private",
        decision=decision,
        provider_ids=["provider-primary"],
        scope={
            "capability_id": "writing_review",
            "output_contract": "writing-review@1",
            "payload_refs": ["session:W-PRIVATE"],
        },
    )
    run = create_agent_run(
        home,
        {
            "run_id": "run-private",
            "adapter_id": "model-provider-chain",
            "action": "review",
            "output_contract": "writing-review@1",
            "status": "queued",
            "privacy_receipt": receipt,
        },
    )
    assert run["privacy_receipt"]["authorization_kind"] == "one_time_consent"
    assert run["privacy_receipt"]["reusable"] is False
    assert run["privacy_receipt"]["consumed_at"]
    assert len(run["privacy_receipt"]["scope_hash"]) == 64

    later = check_processing_permission(
        home,
        remote_processing=True,
        source_type="personal",
        explicit_consent=False,
    )
    assert later["allowed"] is False
    assert later["authorization_kind"] == "blocked"


def test_agent_run_and_privacy_receipt_commit_atomically(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    decision = check_processing_permission(home, remote_processing=False)
    receipt = build_privacy_receipt(
        run_id="different-run",
        decision=decision,
        provider_ids=["local"],
        scope={"capability_id": "study_plan"},
    )
    with pytest.raises(ValueError, match="does not match"):
        create_agent_run(
            home,
            {
                "run_id": "run-atomic",
                "adapter_id": "mock",
                "action": "plan",
                "output_contract": "study-plan@1",
                "status": "queued",
                "privacy_receipt": receipt,
            },
        )
    assert get_agent_run(home, "run-atomic") is None


def test_same_revision_session_fork_blocks_writes_and_health(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "writing")
    session_id = path.stem
    _rewrite_session(path, status="learner_working")

    with pytest.raises(SessionMirrorConflictError) as error:
        submit_writing_version(
            home,
            session_id,
            label="v1",
            content="This draft must not overwrite a fork.",
        )
    assert error.value.details["same_revision_content_conflict"] is True
    with connect(home) as conn:
        row = conn.execute(
            "SELECT mirror_status,payload_json FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    assert row["mirror_status"] == "conflict"
    assert json.loads(row["payload_json"])["status"] == "draft"
    report = audit_data_home(home)
    assert report["status"] == "failed"
    assert report["checks"]["sessions"]["content_mismatches"] == 1

    with pytest.raises(SessionMirrorConflictError, match="choose markdown or sqlite"):
        reconcile_session(home, session_id)
    reconciled = reconcile_session(home, session_id, prefer="markdown")
    assert reconciled["status"] == "learner_working"
    assert audit_data_home(home)["status"] == "ok"


def test_higher_session_revision_requires_explicit_reconciliation(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "writing")
    session_id = path.stem
    _rewrite_session(path, revision=2, status="learner_working")

    with pytest.raises(SessionMirrorConflictError):
        resume_session(home, module="writing")
    reconciled = reconcile_session(home, session_id)
    assert reconciled["revision"] == 2
    with connect(home) as conn:
        row = conn.execute(
            "SELECT payload_hash,mirror_status FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    assert len(row["payload_hash"]) == 64
    assert row["mirror_status"] == "synced"


def test_reconcile_refreshes_stale_database_payload_hash(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "reading")
    session_id = path.stem
    with connect(home) as conn:
        conn.execute(
            "UPDATE sessions SET payload_hash=? WHERE session_id=?",
            ("0" * 64, session_id),
        )
        conn.commit()

    before = audit_data_home(home)
    assert before["status"] == "failed"
    assert before["checks"]["sessions"]["stored_hash_mismatches"] == 1

    reconcile_session(home, session_id)

    after = audit_data_home(home)
    assert after["status"] == "ok"
    assert after["checks"]["sessions"]["stored_hash_mismatches"] == 0
