from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .content_reviews import get_target_review
from .locking import runtime_lock
from .media import resolve_media_file
from .rubrics import DEFAULT_RUBRICS
from .score_results import build_score_result
from .session_io import load_session_file
from .session_manager import persist_session_atomic, start_session
from .storage import (
    connect,
    bind_media_asset,
    get_assessment_pack,
    get_idempotency_record,
    get_media_asset,
    get_question_for_grading,
    initialise_database,
    save_idempotency_record,
)


TERMINAL_STATUSES = {"submitted", "completed", "cancelled", "expired"}
OBJECTIVE_MODULES = {"reading", "listening"}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def start_assessment_run(
    home: Path,
    pack_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Freeze a verified pack and create one authoritative Session/run pair."""
    initialise_database(home)
    scope = f"assessment-run-start:{pack_id}"
    if idempotency_key:
        replay = get_idempotency_record(home, scope, idempotency_key)
        if replay:
            return get_assessment_run(home, str(replay["response"]["run_id"]))
    pack = get_assessment_pack(home, pack_id)
    if not pack:
        raise ValueError(f"Unknown assessment pack: {pack_id}")
    if pack.get("practice_mode") != "full_mock":
        raise ValueError("V0.9 Assessment Runner requires a full_mock pack")
    if pack.get("conformance_status") != "verified":
        raise ValueError("Only a verified Assessment Pack can start a full mock")
    local_review = get_target_review(
        home, "assessment_pack", pack_id, include_material=False
    )
    if local_review["local_review_status"] != "approved":
        raise ValueError("Assessment Pack requires an approved local content review")
    snapshot = _build_snapshot(home, pack)
    pack_hash = _hash_json(snapshot)
    structure = snapshot.get("structure") or {}
    time_limit = _time_limit_seconds(str(pack["module"]), structure)
    path = start_session(
        home,
        str(pack["module"]),
        assessment_pack_id=pack_id,
        practice_mode="full_mock",
        mode="timed-practice",
        time_limit_minutes=time_limit / 60 if time_limit else None,
        idempotency_key=f"assessment:{idempotency_key}" if idempotency_key else None,
    )
    session_id = path.stem
    run_id = f"AR-{uuid.uuid4().hex}"
    now = _now()
    sections = _sections(snapshot)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO assessment_runs(
              run_id,pack_id,session_id,module,practice_mode,status,revision,
              pack_hash,pack_snapshot_json,time_limit_seconds,elapsed_active_seconds,
              resumed_at,navigation_json,submission_json,media_state_json,
              score_result_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,'active',0,?,?,?,0,?,'{}','{}','{}','{}',?,?)
            """,
            (
                run_id,
                pack_id,
                session_id,
                pack["module"],
                pack["practice_mode"],
                pack_hash,
                json.dumps(snapshot, ensure_ascii=False),
                time_limit,
                now,
                now,
                now,
            ),
        )
        for index, section in enumerate(sections):
            conn.execute(
                """
                INSERT INTO section_runs(
                  run_id,section_key,order_index,status,revision,payload_json,updated_at
                ) VALUES(?,?,?,'not_started',0,?,?)
                """,
                (
                    run_id,
                    section["section_key"],
                    index,
                    json.dumps(section, ensure_ascii=False),
                    now,
                ),
            )
    with runtime_lock(home, f"session:{session_id}"):
        data = load_session_file(path)
        data["assessment_run_id"] = run_id
        data["status"] = "learner_working"
        data["revision"] = int(data.get("revision", 0)) + 1
        persist_session_atomic(home, path, data)
    for media_id in _snapshot_media_ids(snapshot):
        bind_media_asset(
            home,
            media_id,
            owner_type="session",
            owner_id=session_id,
            purpose="assessment_evidence",
        )
    if idempotency_key:
        save_idempotency_record(
            home, scope, idempotency_key, "assessment_run_start", {"run_id": run_id}
        )
    return get_assessment_run(home, run_id)


def get_assessment_run(
    home: Path,
    run_id: str,
    *,
    include_answers: bool = False,
) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM assessment_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown AssessmentRun: {run_id}")
        section_rows = conn.execute(
            "SELECT * FROM section_runs WHERE run_id=? ORDER BY order_index",
            (run_id,),
        ).fetchall()
        response_rows = conn.execute(
            "SELECT * FROM question_responses WHERE run_id=? ORDER BY updated_at",
            (run_id,),
        ).fetchall()
    result = dict(row)
    snapshot = json.loads(result.pop("pack_snapshot_json"))
    reveal = include_answers or result["status"] in {"submitted", "completed"}
    result["pack_snapshot"] = snapshot if reveal else _redact_answers(snapshot)
    result["navigation"] = json.loads(result.pop("navigation_json"))
    result["submission"] = json.loads(result.pop("submission_json"))
    result["media_state"] = json.loads(result.pop("media_state_json"))
    result["score_result"] = json.loads(result.pop("score_result_json"))
    result["sections"] = [
        {
            **dict(item),
            "payload": json.loads(item["payload_json"]),
        }
        for item in section_rows
    ]
    for item in result["sections"]:
        item.pop("payload_json", None)
    result["responses"] = [
        {
            "question_id": item["question_id"],
            "section_key": item["section_key"],
            "revision": int(item["revision"]),
            "response": json.loads(item["response_json"]),
            "flagged": bool(item["flagged"]),
            "answered_at": item["answered_at"],
            "updated_at": item["updated_at"],
        }
        for item in response_rows
    ]
    result["timer"] = _timer_state(result)
    return result


