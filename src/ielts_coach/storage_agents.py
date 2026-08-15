from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import _now, connect, initialise_database

__all__ = [
    "create_agent_run",
    "update_agent_run",
    "get_agent_run",
    "compact_agent_run_request",
    "get_privacy_receipt",
    "json_payload_hash",
    "claim_agent_run",
    "claim_agent_run_recovery",
    "renew_agent_run_lease",
    "release_agent_run_lease",
    "list_agent_runs",
    "append_agent_run_event",
    "list_agent_run_events",
    "record_audit_event",
    "list_audit_events",
]


def create_agent_run(home: Path, run: dict[str, Any]) -> dict[str, Any]:
    initialise_database(home)
    inferred_backend_kind = {
        "mock": "mock",
        "manual": "manual",
        "codex-managed": "managed_runtime",
    }.get(str(run["adapter_id"]), "external_agent")
    columns = (
        "run_id", "study_session_id", "study_thread_id", "adapter_id",
        "capability_id", "execution_profile_id", "model_provider_id",
        "backend_kind", "transport", "auth_mode", "agent_provider",
        "agent_version", "model_id", "model_display_name", "agent_session_id",
        "launcher_kind", "capabilities_json", "calibration_status", "action",
        "output_contract", "base_revision", "status", "error_code",
        "request_json", "result_json", "usage_json", "created_at", "started_at",
        "completed_at", "timeout_seconds", "attempt_count", "cancel_requested",
        "heartbeat_at", "recovery_action", "execution_ref", "skill_hash",
        "inference_route_json", "checkpoint", "input_hash", "lease_owner",
        "lease_expires_at", "resume_count", "persistence_json",
        "request_compacted_at",
    )
    values = (
        run["run_id"], run.get("study_session_id"), run.get("study_thread_id"),
        run["adapter_id"], run.get("capability_id"),
        run.get("execution_profile_id"), run.get("model_provider_id"),
        run.get("backend_kind", inferred_backend_kind), run.get("transport"),
        run.get("auth_mode"), run.get("agent_provider"), run.get("agent_version"),
        run.get("model_id"), run.get("model_display_name"),
        run.get("agent_session_id"), run.get("launcher_kind", "unknown"),
        json.dumps(run.get("capabilities") or {}, ensure_ascii=False),
        run.get("calibration_status", "unknown"), run["action"],
        run["output_contract"], run.get("base_revision"), run["status"],
        run.get("error_code"),
        json.dumps(run.get("request") or {}, ensure_ascii=False),
        json.dumps(run.get("result"), ensure_ascii=False)
        if run.get("result") is not None else None,
        json.dumps(run.get("usage") or {}, ensure_ascii=False),
        run.get("created_at") or _now(), run.get("started_at"),
        run.get("completed_at"), int(run.get("timeout_seconds") or 120),
        int(run.get("attempt_count") or 1),
        int(bool(run.get("cancel_requested", False))), run.get("heartbeat_at"),
        run.get("recovery_action"), run.get("execution_ref"),
        run.get("skill_hash"),
        json.dumps(run.get("inference_route") or [], ensure_ascii=False),
        run.get("checkpoint", "queued"),
        run.get("input_hash") or json_payload_hash(run.get("request") or {}),
        run.get("lease_owner"), run.get("lease_expires_at"),
        int(run.get("resume_count") or 0),
        json.dumps(run.get("persistence") or {}, ensure_ascii=False),
        run.get("request_compacted_at"),
    )
    with connect(home) as conn:
        conn.execute(
            f"INSERT INTO agent_runs({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in columns)})",
            values,
        )
        receipt = run.get("privacy_receipt")
        if receipt:
            if str(receipt.get("run_id") or run["run_id"]) != str(run["run_id"]):
                raise ValueError("Privacy receipt run_id does not match Agent run")
            conn.execute(
                """
                INSERT INTO privacy_receipts(
                  receipt_id,run_id,authorization_kind,reason,remote_processing,
                  private_source,source_type,provider_ids_json,scope_hash,
                  policy_json,reusable,created_at,consumed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)
                """,
                (
                    receipt["receipt_id"],
                    run["run_id"],
                    receipt["authorization_kind"],
                    receipt["reason"],
                    int(bool(receipt.get("remote_processing"))),
                    int(bool(receipt.get("private_source"))),
                    receipt.get("source_type"),
                    json.dumps(receipt.get("provider_ids") or [], ensure_ascii=False),
                    receipt["scope_hash"],
                    json.dumps(receipt.get("policy") or {}, ensure_ascii=False),
                    receipt.get("created_at") or _now(),
                    receipt.get("consumed_at") or _now(),
                ),
            )
    return get_agent_run(home, run["run_id"]) or run


