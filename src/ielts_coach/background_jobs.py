from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import connect, initialise_database


ACTIVE_BACKGROUND_STATES = {"queued", "running"}
BACKGROUND_TIMEOUTS = {
    "ocr_install": 3600,
    "content_prepare": 900,
    "content_ocr": 3600,
    "content_review_draft": 900,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalBackgroundJobManager:
    """Runs heavy local maintenance in disposable child processes.

    The SQLite row is the durable control plane. The web process only schedules
    and monitors workers, so OCR/PDF work cannot block request handling and a
    crashed worker cannot take the local application service down with it.
    """

    def __init__(self, home: Path, *, workers: int = 2) -> None:
        self.home = home.resolve()
        self.workers = max(1, min(int(workers), 4))
        self._queue: queue.PriorityQueue[tuple[int, int, str | None]] = (
            queue.PriorityQueue()
        )
        self._lock = threading.RLock()
        self._scheduled: set[str] = set()
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._threads: list[threading.Thread] = []
        self._sequence = 0
        self._stop = threading.Event()
        self._started = False

    def recover(self) -> dict[str, int]:
        initialise_database(self.home)
        with self._lock:
            if not self._started:
                self._started = True
                for index in range(self.workers):
                    thread = threading.Thread(
                        target=self._worker_loop,
                        name=f"ielts-local-worker-supervisor-{index + 1}",
                        daemon=True,
                    )
                    thread.start()
                    self._threads.append(thread)
        now = _now()
        with connect(self.home) as conn:
            interrupted = conn.execute(
                """
                UPDATE local_background_jobs
                SET status='failed',completed_at=?,heartbeat_at=?,pid=NULL,
                    error_code='SERVICE_RESTARTED',
                    error_message='The local service stopped while this job was running.'
                WHERE status='running'
                """,
                (now, now),
            ).rowcount
            queued = conn.execute(
                """
                SELECT job_id,priority FROM local_background_jobs
                WHERE status='queued' ORDER BY priority,created_at
                """
            ).fetchall()
        for row in queued:
            self._enqueue(str(row["job_id"]), int(row["priority"]))
        return {"queued": len(queued), "interrupted": int(interrupted)}

    def submit(
        self,
        job_kind: str,
        payload: dict[str, Any],
        *,
        priority: int = 50,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        if job_kind not in BACKGROUND_TIMEOUTS:
            raise ValueError(f"Unsupported local background job: {job_kind}")
        initialise_database(self.home)
        clean_priority = max(0, min(int(priority), 1000))
        clean_dedupe = dedupe_key.strip()[:240] if dedupe_key else None
        with self._lock:
            if clean_dedupe:
                with connect(self.home) as conn:
                    existing = conn.execute(
                        """
                        SELECT * FROM local_background_jobs
                        WHERE dedupe_key=? AND status IN ('queued','running')
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (clean_dedupe,),
                    ).fetchone()
                if existing:
                    return _job_row(existing)
            job_id = f"bg-{uuid.uuid4().hex}"
            with connect(self.home) as conn:
                conn.execute(
                    """
                    INSERT INTO local_background_jobs(
                      job_id,job_kind,priority,status,dedupe_key,payload_json,
                      created_at,heartbeat_at
                    ) VALUES(?,?,?,'queued',?,?,?,?)
                    """,
                    (
                        job_id,
                        job_kind,
                        clean_priority,
                        clean_dedupe,
                        json.dumps(payload, ensure_ascii=False, default=str),
                        _now(),
                        _now(),
                    ),
                )
            self._enqueue(job_id, clean_priority)
        result = get_background_job(self.home, job_id)
        if result is None:  # pragma: no cover - defensive database invariant
            raise RuntimeError("Background job disappeared after creation")
        return result

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with connect(self.home) as conn:
            row = conn.execute(
                "SELECT status FROM local_background_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            if str(row["status"]) in {"completed", "failed", "cancelled"}:
                return get_background_job(self.home, job_id)
            conn.execute(
                """
                UPDATE local_background_jobs
                SET status='cancelled',completed_at=?,heartbeat_at=?,pid=NULL,
                    error_code='CANCELLED',error_message='Cancelled by the user.'
                WHERE job_id=?
                """,
                (_now(), _now(), job_id),
            )
        with self._lock:
            process = self._processes.get(job_id)
        _terminate_process_tree(process)
        return get_background_job(self.home, job_id)

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        with self._lock:
            active = list(self._processes.items())
        for job_id, process in active:
            _terminate_process_tree(process)
            _mark_failed_if_active(
                self.home,
                job_id,
                "SERVICE_STOPPED",
                "The local service stopped before this background job completed.",
            )
        for _ in self._threads:
            self._queue.put((10_000, 0, None))
        for thread in self._threads:
            thread.join(timeout=5)

    def _enqueue(self, job_id: str, priority: int) -> None:
        with self._lock:
            if job_id in self._scheduled or self._stop.is_set():
                return
            self._scheduled.add(job_id)
            self._sequence += 1
            self._queue.put((priority, self._sequence, job_id))

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                _, _, job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job_id is None:
                self._queue.task_done()
                break
            try:
                self._run_job(job_id)
            finally:
                with self._lock:
                    self._scheduled.discard(job_id)
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        job = get_background_job(self.home, job_id)
        if not job or job["status"] != "queued" or self._stop.is_set():
            return
        command = [
            sys.executable,
            "-m",
            "ielts_coach.local_worker",
            "background-job",
            str(self.home),
            job_id,
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with connect(self.home) as conn:
            claimed = conn.execute(
                """
                UPDATE local_background_jobs
                SET status='running',started_at=COALESCE(started_at,?),
                    heartbeat_at=?,attempt_count=attempt_count+1,
                    error_code=NULL,error_message=NULL
                WHERE job_id=? AND status='queued'
                """,
                (_now(), _now(), job_id),
            ).rowcount
        if claimed != 1:
            return
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            _mark_failed_if_active(
                self.home, job_id, "WORKER_START_FAILED", str(exc)[-1000:]
            )
            return
        with self._lock:
            self._processes[job_id] = process
        with connect(self.home) as conn:
            conn.execute(
                """
                UPDATE local_background_jobs
                SET pid=?,heartbeat_at=?
                WHERE job_id=? AND status='running'
                """,
                (process.pid, _now(), job_id),
            )
        deadline = time.monotonic() + BACKGROUND_TIMEOUTS[str(job["job_kind"])]
        try:
            while process.poll() is None and not self._stop.wait(1.0):
                if time.monotonic() >= deadline:
                    _terminate_process_tree(process)
                    _mark_failed_if_active(
                        self.home,
                        job_id,
                        "BACKGROUND_TIMEOUT",
                        "The isolated local worker exceeded its execution timeout.",
                    )
                    return
                with connect(self.home) as conn:
                    status = conn.execute(
                        "SELECT status FROM local_background_jobs WHERE job_id=?",
                        (job_id,),
                    ).fetchone()
                    if status is None or str(status["status"]) == "cancelled":
                        _terminate_process_tree(process)
                        return
                    conn.execute(
                        "UPDATE local_background_jobs SET heartbeat_at=? WHERE job_id=?",
                        (_now(), job_id),
                    )
            return_code = process.poll()
            if return_code not in {0, None}:
                _mark_failed_if_active(
                    self.home,
                    job_id,
                    "WORKER_CRASHED",
                    f"The isolated local worker exited with code {return_code}.",
                )
        finally:
            with self._lock:
                self._processes.pop(job_id, None)


def execute_background_job(home: Path, job_id: str) -> None:
    job = get_background_job(home, job_id)
    if not job or job["status"] not in ACTIVE_BACKGROUND_STATES:
        return
    if job["status"] == "queued":
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE local_background_jobs
                SET status='running',started_at=COALESCE(started_at,?),heartbeat_at=?
                WHERE job_id=? AND status='queued'
                """,
                (_now(), _now(), job_id),
            )
    payload = dict(job.get("payload") or {})
    try:
        if job["job_kind"] == "ocr_install":
            from .ocr_runtime import install_ocr_runtime

            install_ocr_runtime(home)
        elif job["job_kind"] == "content_prepare":
            from .content_imports import prepare_import

            prepare_import(home, str(payload["import_id"]))
        elif job["job_kind"] == "content_ocr":
            from .content_imports import run_import_ocr

            run_import_ocr(
                home,
                str(payload["import_id"]),
                stored_name=str(payload["stored_name"]),
                pages=[int(value) for value in payload.get("pages") or []],
            )
        elif job["job_kind"] == "content_review_draft":
            from .content_imports import build_import_review_draft

            build_import_review_draft(home, str(payload["import_id"]))
        else:  # pragma: no cover - submit validates the kind
            raise ValueError(f"Unsupported local background job: {job['job_kind']}")
    except BaseException as exc:
        _mark_failed_if_active(
            home, job_id, "BACKGROUND_JOB_FAILED", str(exc)[-2000:]
        )
        raise
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE local_background_jobs
            SET status='completed',completed_at=?,heartbeat_at=?,pid=NULL,
                error_code=NULL,error_message=NULL
            WHERE job_id=? AND status='running'
            """,
            (_now(), _now(), job_id),
        )


def get_background_job(home: Path, job_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM local_background_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    return _job_row(row) if row else None


def list_background_jobs(home: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM local_background_jobs
            ORDER BY created_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [_job_row(row) for row in rows]


def _job_row(row: Any) -> dict[str, Any]:
    return {
        **{key: row[key] for key in row.keys() if key != "payload_json"},
        "priority": int(row["priority"]),
        "attempt_count": int(row["attempt_count"]),
        "payload": json.loads(row["payload_json"] or "{}"),
    }


def _mark_failed_if_active(
    home: Path, job_id: str, error_code: str, error_message: str
) -> None:
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE local_background_jobs
            SET status='failed',completed_at=?,heartbeat_at=?,pid=NULL,
                error_code=?,error_message=?
            WHERE job_id=? AND status IN ('queued','running')
            """,
            (_now(), _now(), error_code, error_message[-2000:], job_id),
        )


def _terminate_process_tree(process: subprocess.Popen[bytes] | None) -> bool:
    if process is None or process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return completed.returncode == 0
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        return True
    except (OSError, ProcessLookupError, subprocess.SubprocessError):
        return False