def list_assessment_runs(
    home: Path,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    sql = "SELECT run_id FROM assessment_runs"
    params: list[Any] = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        ids = [str(row["run_id"]) for row in conn.execute(sql, params).fetchall()]
    return [get_assessment_run(home, run_id) for run_id in ids]


def save_response(
    home: Path,
    run_id: str,
    question_id: str,
    response: dict[str, Any],
    *,
    section_key: str,
    expected_revision: int | None = None,
    flagged: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    scope = f"assessment-response:{run_id}:{question_id}"
    if idempotency_key:
        replay = get_idempotency_record(home, scope, idempotency_key)
        if replay:
            return replay["response"]
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run)
        _require_question(run, question_id, section_key)
        with connect(home) as conn:
            current = conn.execute(
                "SELECT revision FROM question_responses WHERE run_id=? AND question_id=?",
                (run_id, question_id),
            ).fetchone()
            revision = int(current["revision"]) if current else 0
            if expected_revision is not None and revision != expected_revision:
                raise ValueError(
                    f"Stale response revision: expected {expected_revision}, current {revision}"
                )
            next_revision = revision + 1
            now = _now()
            conn.execute(
                """
                INSERT INTO question_responses(
                  run_id,question_id,section_key,revision,response_json,flagged,
                  answered_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id,question_id) DO UPDATE SET
                  section_key=excluded.section_key,revision=excluded.revision,
                  response_json=excluded.response_json,flagged=excluded.flagged,
                  answered_at=excluded.answered_at,updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    question_id,
                    section_key,
                    next_revision,
                    json.dumps(response, ensure_ascii=False),
                    int(flagged),
                    now if _has_answer(response) else None,
                    now,
                ),
            )
            conn.execute(
                "UPDATE assessment_runs SET revision=revision+1,updated_at=? WHERE run_id=?",
                (now, run_id),
            )
            conn.execute(
                """
                UPDATE section_runs SET
                  status=CASE WHEN status='not_started' THEN 'active' ELSE status END,
                  revision=revision+1,started_at=COALESCE(started_at,?),updated_at=?
                WHERE run_id=? AND section_key=?
                """,
                (now, now, run_id, section_key),
            )
    result = {
        "run_id": run_id,
        "question_id": question_id,
        "section_key": section_key,
        "revision": next_revision,
        "response": response,
        "flagged": flagged,
        "updated_at": now,
    }
    if idempotency_key:
        save_idempotency_record(
            home, scope, idempotency_key, "assessment_response_save", result
        )
    return result


def save_navigation(
    home: Path,
    run_id: str,
    navigation: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run, allow_paused=True, allow_expired=True)
        if expected_revision is not None and int(run["revision"]) != expected_revision:
            raise ValueError(
                f"Stale AssessmentRun revision: expected {expected_revision}, current {run['revision']}"
            )
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs
                SET navigation_json=?,revision=revision+1,updated_at=?
                WHERE run_id=?
                """,
                (json.dumps(navigation, ensure_ascii=False), now, run_id),
            )
    return get_assessment_run(home, run_id)


def pause_assessment_run(home: Path, run_id: str) -> dict[str, Any]:
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        if run["practice_mode"] == "full_mock":
            raise ValueError("A strict full mock cannot be paused")
        if run["status"] != "active":
            raise ValueError("Only an active AssessmentRun can be paused")
        elapsed = _elapsed_seconds(run)
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET status='paused',elapsed_active_seconds=?,
                resumed_at=NULL,paused_at=?,revision=revision+1,updated_at=?
                WHERE run_id=?
                """,
                (elapsed, now, now, run_id),
            )
    return get_assessment_run(home, run_id)


def resume_assessment_run(home: Path, run_id: str) -> dict[str, Any]:
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        if run["status"] != "paused":
            raise ValueError("Only a paused AssessmentRun can be resumed")
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET status='active',resumed_at=?,paused_at=NULL,
                revision=revision+1,updated_at=? WHERE run_id=?
                """,
                (now, now, run_id),
            )
    return get_assessment_run(home, run_id)


def start_audio_playback(
    home: Path,
    run_id: str,
    media_id: str,
) -> dict[str, Any]:
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run)
        if run["module"] != "listening":
            raise ValueError("Audio playback state only applies to Listening")
        allowed = {
            str(part.get("audio_media_id"))
            for part in (run["pack_snapshot"].get("structure") or {}).get("parts", [])
        }
        if media_id not in allowed:
            raise ValueError("Audio is not part of this frozen Assessment Pack")
        asset, _ = resolve_media_file(home, media_id)
        if asset["media_type"] != "audio":
            raise ValueError("Registered Listening media must be audio")
        state = dict(run["media_state"])
        current = dict(state.get(media_id) or {})
        if int(current.get("play_count", 0)) >= 1:
            raise ValueError("IELTS Listening audio may only be started once")
        current.update(
            {
                "play_count": 1,
                "started_at": _now(),
                "position_seconds": 0,
                "completed": False,
            }
        )
        state[media_id] = current
        _update_media_state(home, run_id, state)
        lease = _create_audio_playback_lease(home, run_id, media_id)
    result = get_assessment_run(home, run_id)
    result["playback_lease"] = lease
    return result


def renew_audio_playback_lease(
    home: Path,
    run_id: str,
    media_id: str,
) -> dict[str, Any]:
    """Renew transport access without counting a second IELTS playback."""
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run)
        if run["module"] != "listening":
            raise ValueError("Audio playback leases only apply to Listening")
        current = dict((run.get("media_state") or {}).get(media_id) or {})
        if int(current.get("play_count", 0)) != 1:
            raise ValueError("Audio playback has not been started")
        if current.get("completed"):
            raise ValueError("Completed audio playback cannot be renewed")
        lease = _create_audio_playback_lease(home, run_id, media_id)
    result = get_assessment_run(home, run_id)
    result["playback_lease"] = lease
    return result


def validate_audio_playback_lease(
    home: Path,
    run_id: str,
    media_id: str,
    token: str,
) -> dict[str, Any]:
    if not token or len(token) > 512:
        raise ValueError("A valid audio playback lease is required")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _now()
    with connect(home) as conn:
        row = conn.execute(
            """
            SELECT l.*,a.status AS run_status
            FROM audio_playback_leases l
            JOIN assessment_runs a ON a.run_id=l.run_id
            WHERE l.lease_hash=? AND l.run_id=? AND l.media_id=?
            """,
            (digest, run_id, media_id),
        ).fetchone()
        if (
            not row
            or row["revoked_at"] is not None
            or row["run_status"] != "active"
            or datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            <= _now_dt()
        ):
            raise ValueError("Audio playback lease is missing, expired, or revoked")
        conn.execute(
            """
            UPDATE audio_playback_leases SET last_accessed_at=?
            WHERE lease_hash=?
            """,
            (now, digest),
        )
    return {
        "run_id": run_id,
        "media_id": media_id,
        "expires_at": row["expires_at"],
    }


