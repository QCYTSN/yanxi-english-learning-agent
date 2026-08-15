from __future__ import annotations

from typing import Any
from collections.abc import Mapping


OBJECTIVE_MODULES = {"listening", "reading"}
AI_MODULES = {"writing", "speaking"}
CALIBRATED_STATES = {"calibrated", "passed", "verified"}


def build_score_result(
    session: Mapping[str, Any],
    *,
    evaluator_model: str | None = None,
    calibration_status: str | None = None,
) -> dict[str, Any]:
    """Return the single V1 ScoreResult representation for a Session.

    The function is intentionally deterministic and side-effect free so every
    report, API and UI can use the same admission decision.
    """
    payload = _payload(session)
    existing = payload.get("score_result")
    if isinstance(existing, dict):
        source = {**payload, **existing}
    else:
        source = payload

    raw_score = source.get("raw_score")
    score = source.get("score")
    total = source.get("total")
    if isinstance(score, dict):
        raw_score = raw_score if raw_score is not None else score.get("correct")
        total = total if total is not None else score.get("total")

    band = source.get("band", source.get("estimated_overall"))
    band_range = source.get("band_range") or source.get("estimated_band")
    if band_range and not isinstance(band_range, dict):
        band_range = None
    rubric = source.get("rubric") if isinstance(source.get("rubric"), dict) else {}
    identity = (
        source.get("evaluator_model")
        if isinstance(source.get("evaluator_model"), str)
        else evaluator_model
    )
    calibration = str(
        source.get("calibration_status") or calibration_status or "unknown"
    )
    result: dict[str, Any] = {
        "raw_score": raw_score,
        "total": total,
        "band": band,
        "band_range": band_range,
        "score_kind": source.get("score_kind") or "unspecified",
        "confidence": source.get("confidence")
        or source.get("score_confidence")
        or "unknown",
        "rubric_version": source.get("rubric_version") or rubric.get("version"),
        "conversion_source": source.get("conversion_source")
        or source.get("band_conversion_source"),
        "evidence_scope": source.get("evidence_scope")
        or _evidence_scope(source),
        "evaluator_model": identity,
        "calibration_status": calibration,
    }
    eligible, reason = score_progress_eligibility(source, result)
    result["eligible_for_progress"] = eligible
    result["eligibility_reason"] = reason
    return result


def score_progress_eligibility(
    session: Mapping[str, Any], score_result: Mapping[str, Any] | None = None
) -> tuple[bool, str]:
    """Apply the authoritative V1 progress-admission policy."""
    payload = _payload(session)
    result = dict(score_result or build_score_result(payload))
    if str(payload.get("status", "completed")) != "completed":
        return False, "session_not_completed"
    if result.get("band") is None:
        return False, "no_numeric_band"

    kind = str(result.get("score_kind") or "unspecified")
    module = str(payload.get("module") or "")
    if kind == "official_result":
        return True, "official_result"
    if kind == "answer_key_estimate":
        verified = (
            payload.get("practice_mode") == "full_mock"
            and payload.get("conformance_status") == "verified"
        )
        if module not in OBJECTIVE_MODULES:
            return False, "objective_score_wrong_module"
        if not verified:
            return False, "not_verified_full_mock"
        if int(result.get("total") or 0) != 40:
            return False, "objective_mock_not_40_questions"
        if not result.get("conversion_source"):
            return False, "missing_conversion_source"
        return True, "verified_answer_key_full_mock"
    if kind == "ai_training_estimate":
        if module not in AI_MODULES:
            return False, "ai_estimate_wrong_module"
        if result.get("confidence") not in {"medium", "high"}:
            return False, "low_confidence_ai_estimate"
        if result.get("calibration_status") not in CALIBRATED_STATES:
            return False, "uncalibrated_ai_estimate"
        if module == "writing" and not _writing_evidence_complete(payload):
            return False, "incomplete_writing_evidence"
        if module == "speaking" and not _speaking_evidence_complete(payload):
            return False, "incomplete_speaking_evidence"
        return True, "calibrated_ai_estimate"
    return False, "non_admissible_score_kind"


def _payload(session: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(session)
    raw = value.get("payload_json")
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            return {**value, **parsed}
    return value


def _writing_evidence_complete(payload: Mapping[str, Any]) -> bool:
    if payload.get("practice_mode") == "full_mock":
        results = payload.get("writing_task_results")
        return isinstance(results, dict) and {"task1", "task2"}.issubset(results)
    task = payload.get("task")
    required = {"TA", "CC", "LR", "GRA"} if task == "task1" else {
        "TR",
        "CC",
        "LR",
        "GRA",
    }
    label = payload.get("scored_version")
    criteria = {
        str(item.get("criterion"))
        for item in payload.get("criterion_scores") or []
        if item.get("score") is not None
        and (label is None or item.get("version", item.get("version_label")) == label)
    }
    return required == criteria


def _speaking_evidence_complete(payload: Mapping[str, Any]) -> bool:
    items = [
        item
        for item in payload.get("criterion_scores") or []
        if item.get("assessment_role", "local_rubric") == "local_rubric"
        and item.get("score") is not None
    ]
    criteria = {str(item.get("criterion")) for item in items}
    pron = next((item for item in items if item.get("criterion") == "PRON"), {})
    return criteria == {"FC", "LR", "GRA", "PRON"} and pron.get(
        "evidence_source"
    ) in {"audio", "voice_model_observation", "mixed"}


def _evidence_scope(payload: Mapping[str, Any]) -> str:
    module = payload.get("module")
    if payload.get("practice_mode") == "full_mock":
        return f"verified_full_{module}_mock"
    if module == "writing":
        return "single_writing_task"
    if module == "speaking":
        return "speaking_report"
    if module in OBJECTIVE_MODULES:
        return "partial_objective_practice"
    return "training_observation"
