from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import load_profile
from .storage import connect, get_session, initialise_database
from .validation import validate_data


QUICK_PLAN: dict[str, Any] = {
    "purpose": "Initial placement profile, not an official mock score",
    "requirements": {
        "listening": "Attach a recent verified timed result or complete a user-owned practice test.",
        "reading": "Complete one passage in timed-practice mode, normally 20 minutes.",
        "writing": "Complete one Academic Task 2 response in 40 minutes.",
        "speaking": "Complete a three-part mock; 11-14 minutes is preferred for a full estimate.",
    },
}

FULL_PLAN: dict[str, Any] = {
    "purpose": "Full four-skill baseline using user-owned official-length practice material",
    "requirements": {
        "listening": "Complete one full timed Academic Listening practice test.",
        "reading": "Complete one full 60-minute Academic Reading practice test without hints.",
        "writing_task1": "Complete Academic Writing Task 1 in about 20 minutes.",
        "writing_task2": "Complete Academic Writing Task 2 in about 40 minutes.",
        "speaking": "Complete an uninterrupted three-part 11-14 minute mock.",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(home: Path) -> str:
    date_part = datetime.now().strftime("%Y%m%d")
    prefix = f"D-{date_part}-"
    with connect(home) as conn:
        row = conn.execute(
            "SELECT diagnostic_id FROM diagnostic_runs WHERE diagnostic_id LIKE ? "
            "ORDER BY diagnostic_id DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
    number = int(str(row["diagnostic_id"]).rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{number:03d}"


def start_diagnostic(home: Path, mode: str) -> dict[str, Any]:
    initialise_database(home)
    mode = mode.lower()
    if mode not in {"quick", "full"}:
        raise ValueError("Diagnostic mode must be quick or full")
    with connect(home) as conn:
        active = conn.execute(
            "SELECT diagnostic_id FROM diagnostic_runs WHERE status='active' "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if active:
        raise ValueError(
            f"Diagnostic {active['diagnostic_id']} is already active; complete or cancel it first"
        )
    diagnostic_id = _next_id(home)
    plan = QUICK_PLAN if mode == "quick" else FULL_PLAN
    started_at = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO diagnostic_runs(
              diagnostic_id,mode,status,exam_type,started_at,session_ids_json,plan_json,result_json
            ) VALUES(?,?, 'active','academic',?,?,?, '{}')
            """,
            (diagnostic_id, mode, started_at, "[]", json.dumps(plan, ensure_ascii=False)),
        )
    return diagnostic_status(home, diagnostic_id)


def attach_diagnostic_session(home: Path, diagnostic_id: str, session_id: str) -> dict[str, Any]:
    run = _get_run(home, diagnostic_id)
    if run["status"] != "active":
        raise ValueError("Sessions can only be attached to an active diagnostic")
    session = get_session(home, session_id)
    if session is None or session["status"] != "completed":
        raise ValueError("Diagnostic evidence must reference a completed Session")
    session_ids = json.loads(run["session_ids_json"])
    if session_id not in session_ids:
        session_ids.append(session_id)
    with connect(home) as conn:
        conn.execute(
            "UPDATE diagnostic_runs SET session_ids_json=? WHERE diagnostic_id=?",
            (json.dumps(session_ids, ensure_ascii=False), diagnostic_id),
        )
    return diagnostic_status(home, diagnostic_id)


def diagnostic_status(home: Path, diagnostic_id: str | None = None) -> dict[str, Any]:
    initialise_database(home)
    if diagnostic_id is None:
        with connect(home) as conn:
            row = conn.execute(
                "SELECT diagnostic_id FROM diagnostic_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"status": "not_started", "exam_type": "academic"}
        diagnostic_id = str(row["diagnostic_id"])
    run = _get_run(home, diagnostic_id)
    session_ids = json.loads(run["session_ids_json"])
    evidence = _session_evidence(home, session_ids)
    missing = _missing_requirements(str(run["mode"]), evidence)
    return {
        "diagnostic_id": diagnostic_id,
        "mode": run["mode"],
        "status": run["status"],
        "exam_type": run["exam_type"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "session_ids": session_ids,
        "coverage": sorted(evidence["modules"]),
        "missing_requirements": missing,
        "plan": json.loads(run["plan_json"]),
        "result": json.loads(run["result_json"]),
    }


def complete_diagnostic(home: Path, diagnostic_id: str) -> dict[str, Any]:
    run = _get_run(home, diagnostic_id)
    if run["status"] != "active":
        raise ValueError("Only an active diagnostic can be completed")
    session_ids = json.loads(run["session_ids_json"])
    evidence = _session_evidence(home, session_ids)
    missing = _missing_requirements(str(run["mode"]), evidence)
    if missing:
        raise ValueError("Diagnostic is incomplete: " + ", ".join(missing))
    baselines = _usable_baselines(evidence["sessions"])
    result = {
        "baseline_scores": baselines,
        "baseline_status": "complete" if len(baselines) == 4 else "partial",
        "note": "Missing numeric scores remain unknown; coverage does not imply an official Band.",
    }
    completed_at = _now()
    with connect(home) as conn:
        conn.execute(
            "UPDATE diagnostic_runs SET status='completed',completed_at=?,result_json=? "
            "WHERE diagnostic_id=?",
            (completed_at, json.dumps(result, ensure_ascii=False), diagnostic_id),
        )
    _save_baselines(home, baselines)
    return diagnostic_status(home, diagnostic_id)


def cancel_diagnostic(home: Path, diagnostic_id: str) -> dict[str, Any]:
    run = _get_run(home, diagnostic_id)
    if run["status"] != "active":
        raise ValueError("Only an active diagnostic can be cancelled")
    with connect(home) as conn:
        conn.execute(
            "UPDATE diagnostic_runs SET status='cancelled',completed_at=? WHERE diagnostic_id=?",
            (_now(), diagnostic_id),
        )
    return diagnostic_status(home, diagnostic_id)


def _get_run(home: Path, diagnostic_id: str):
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM diagnostic_runs WHERE diagnostic_id=?", (diagnostic_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown diagnostic: {diagnostic_id}")
    return row


def _session_evidence(home: Path, session_ids: list[str]) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    modules: set[str] = set()
    writing_tasks: set[str] = set()
    for session_id in session_ids:
        row = get_session(home, session_id)
        if row is None or row["status"] != "completed":
            continue
        payload = json.loads(row["payload_json"])
        payload["_stored_band"] = row["band"]
        payload["_score_kind"] = row["score_kind"]
        payload["_score_confidence"] = row["score_confidence"]
        sessions.append(payload)
        modules.add(str(row["module"]))
        if row["module"] == "writing" and payload.get("task") in {"task1", "task2"}:
            writing_tasks.add(str(payload["task"]))
    return {"sessions": sessions, "modules": modules, "writing_tasks": writing_tasks}


def _missing_requirements(mode: str, evidence: dict[str, Any]) -> list[str]:
    sessions = evidence["sessions"]
    missing: list[str] = []
    listening = [item for item in sessions if item.get("module") == "listening"]
    listening_ready = [item for item in listening if _verified_objective_result(item)]
    if mode == "full":
        listening_ready = [item for item in listening_ready if _is_full_listening(item)]
    if not listening_ready:
        missing.append("listening_verified_result")

    reading = [item for item in sessions if item.get("module") == "reading"]
    reading_ready = [
        item for item in reading
        if item.get("mode") == "timed-practice"
        and item.get("submitted_at")
        and item.get("questions")
    ]
    if mode == "full":
        reading_ready = [
            item for item in reading_ready
            if float(item.get("time_limit_minutes") or 0) >= 60
            and len(item.get("questions") or []) >= 40
        ]
    if not reading_ready:
        missing.append("reading_timed_passage" if mode == "quick" else "reading_full_timed_test")

    writing = [item for item in sessions if item.get("module") == "writing"]
    if not any(_timed_writing(item, "task2") for item in writing):
        missing.append("writing_task2")

    speaking = [item for item in sessions if item.get("module") == "speaking"]
    speaking_ready = [item for item in speaking if _has_three_speaking_parts(item)]
    if mode == "full":
        speaking_ready = [
            item for item in speaking_ready
            if float(item.get("duration_minutes") or 0) >= 11
        ]
    if not speaking_ready:
        missing.append("speaking_three_part_mock")

    if mode == "full":
        if not any(_timed_writing(item, "task1") for item in writing):
            missing.append("writing_task1")
    return missing


def _verified_objective_result(item: dict[str, Any]) -> bool:
    kind = item.get("_score_kind") or item.get("score_kind")
    if kind not in {"official_result", "answer_key_estimate"}:
        return False
    score = item.get("score") or {}
    return bool(
        item.get("_stored_band") is not None
        or item.get("raw_score") is not None
        or (isinstance(score, dict) and score.get("correct") is not None)
    )


def _is_full_listening(item: dict[str, Any]) -> bool:
    score = item.get("score") or {}
    return bool(
        item.get("mode") == "timed-practice"
        and isinstance(score, dict)
        and score.get("total") == 40
    )


def _timed_writing(item: dict[str, Any], task: str) -> bool:
    return bool(
        item.get("task") == task
        and item.get("mode") == "timed-practice"
        and item.get("versions")
    )


def _has_three_speaking_parts(item: dict[str, Any]) -> bool:
    report = item.get("speaking_report") or {}
    source = report.get("source_observations") or {} if isinstance(report, dict) else {}
    parts = source.get("parts") or report.get("parts") or item.get("parts") or []
    seen: set[int] = set()
    for part in parts:
        value = part.get("part") if isinstance(part, dict) else part
        try:
            seen.add(int(value))
        except (TypeError, ValueError):
            continue
    evidence_exists = bool(
        source.get("evidence_types")
        or source.get("transcript")
        or source.get("answer_summary")
        or report.get("transcript")
        or report.get("answer_summary")
    )
    return {1, 2, 3}.issubset(seen) and evidence_exists


def _usable_baselines(sessions: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in sessions:
        band = item.get("_stored_band")
        kind = item.get("_score_kind") or "unspecified"
        confidence = item.get("_score_confidence")
        usable = band is not None and kind in {
            "official_result", "answer_key_estimate", "ai_training_estimate"
        }
        if kind == "ai_training_estimate":
            usable = usable and confidence in {"medium", "high"}
        if usable:
            result[str(item["module"])] = float(band)
    return result


def _save_baselines(home: Path, baselines: dict[str, float]) -> None:
    path = home / "config" / "profile.yaml"
    profile = load_profile(home)
    profile["current"].update(baselines)
    profile = validate_data(profile, "profile")
    path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