def update_agent_run(home: Path, run_id: str, **changes: Any) -> dict[str, Any]:
    allowed = {
        "study_thread_id",
        "capability_id", "execution_profile_id", "model_provider_id",
        "backend_kind", "transport",
        "auth_mode",
        "agent_provider", "agent_version", "model_id", "model_display_name",
        "agent_session_id", "launcher_kind", "capabilities_json",
        "calibration_status", "status", "error_code", "result_json", "usage_json",
        "started_at", "completed_at", "timeout_seconds", "attempt_count",
        "cancel_requested", "heartbeat_at", "recovery_action", "execution_ref",
        "base_revision", "skill_hash", "inference_route_json",
        "checkpoint", "input_hash", "lease_owner", "lease_expires_at",
        "resume_count", "persistence_json", "orchestration_json",
        "request_json", "request_compacted_at",
    }
    columns: list[str] = []
    values: list[Any] = []
    for key, value in changes.items():
        column = key
        if key == "result":
            column, value = "result_json", json.dumps(value, ensure_ascii=False)
        elif key == "usage":
            column, value = "usage_json", json.dumps(value, ensure_ascii=False)
        elif key == "capabilities":
            column, value = "capabilities_json", json.dumps(value, ensure_ascii=False)
        elif key == "inference_route":
            column, value = "inference_route_json", json.dumps(
                value, ensure_ascii=False
            )
        elif key == "persistence":
            column, value = "persistence_json", json.dumps(
                value or {}, ensure_ascii=False
            )
        elif key == "orchestration":
            column, value = "orchestration_json", json.dumps(
                value or {}, ensure_ascii=False
            )
        elif key == "request":
            column, value = "request_json", json.dumps(
                value or {}, ensure_ascii=False
            )
        if column not in allowed:
            continue
        columns.append(f"{column}=?")
        values.append(value)
    if not columns:
        return get_agent_run(home, run_id) or {}
    values.append(run_id)
    with connect(home) as conn:
        conn.execute(f"UPDATE agent_runs SET {','.join(columns)} WHERE run_id=?", values)
    return get_agent_run(home, run_id) or {}


