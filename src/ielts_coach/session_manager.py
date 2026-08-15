from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .session_io import load_session_file
from .storage import (
    connect,
    get_assessment_pack,
    get_question,
    get_idempotency_record,
    get_session,
    record_session,
    save_idempotency_record,
    session_payload_hash,
    set_session_mirror_status,
)
from .conformance import assess_pack
from .validation import validate_data
from .errors import InvalidSessionTransitionError, SessionMirrorConflictError
from .locking import runtime_lock

PREFIXES = {"listening": "L", "reading": "R", "writing": "W", "speaking": "S"}
SESSION_TRANSITIONS = {
    "draft": {"question_presented", "learner_working", "cancelled"},
    "question_presented": {"learner_working", "cancelled"},
    "learner_working": {"awaiting_feedback", "completed", "cancelled"},
    "awaiting_feedback": {"awaiting_revision", "completed", "cancelled"},
    "awaiting_revision": {"learner_working", "awaiting_feedback", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def generate_session_id(home: Path, module: str) -> str:
    module = module.lower()
    if module not in PREFIXES:
        raise ValueError(f"Unsupported module: {module}")
    date_part = datetime.now().strftime("%Y%m%d")
    prefix = f"{PREFIXES[module]}-{date_part}-"
    with connect(home) as conn:
        row = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id LIKE ? ORDER BY session_id DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
    next_number = 1
    if row:
        try:
            next_number = int(str(row["session_id"]).rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            next_number = 1
    # Also account for draft files not yet recorded.
    folder = home / "sessions" / module
    while (folder / f"{prefix}{next_number:03d}.md").exists():
        next_number += 1
    return f"{prefix}{next_number:03d}"


def _module_fields(module: str) -> dict[str, Any]:
    if module == "writing":
        return {
            "versions": [],
            "criterion_scores": [],
            "errors": [],
        }
    if module == "reading":
        return {
            "score": {"correct": None, "total": None},
            "questions": [],
            "errors": [],
        }
    if module == "speaking":
        return {
            "speaking_report": {
                "report_version": 2,
                "mode": "full_mock",
                "source_observations": {"evidence_types": [], "parts": []},
                "source_model_estimate": {"criterion_scores": []},
                "local_evaluation": {"status": "pending", "criterion_scores": []},
            },
            "criterion_scores": [],
            "errors": [],
        }
    return {"errors": []}


def start_session(
    home: Path,
    module: str,
    *,
    question_id: str | None = None,
    source_id: str | None = None,
    passage_id: str | None = None,
    assessment_pack_id: str | None = None,
    assessment_contract: dict[str, Any] | None = None,
    practice_mode: str | None = None,
    mode: str | None = None,
    time_limit_minutes: float | None = None,
    idempotency_key: str | None = None,
) -> Path:
    module = module.lower()
    scope = f"session-create:{module}"
    with runtime_lock(home, scope):
        if idempotency_key:
            replay = get_idempotency_record(home, scope, idempotency_key)
            if replay:
                return Path(str(replay["response"]["path"]))
        path = _start_session_unlocked(
            home,
            module,
            question_id=question_id,
            source_id=source_id,
            passage_id=passage_id,
            assessment_pack_id=assessment_pack_id,
            assessment_contract=assessment_contract,
            practice_mode=practice_mode,
            mode=mode,
            time_limit_minutes=time_limit_minutes,
        )
        if idempotency_key:
            save_idempotency_record(
                home, scope, idempotency_key, "session_create", {"path": str(path)}
            )
        return path


def _start_session_unlocked(
    home: Path,
    module: str,
    *,
    question_id: str | None = None,
    source_id: str | None = None,
    passage_id: str | None = None,
    assessment_pack_id: str | None = None,
    assessment_contract: dict[str, Any] | None = None,
    practice_mode: str | None = None,
    mode: str | None = None,
    time_limit_minutes: float | None = None,
) -> Path:
    module = module.lower()
    contract = _resolve_assessment_contract(
        home,
        module,
        question_id=question_id,
        assessment_pack_id=assessment_pack_id,
        assessment_contract=assessment_contract,
        practice_mode=practice_mode,
    )
    practice_mode = str(contract["practice_mode"])
    conformance_status = str(contract["conformance_status"])
    session_id = generate_session_id(home, module)
    now = datetime.now(timezone.utc).isoformat()
    if time_limit_minutes is None:
        structure = contract.get("structure") or {}
        if structure.get("time_limit_minutes"):
            time_limit_minutes = float(structure["time_limit_minutes"])
        elif module == "reading" and mode == "timed-practice":
            time_limit_minutes = 20.0
        elif module == "writing" and question_id:
            question = get_question(home, question_id) or {}
            time_limit_minutes = 20.0 if question.get("task") == "task1" else 40.0
    data: dict[str, Any] = {
        "session_id": session_id,
        "module": module,
        "status": "draft",
        "revision": 0,
        "occurred_at": now,
        "question_id": question_id,
        "passage_id": passage_id,
        "assessment_pack_id": assessment_pack_id,
        "assessment_contract": contract,
        "source_id": source_id,
        "mode": mode,
        "practice_mode": practice_mode,
        "conformance_status": conformance_status,
        "time_limit_minutes": time_limit_minutes,
        "started_at": now if mode == "timed-practice" or practice_mode == "full_mock" else None,
        "submitted_at": None,
        "answer_revealed_at": None,
        "hints_used": 0,
        "duration_minutes": None,
        "band": None,
    }
    data.update(_module_fields(module))
    path = home / "sessions" / module / f"{session_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "writing": "# Question\n\n# Version 1\n\n# Feedback\n\n# Version 2\n\n# Final Review\n",
        "reading": "# Passage / Question Reference\n\n# Answers and Explanations\n\n# Review\n",
        "speaking": "# Handoff / Questions\n\n# Transcript or Summary\n\n# Feedback\n",
        "listening": "# Test Reference\n\n# Wrong Answers\n\n# Review\n",
    }[module]
    _write_session_document_atomic(path, data, body)
    try:
        record_session(home, data, mirror_status="synced")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _resolve_assessment_contract(
    home: Path,
    module: str,
    *,
    question_id: str | None,
    assessment_pack_id: str | None,
    assessment_contract: dict[str, Any] | None,
    practice_mode: str | None,
) -> dict[str, Any]:
    if assessment_pack_id:
        pack = get_assessment_pack(home, assessment_pack_id)
        if not pack:
            raise ValueError(f"Unknown assessment pack: {assessment_pack_id}")
        if pack.get("module") != module:
            raise ValueError("Assessment pack module does not match the Session module")
        contract = dict(pack)
    elif assessment_contract:
        contract = dict(assessment_contract)
        if contract.get("module") != module:
            raise ValueError("Assessment contract module does not match the Session module")
        report = assess_pack(contract)
        contract["conformance_status"] = report["status"]
        contract["conformance_report"] = report
    elif question_id:
        question = get_question(home, question_id)
        if not question:
            raise ValueError(f"Unknown question: {question_id}")
        if question.get("module") != module:
            raise ValueError("Question module does not match the Session module")
        contract = {
            "module": module,
            "practice_mode": practice_mode or question.get("practice_mode") or "question_type_drill",
            "conformance_status": question.get("conformance_status") or "provisional",
            "standard_profile": question.get("standard_profile") or "ielts-academic",
            "standard_version": question.get("standard_version"),
            "question_id": question_id,
        }
    else:
        inferred = practice_mode or ("skill_drill" if module == "listening" else "section_practice")
        contract = {
            "module": module,
            "practice_mode": inferred,
            "conformance_status": "skill_only" if inferred == "skill_drill" else "provisional",
            "standard_profile": "ielts-academic",
        }
    resolved_mode = str(practice_mode or contract.get("practice_mode") or "section_practice")
    status = str(contract.get("conformance_status") or (contract.get("conformance_report") or {}).get("status") or "provisional")
    contract["practice_mode"] = resolved_mode
    contract["conformance_status"] = status
    if status == "rejected":
        raise ValueError("This content failed IELTS conformance checks and cannot start a practice Session")
    if resolved_mode == "full_mock" and status != "verified":
        raise ValueError("A full IELTS mock requires a verified assessment contract")
    return contract


def _render_session_document(data: dict[str, Any], body: str) -> str:
    clean = dict(data)
    clean.pop("document_body", None)
    frontmatter = yaml.safe_dump(clean, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_session_document_atomic(path: Path, data: dict[str, Any], body: str) -> None:
    _write_text_atomic(path, _render_session_document(data, body))


def persist_session_atomic(
    home: Path,
    path: Path,
    data: dict[str, Any],
    *,
    body: str | None = None,
    allow_reconcile: bool = False,
) -> dict[str, Any]:
    """Commit one revision to both Session projections or restore the old file."""
    validated = validate_data(data, "session")
    if not allow_reconcile:
        assert_session_mirror_consistent(home, path)
    if body is None:
        body = str(validated.get("document_body", ""))
    old_text = path.read_text(encoding="utf-8") if path.exists() else None
    _write_session_document_atomic(path, validated, body)
    try:
        db_data = dict(validated)
        db_data.pop("document_body", None)
        record_session(home, db_data, mirror_status="synced")
    except Exception:
        if old_text is None:
            path.unlink(missing_ok=True)
        else:
            _write_text_atomic(path, old_text)
        raise
    return validated


def assert_session_mirror_consistent(home: Path, path: Path) -> None:
    """Block mutations when Markdown and SQLite no longer share one revision."""
    row = get_session(home, path.stem)
    if not row or not path.exists():
        return
    try:
        file_data = load_session_file(path)
        db_data = json.loads(str(row["payload_json"]))
        file_revision = int(file_data.get("revision", 0))
        db_revision = int(db_data.get("revision", 0))
        file_hash = session_payload_hash(file_data)
        db_hash = session_payload_hash(db_data)
    except Exception as exc:
        set_session_mirror_status(home, path.stem, "conflict")
        raise SessionMirrorConflictError(
            f"Session projections cannot be compared: {exc}",
            details={"session_id": path.stem},
        ) from exc
    if file_revision == db_revision and file_hash == db_hash:
        return
    set_session_mirror_status(home, path.stem, "conflict")
    raise SessionMirrorConflictError(
        "Session Markdown and SQLite disagree; reconcile them before writing.",
        details={
            "session_id": path.stem,
            "markdown_revision": file_revision,
            "sqlite_revision": db_revision,
            "same_revision_content_conflict": (
                file_revision == db_revision and file_hash != db_hash
            ),
            "markdown_hash": file_hash,
            "sqlite_hash": db_hash,
        },
    )


def transition_session(home: Path, path: Path, new_status: str) -> dict[str, Any]:
    with runtime_lock(home, f"session:{path.stem}"):
        data = load_session_file(path)
        old_status = str(data.get("status", "draft"))
        new_status = new_status.lower()
        if new_status == "completed":
            return _finish_session_unlocked(home, path, data)
        if new_status not in SESSION_TRANSITIONS.get(old_status, set()):
            raise InvalidSessionTransitionError(
                f"Invalid session transition: {old_status} -> {new_status}",
                details={"from": old_status, "to": new_status},
            )
        data["status"] = new_status
        data["revision"] = int(data.get("revision", 0)) + 1
        return persist_session_atomic(home, path, data)


def finish_session(home: Path, path: Path) -> dict[str, Any]:
    with runtime_lock(home, f"session:{path.stem}"):
        return _finish_session_unlocked(home, path, load_session_file(path))


def _finish_session_unlocked(home: Path, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    data["status"] = "completed"
    data["revision"] = int(data.get("revision", 0)) + 1
    return persist_session_atomic(home, path, data)


def show_session(home: Path, session_id: str) -> dict[str, Any] | None:
    row = get_session(home, session_id)
    if row:
        return json.loads(row["payload_json"])
    for module in PREFIXES:
        path = home / "sessions" / module / f"{session_id}.md"
        if path.exists():
            return load_session_file(path)
    return None
