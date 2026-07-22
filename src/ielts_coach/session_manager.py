from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .session_io import load_session_file
from .storage import connect, get_session, record_session
from .validation import validate_data

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
    mode: str | None = None,
    time_limit_minutes: float | None = None,
) -> Path:
    module = module.lower()
    session_id = generate_session_id(home, module)
    now = datetime.now(timezone.utc).isoformat()
    if module == "reading" and mode == "timed-practice" and time_limit_minutes is None:
        time_limit_minutes = 20.0
    data: dict[str, Any] = {
        "session_id": session_id,
        "module": module,
        "status": "draft",
        "revision": 0,
        "occurred_at": now,
        "question_id": question_id,
        "passage_id": passage_id,
        "source_id": source_id,
        "mode": mode,
        "time_limit_minutes": time_limit_minutes,
        "started_at": now if mode == "timed-practice" else None,
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
    frontmatter = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    _write_session_document_atomic(path, data, body)
    try:
        record_session(home, data)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


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
) -> dict[str, Any]:
    """Keep the human-readable Session and SQLite mirror consistent on errors."""
    validated = validate_data(data, "session")
    if body is None:
        body = str(validated.get("document_body", ""))
    old_text = path.read_text(encoding="utf-8") if path.exists() else None
    _write_session_document_atomic(path, validated, body)
    try:
        db_data = dict(validated)
        db_data.pop("document_body", None)
        record_session(home, db_data)
    except Exception:
        if old_text is None:
            path.unlink(missing_ok=True)
        else:
            _write_text_atomic(path, old_text)
        raise
    return validated


def transition_session(home: Path, path: Path, new_status: str) -> dict[str, Any]:
    data = load_session_file(path)
    old_status = str(data.get("status", "draft"))
    new_status = new_status.lower()
    if new_status == "completed":
        return finish_session(home, path)
    if new_status not in SESSION_TRANSITIONS.get(old_status, set()):
        raise ValueError(f"Invalid session transition: {old_status} -> {new_status}")
    data["status"] = new_status
    data["revision"] = int(data.get("revision", 0)) + 1
    return persist_session_atomic(home, path, data)


def finish_session(home: Path, path: Path) -> dict[str, Any]:
    data = load_session_file(path)
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
