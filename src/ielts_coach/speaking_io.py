from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .session_io import load_data_file
from .session_manager import generate_session_id, persist_session_atomic, show_session
from .study_runtime import mutate_session
from .speaking_evaluation import criterion_rows, local_session_band, normalise_speaking_report
from .validation import validate_data


def import_speaking_report(home: Path, path: Path) -> dict[str, Any]:
    raw_report = load_data_file(path)
    return import_speaking_report_data(home, raw_report)


def import_speaking_report_data(
    home: Path,
    raw_report: dict[str, Any],
    *,
    session_id: str | None = None,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if session_id and raw_report.get("session_id") not in {None, session_id}:
        raise ValueError("Speaking report session_id does not match the target Session")
    raw_report = dict(raw_report)
    if session_id:
        raw_report["session_id"] = session_id
    report = validate_data(normalise_speaking_report(raw_report), "speaking-report")
    session_id = str(report.get("session_id") or generate_session_id(home, "speaking"))
    local_band = local_session_band(report)
    existing = show_session(home, session_id) or {}
    if existing and existing.get("module") != "speaking":
        raise ValueError("Speaking report target belongs to another module")
    assessment_bound = bool(existing.get("assessment_run_id"))
    fields: dict[str, Any] = {
        "session_id": session_id,
        "module": "speaking",
        "status": (
            "awaiting_feedback"
            if assessment_bound
            else "completed"
            if local_band is not None
            else "awaiting_feedback"
        ),
        "occurred_at": report.get("occurred_at") or existing.get("occurred_at") or datetime.now(timezone.utc).isoformat(),
        "duration_minutes": report.get("duration_minutes"),
        "band": None if assessment_bound else local_band,
        "score_kind": (
            "partial_profile"
            if assessment_bound or local_band is None
            else "ai_training_estimate"
        ),
        "score_confidence": (
            None
            if assessment_bound
            else (report.get("local_evaluation") or {}).get("confidence")
        ),
        "rubric": (
            {}
            if assessment_bound
            else (report.get("local_evaluation") or {}).get("rubric", {})
        ),
        "speaking_report": report,
        "speaking_raw_report": raw_report,
        "criterion_scores": [] if assessment_bound else criterion_rows(report),
        "errors": report.get("errors", []),
    }
    if not existing:
        session_path = home / "sessions" / "speaking" / f"{session_id}.md"
        saved = persist_session_atomic(
            home,
            session_path,
            fields,
            body=(
                "# Handoff / Questions\n\n"
                "# Transcript or Summary\n\n"
                "# Feedback\n"
            ),
        )
        saved.pop("document_body", None)
        return saved

    def apply(data: dict[str, Any]) -> None:
        if data.get("module") != "speaking":
            raise ValueError("Speaking report target belongs to another module")
        data.update(fields)

    return mutate_session(
        home,
        session_id,
        "speaking_report_import",
        apply,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