def update_audio_playback(
    home: Path,
    run_id: str,
    media_id: str,
    *,
    position_seconds: float,
    completed: bool = False,
) -> dict[str, Any]:
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run)
        state = dict(run["media_state"])
        current = dict(state.get(media_id) or {})
        if int(current.get("play_count", 0)) != 1:
            raise ValueError("Audio playback has not been authorised")
        previous = float(current.get("position_seconds", 0))
        if float(position_seconds) + 0.5 < previous:
            raise ValueError("Audio playback position cannot move backwards")
        asset = get_media_asset(home, media_id) or {}
        duration = float((asset.get("metadata") or {}).get("duration_seconds") or 0)
        if duration and float(position_seconds) > duration + 1:
            raise ValueError("Audio playback position exceeds registered duration")
        current["position_seconds"] = float(position_seconds)
        current["completed"] = bool(completed)
        current["updated_at"] = _now()
        state[media_id] = current
        _update_media_state(home, run_id, state)
        if completed:
            _revoke_audio_playback_leases(home, run_id, media_id)
    return get_assessment_run(home, run_id)


def submit_assessment_run(
    home: Path,
    run_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    scope = f"assessment-submit:{run_id}"
    if idempotency_key:
        replay = get_idempotency_record(home, scope, idempotency_key)
        if replay:
            return get_assessment_run(home, run_id)
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run, allow_paused=True, allow_expired=True)
        result = _score_submission(run)
        now = _now()
        final_status = "completed" if run["module"] in OBJECTIVE_MODULES else "reviewing"
        submission = {
            "submitted_at": now,
            "answered": sum(1 for item in run["responses"] if _has_answer(item["response"])),
            "total": len(run["pack_snapshot"].get("question_ids") or []),
            "unanswered_question_ids": _unanswered_ids(run),
        }
        elapsed = _elapsed_seconds(run)
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET status=?,elapsed_active_seconds=?,
                resumed_at=NULL,submitted_at=?,submission_json=?,score_result_json=?,
                revision=revision+1,updated_at=? WHERE run_id=?
                """,
                (
                    final_status,
                    elapsed,
                    now,
                    json.dumps(submission, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    now,
                    run_id,
                ),
            )
            conn.execute(
                """
                UPDATE section_runs SET status='submitted',submitted_at=?,updated_at=?,
                revision=revision+1 WHERE run_id=?
                """,
                (now, now, run_id),
            )
            conn.execute(
                """
                UPDATE audio_playback_leases SET revoked_at=?
                WHERE run_id=? AND revoked_at IS NULL
                """,
                (now, run_id),
            )
        _finalise_session(home, run, result, final_status, now)
    if idempotency_key:
        save_idempotency_record(
            home, scope, idempotency_key, "assessment_submit", {"run_id": run_id}
        )
    return get_assessment_run(home, run_id)


def record_writing_score(
    home: Path,
    run_id: str,
    *,
    task1: dict[str, Any],
    task2: dict[str, Any],
    expected_revision: int | None = None,
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate two evidence-based task reviews; Task 2 weight lives in Runtime."""
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        if run["module"] != "writing" or run["status"] != "reviewing":
            raise ValueError("Writing scores require a submitted Writing AssessmentRun")
        task1_question = next(
            (item for item in run["pack_snapshot"]["questions"] if item.get("task") == "task1"),
            {},
        )
        if not (
            task1_question.get("media_id")
            or task1_question.get("media_ids")
            or task1_question.get("task_data")
        ):
            raise ValueError("Task 1 visual evidence is missing; complete TA scoring is not allowed")
        band1 = _validate_task_score(task1, "TA")
        band2 = _validate_task_score(task2, "TR")
        overall = _round_half((Decimal(str(band1)) + Decimal(str(band2)) * 2) / 3)
        result = {
            "raw_score": None,
            "score_kind": "ai_training_estimate",
            "band": overall,
            "band_range": None,
            "confidence": _lower_confidence(task1.get("confidence"), task2.get("confidence")),
            "rubric_version": task2.get("rubric_version") or task1.get("rubric_version"),
            "conversion_source": None,
            "evidence_scope": "verified_full_writing_mock",
            "evaluator_model": task2.get("evaluator_model") or task1.get("evaluator_model"),
            "calibration_status": task2.get("calibration_status")
            or task1.get("calibration_status")
            or "unknown",
            "task1": {**task1, "band": band1, "weight": 1},
            "task2": {**task2, "band": band2, "weight": 2},
            "aggregation": "(Task 1 + 2 × Task 2) / 3",
        }
        result = {
            **result,
            **build_score_result(
                {
                    **result,
                    "module": "writing",
                    "status": "completed",
                    "practice_mode": "full_mock",
                    "conformance_status": "verified",
                    "writing_task_results": {
                        "task1": result["task1"],
                        "task2": result["task2"],
                    },
                }
            ),
        }
        _complete_review_session(
            home,
            run,
            result,
            expected_revision=expected_revision,
            review_result=review_result,
        )
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET status='completed',score_result_json=?,
                revision=revision+1,updated_at=? WHERE run_id=?
                """,
                (json.dumps(result, ensure_ascii=False), now, run_id),
            )
    return get_assessment_run(home, run_id)


def persist_writing_mock_review(
    home: Path,
    review: dict[str, Any],
    *,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
    agent_request: dict[str, Any] | None = None,
    evaluator_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a two-task review without trusting Agent-side aggregation."""
    run_id = str(review["assessment_run_id"])
    session_id = str(review["session_id"])
    if review.get("score_kind") != "ai_training_estimate":
        raise ValueError("Only a real AI training estimate can enter learning records")
    scope = f"writing-mock-review:{run_id}"
    if idempotency_key:
        replay = get_idempotency_record(home, scope, idempotency_key)
        if replay:
            return get_assessment_run(home, run_id)
    run = _private_run(home, run_id)
    if run["module"] != "writing" or run["status"] != "reviewing":
        raise ValueError("Writing mock review requires a submitted Writing AssessmentRun")
    if str(run["session_id"]) != session_id:
        raise ValueError("Writing mock review must use the AssessmentRun's Session")
    _validate_agent_visual_evidence(run, review, agent_request or {})
    identity = evaluator_identity or {}
    rubric_version = str((review.get("rubric") or {}).get("version") or "")

    def task_payload(task_name: str) -> dict[str, Any]:
        source = review[task_name]
        evidence = [
            text
            for criterion in source["criteria"]
            for text in [
                *(criterion.get("evidence_support") or []),
                *(criterion.get("evidence_limit") or []),
            ]
        ]
        return {
            "criteria": {
                str(item["criterion"]): item.get("score")
                for item in source["criteria"]
            },
            "evidence": evidence,
            "criterion_evidence": source["criteria"],
            "priority_issues": source.get("priority_issues") or [],
            "confidence": source["confidence"],
            "evaluator_model": identity.get("model_display_name")
            or identity.get("model_id"),
            "evaluator_identity": identity,
            "calibration_status": identity.get("calibration_status") or "unknown",
            "rubric_version": rubric_version,
        }

    task1 = task_payload("task1")
    task2 = task_payload("task2")
    if review["visual_evidence"]["status"] == "insufficient":
        partial = _persist_partial_writing_mock_review(
            home,
            run,
            review,
            task1=task1,
            task2=task2,
            expected_revision=expected_revision,
        )
        if idempotency_key:
            save_idempotency_record(
                home,
                scope,
                idempotency_key,
                "writing_mock_review_partial",
                {"run_id": run_id},
            )
        return partial
    completed = record_writing_score(
        home,
        run_id,
        task1=task1,
        task2=task2,
        expected_revision=expected_revision,
        review_result=review,
    )
    if idempotency_key:
        save_idempotency_record(
            home,
            scope,
            idempotency_key,
            "writing_mock_review_complete",
            {"run_id": run_id},
        )
    return completed


