from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .session_io import load_data_file
from .session_manager import generate_session_id
from .storage import record_session
from .validation import validate_data


def import_speaking_report(home: Path, path: Path) -> dict[str, Any]:
    report = validate_data(load_data_file(path), "speaking-report")
    session_id = report.get("session_id") or generate_session_id(home, "speaking")
    data: dict[str, Any] = {
        "session_id": session_id,
        "module": "speaking",
        "status": "completed",
        "occurred_at": report.get("occurred_at") or datetime.now(timezone.utc).isoformat(),
        "duration_minutes": report.get("duration_minutes"),
        "band": report.get("estimated_overall"),
        "speaking_report": report,
        "criterion_scores": report.get("criterion_scores", []),
        "errors": report.get("errors", []),
    }
    record_session(home, data)
    return data
