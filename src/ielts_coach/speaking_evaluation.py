from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


OFFICIAL_SPEAKING_STANDARD = "IELTS Speaking Band Descriptors"
SPEAKING_CRITERIA = {"FC", "LR", "GRA", "PRON"}


def normalise_speaking_report(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a legacy Voice report without treating its estimate as local scoring."""
    report = deepcopy(raw)
    report.setdefault("report_version", 2)

    observations = deepcopy(report.get("source_observations") or {})
    if report.get("transcript") and not observations.get("transcript"):
        observations["transcript"] = report["transcript"]
    if report.get("parts") and not observations.get("parts"):
        observations["parts"] = report["parts"]
    evidence_types = list(observations.get("evidence_types") or [])
    if observations.get("transcript") and "transcript" not in evidence_types:
        evidence_types.append("transcript")
    if report.get("document_body") and "summary" not in evidence_types:
        evidence_types.append("summary")
    observations["evidence_types"] = evidence_types
    report["source_observations"] = observations

    source_estimate = deepcopy(report.get("source_model_estimate") or {})
    if report.get("estimated_overall") is not None and source_estimate.get("estimated_overall") is None:
        source_estimate["estimated_overall"] = report["estimated_overall"]
    if report.get("criterion_scores") and not source_estimate.get("criterion_scores"):
        source_estimate["criterion_scores"] = report["criterion_scores"]
    report["source_model_estimate"] = source_estimate

    report.setdefault("local_evaluation", {"status": "pending", "criterion_scores": []})
    return report


def criterion_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role, key, label in (
        ("source_model", "source_model_estimate", "source-model"),
        ("local_rubric", "local_evaluation", "local"),
    ):
        assessment = report.get(key) or {}
        for item in assessment.get("criterion_scores", []) or []:
            row = deepcopy(item)
            row["version"] = label
            row["assessment_role"] = role
            if role == "local_rubric":
                row["rubric"] = deepcopy(assessment.get("rubric") or {})
            rows.append(row)
    return rows


def local_session_band(report: dict[str, Any]) -> float | None:
    evaluation = report.get("local_evaluation") or {}
    if evaluation.get("status") != "completed":
        return None
    value = evaluation.get("estimated_overall")
    return None if value is None else float(value)


def validate_speaking_report_semantics(report: dict[str, Any]) -> None:
    observations = report.get("source_observations") or {}
    evidence_types = set(observations.get("evidence_types") or [])
    pronunciation_observations = observations.get("pronunciation_observations") or []

    for section_name in ("source_model_estimate", "local_evaluation"):
        section = report.get(section_name) or {}
        seen: set[str] = set()
        for item in section.get("criterion_scores", []) or []:
            criterion = str(item.get("criterion", ""))
            if criterion not in SPEAKING_CRITERIA:
                raise ValueError(f"Unsupported Speaking criterion: {criterion!r}")
            if criterion in seen:
                raise ValueError(f"Duplicate Speaking criterion in {section_name}: {criterion}")
            seen.add(criterion)
            low, high = item.get("score_low"), item.get("score_high")
            if low is not None and high is not None and float(low) > float(high):
                raise ValueError("Speaking score_low must not exceed score_high")
            if not any(item.get(key) is not None for key in ("score", "score_low", "score_high")):
                raise ValueError(f"Speaking {criterion} entry contains no score or range")

    evaluation = report.get("local_evaluation") or {}
    status = evaluation.get("status", "pending")
    local_scores = evaluation.get("criterion_scores", []) or []
    local_criteria = {str(item.get("criterion")) for item in local_scores}
    has_local_pron = "PRON" in local_criteria
    has_pron_evidence = bool(
        {"audio", "voice_model_observation"} & evidence_types or pronunciation_observations
    )
    if has_local_pron and not has_pron_evidence:
        raise ValueError(
            "A local PRON estimate requires audio or explicit voice-model pronunciation observations"
        )

    overall = evaluation.get("estimated_overall")
    if overall is not None and local_criteria != SPEAKING_CRITERIA:
        raise ValueError("A complete Speaking overall estimate requires FC, LR, GRA, and PRON")
    if status == "completed":
        if local_criteria != SPEAKING_CRITERIA or overall is None:
            raise ValueError("Completed local Speaking evaluation requires four criteria and overall")
        exact_scores = {
            str(item["criterion"]): item.get("score")
            for item in local_scores
        }
        if any(value is None for value in exact_scores.values()):
            raise ValueError("Completed local Speaking evaluation requires an exact score for each criterion")
        mean_score = sum(Decimal(str(value)) for value in exact_scores.values()) / Decimal("4")
        expected = float((mean_score * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
        if float(overall) != expected:
            raise ValueError(
                f"Speaking overall must be the equally weighted four-criterion result ({expected})"
            )
    elif status == "partial" and overall is not None:
        raise ValueError("A partial Speaking profile must not contain an overall estimate")

    if status in {"completed", "partial"}:
        rubric = evaluation.get("rubric") or {}
        if rubric.get("publisher") != "IELTS" or rubric.get("standard") != OFFICIAL_SPEAKING_STANDARD:
            raise ValueError("Local Speaking evaluation must cite the official IELTS Speaking standard")
        if not rubric.get("source_reference"):
            raise ValueError("Local Speaking evaluation requires an official rubric source_reference")
