from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .session_io import load_session_file
from .storage import connect, get_session, record_session
from .validation import validate_data

PREFIXES = {"listening": "L", "reading": "R", "writing": "W", "speaking": "S"}


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
            "speaking_report": {"mode": "full_mock", "parts": [], "feedback": {}},
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
    mode: str | None = None,
) -> Path:
    module = module.lower()
    session_id = generate_session_id(home, module)
    data: dict[str, Any] = {
        "session_id": session_id,
        "module": module,
        "status": "draft",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "question_id": question_id,
        "source_id": source_id,
        "mode": mode,
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
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return path


def finish_session(home: Path, path: Path) -> dict[str, Any]:
    data = load_session_file(path)
    data["status"] = "completed"
    data = validate_data(data, "session")
    record_session(home, data)
    # Keep the canonical Markdown frontmatter in sync with completed status.
    if path.suffix.lower() in {".md", ".markdown"}:
        body = data.pop("document_body", "")
        frontmatter = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
        path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return data


def show_session(home: Path, session_id: str) -> dict[str, Any] | None:
    row = get_session(home, session_id)
    if row:
        return json.loads(row["payload_json"])
    for module in PREFIXES:
        path = home / "sessions" / module / f"{session_id}.md"
        if path.exists():
            return load_session_file(path)
    return None