def bind_speaking_result(
    home: Path,
    run_id: str,
    session_result: dict[str, Any],
) -> dict[str, Any]:
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        if run["module"] != "speaking":
            raise ValueError("Speaking result can only bind to a Speaking AssessmentRun")
        if run["status"] != "reviewing":
            raise ValueError("Speaking result requires a submitted Speaking AssessmentRun")
        if str(session_result.get("session_id")) != str(run["session_id"]):
            raise ValueError("Speaking result must use the AssessmentRun's authoritative Session")
        report = session_result.get("speaking_report") or {}
        evaluation = session_result.get("speaking_evaluation") or {}
        evidence = set(report.get("evidence_types") or []) | set(
            evaluation.get("evidence_types") or []
        )
        band = session_result.get("band")
        pronunciation_sources = {
            str(item.get("evidence_source"))
            for item in evaluation.get("criteria") or []
            if item.get("criterion") == "PRON"
        }
        if band is not None and not (
            {"audio", "voice_model_observation"} & evidence
            or pronunciation_sources
            & {"audio", "voice_model_observation", "mixed"}
        ):
            raise ValueError("A Speaking overall estimate requires audio-based pronunciation evidence")
        result = {
            "raw_score": None,
            "score_kind": session_result.get("score_kind") or "partial_profile",
            "band": band,
            "band_range": session_result.get("band_range"),
            "confidence": session_result.get("score_confidence"),
            "rubric_version": (session_result.get("rubric") or {}).get("version"),
            "conversion_source": None,
            "evidence_scope": sorted(evidence) or ["text_only"],
            "evaluator_model": session_result.get("evaluator_model"),
            "calibration_status": session_result.get("calibration_status") or "unknown",
            "pronunciation_evidence_sufficient": bool(
                {"audio", "voice_model_observation"} & evidence
                or pronunciation_sources
                & {"audio", "voice_model_observation", "mixed"}
            ),
        }
        result = {
            **result,
            **build_score_result(
                {
                    **session_result,
                    **result,
                    "module": "speaking",
                    "status": "completed",
                    "practice_mode": run["practice_mode"],
                    "conformance_status": run["pack_snapshot"].get(
                        "conformance_status"
                    ),
                }
            ),
        }
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET status='completed',score_result_json=?,
                submitted_at=COALESCE(submitted_at,?),resumed_at=NULL,
                revision=revision+1,updated_at=? WHERE run_id=?
                """,
                (json.dumps(result, ensure_ascii=False), now, now, run_id),
            )
        if session_result.get("speaking_evaluation"):
            path = home / "sessions" / "speaking" / f"{run['session_id']}.md"
            with runtime_lock(home, f"session:{run['session_id']}"):
                data = load_session_file(path)
                data["status"] = "completed"
                data["score_result"] = result
                data["revision"] = int(data.get("revision", 0)) + 1
                persist_session_atomic(home, path, data)
    return get_assessment_run(home, run_id)


def register_speaking_source_report(
    home: Path,
    run_id: str,
    session_result: dict[str, Any],
) -> dict[str, Any]:
    """Mark external Voice/Live evidence as imported without treating it as local scoring."""
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        if run["module"] != "speaking" or run["status"] != "reviewing":
            raise ValueError(
                "Speaking source report requires a submitted Speaking AssessmentRun"
            )
        if str(session_result.get("session_id")) != str(run["session_id"]):
            raise ValueError(
                "Speaking source report must use the AssessmentRun's Session"
            )
        navigation = dict(run.get("navigation") or {})
        navigation["speaking_source_report"] = {
            "status": "imported",
            "imported_at": _now(),
            "evidence_types": (
                session_result.get("speaking_report") or {}
            ).get("evidence_types")
            or [],
        }
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET navigation_json=?,revision=revision+1,
                updated_at=? WHERE run_id=?
                """,
                (
                    json.dumps(navigation, ensure_ascii=False),
                    now,
                    run_id,
                ),
            )
    return get_assessment_run(home, run_id)


