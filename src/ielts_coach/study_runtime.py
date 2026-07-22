from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable

from .rubrics import require_rubric
from .session_io import load_session_file
from .session_manager import PREFIXES, persist_session_atomic
from .storage import connect, get_session, initialise_database, record_runtime_event
from .validation import validate_data


TERMINAL_STATUSES = {"completed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_path(home: Path, session_id: str, module: str | None = None) -> Path:
    modules = (module,) if module else tuple(PREFIXES)
    for candidate_module in modules:
        candidate = home / "sessions" / str(candidate_module) / f"{session_id}.md"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Session document not found: {session_id}")


def _db_payload(home: Path, session_id: str) -> dict[str, Any] | None:
    row = get_session(home, session_id)
    return json.loads(row["payload_json"]) if row else None


def reconcile_session(home: Path, session_id: str) -> dict[str, Any]:
    """Repair a stale file/DB mirror by keeping the highest validated revision."""
    db_data = _db_payload(home, session_id)
    module = str(db_data["module"]) if db_data else None
    path = session_path(home, session_id, module)
    file_data = load_session_file(path)
    file_revision = int(file_data.get("revision", 0))
    db_revision = int((db_data or {}).get("revision", 0))
    if not db_data or file_revision >= db_revision:
        return persist_session_atomic(home, path, file_data)
    body = str(file_data.get("document_body", ""))
    return persist_session_atomic(home, path, db_data, body=body)


def resume_session(home: Path, module: str | None = None) -> dict[str, Any] | None:
    initialise_database(home)
    sql = "SELECT session_id FROM sessions WHERE status NOT IN ('completed','cancelled')"
    params: list[Any] = []
    if module:
        sql += " AND module=?"
        params.append(module)
    sql += " ORDER BY updated_at DESC,occurred_at DESC LIMIT 1"
    with connect(home) as conn:
        row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    data = reconcile_session(home, str(row["session_id"]))
    data.pop("document_body", None)
    return data


def _mutate(
    home: Path,
    session_id: str,
    event_type: str,
    mutator: Callable[[dict[str, Any]], None],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    path = session_path(home, session_id)
    data = load_session_file(path)
    current = int(data.get("revision", 0))
    if expected_revision is not None and current != expected_revision:
        raise ValueError(f"Stale Session revision: expected {expected_revision}, current {current}")
    if data.get("status") in TERMINAL_STATUSES:
        raise ValueError(f"Cannot modify a {data.get('status')} Session")
    mutator(data)
    data["revision"] = current + 1
    saved = persist_session_atomic(home, path, data)
    record_runtime_event(
        home,
        event_id=f"{session_id}:{saved['revision']}:{event_type}",
        event_type=event_type,
        session_id=session_id,
        module=str(saved["module"]),
        revision=int(saved["revision"]),
        payload={"status": saved.get("status")},
    )
    saved.pop("document_body", None)
    return saved


def submit_writing_version(
    home: Path,
    session_id: str,
    *,
    label: str,
    content: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    label = label.lower()
    if label not in {"v1", "v2", "final"}:
        raise ValueError("Writing version label must be v1, v2, or final")
    if not content.strip():
        raise ValueError("Writing content must not be empty")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "writing":
            raise ValueError("This operation requires a Writing Session")
        versions = data.setdefault("versions", [])
        existing = next((item for item in versions if item.get("label") == label), None)
        item = {"label": label, "content": content.strip(), "word_count": len(content.split())}
        if existing:
            existing.update(item)
        else:
            versions.append(item)
        data["status"] = "awaiting_feedback"
        data["submitted_at"] = _now()

    return _mutate(
        home, session_id, f"writing_version_{label}", apply, expected_revision=expected_revision
    )


def apply_writing_review(
    home: Path,
    session_id: str,
    review: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    review = validate_data(review, "writing-review")
    if review["session_id"] != session_id:
        raise ValueError("Writing review session_id does not match the target Session")
    require_rubric(home, review["rubric"]["rubric_id"], "writing")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "writing":
            raise ValueError("This operation requires a Writing Session")
        if data.get("task") and data["task"] != review["task"]:
            raise ValueError("Writing review task does not match the Session task")
        labels = {item.get("label") for item in data.get("versions") or []}
        if review["version_label"] not in labels:
            raise ValueError("Writing review references a version not submitted by the learner")
        data["task"] = review["task"]
        data["scored_version"] = review["version_label"]
        data["score_kind"] = "ai_training_estimate"
        data["score_confidence"] = review["confidence"]
        data["rubric"] = review["rubric"]
        data["estimated_band_range"] = review.get("estimated_band")
        scores: list[dict[str, Any]] = []
        exact = True
        for item in review["criteria"]:
            exact = exact and item["score_low"] == item["score_high"]
            scores.append(
                {
                    "version": review["version_label"],
                    "criterion": item["criterion"],
                    "score_low": item["score_low"],
                    "score_high": item["score_high"],
                    "score": item["score_low"] if item["score_low"] == item["score_high"] else None,
                    "confidence": review["confidence"],
                    "assessment_role": "local_rubric",
                    "evidence_source": "text",
                    "rubric": review["rubric"],
                    "evidence": item["evidence_support"] + item["evidence_limit"],
                }
            )
        previous = [
            item for item in data.get("criterion_scores") or []
            if item.get("version", item.get("version_label")) != review["version_label"]
        ]
        data["criterion_scores"] = previous + scores
        if exact:
            mean = sum(Decimal(str(item["score"])) for item in scores) / Decimal("4")
            data["band"] = float((mean * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
        else:
            data["band"] = None
        data["errors"] = [
            {"tag": item["tag"], "count": 1, "evidence": item["evidence"], "status": "active"}
            for item in review["priority_issues"]
        ]
        data["writing_review"] = review
        data["status"] = "awaiting_revision"

    return _mutate(home, session_id, "writing_review", apply, expected_revision=expected_revision)


def record_reading_hint(
    home: Path,
    session_id: str,
    *,
    level: int | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "reading":
            raise ValueError("This operation requires a Reading Session")
        if data.get("mode") == "timed-practice":
            raise ValueError("Timed Reading practice cannot use hints")
        current = int(data.get("hints_used") or 0)
        next_level = current + 1 if level is None else level
        if next_level not in {1, 2, 3} or next_level < current:
            raise ValueError("Reading hint level must progress monotonically from 1 to 3")
        data["hints_used"] = next_level
        data["status"] = "learner_working"

    return _mutate(home, session_id, "reading_hint", apply, expected_revision=expected_revision)


def submit_reading_answers(
    home: Path,
    session_id: str,
    answers: list[dict[str, Any]],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    if not answers:
        raise ValueError("At least one Reading answer is required")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "reading":
            raise ValueError("This operation requires a Reading Session")
        clean: list[dict[str, Any]] = []
        for item in answers:
            if not item.get("question_type") or item.get("user_answer") in {None, ""}:
                raise ValueError("Each Reading answer needs question_type and user_answer")
            clean.append(
                {
                    "question_id": item.get("question_id"),
                    "question_number": item.get("question_number"),
                    "question_type": item["question_type"],
                    "user_answer": item["user_answer"],
                    "duration_seconds": item.get("duration_seconds"),
                    "error_tags": [],
                }
            )
        data["questions"] = clean
        data["submitted_at"] = _now()
        data["status"] = "awaiting_feedback"

    return _mutate(home, session_id, "reading_submission", apply, expected_revision=expected_revision)


def apply_reading_review(
    home: Path,
    session_id: str,
    review: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    review = validate_data(review, "reading-review")
    if review["session_id"] != session_id:
        raise ValueError("Reading review session_id does not match the target Session")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "reading":
            raise ValueError("This operation requires a Reading Session")
        if review["mode"] == "guided_hint":
            if data.get("mode") == "timed-practice":
                raise ValueError("Timed Reading practice cannot receive guided hints")
            data["hints_used"] = max(int(data.get("hints_used") or 0), int(review["hint_level"]))
            data["reading_review"] = review
            data["status"] = "learner_working"
            return
        if review["answer_revealed"] and not data.get("submitted_at"):
            raise ValueError("Reading answers cannot be revealed before learner submission")
        submitted = {str(item.get("question_id") or item.get("question_number")): item for item in data.get("questions") or []}
        merged_by_key = {key: dict(value) for key, value in submitted.items()}
        errors: list[dict[str, Any]] = []
        for item in review["items"]:
            key = str(item.get("question_id") or item.get("question_number"))
            base = dict(merged_by_key.get(key, {}))
            base.update(item)
            if "correct_answer" in item:
                base["is_correct"] = str(base.get("user_answer")).casefold() == str(item["correct_answer"]).casefold()
            merged_by_key[key] = base
            for tag in item.get("error_tags") or []:
                errors.append({"tag": tag, "count": 1, "evidence": item.get("reasoning"), "status": "active"})
        data["questions"] = list(merged_by_key.values()) or data.get("questions", [])
        data["errors"] = errors
        data["reading_review"] = review
        data["answer_revealed_at"] = _now() if review["answer_revealed"] else data.get("answer_revealed_at")
        correct = sum(1 for item in data["questions"] if item.get("is_correct") is True)
        scored = sum(1 for item in data["questions"] if item.get("is_correct") is not None)
        data["score"] = {"correct": correct, "total": scored} if scored else data.get("score")
        data["status"] = "awaiting_revision"

    return _mutate(home, session_id, "reading_review", apply, expected_revision=expected_revision)
