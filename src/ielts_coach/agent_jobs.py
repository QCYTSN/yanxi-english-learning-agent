from __future__ import annotations

import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_contracts import (
    persist_agent_contract,
    validate_agent_contract_domain,
    validate_agent_contract_schema,
)
from .inference import InferenceBroker
from .session_manager import show_session
from .storage import (
    append_agent_run_event,
    claim_agent_run,
    claim_agent_run_recovery,
    close_open_provider_attempts,
    connect,
    get_agent_run,
    json_payload_hash,
    release_agent_run_lease,
    renew_agent_run_lease,
    update_agent_run,
)


ACTIVE_STATES = {"queued", "running", "validating", "persisting"}
TERMINAL_STATES = {
    "persisted",
    "test_passed",
    "failed",
    "cancelled",
    "invalid_output",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentJobManager:
    """Durable local Agent job coordinator backed by SQLite state."""

    def __init__(
        self,
        home: Path,
        *,
        workers: int = 2,
        lease_seconds: int = 30,
        heartbeat_seconds: int = 5,
    ) -> None:
        self.home = home
        self.instance_id = f"job-manager:{uuid.uuid4().hex}"
        self.lease_seconds = max(10, int(lease_seconds))
        self.heartbeat_seconds = max(
            1,
            min(int(heartbeat_seconds), self.lease_seconds // 2),
        )
        self._slots = threading.BoundedSemaphore(max(1, workers))
        self._lock = threading.Lock()
        self._scheduled: set[str] = set()
        self._closed = False
        self._sweeper_stop = threading.Event()
        self._sweeper: threading.Thread | None = None
        self.broker = InferenceBroker(home)

    def recover(self) -> dict[str, int]:
        result = self._recover_stale_runs()
        self._start_sweeper()
        return result

    def _recover_stale_runs(self) -> dict[str, int]:
        with connect(self.home) as conn:
            rows = conn.execute(
                """
                SELECT run_id,status,result_json,checkpoint,lease_owner,
                       lease_expires_at,resume_count
                FROM agent_runs
                WHERE status IN ('queued','running','validating','persisting')
                """
            ).fetchall()
        recovered = 0
        interrupted = 0
        for row in rows:
            run_id = str(row["run_id"])
            if _lease_is_active(row["lease_expires_at"]):
                continue
            claimed = claim_agent_run_recovery(
                self.home,
                run_id,
                expected_status=str(row["status"]),
                lease_owner=self.instance_id,
                lease_seconds=self.lease_seconds,
            )
            if not claimed:
                continue
            if claimed["status"] == "queued":
                self.enqueue(run_id)
                recovered += 1
            elif (
                isinstance(claimed.get("result"), dict)
                and "error" not in claimed["result"]
                and claimed["checkpoint"]
                in {"candidate_received", "validated", "persisting"}
            ):
                close_open_provider_attempts(
                    self.home,
                    run_id,
                    status="interrupted",
                    failure_stage="recovery",
                    error_code="LEASE_EXPIRED_AFTER_RESULT",
                    error_message=(
                        "The worker lease expired after a candidate result was "
                        "stored; the Runtime will resume validation/persistence."
                    ),
                )
                updated = update_agent_run(
                    self.home,
                    run_id,
                    status="queued",
                    error_code=None,
                    completed_at=None,
                    recovery_action="resume_checkpoint",
                    resume_count=int(claimed["resume_count"] or 0) + 1,
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "recovered",
                    {
                        "checkpoint": updated["checkpoint"],
                        "resume_count": updated["resume_count"],
                        "model_called_again": False,
                    },
                )
                self.enqueue(run_id)
                recovered += 1
            else:
                close_open_provider_attempts(
                    self.home,
                    run_id,
                    status="interrupted",
                    failure_stage="recovery",
                    error_code="SERVICE_RESTARTED",
                    error_message=(
                        "The local service restarted before this provider "
                        "attempt completed."
                    ),
                )
                update_agent_run(
                    self.home,
                    run_id,
                    status="failed",
                    error_code="SERVICE_RESTARTED",
                    recovery_action="retry",
                    completed_at=_now(),
                    checkpoint="failed",
                    lease_owner=None,
                    lease_expires_at=None,
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "failed",
                    {
                        "code": "SERVICE_RESTARTED",
                        "message": "The local service restarted before this task completed.",
                        "recovery_action": "retry",
                    },
                )
                interrupted += 1
        return {"recovered": recovered, "interrupted": interrupted}

    def _start_sweeper(self) -> None:
        with self._lock:
            if self._closed or (self._sweeper and self._sweeper.is_alive()):
                return
            self._sweeper = threading.Thread(
                target=self._sweep_loop,
                name="ielts-agent-lease-sweeper",
                daemon=True,
            )
            self._sweeper.start()

    def _sweep_loop(self) -> None:
        while not self._sweeper_stop.wait(self.heartbeat_seconds):
            if self._closed:
                return
            try:
                self._recover_stale_runs()
            except Exception:
                # A later sweep or explicit retry can recover from a transient
                # SQLite/filesystem failure without taking down the app.
                continue

    def enqueue(self, run_id: str) -> None:
        with self._lock:
            if self._closed or run_id in self._scheduled:
                return
            self._scheduled.add(run_id)
        threading.Thread(
            target=self._execute_safely,
            args=(run_id,),
            name=f"ielts-agent-{run_id[-8:]}",
            daemon=True,
        ).start()

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = get_agent_run(self.home, run_id)
        if not run:
            raise ValueError("Agent run not found")
        if run["status"] in TERMINAL_STATES:
            return run
        update_agent_run(
            self.home,
            run_id,
            cancel_requested=1,
            recovery_action=None,
        )
        execution_ref = run.get("execution_ref") or run_id
        try:
            self.broker.for_run(run).adapter.cancel(
                self.home, str(execution_ref)
            )
        except Exception:
            pass
        close_open_provider_attempts(
            self.home,
            run_id,
            status="cancelled",
            failure_stage="cancellation",
            error_code="AGENT_CANCELLED",
            error_message="The user cancelled the Agent task.",
        )
        updated = update_agent_run(
            self.home,
            run_id,
            status="cancelled",
            completed_at=_now(),
            checkpoint="cancelled",
            lease_owner=None,
            lease_expires_at=None,
        )
        append_agent_run_event(
            self.home,
            run_id,
            "cancelled",
            {"recovery_action": "retry"},
        )
        return updated

    def retry(self, run_id: str) -> dict[str, Any]:
        run = get_agent_run(self.home, run_id)
        if not run:
            raise ValueError("Agent run not found")
        if run["status"] not in {"failed", "cancelled", "invalid_output"}:
            raise ValueError("Only failed or cancelled Agent runs can be retried")
        session = (
            show_session(self.home, str(run["study_session_id"]))
            if run.get("study_session_id")
            else None
        )
        updated = update_agent_run(
            self.home,
            run_id,
            status="queued",
            error_code=None,
            result=None,
            completed_at=None,
            started_at=None,
            cancel_requested=0,
            recovery_action=None,
            checkpoint="queued",
            persistence={},
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=int(run.get("attempt_count") or 1) + 1,
            timeout_seconds=(
                max(300, int(run.get("timeout_seconds") or 120))
                if run.get("backend_kind") in {
                    "managed_runtime",
                    "model_provider",
                    "external_agent",
                }
                else int(run.get("timeout_seconds") or 120)
            ),
            base_revision=(
                int(session.get("revision", 0))
                if session
                else run.get("base_revision")
            ),
        )
        append_agent_run_event(
            self.home,
            run_id,
            "status",
            {
                "stage": "queued",
                "label": "Retry queued",
                "attempt": updated["attempt_count"],
            },
        )
        self.enqueue(run_id)
        return updated

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._sweeper_stop.set()
        if self._sweeper and self._sweeper.is_alive():
            self._sweeper.join(timeout=1)
        self.broker.shutdown()

    def _execute_safely(self, run_id: str) -> None:
        with self._slots:
            try:
                self._execute(run_id)
            finally:
                with self._lock:
                    self._scheduled.discard(run_id)

    def _execute(self, run_id: str) -> None:
        run = claim_agent_run(
            self.home,
            run_id,
            lease_owner=self.instance_id,
            lease_seconds=self.lease_seconds,
        )
        if not run:
            return
        heartbeat_stop, heartbeat = self._start_lease_heartbeat(run_id)
        try:
            if run.get("input_hash") and run["input_hash"] != json_payload_hash(
                run.get("request") or {}
            ):
                raise ValueError("Persisted Agent request hash does not match its payload")
            resume_candidate = (
                run.get("checkpoint")
                in {"candidate_received", "validated", "persisting"}
                and isinstance(run.get("result"), dict)
                and "error" not in run["result"]
            )
            provider_validation: dict[str, Any] = {}
            if resume_candidate:
                result = dict(run["result"])
                run = update_agent_run(
                    self.home,
                    run_id,
                    status="validating",
                    recovery_action="resume_checkpoint",
                    heartbeat_at=_now(),
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "status",
                    {
                        "stage": "resuming_validation",
                        "label": "Resuming saved model result",
                        "model_called_again": False,
                    },
                )
            else:
                prepared = self.broker.for_run(run)
                adapter = prepared.adapter
                started = _now()
                run = update_agent_run(
                    self.home,
                    run_id,
                    status="running",
                    checkpoint="invoking",
                    started_at=run.get("started_at") or started,
                    heartbeat_at=started,
                    execution_ref=run_id,
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "status",
                    {"stage": "running", "label": "Agent task running"},
                )
                result = self._run_with_timeout(
                    adapter,
                    run["request"],
                    timeout_seconds=int(run.get("timeout_seconds") or 120),
                    execution_ref=run_id,
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "provider_completed",
                    {"stage": "provider_completed"},
                )
                identity_reader = getattr(adapter, "execution_identity", None)
                if callable(identity_reader):
                    runtime_identity = {
                        key: value
                        for key, value in identity_reader(run_id).items()
                        if value is not None
                    }
                    if runtime_identity:
                        update_agent_run(self.home, run_id, **runtime_identity)
                current = get_agent_run(self.home, run_id)
                if (
                    not current
                    or current["cancel_requested"]
                    or current["status"] == "cancelled"
                ):
                    return
                usage_reader = getattr(adapter, "execution_usage", None)
                if callable(usage_reader):
                    runtime_usage = usage_reader(run_id)
                    if runtime_usage:
                        current = update_agent_run(
                            self.home,
                            run_id,
                            usage=runtime_usage,
                        )
                run = current
                validation_reader = getattr(adapter, "execution_validation", None)
                provider_validation = (
                    validation_reader(run_id)
                    if callable(validation_reader)
                    else {}
                )
            if run.get("backend_kind") == "manual":
                update_agent_run(
                    self.home,
                    run_id,
                    status="awaiting_import",
                    result=result,
                    heartbeat_at=_now(),
                    checkpoint="awaiting_import",
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "status",
                    {
                        "stage": "awaiting_import",
                        "label": "Waiting for structured result",
                    },
                )
                return
            run = update_agent_run(
                self.home,
                run_id,
                status="validating",
                result=result,
                checkpoint="candidate_received",
                heartbeat_at=_now(),
            )
            append_agent_run_event(
                self.home,
                run_id,
                "status",
                {"stage": "validating", "label": "Validating structured result"},
            )
            provider_prevalidated = (
                provider_validation.get("validated") is True
                and provider_validation.get("contract") == run["output_contract"]
            )
            if provider_prevalidated:
                append_agent_run_event(
                    self.home,
                    run_id,
                    "domain_validation_started",
                    {
                        "stage": "domain_validating",
                        "validated_by_provider_route": True,
                    },
                )
                validated = result
            else:
                structured = validate_agent_contract_schema(
                    run["output_contract"], result
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "domain_validation_started",
                    {"stage": "domain_validating"},
                )
                validated = validate_agent_contract_domain(
                    run["output_contract"], structured
                )
            run = update_agent_run(
                self.home,
                run_id,
                result=validated,
                checkpoint="validated",
                heartbeat_at=_now(),
            )
            if run.get("backend_kind") == "mock":
                update_agent_run(
                    self.home,
                    run_id,
                    status="test_passed",
                    result=validated,
                    completed_at=_now(),
                    heartbeat_at=_now(),
                    recovery_action=None,
                    checkpoint="test_passed",
                )
                append_agent_run_event(
                    self.home,
                    run_id,
                    "test_passed",
                    {
                        "stage": "test_passed",
                        "label": "Pipeline test passed",
                        "learning_record_written": False,
                        "model_called": False,
                    },
                )
                return
            run = update_agent_run(
                self.home,
                run_id,
                status="persisting",
                checkpoint="persisting",
                heartbeat_at=_now(),
            )
            append_agent_run_event(
                self.home,
                run_id,
                "status",
                {"stage": "persisting", "label": "Saving authoritative result"},
            )
            canonical = persist_agent_contract(self.home, run, validated)
            update_agent_run(
                self.home,
                run_id,
                status="persisted",
                result=validated,
                completed_at=_now(),
                heartbeat_at=_now(),
                recovery_action=None,
                checkpoint="persisted",
                persistence=canonical,
            )
            append_agent_run_event(
                self.home,
                run_id,
                "completed",
                {
                    "session_id": run.get("study_session_id"),
                    "revision": canonical.get("revision"),
                },
            )
        except TimeoutError as exc:
            recovery = (
                "check_primary_model_then_retry"
                if run.get("backend_kind") in {
                    "managed_runtime",
                    "model_provider",
                }
                else "check_claude_provider_then_retry"
                if run.get("adapter_id") == "claude"
                else "check_agent_cli_then_retry"
            )
            self._fail(run_id, "AGENT_TIMEOUT", str(exc), recovery)
        except Exception as exc:
            code = getattr(exc, "code", "AGENT_RUN_FAILED")
            recovery = {
                "SESSION_REVISION_CONFLICT": "refresh_session_and_retry",
                "CODEX_AUTH_REQUIRED": "connect_codex_then_retry",
                "CODEX_EXECUTABLE_UNAVAILABLE": "configure_codex_cli_then_retry",
                "CODEX_APP_SERVER_STOPPED": "restart_codex_runtime_then_retry",
                "MODEL_PROVIDER_REQUIRED": "configure_primary_model",
                "MODEL_PROVIDER_AUTH_REQUIRED": "configure_model_credential",
                "MODEL_PROVIDER_AUTH_FAILED": "check_model_credential",
                "MODEL_PROVIDER_CONNECTION_FAILED": "check_model_connection",
                "MODEL_ROUTE_FAILED": "check_model_route_then_retry",
            }.get(code, "retry")
            self._fail(run_id, code, str(exc), recovery)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)
            release_agent_run_lease(
                self.home,
                run_id,
                lease_owner=self.instance_id,
            )

    def _start_lease_heartbeat(
        self,
        run_id: str,
    ) -> tuple[threading.Event, threading.Thread]:
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(self.heartbeat_seconds):
                if not renew_agent_run_lease(
                    self.home,
                    run_id,
                    lease_owner=self.instance_id,
                    lease_seconds=self.lease_seconds,
                ):
                    return

        thread = threading.Thread(
            target=heartbeat,
            name=f"ielts-agent-heartbeat-{run_id[-8:]}",
            daemon=True,
        )
        thread.start()
        return stop, thread

    def _run_with_timeout(
        self,
        adapter: Any,
        request: dict[str, Any],
        *,
        timeout_seconds: int,
        execution_ref: str,
    ) -> dict[str, Any]:
        output: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                start_with_events = getattr(adapter, "start_with_events", None)
                if callable(start_with_events):
                    value = start_with_events(
                        self.home,
                        request,
                        lambda payload: append_agent_run_event(
                            self.home,
                            execution_ref,
                            "progress",
                            payload,
                        ),
                    )
                else:
                    value = adapter.start(self.home, request)
                output.put((True, value))
            except BaseException as exc:
                output.put((False, exc))

        thread = threading.Thread(
            target=invoke, name=f"ielts-agent-call-{execution_ref}", daemon=True
        )
        thread.start()
        thread.join(max(0.01, timeout_seconds))
        if thread.is_alive():
            try:
                adapter.cancel(self.home, execution_ref)
            finally:
                raise TimeoutError(
                    f"Agent task exceeded the {timeout_seconds}s timeout"
                )
        ok, value = output.get_nowait()
        if not ok:
            raise value
        return value

    def _fail(
        self, run_id: str, code: str, message: str, recovery_action: str
    ) -> None:
        current = get_agent_run(self.home, run_id)
        if current and current["status"] == "cancelled":
            return
        if code == "AGENT_OUTPUT_SCHEMA_INVALID":
            append_agent_run_event(
                self.home,
                run_id,
                "schema_validation_failed",
                {"stage": "schema_validation", "code": code, "recoverable": True},
            )
        elif code == "AGENT_OUTPUT_DOMAIN_INVALID":
            append_agent_run_event(
                self.home,
                run_id,
                "domain_validation_failed",
                {"stage": "domain_validation", "code": code, "recoverable": True},
            )
        close_open_provider_attempts(
            self.home,
            run_id,
            status="failed",
            failure_stage="timeout" if code == "AGENT_TIMEOUT" else "job",
            error_code=code,
            error_message=message,
        )
        update_agent_run(
            self.home,
            run_id,
            status="failed",
            error_code=code,
            result={
                "error": {
                    "code": code,
                    "message": message[-2000:],
                }
            },
            recovery_action=recovery_action,
            completed_at=_now(),
            heartbeat_at=_now(),
            checkpoint="failed",
        )
        append_agent_run_event(
            self.home,
            run_id,
            "failed",
            {
                "code": code,
                "message": message,
                "recovery_action": recovery_action,
            },
        )


def _lease_is_active(value: Any) -> bool:
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(str(value))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > datetime.now(timezone.utc)
    except ValueError:
        return False