def create_speaking_handoff(
    home: Path,
    run_id: str,
    *,
    provider: str = "external_voice_live",
) -> dict[str, Any]:
    """Create an external Voice/Live package on the existing authoritative Session."""
    with runtime_lock(home, f"assessment:{run_id}"):
        run = _private_run(home, run_id)
        _require_writable(run)
        if run["module"] != "speaking":
            raise ValueError("Speaking handoff requires a Speaking AssessmentRun")
        questions = run["pack_snapshot"].get("questions") or []
        lines = [
            "You are hosting an IELTS Academic Speaking full mock.",
            "",
            "NON-NEGOTIABLE MOCK RULES",
            "1. Ask one supplied question at a time and wait for the spoken answer.",
            "2. Do not correct, hint, paraphrase, evaluate, or give feedback during the mock.",
            "3. Keep Part 1, Part 2 and Part 3 in the supplied order.",
            "4. Give exactly one minute of Part 2 preparation and allow up to two minutes to speak.",
            "5. Target 11-14 minutes overall; announce timing only if your interface can measure it.",
            "6. After the final question, return a transcript and distinguish audio observations from text inference.",
            "7. Do not claim a Pronunciation score without direct audio observation.",
            "",
            f"AssessmentRun: {run_id}",
            f"Authoritative Session: {run['session_id']}",
            f"External host: {provider}",
            "",
            "QUESTIONS",
        ]
        current_part = None
        public_questions = []
        for question in questions:
            part = str(question.get("part"))
            if part != current_part:
                lines.extend(["", f"Part {part}"])
                current_part = part
            lines.append(f"- {question['content']}")
            public_questions.append(
                {
                    "question_id": question["question_id"],
                    "part": question.get("part"),
                    "topic": question.get("topic"),
                    "content": question["content"],
                }
            )
        package = {
            "assessment_run_id": run_id,
            "session_id": run["session_id"],
            "provider": provider,
            "mode": "full_mock",
            "questions": public_questions,
            "prompt": "\n".join(lines),
            "created_at": _now(),
        }
        path = home / "sessions" / "speaking" / f"{run['session_id']}.md"
        with runtime_lock(home, f"session:{run['session_id']}"):
            data = load_session_file(path)
            data["speaking_handoff"] = package
            data["status"] = "learner_working"
            data["revision"] = int(data.get("revision", 0)) + 1
            persist_session_atomic(home, path, data)
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET navigation_json=?,revision=revision+1,
                updated_at=? WHERE run_id=?
                """,
                (
                    json.dumps(
                        {"speaking_handoff": {"provider": provider, "created_at": now}},
                        ensure_ascii=False,
                    ),
                    now,
                    run_id,
                ),
            )
    return package


def _build_snapshot(home: Path, pack: dict[str, Any]) -> dict[str, Any]:
    questions = []
    for question_id in pack.get("question_ids") or []:
        question = get_question_for_grading(home, str(question_id))
        if not question:
            raise ValueError(f"Assessment Pack references unknown question: {question_id}")
        questions.append(question)
    passages: dict[str, dict[str, Any]] = {}
    passage_ids = list(pack.get("passage_ids") or [])
    if passage_ids:
        with connect(home) as conn:
            for passage_id in passage_ids:
                row = conn.execute(
                    "SELECT payload_json FROM question_passages WHERE passage_id=?",
                    (passage_id,),
                ).fetchone()
                if not row:
                    raise ValueError(f"Assessment Pack references unknown passage: {passage_id}")
                passage = json.loads(row["payload_json"])
                if isinstance(passage.get("body"), list):
                    passage["body"] = "\n\n".join(
                        str(value) for value in passage["body"]
                    )
                passages[str(passage_id)] = passage
    if pack.get("module") == "listening":
        for part in (pack.get("structure") or {}).get("parts", []):
            media_id = str(part.get("audio_media_id") or "")
            if not media_id:
                raise ValueError("Every Listening part requires audio")
            asset, _ = resolve_media_file(home, media_id)
            if asset["media_type"] != "audio":
                raise ValueError("Listening full mock media must be registered audio")
    if pack.get("module") == "writing":
        task1 = next(
            (item for item in questions if item.get("task") == "task1"),
            {},
        )
        for media_id in _question_media_ids(task1):
            asset, _ = resolve_media_file(home, media_id)
            if asset["media_type"] != "image":
                raise ValueError("Writing Task 1 media must be a registered image")
    return {**pack, "questions": questions, "passages": passages}


def _question_media_ids(question: dict[str, Any]) -> list[str]:
    values = []
    if question.get("media_id"):
        values.append(str(question["media_id"]))
    for value in question.get("media_ids") or []:
        values.append(str(value))
    return list(dict.fromkeys(values))


def _snapshot_media_ids(snapshot: dict[str, Any]) -> list[str]:
    values = [
        media_id
        for question in snapshot.get("questions") or []
        for media_id in _question_media_ids(question)
    ]
    for part in (snapshot.get("structure") or {}).get("parts", []):
        if part.get("audio_media_id"):
            values.append(str(part["audio_media_id"]))
    return list(dict.fromkeys(values))


def _sections(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    module = snapshot["module"]
    if module == "reading":
        return [
            {"section_key": str(item["passage_id"]), **item}
            for item in snapshot["structure"]["passages"]
        ]
    if module == "listening":
        return [
            {"section_key": f"part-{item['part']}", **item}
            for item in snapshot["structure"]["parts"]
        ]
    if module == "writing":
        return [
            {"section_key": str(item["task"]), **item}
            for item in snapshot["structure"]["tasks"]
        ]
    return [
        {"section_key": f"part-{item['part']}", **item}
        for item in snapshot["structure"]["parts"]
    ]


def _time_limit_seconds(module: str, structure: dict[str, Any]) -> int | None:
    if structure.get("time_limit_minutes"):
        return int(float(structure["time_limit_minutes"]) * 60)
    if module == "listening":
        media_seconds = 0.0
        return None if not media_seconds else int(media_seconds)
    if module == "speaking":
        # Voice/Live owns the spoken mock clock. Starting the local handoff must not
        # consume the learner's 11-14 minute interview window.
        return None
    return None


def _private_run(home: Path, run_id: str) -> dict[str, Any]:
    return get_assessment_run(home, run_id, include_answers=True)


def _require_writable(
    run: dict[str, Any],
    *,
    allow_paused: bool = False,
    allow_expired: bool = False,
) -> None:
    allowed = {"active"}
    if allow_paused:
        allowed.add("paused")
    if run["status"] not in allowed:
        raise ValueError(f"AssessmentRun is not writable in status {run['status']}")
    timer = run["timer"]
    if timer.get("expired") and not allow_expired:
        raise ValueError("AssessmentRun time limit has expired")


def _require_question(run: dict[str, Any], question_id: str, section_key: str) -> None:
    question = next(
        (
            item
            for item in run["pack_snapshot"].get("questions") or []
            if str(item.get("question_id")) == question_id
        ),
        None,
    )
    if not question:
        raise ValueError("Question is not part of the frozen Assessment Pack")
    expected = _question_section(run["module"], question)
    if expected != section_key:
        raise ValueError(f"Question belongs to section {expected}, not {section_key}")


def _question_section(module: str, question: dict[str, Any]) -> str:
    if module == "reading":
        return str(question.get("passage_id"))
    if module in {"listening", "speaking"}:
        return f"part-{question.get('part')}"
    return str(question.get("task"))


def _timer_state(run: dict[str, Any]) -> dict[str, Any]:
    limit = run.get("time_limit_seconds")
    elapsed = _elapsed_seconds(run)
    remaining = max(0, int(float(limit) - elapsed)) if limit is not None else None
    return {
        "authoritative_at": _now(),
        "time_limit_seconds": limit,
        "elapsed_active_seconds": round(elapsed, 3),
        "remaining_seconds": remaining,
        "running": run["status"] == "active",
        "pause_allowed": run["practice_mode"] != "full_mock",
        "expired": remaining == 0 if remaining is not None else False,
    }


def _elapsed_seconds(run: dict[str, Any]) -> float:
    elapsed = float(run.get("elapsed_active_seconds") or 0)
    if run.get("status") == "active" and run.get("resumed_at"):
        resumed = datetime.fromisoformat(str(run["resumed_at"]).replace("Z", "+00:00"))
        elapsed += max(0.0, (_now_dt() - resumed).total_seconds())
    return elapsed


def _update_media_state(home: Path, run_id: str, state: dict[str, Any]) -> None:
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE assessment_runs SET media_state_json=?,revision=revision+1,updated_at=?
            WHERE run_id=?
            """,
            (json.dumps(state, ensure_ascii=False), now, run_id),
        )