def get_agent_run(home: Path, run_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        receipt = conn.execute(
            "SELECT * FROM privacy_receipts WHERE run_id=?", (run_id,)
        ).fetchone()
    if not row:
        return None
    result = _agent_run_row(row)
    result["privacy_receipt"] = _privacy_receipt_row(receipt) if receipt else None
    return result


def _agent_run_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "study_session_id": row["study_session_id"],
        "study_thread_id": row["study_thread_id"],
        "adapter_id": row["adapter_id"],
        "capability_id": row["capability_id"],
        "execution_profile_id": row["execution_profile_id"],
        "model_provider_id": row["model_provider_id"],
        "backend_kind": row["backend_kind"],
        "transport": row["transport"],
        "auth_mode": row["auth_mode"],
        "agent_provider": row["agent_provider"],
        "agent_version": row["agent_version"],
        "model_id": row["model_id"],
        "model_display_name": row["model_display_name"],
        "agent_session_id": row["agent_session_id"],
        "launcher_kind": row["launcher_kind"],
        "capabilities": json.loads(row["capabilities_json"]),
        "calibration_status": row["calibration_status"],
        "action": row["action"],
        "output_contract": row["output_contract"],
        "base_revision": row["base_revision"],
        "status": row["status"],
        "error_code": row["error_code"],
        "request": json.loads(row["request_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "usage": json.loads(row["usage_json"]),
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "timeout_seconds": int(row["timeout_seconds"]),
        "attempt_count": int(row["attempt_count"]),
        "cancel_requested": bool(row["cancel_requested"]),
        "heartbeat_at": row["heartbeat_at"],
        "recovery_action": row["recovery_action"],
        "execution_ref": row["execution_ref"],
        "skill_hash": row["skill_hash"],
        "inference_route": json.loads(row["inference_route_json"]),
        "checkpoint": row["checkpoint"],
        "input_hash": row["input_hash"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "resume_count": int(row["resume_count"]),
        "persistence": json.loads(row["persistence_json"]),
        "orchestration": json.loads(row["orchestration_json"]),
        "request_compacted_at": row["request_compacted_at"],
    }


def compact_agent_run_request(home: Path, run_id: str) -> dict[str, Any]:
    """Discard replay-only private context after an authoritative result exists."""
    run = get_agent_run(home, run_id)
    if not run:
        raise ValueError("Agent run not found")
    if run["status"] not in {"persisted", "test_passed"}:
        return run
    request = dict(run.get("request") or {})
    compact = {
        "request_version": request.get("request_version"),
        "request_id": request.get("request_id") or run_id,
        "study_session_id": request.get("study_session_id"),
        "study_thread_id": request.get("study_thread_id"),
        "user_message_id": request.get("user_message_id"),
        "capability_id": request.get("capability_id"),
        "skill": request.get("skill"),
        "action": request.get("action"),
        "context_ref": request.get("context_ref"),
        "payload_refs": request.get("payload_refs") or [],
        "output_contract": request.get("output_contract"),
        "privacy_receipt_id": (
            (request.get("privacy_decision") or {}).get("receipt_id")
        ),
        "media_refs": [
            {
                "media_id": item.get("media_id"),
                "content_hash": item.get("content_hash"),
            }
            for item in request.get("media_refs") or []
            if isinstance(item, dict)
        ],
        "compacted": True,
        "input_hash": run.get("input_hash"),
    }
    return update_agent_run(
        home,
        run_id,
        request=compact,
        request_compacted_at=_now(),
    )


def _privacy_receipt_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "receipt_id": row["receipt_id"],
        "run_id": row["run_id"],
        "authorization_kind": row["authorization_kind"],
        "reason": row["reason"],
        "remote_processing": bool(row["remote_processing"]),
        "private_source": bool(row["private_source"]),
        "source_type": row["source_type"],
        "provider_ids": json.loads(row["provider_ids_json"]),
        "scope_hash": row["scope_hash"],
        "policy": json.loads(row["policy_json"]),
        "reusable": bool(row["reusable"]),
        "created_at": row["created_at"],
        "consumed_at": row["consumed_at"],
    }


def get_privacy_receipt(home: Path, run_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM privacy_receipts WHERE run_id=?", (run_id,)
        ).fetchone()
    return _privacy_receipt_row(row) if row else None


def json_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim_agent_run(
    home: Path,
    run_id: str,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> dict[str, Any] | None:
    """Atomically claim one queued run for a single local worker instance."""
    initialise_database(home)
    now = _now()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))
    ).isoformat()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_owner=?,lease_expires_at=?,heartbeat_at=?
            WHERE run_id=? AND status='queued' AND cancel_requested=0
              AND (
                lease_owner IS NULL OR lease_owner=? OR lease_expires_at IS NULL
                OR lease_expires_at<=?
              )
            """,
            (lease_owner, expires_at, now, run_id, lease_owner, now),
        )
        claimed = cursor.rowcount == 1
    return get_agent_run(home, run_id) if claimed else None


def claim_agent_run_recovery(
    home: Path,
    run_id: str,
    *,
    expected_status: str,
    lease_owner: str,
    lease_seconds: int,
) -> dict[str, Any] | None:
    """Atomically reserve one expired, unfinished run for recovery."""
    if expected_status not in {"queued", "running", "validating", "persisting"}:
        return None
    initialise_database(home)
    now = _now()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))
    ).isoformat()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_owner=?,lease_expires_at=?,heartbeat_at=?
            WHERE run_id=? AND status=? AND cancel_requested=0
              AND (lease_expires_at IS NULL OR lease_expires_at<=?)
            """,
            (lease_owner, expires_at, now, run_id, expected_status, now),
        )
        claimed = cursor.rowcount == 1
    return get_agent_run(home, run_id) if claimed else None


def renew_agent_run_lease(
    home: Path,
    run_id: str,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> bool:
    now = _now()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))
    ).isoformat()
    with connect(home) as conn:
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_expires_at=?,heartbeat_at=?
            WHERE run_id=? AND lease_owner=?
              AND status IN ('queued','running','validating','persisting')
            """,
            (expires_at, now, run_id, lease_owner),
        )
    return cursor.rowcount == 1


def release_agent_run_lease(
    home: Path,
    run_id: str,
    *,
    lease_owner: str,
) -> bool:
    with connect(home) as conn:
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_owner=NULL,lease_expires_at=NULL
            WHERE run_id=? AND lease_owner=?
            """,
            (run_id, lease_owner),
        )
    return cursor.rowcount == 1


