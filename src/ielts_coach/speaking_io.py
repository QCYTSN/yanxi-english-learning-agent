from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .session_io import load_data_file
from .session_manager import generate_session_id
from .speaking_evaluation import criterion_rows, local_session_band, normalise_speaking_report
from .storage import record_session
from .validation import validate_data


def import_speaking_report(home: Path, path: Path) -> dict[str, Any]:
    raw_report = load_data_file(path)
    report = validate_data(normalise_speaking_report(raw_report), "speaking-report")
    session_id = report.get("session_id") or generate_session_id(home, "speaking")
    local_band = local_session_band(report)
    data: dict[str, Any] = {
        "session_id": session_id,
        "module": "speaking",
        "status": "completed",
        "occurred_at": report.get("occurred_at") or datetime.now(timezone.utc).isoformat(),
        "duration_minutes": report.get("duration_minutes"),
        "band": local_band,
        "score_kind": "ai_training_estimate" if local_band is not None else "partial_profile",
        "score_confidence": (report.get("local_evaluation") or {}).get("confidence"),
        "rubric": (report.get("local_evaluation") or {}).get("rubric", {}),
        "speaking_report": report,
        "speaking_raw_report": raw_report,
        "criterion_scores": criterion_rows(report),
        "errors": report.get("errors", []),
    }
    record_session(home, data)
    return data