def _create_audio_playback_lease(
    home: Path,
    run_id: str,
    media_id: str,
) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    created = _now_dt()
    expires = created + timedelta(minutes=20)
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE audio_playback_leases SET revoked_at=?
            WHERE run_id=? AND media_id=? AND revoked_at IS NULL
            """,
            (created.isoformat(), run_id, media_id),
        )
        conn.execute(
            """
            INSERT INTO audio_playback_leases(
              lease_hash,run_id,media_id,created_at,expires_at
            ) VALUES(?,?,?,?,?)
            """,
            (
                digest,
                run_id,
                media_id,
                created.isoformat(),
                expires.isoformat(),
            ),
        )
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "run_id": run_id,
        "media_id": media_id,
    }


def _revoke_audio_playback_leases(
    home: Path,
    run_id: str,
    media_id: str | None = None,
) -> None:
    sql = (
        "UPDATE audio_playback_leases SET revoked_at=? "
        "WHERE run_id=? AND revoked_at IS NULL"
    )
    params: list[Any] = [_now(), run_id]
    if media_id is not None:
        sql += " AND media_id=?"
        params.append(media_id)
    with connect(home) as conn:
        conn.execute(sql, params)


def _score_submission(run: dict[str, Any]) -> dict[str, Any]:
    if run["module"] not in OBJECTIVE_MODULES:
        return {
            "score_kind": "pending_evidence_review",
            "eligible_for_progress": False,
        }
    responses = {
        str(item["question_id"]): item["response"] for item in run["responses"]
    }
    graded = []
    for question in run["pack_snapshot"].get("questions") or []:
        question_id = str(question["question_id"])
        response = responses.get(question_id, {})
        graded.append(_grade_objective(question, response))
    _apply_option_reuse_constraints(
        run["pack_snapshot"].get("questions") or [],
        graded,
    )
    correct = sum(1 for item in graded if item["is_correct"])
    total = len(graded)
    score: dict[str, Any] = {
        "raw_score": correct,
        "total": total,
        "score_kind": "answer_key_estimate",
        "answer_key_source": "frozen-reviewed-pack",
        "confidence": "high",
        "evidence_scope": f"verified_full_{run['module']}_mock",
        "evaluator_model": None,
        "calibration_status": "not_applicable",
        "question_results": graded,
    }
    conversion = run["pack_snapshot"].get("band_conversion")
    source = run["pack_snapshot"].get("band_conversion_source")
    if total == 40 and conversion and source:
        score["band"] = _convert_band(correct, conversion)
        score["band_conversion_source"] = source
    admission = build_score_result(
        {
            **score,
            "module": run["module"],
            "status": "completed",
            "practice_mode": run["practice_mode"],
            "conformance_status": run["pack_snapshot"].get("conformance_status"),
            "band_conversion_source": score.get("band_conversion_source"),
        }
    )
    return {**score, **admission}


def _grade_objective(
    question: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    submitted = response.get("answer")
    correct = question.get("correct_answer")
    accepted = question.get("accepted_variants") or question.get("accepted_answers") or []
    constraints = question.get("answer_constraints") or {}
    candidates = [correct, *(accepted if isinstance(accepted, list) else [accepted])]
    word_limit = constraints.get("word_limit") or question.get("word_limit")
    word_limit_ok = not word_limit or _word_count(submitted) <= int(word_limit)
    required_count = constraints.get("answer_count") or question.get("selection_count")
    submitted_count = len(submitted) if isinstance(submitted, list) else (1 if str(submitted or "").strip() else 0)
    selection_count_ok = required_count is None or submitted_count == int(required_count)
    order_matters = bool(constraints.get("order_matters"))
    normalised_submitted = _normalise_answer(submitted, order_matters=order_matters)
    matched = any(
        normalised_submitted == _normalise_answer(item, order_matters=order_matters)
        for item in candidates
    )
    return {
        "question_id": question["question_id"],
        "question_number": question.get("question_number"),
        "question_type": question.get("question_type"),
        "user_answer": submitted,
        "correct_answer": correct,
        "accepted_variants": accepted,
        "is_correct": bool(word_limit_ok and selection_count_ok and matched),
        "word_limit_ok": word_limit_ok,
        "selection_count_ok": selection_count_ok,
        "evidence_location": question.get("evidence_location"),
        "explanation": question.get("explanation"),
        "transcript_timestamp": question.get("transcript_timestamp"),
        "distractor_explanation": question.get("distractor_explanation"),
    }


def _apply_option_reuse_constraints(
    questions: list[dict[str, Any]],
    graded: list[dict[str, Any]],
) -> None:
    """Enforce shared Matching-bank reuse instructions across indexed questions."""
    groups: dict[str, list[int]] = {}
    for index, question in enumerate(questions):
        constraints = question.get("answer_constraints") or {}
        if constraints.get("option_reuse_allowed") is not False:
            continue
        group_id = (
            question.get("option_bank_id")
            or question.get("matching_group_id")
            or constraints.get("option_bank_id")
        )
        if group_id:
            groups.setdefault(str(group_id), []).append(index)
    for indexes in groups.values():
        selected: dict[str, list[int]] = {}
        for index in indexes:
            answer = graded[index].get("user_answer")
            if answer is None or answer == "" or answer == []:
                continue
            key = _normalise_answer(answer, order_matters=True)
            selected.setdefault(key, []).append(index)
        for duplicate_indexes in selected.values():
            if len(duplicate_indexes) < 2:
                continue
            for index in duplicate_indexes:
                graded[index]["is_correct"] = False
                graded[index]["constraint_violation"] = "option_reuse_not_allowed"


def _normalise_answer(value: Any, *, order_matters: bool) -> str:
    if isinstance(value, list):
        rows = [_normalise_answer(item, order_matters=True) for item in value]
        return "|".join(rows if order_matters else sorted(rows))
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"\s+", " ", text.strip().casefold())
    return text


def _word_count(value: Any) -> int:
    if isinstance(value, list):
        return sum(_word_count(item) for item in value)
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", str(value or "")))


def _convert_band(raw: int, conversion: Any) -> float:
    if isinstance(conversion, dict):
        if str(raw) not in conversion:
            raise ValueError("Band conversion table does not cover the submitted raw score")
        return float(conversion[str(raw)])
    if isinstance(conversion, list):
        for row in conversion:
            if int(row.get("min", row.get("raw_score", -1))) <= raw <= int(
                row.get("max", row.get("raw_score", -1))
            ):
                return float(row["band"])
    raise ValueError("Unsupported band conversion table")


def _unanswered_ids(run: dict[str, Any]) -> list[str]:
    answered = {
        str(item["question_id"])
        for item in run["responses"]
        if _has_answer(item["response"])
    }
    return [
        str(value)
        for value in run["pack_snapshot"].get("question_ids") or []
        if str(value) not in answered
    ]


def _finalise_session(
    home: Path,
    run: dict[str, Any],
    result: dict[str, Any],
    final_status: str,
    submitted_at: str,
) -> None:
    path = home / "sessions" / run["module"] / f"{run['session_id']}.md"
    with runtime_lock(home, f"session:{run['session_id']}"):
        data = load_session_file(path)
        attempts = (result.get("question_results") or []) if run["module"] in OBJECTIVE_MODULES else []
        data["questions"] = attempts
        data["submitted_at"] = submitted_at
        data["duration_minutes"] = round(_elapsed_seconds(run) / 60, 2)
        data["assessment_run_id"] = run["run_id"]
        data["score_result"] = {
            key: value
            for key, value in result.items()
            if key
            in {
                "raw_score",
                "total",
                "band",
                "band_range",
                "score_kind",
                "confidence",
                "rubric_version",
                "conversion_source",
                "evidence_scope",
                "evaluator_model",
                "calibration_status",
                "eligible_for_progress",
                "eligibility_reason",
            }
        }
        data["status"] = "completed" if final_status == "completed" else "awaiting_feedback"
        if attempts:
            data["raw_score"] = result["raw_score"]
            data["score"] = {"correct": result["raw_score"], "total": result["total"]}
            data["score_kind"] = result["score_kind"]
            data["answer_key_source"] = result["answer_key_source"]
            data["answer_revealed_at"] = submitted_at
            if result.get("band") is not None:
                data["band"] = result["band"]
                data["band_conversion_source"] = result["band_conversion_source"]
        elif run["module"] == "writing":
            versions = []
            by_id = {
                str(item["question_id"]): item["response"] for item in run["responses"]
            }
            for question in run["pack_snapshot"].get("questions") or []:
                text = str((by_id.get(str(question["question_id"])) or {}).get("text") or "")
                versions.append(
                    {
                        "label": f"{question.get('task')}-v1",
                        "task": question.get("task"),
                        "content": text,
                        "word_count": _word_count(text),
                    }
                )
            data["versions"] = versions
        data["revision"] = int(data.get("revision", 0)) + 1
        persist_session_atomic(home, path, data)


def _complete_review_session(
    home: Path,
    run: dict[str, Any],
    result: dict[str, Any],
    *,
    expected_revision: int | None = None,
    review_result: dict[str, Any] | None = None,
) -> None:
    path = home / "sessions" / run["module"] / f"{run['session_id']}.md"
    with runtime_lock(home, f"session:{run['session_id']}"):
        data = load_session_file(path)
        current_revision = int(data.get("revision", 0))
        if (
            expected_revision is not None
            and current_revision != int(expected_revision)
        ):
            error = ValueError(
                f"Stale Session revision: expected {expected_revision}, "
                f"found {current_revision}"
            )
            error.code = "SESSION_REVISION_CONFLICT"  # type: ignore[attr-defined]
            raise error
        data["status"] = "completed"
        data["band"] = result["band"]
        data["score_kind"] = result["score_kind"]
        data["score_confidence"] = result["confidence"]
        data["rubric"] = next(
            dict(item) for item in DEFAULT_RUBRICS if item["module"] == "writing"
        )
        data["writing_task_results"] = {
            "task1": result["task1"],
            "task2": result["task2"],
        }
        data["criterion_scores"] = [
            {
                "criterion": criterion,
                "version": f"{task_name}-v1",
                "score": score,
                "confidence": task_result.get("confidence"),
                "evidence": task_result.get("evidence"),
                "assessment_role": "local_rubric",
                "evidence_source": "text",
            }
            for task_name, task_result in (
                ("task1", result["task1"]),
                ("task2", result["task2"]),
            )
            for criterion, score in (task_result.get("criteria") or {}).items()
        ]
        data["writing_assessment_result"] = result
        if review_result is not None:
            data["writing_mock_review"] = review_result
        data["score_result"] = {
            key: value
            for key, value in result.items()
            if key
            in {
                "raw_score",
                "total",
                "band",
                "band_range",
                "score_kind",
                "confidence",
                "rubric_version",
                "conversion_source",
                "evidence_scope",
                "evaluator_model",
                "calibration_status",
                "eligible_for_progress",
                "eligibility_reason",
            }
        }
        data["revision"] = int(data.get("revision", 0)) + 1
        persist_session_atomic(home, path, data)


def _persist_partial_writing_mock_review(
    home: Path,
    run: dict[str, Any],
    review: dict[str, Any],
    *,
    task1: dict[str, Any],
    task2: dict[str, Any],
    expected_revision: int | None,
) -> dict[str, Any]:
    result = {
        "raw_score": None,
        "score_kind": "partial_profile",
        "band": None,
        "band_range": None,
        "confidence": "low",
        "rubric_version": str((review.get("rubric") or {}).get("version") or ""),
        "conversion_source": None,
        "evidence_scope": "writing_mock_visual_evidence_insufficient",
        "evaluator_model": task2.get("evaluator_model"),
        "calibration_status": task2.get("calibration_status") or "unknown",
        "eligible_for_progress": False,
        "eligibility_reason": "task1_visual_evidence_insufficient",
        "task1": {**task1, "band": None, "weight": 1},
        "task2": {
            **task2,
            "band": _validate_task_score(task2, "TR"),
            "weight": 2,
        },
        "aggregation": None,
        "visual_evidence": review["visual_evidence"],
    }
    path = home / "sessions" / "writing" / f"{run['session_id']}.md"
    with runtime_lock(home, f"assessment:{run['run_id']}"):
        fresh = _private_run(home, str(run["run_id"]))
        if fresh["status"] != "reviewing":
            raise ValueError("Writing AssessmentRun is no longer awaiting review")
        with runtime_lock(home, f"session:{run['session_id']}"):
            data = load_session_file(path)
            current_revision = int(data.get("revision", 0))
            if (
                expected_revision is not None
                and current_revision != int(expected_revision)
            ):
                error = ValueError(
                    f"Stale Session revision: expected {expected_revision}, "
                    f"found {current_revision}"
                )
                error.code = "SESSION_REVISION_CONFLICT"  # type: ignore[attr-defined]
                raise error
            data["status"] = "awaiting_feedback"
            data["writing_mock_review"] = review
            data["writing_assessment_result"] = result
            data["rubric"] = review["rubric"]
            data["score_kind"] = "partial_profile"
            data["score_confidence"] = "low"
            data["band"] = None
            data["criterion_scores"] = [
                {
                    "criterion": criterion,
                    "version": f"{task_name}-v1",
                    "score": score,
                    "confidence": task_result.get("confidence"),
                    "evidence": task_result.get("evidence"),
                    "assessment_role": "local_rubric",
                    "evidence_source": "text",
                }
                for task_name, task_result in (
                    ("task1", task1),
                    ("task2", task2),
                )
                for criterion, score in (task_result.get("criteria") or {}).items()
                if score is not None
            ]
            data["score_result"] = result
            data["revision"] = current_revision + 1
            persist_session_atomic(home, path, data)
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE assessment_runs SET score_result_json=?,
                revision=revision+1,updated_at=? WHERE run_id=?
                """,
                (
                    json.dumps(result, ensure_ascii=False),
                    now,
                    run["run_id"],
                ),
            )
    return get_assessment_run(home, str(run["run_id"]))