def list_agent_runs(
    home: Path,
    *,
    study_session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    params: list[Any] = []
    sql = "SELECT * FROM agent_runs"
    if study_session_id:
        sql += " WHERE study_session_id=?"
        params.append(study_session_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_agent_run_row(row) for row in rows]


_AGENT_EVENT_NAMES = {
    "queued": "job_queued",
    "running": "provider_started",
    "awaiting_import": "awaiting_user",
    "validating": "schema_validation_started",
    "resuming_validation": "schema_validation_started",
    "domain_validating": "domain_validation_started",
    "persisting": "persistence_started",
    "persisted": "persisted",
    "test_passed": "pipeline_test_passed",
    "connecting_model": "provider_started",
    "schema_validation": "schema_validation_started",
    "domain_validation": "domain_validation_started",
    "provider_validated": "provider_completed",
    "provider_failed": "provider_failed",
    "provider_skipped": "provider_failed",
    "fallback_started": "fallback_started",
}

_AGENT_EVENT_MESSAGES = {
    "job_queued": "任务已进入本地队列",
    "context_preparing": "正在整理本次学习所需内容",
    "context_ready": "学习上下文已准备完成",
    "skill_compiled": "教学规则已加载",
    "provider_started": "模型正在生成反馈",
    "provider_stream_delta": "模型正在继续生成",
    "provider_progress": "模型任务正在处理",
    "provider_completed": "模型结果已返回",
    "provider_failed": "当前模型调用失败",
    "fallback_started": "正在尝试备用模型",
    "schema_validation_started": "正在检查结果格式",
    "schema_validation_failed": "结果格式未通过检查",
    "domain_validation_started": "正在检查 IELTS 教学规则",
    "domain_validation_failed": "结果未通过教学规则检查",
    "awaiting_user": "等待用户导入结构化结果",
    "persistence_started": "正在保存正式学习记录",
    "persisted": "反馈已验证并保存",
    "pipeline_test_passed": "本地反馈管线验证通过",
    "job_cancelled": "任务已取消",
    "job_failed": "任务未能完成",
}


def _normalise_agent_event(
    event_type: str,
    payload: dict[str, Any],
) -> tuple[str, str, str, bool]:
    stage = str(payload.get("stage") or event_type or "unknown")
    if event_type == "status":
        canonical = _AGENT_EVENT_NAMES.get(stage, "provider_progress")
    elif event_type == "progress":
        if stage == "provider_rejected":
            canonical = (
                "schema_validation_failed"
                if payload.get("failure_stage") == "schema"
                else "domain_validation_failed"
                if payload.get("failure_stage") == "domain"
                else "provider_failed"
            )
        else:
            canonical = _AGENT_EVENT_NAMES.get(
                stage,
                "provider_stream_delta"
                if any(key in payload for key in ("delta", "text_delta", "content_delta"))
                else "provider_progress",
            )
    elif event_type == "completed":
        canonical = "persisted"
        stage = "persisted"
    elif event_type == "cancelled":
        canonical = "job_cancelled"
        stage = "cancelled"
    elif event_type == "failed":
        canonical = "job_failed"
        stage = "failed"
    elif event_type == "test_passed":
        canonical = "pipeline_test_passed"
        stage = "test_passed"
    else:
        canonical = event_type
    display_message = str(
        payload.get("display_message")
        or payload.get("label")
        or _AGENT_EVENT_MESSAGES.get(canonical, "任务状态已更新")
    )[:240]
    recoverable = bool(
        payload.get("recoverable")
        if "recoverable" in payload
        else canonical
        in {
            "provider_failed",
            "schema_validation_failed",
            "domain_validation_failed",
            "job_failed",
            "job_cancelled",
        }
    )
    return canonical, stage[:80], display_message, recoverable


def append_agent_run_event(
    home: Path, run_id: str, event_type: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    initialise_database(home)
    event_payload = dict(payload or {})
    canonical, stage, display_message, recoverable = _normalise_agent_event(
        event_type, event_payload
    )
    payload_hash = json_payload_hash(event_payload)
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 AS next_sequence FROM agent_run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
        sequence = int(row["next_sequence"])
        created_at = _now()
        conn.execute(
            """
            INSERT INTO agent_run_events(
              run_id,sequence,event_type,stage,display_message,recoverable,
              payload_hash,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                sequence,
                canonical,
                stage,
                display_message,
                int(recoverable),
                payload_hash,
                json.dumps(event_payload, ensure_ascii=False),
                created_at,
            ),
        )
        run = conn.execute(
            "SELECT study_session_id,capability_id FROM agent_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        audit_metadata = {
            key: event_payload[key]
            for key in (
                "code",
                "recovery_action",
                "provider_id",
                "attempt",
                "model_called",
                "model_called_again",
                "skill_hash",
                "contract",
            )
            if key in event_payload
        }
        outcome = (
            "failed"
            if canonical.endswith("_failed") or canonical == "job_failed"
            else "cancelled"
            if canonical == "job_cancelled"
            else "succeeded"
            if canonical in {"persisted", "pipeline_test_passed"}
            else "recorded"
        )
        actor_type = (
            "local_user"
            if canonical == "job_queued"
            else "model_provider"
            if canonical.startswith("provider_") or canonical == "fallback_started"
            else "teaching_runtime"
        )
        _insert_audit_event(
            conn,
            category="agent_job",
            action=canonical,
            outcome=outcome,
            actor_type=actor_type,
            subject_type="agent_run",
            subject_id=run_id,
            session_id=str(run["study_session_id"]) if run and run["study_session_id"] else None,
            run_id=run_id,
            capability_id=str(run["capability_id"]) if run and run["capability_id"] else None,
            request_id=None,
            payload_hash=payload_hash,
            metadata={"sequence": sequence, "stage": stage, **audit_metadata},
            created_at=created_at,
        )
    return {
        "run_id": run_id,
        "sequence": sequence,
        "type": canonical,
        "stage": stage,
        "display_message": display_message,
        "recoverable": recoverable,
        "payload_hash": payload_hash,
        "payload": event_payload,
        "created_at": created_at,
    }


def list_agent_run_events(home: Path, run_id: str, after: int = 0) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_run_events WHERE run_id=? AND sequence>? ORDER BY sequence",
            (run_id, after),
        ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "sequence": int(row["sequence"]),
            "type": row["event_type"],
            "stage": row["stage"],
            "display_message": row["display_message"],
            "recoverable": bool(row["recoverable"]),
            "payload_hash": row["payload_hash"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _insert_audit_event(
    conn: sqlite3.Connection,
    *,
    category: str,
    action: str,
    outcome: str,
    actor_type: str,
    subject_type: str | None,
    subject_id: str | None,
    session_id: str | None,
    run_id: str | None,
    capability_id: str | None,
    request_id: str | None,
    payload_hash: str | None,
    metadata: dict[str, Any],
    created_at: str,
) -> str:
    audit_id = f"audit_{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO audit_events(
          audit_id,category,action,outcome,actor_type,subject_type,subject_id,
          session_id,run_id,capability_id,request_id,payload_hash,
          metadata_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            audit_id,
            category,
            action,
            outcome,
            actor_type,
            subject_type,
            subject_id,
            session_id,
            run_id,
            capability_id,
            request_id,
            payload_hash,
            json.dumps(metadata, ensure_ascii=False, default=str),
            created_at,
        ),
    )
    return audit_id


def record_audit_event(
    home: Path,
    *,
    category: str,
    action: str,
    outcome: str = "recorded",
    actor_type: str = "local_user",
    subject_type: str | None = None,
    subject_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    capability_id: str | None = None,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a privacy-safe audit fact without storing learner content."""
    initialise_database(home)
    payload_hash = json_payload_hash(payload) if payload is not None else None
    created_at = _now()
    with connect(home) as conn:
        audit_id = _insert_audit_event(
            conn,
            category=category,
            action=action,
            outcome=outcome,
            actor_type=actor_type,
            subject_type=subject_type,
            subject_id=subject_id,
            session_id=session_id,
            run_id=run_id,
            capability_id=capability_id,
            request_id=request_id,
            payload_hash=payload_hash,
            metadata=dict(metadata or {}),
            created_at=created_at,
        )
    return {
        "audit_id": audit_id,
        "category": category,
        "action": action,
        "outcome": outcome,
        "payload_hash": payload_hash,
        "created_at": created_at,
    }


def list_audit_events(
    home: Path,
    *,
    category: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if category:
        clauses.append("category=?")
        params.append(category)
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    sql = "SELECT * FROM audit_events"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            **{key: row[key] for key in row.keys() if key != "metadata_json"},
            "metadata": json.loads(row["metadata_json"]),
        }
        for row in rows
    ]


