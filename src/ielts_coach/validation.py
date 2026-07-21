from __future__ import annotations

import json
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import FormatChecker


def normalise_json_value(value: Any) -> Any:
    """Convert YAML-native values into JSON-schema-compatible values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): normalise_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalise_json_value(v) for v in value]
    return value


def load_schema(name: str) -> dict[str, Any]:
    path = resources.files("ielts_coach.resources").joinpath(f"schemas/{name}.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_data(data: dict[str, Any], schema_name: str) -> dict[str, Any]:
    normalised = normalise_json_value(data)
    jsonschema.validate(normalised, load_schema(schema_name), format_checker=FormatChecker())
    if schema_name == "session":
        _validate_session_semantics(normalised)
    elif schema_name == "profile":
        _validate_profile_semantics(normalised)
    elif schema_name == "calibration-record":
        low, high = normalised.get("predicted_low"), normalised.get("predicted_high")
        if low is not None and high is not None and float(low) > float(high):
            raise ValueError("predicted_low must not exceed predicted_high")
    return normalised


def _validate_session_semantics(data: dict[str, Any]) -> None:
    score = data.get("score") or {}
    if isinstance(score, dict):
        correct, total = score.get("correct"), score.get("total")
        if correct is not None and total is not None and int(correct) > int(total):
            raise ValueError("score.correct must not exceed score.total")
    module = data["module"]
    allowed_criteria = {
        "writing": {"TA", "TR", "CC", "LR", "GRA"},
        "speaking": {"FC", "LR", "GRA", "PRON"},
    }
    for item in data.get("criterion_scores", []) or []:
        low, high = item.get("score_low"), item.get("score_high")
        if low is not None and high is not None and float(low) > float(high):
            raise ValueError("criterion score_low must not exceed score_high")
        criterion = str(item.get("criterion", ""))
        if module in allowed_criteria and criterion not in allowed_criteria[module]:
            expected = ", ".join(sorted(allowed_criteria[module]))
            raise ValueError(f"Unsupported {module} criterion {criterion!r}; expected one of {expected}")

    if data.get("status", "completed") != "completed":
        return
    common_score = any(data.get(key) is not None for key in ("raw_score", "band", "estimated_overall"))
    errors = bool(data.get("errors") or data.get("error_tags"))
    if module == "reading":
        meaningful = bool(data.get("questions")) or common_score or errors or (
            isinstance(score, dict) and score.get("correct") is not None and score.get("total") is not None
        )
    elif module == "writing":
        meaningful = bool(data.get("versions") or data.get("criterion_scores")) or common_score or errors
    elif module == "speaking":
        report = data.get("speaking_report") or {}
        report_content = bool(
            report.get("parts") or report.get("transcript") or report.get("feedback")
        ) if isinstance(report, dict) else False
        meaningful = report_content or bool(data.get("criterion_scores")) or common_score or errors
    else:
        meaningful = bool(data.get("questions")) or common_score or errors
    if not meaningful:
        raise ValueError(f"Completed {module} session contains no score, attempt, feedback, or error evidence")


def _validate_profile_semantics(data: dict[str, Any]) -> None:
    allocation = data["base_allocation"]
    if abs(sum(float(value) for value in allocation.values()) - 1.0) > 1e-6:
        raise ValueError("base_allocation values must sum to 1.0")
    policy = data["allocation_policy"]
    low = float(policy["minimum_listening_reading_share"])
    base = float(policy["listening_reading_share"])
    high = float(policy["maximum_listening_reading_share"])
    if not low <= base <= high:
        raise ValueError("minimum_listening_reading_share <= listening_reading_share <= maximum_listening_reading_share is required")
    minimum = data.get("minimum_required") or {}
    target = data.get("target") or {}
    stretch = data.get("stretch_target") or {}
    for key in target:
        if minimum and float(minimum[key]) > float(target[key]):
            raise ValueError(f"minimum_required.{key} must not exceed target.{key}")
        if stretch and float(target[key]) > float(stretch[key]):
            raise ValueError(f"target.{key} must not exceed stretch_target.{key}")