def _validate_agent_visual_evidence(
    run: dict[str, Any],
    review: dict[str, Any],
    agent_request: dict[str, Any],
) -> None:
    visual = review["visual_evidence"]
    if visual["status"] != "sufficient":
        return
    task1_question = next(
        (
            item
            for item in run["pack_snapshot"].get("questions") or []
            if item.get("task") == "task1"
        ),
        {},
    )
    request_task1 = next(
        (
            item
            for item in (
                (
                    (agent_request.get("canonical_session") or {}).get(
                        "assessment_context"
                    )
                    or {}
                ).get("tasks")
                or []
            )
            if item.get("task") == "task1"
        ),
        {},
    )
    sources = set(visual.get("sources") or [])
    structured_available = bool(
        "structured_task_data" in sources
        and task1_question.get("task_data")
        and request_task1.get("task_data") == task1_question.get("task_data")
    )
    available_media = {
        str(item["media_id"])
        for item in (agent_request.get("media_refs") or [])
        if item.get("available_to_agent")
    }
    claimed_media = {str(value) for value in visual.get("media_ids") or []}
    image_available = bool(
        "image_attachment" in sources
        and claimed_media
        and claimed_media.issubset(available_media)
    )
    if not (structured_available or image_available):
        raise ValueError(
            "Agent claimed sufficient Task 1 visual evidence without a "
            "delivered image or structured task data"
        )


def _validate_task_score(value: dict[str, Any], task_criterion: str) -> float:
    criteria = value.get("criteria") or {}
    required = {task_criterion, "CC", "LR", "GRA"}
    if set(criteria) != required:
        raise ValueError(f"Task score requires exactly {', '.join(sorted(required))}")
    scores = [Decimal(str(criteria[key])) for key in required]
    if any(score < 0 or score > 9 or score * 2 != (score * 2).to_integral() for score in scores):
        raise ValueError("Writing criterion scores must be 0-9 in half-band steps")
    if not value.get("evidence"):
        raise ValueError("Writing task score requires evidence")
    return _round_half(sum(scores) / 4)


def _round_half(value: Decimal) -> float:
    return float((value * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)


def _lower_confidence(first: Any, second: Any) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    values = [str(first or "low"), str(second or "low")]
    return min(values, key=lambda item: order.get(item, 0))


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


ANSWER_KEYS = {
    "correct_answer",
    "correct_answers",
    "accepted_answers",
    "accepted_variants",
    "answer_key",
    "explanation",
    "evidence_location",
    "distractor_explanation",
    "transcript",
    "transcript_timestamp",
}


def _redact_answers(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_answers(item)
            for key, item in value.items()
            if str(key).casefold() not in ANSWER_KEYS
        }
    if isinstance(value, list):
        return [_redact_answers(item) for item in value]
    return value


def _has_answer(response: dict[str, Any]) -> bool:
    value = response.get("text") if "text" in response else response.get("answer")
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(str(value or "").strip())
