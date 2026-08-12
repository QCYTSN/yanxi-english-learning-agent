from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import FormatChecker

from .speaking_evaluation import validate_speaking_report_semantics
from .conformance import assess_pack


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


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    path = resources.files("ielts_coach.resources").joinpath(f"schemas/{name}.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema_data(data: dict[str, Any], schema_name: str) -> dict[str, Any]:
    """Validate only the JSON shape and return a normalised copy.

    Keeping structural validation separate lets the inference route reject a
    malformed provider response before running IELTS-specific policy checks.
    """
    normalised = normalise_json_value(data)
    jsonschema.validate(normalised, load_schema(schema_name), format_checker=FormatChecker())
    return normalised


def validate_data_semantics(data: dict[str, Any], schema_name: str) -> dict[str, Any]:
    """Validate deterministic domain rules for already structured data."""
    normalised = normalise_json_value(data)
    if schema_name == "session":
        _validate_session_semantics(normalised)
    elif schema_name == "profile":
        _validate_profile_semantics(normalised)
    elif schema_name == "calibration-record":
        low, high = normalised.get("predicted_low"), normalised.get("predicted_high")
        if low is not None and high is not None and float(low) > float(high):
            raise ValueError("predicted_low must not exceed predicted_high")
    elif schema_name == "speaking-report":
        validate_speaking_report_semantics(normalised)
    elif schema_name == "writing-review":
        _validate_writing_review_semantics(normalised)
    elif schema_name == "reading-review":
        _validate_reading_review_semantics(normalised)
    elif schema_name == "listening-review":
        _validate_listening_review_semantics(normalised)
    elif schema_name == "speaking-evaluation":
        _validate_speaking_evaluation_semantics(normalised)
    elif schema_name == "study-help":
        _validate_study_help_semantics(normalised)
    elif schema_name == "tutor-turn-plan":
        _validate_tutor_turn_plan_semantics(normalised)
    elif schema_name == "study-plan":
        allocation = normalised["allocation"]
        if abs(sum(float(value) for value in allocation.values()) - 1.0) > 0.001:
            raise ValueError("Study plan allocation must sum to 1")
    elif schema_name == "rubric-manifest":
        _validate_rubric_manifest_semantics(normalised)
    elif schema_name == "assessment-pack":
        report = assess_pack(normalised)
        declared = normalised.get("conformance_status")
        if declared == "verified" and report["status"] != "verified":
            raise ValueError("Assessment pack claims verified conformance but failed: " + "; ".join(report["errors"] or report["warnings"]))
    return normalised


def validate_data(data: dict[str, Any], schema_name: str) -> dict[str, Any]:
    normalised = validate_schema_data(data, schema_name)
    return validate_data_semantics(normalised, schema_name)


def _validate_writing_review_semantics(data: dict[str, Any]) -> None:
    band = data.get("estimated_band") or {}
    if float(band.get("low", 0)) > float(band.get("high", 0)):
        raise ValueError("estimated_band.low must not exceed estimated_band.high")
    expected = {"TA", "CC", "LR", "GRA"} if data["task"] == "task1" else {"TR", "CC", "LR", "GRA"}
    criteria = data.get("criteria") or []
    names = {str(item.get("criterion")) for item in criteria}
    if names != expected or len(names) != len(criteria):
        raise ValueError(f"Writing review requires exactly these criteria: {', '.join(sorted(expected))}")
    for item in criteria:
        if float(item["score_low"]) > float(item["score_high"]):
            raise ValueError("criterion score_low must not exceed score_high")
    if data["stage"] == "first_review" and data.get("full_model_answer"):
        raise ValueError("First Writing review must not reveal a full model answer before learner revision")


def _validate_reading_review_semantics(data: dict[str, Any]) -> None:
    if data["mode"] == "guided_hint":
        if data.get("answer_revealed"):
            raise ValueError("Guided Reading hints must not reveal the answer")
        if data.get("hint_level") not in {1, 2, 3}:
            raise ValueError("Guided Reading hints require hint_level 1, 2, or 3")
        for item in data.get("items") or []:
            if item.get("correct_answer") not in {None, ""}:
                raise ValueError("Guided Reading hints must not include correct_answer")
    if data["mode"] == "wrong_answer_review":
        if not data.get("answer_revealed"):
            raise ValueError("Wrong-answer review must explicitly mark answer_revealed=true")
        for item in data.get("items") or []:
            missing = [key for key in ("correct_answer", "evidence_location", "evidence", "reasoning", "next_rule") if not item.get(key)]
            if missing:
                raise ValueError(f"Wrong-answer review item is missing: {', '.join(missing)}")


def _validate_listening_review_semantics(data: dict[str, Any]) -> None:
    numbers = [str(item["question_number"]) for item in data["items"]]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Listening review question numbers must be unique")


def _validate_speaking_evaluation_semantics(data: dict[str, Any]) -> None:
    names = [item["criterion"] for item in data["criteria"]]
    if len(names) != len(set(names)):
        raise ValueError("Speaking evaluation criteria must be unique")
    if data.get("band") is not None:
        if set(names) != {"FC", "LR", "GRA", "PRON"}:
            raise ValueError("Speaking overall band requires all four criteria")
        pron = next(item for item in data["criteria"] if item["criterion"] == "PRON")
        if pron["evidence_source"] not in {
            "audio",
            "voice_model_observation",
            "mixed",
        }:
            raise ValueError(
                "Speaking overall band requires audio-based Pronunciation evidence"
            )


def _validate_study_help_semantics(data: dict[str, Any]) -> None:
    request_kind = str(data["request_kind"])
    answer_status = str(data["answer_status"])
    evidence_status = str(data["evidence_status"])
    if request_kind == "guided_hint" and answer_status != "withheld":
        raise ValueError("Guided material help must keep the answer withheld")
    if request_kind in {"close_reading", "context_analysis", "writing_feedback"}:
        if answer_status != "not_applicable":
            raise ValueError(
                "Close reading and Writing feedback do not have an answer status"
            )
    if request_kind == "teacher_dialogue":
        if answer_status != "not_applicable":
            raise ValueError("Teacher dialogue does not have an answer status")
        if evidence_status != "not_required":
            raise ValueError(
                "Teacher dialogue without a source task must mark evidence not required"
            )
    if answer_status == "verified" and (
        evidence_status != "sufficient" or not data.get("evidence")
    ):
        raise ValueError(
            "A verified answer requires sufficient, explicit evidence"
        )


def _validate_tutor_turn_plan_semantics(data: dict[str, Any]) -> None:
    calls = data.get("tool_calls") or []
    if data["status"] == "needs_tools" and not calls:
        raise ValueError("A needs_tools tutor plan must request at least one tool")
    if data["status"] != "needs_tools" and calls:
        raise ValueError("Only needs_tools tutor plans may request tools")
    call_ids = [str(item["call_id"]) for item in calls]
    if len(call_ids) != len(set(call_ids)):
        raise ValueError("Tutor tool call IDs must be unique within a planning round")


def _validate_rubric_manifest_semantics(data: dict[str, Any]) -> None:
    expected = {
        "writing": "IELTS Writing Band Descriptors",
        "speaking": "IELTS Speaking Band Descriptors",
    }
    if data["standard"] != expected[data["module"]]:
        raise ValueError(f"{data['module']} rubric must use {expected[data['module']]}")


def _validate_session_semantics(data: dict[str, Any]) -> None:
    score = data.get("score") or {}
    if isinstance(score, dict):
        correct, total = score.get("correct"), score.get("total")
        if correct is not None and total is not None and int(correct) > int(total):
            raise ValueError("score.correct must not exceed score.total")
    module = data["module"]
    practice_mode = data.get("practice_mode")
    if practice_mode == "full_mock":
        contract = data.get("assessment_contract") or {}
        if data.get("conformance_status") != "verified" or contract.get("conformance_status") != "verified":
            raise ValueError("A full IELTS mock requires a verified assessment contract")
    if practice_mode == "skill_drill" and data.get("band") is not None:
        raise ValueError("Skill drills cannot produce an IELTS Band score")
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

    if module == "writing":
        by_version: dict[str, set[str]] = {}
        for item in data.get("criterion_scores", []) or []:
            label = str(item.get("version", item.get("version_label", "final")))
            by_version.setdefault(label, set()).add(str(item.get("criterion", "")))
        if any({"TA", "TR"}.issubset(criteria) for criteria in by_version.values()):
            raise ValueError("A Writing version cannot use both Task Achievement and Task Response")
        task = data.get("task")
        all_criteria = set().union(*by_version.values()) if by_version else set()
        if task == "task1" and "TR" in all_criteria:
            raise ValueError("Academic Writing Task 1 must use Task Achievement, not Task Response")
        if task == "task2" and "TA" in all_criteria:
            raise ValueError("Academic Writing Task 2 must use Task Response, not Task Achievement")

    explicit_local_writing_estimate = (
        data.get("score_kind") == "ai_training_estimate"
        or bool(data.get("rubric"))
        or any(
            item.get("assessment_role") == "local_rubric"
            for item in (data.get("criterion_scores") or [])
        )
    )
    if module == "writing" and explicit_local_writing_estimate:
        rubric = data.get("rubric") or {}
        if rubric.get("publisher") != "IELTS" or rubric.get("standard") != "IELTS Writing Band Descriptors":
            raise ValueError("Writing estimates must cite the official IELTS Writing Band Descriptors")
        if not rubric.get("source_reference"):
            raise ValueError("Writing estimates require an official rubric source_reference")
        if data.get("band") is not None:
            task_results = data.get("writing_task_results") or {}
            if data.get("practice_mode") == "full_mock" and task_results:
                task_bands: dict[str, Decimal] = {}
                for task_name, task_criterion in (("task1", "TA"), ("task2", "TR")):
                    task_result = task_results.get(task_name) or {}
                    criteria = task_result.get("criteria") or {}
                    required = {task_criterion, "CC", "LR", "GRA"}
                    if set(criteria) != required:
                        raise ValueError(
                            f"Writing full mock {task_name} requires four exact official criterion scores"
                        )
                    mean = sum(Decimal(str(criteria[key])) for key in required) / Decimal("4")
                    expected_task = (mean * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2
                    if Decimal(str(task_result.get("band"))) != expected_task:
                        raise ValueError(
                            f"Writing full mock {task_name} band must equal {expected_task}"
                        )
                    task_bands[task_name] = expected_task
                expected_overall = (
                    ((task_bands["task1"] + task_bands["task2"] * 2) / 3) * 2
                ).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2
                if Decimal(str(data["band"])) != expected_overall:
                    raise ValueError(
                        f"Writing full mock band must use Task 1:Task 2 weighting of 1:2 ({expected_overall})"
                    )
            else:
                task = data.get("task")
                scored_version = data.get("scored_version")
                if task not in {"task1", "task2"} or not scored_version:
                    raise ValueError("A numeric Writing task estimate requires task and scored_version")
                expected_criteria = {"TA", "CC", "LR", "GRA"} if task == "task1" else {"TR", "CC", "LR", "GRA"}
                scored_items = [
                    item for item in (data.get("criterion_scores") or [])
                    if str(item.get("version", item.get("version_label", "final"))) == str(scored_version)
                ]
                exact = {str(item.get("criterion")): item.get("score") for item in scored_items}
                if set(exact) != expected_criteria or any(value is None for value in exact.values()):
                    raise ValueError(
                        "A numeric Writing task estimate requires four exact official criterion scores for scored_version"
                    )
                mean_score = sum(Decimal(str(value)) for value in exact.values()) / Decimal("4")
                expected_band = float((mean_score * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
                if float(data["band"]) != expected_band:
                    raise ValueError(
                        f"Writing task band must be the equally weighted four-criterion result ({expected_band})"
                    )

    if module == "speaking":
        score_kind = data.get("score_kind")
        if score_kind == "partial_profile" and data.get("band") is not None:
            raise ValueError("A partial Speaking profile must not contain an overall band")
        if score_kind == "ai_training_estimate":
            rubric = data.get("rubric") or {}
            if rubric.get("publisher") != "IELTS" or rubric.get("standard") != "IELTS Speaking Band Descriptors":
                raise ValueError("Speaking estimates must cite the official IELTS Speaking Band Descriptors")
            if not rubric.get("source_reference"):
                raise ValueError("Speaking estimates require an official rubric source_reference")
            local_items = [
                item for item in (data.get("criterion_scores") or [])
                if item.get("assessment_role", "local_rubric") == "local_rubric"
            ]
            exact = {str(item.get("criterion")): item.get("score") for item in local_items}
            required = {"FC", "LR", "GRA", "PRON"}
            if data.get("band") is not None:
                if set(exact) != required or any(value is None for value in exact.values()):
                    raise ValueError("A complete Speaking estimate requires four exact local criterion scores")
                pron_item = next(item for item in local_items if item.get("criterion") == "PRON")
                if pron_item.get("evidence_source") not in {"audio", "voice_model_observation", "mixed"}:
                    raise ValueError("A complete Speaking estimate requires audio-based Pronunciation evidence")
                mean_score = sum(Decimal(str(value)) for value in exact.values()) / Decimal("4")
                expected_band = float((mean_score * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
                if float(data["band"]) != expected_band:
                    raise ValueError(
                        f"Speaking band must be the equally weighted four-criterion result ({expected_band})"
                    )

    if data.get("score_kind") == "answer_key_estimate":
        if module not in {"listening", "reading"}:
            raise ValueError("answer_key_estimate is only valid for Listening or Reading")
        has_raw_result = data.get("raw_score") is not None or (
            isinstance(score, dict)
            and score.get("correct") is not None
            and score.get("total") is not None
        )
        if not has_raw_result or not data.get("answer_key_source"):
            raise ValueError("An answer-key estimate requires a raw result and answer_key_source")
        if data.get("band") is not None and not data.get("band_conversion_source"):
            raise ValueError("A derived Listening/Reading band requires band_conversion_source")
    if data.get("score_kind") == "ai_training_estimate" and module not in {"writing", "speaking"}:
        raise ValueError("ai_training_estimate is only valid for Writing or Speaking")

    if module == "reading" and data.get("mode") == "timed-practice":
        if not data.get("time_limit_minutes"):
            raise ValueError("Timed Reading practice requires time_limit_minutes")
        if not data.get("started_at"):
            raise ValueError("Timed Reading practice requires started_at")
        if int(data.get("hints_used") or 0) != 0:
            raise ValueError("Timed Reading practice cannot use progressive hints")
        if data.get("status", "completed") == "completed":
            if not data.get("submitted_at"):
                raise ValueError("Completed timed Reading practice requires submitted_at")
            if not data.get("questions"):
                raise ValueError("Completed timed Reading practice requires submitted answers")
            started = datetime.fromisoformat(str(data["started_at"]).replace("Z", "+00:00"))
            submitted = datetime.fromisoformat(str(data["submitted_at"]).replace("Z", "+00:00"))
            if submitted < started:
                raise ValueError("Reading submission cannot precede the timed Session start")
            revealed_at = data.get("answer_revealed_at")
            if revealed_at:
                revealed = datetime.fromisoformat(str(revealed_at).replace("Z", "+00:00"))
                if revealed < submitted:
                    raise ValueError("Reading answers cannot be revealed before submission")

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
        observations = report.get("source_observations") or {} if isinstance(report, dict) else {}
        report_content = bool(
            report.get("parts")
            or report.get("transcript")
            or report.get("feedback")
            or observations.get("parts")
            or observations.get("transcript")
        ) if isinstance(report, dict) else False
        meaningful = report_content or bool(data.get("criterion_scores")) or common_score or errors
    else:
        meaningful = bool(data.get("questions")) or common_score or errors
    if not meaningful:
        raise ValueError(f"Completed {module} session contains no score, attempt, feedback, or error evidence")


def _validate_profile_semantics(data: dict[str, Any]) -> None:
    exam_type = (data.get("exam") or {}).get("type")
    if exam_type not in ("academic", "none"):
        raise ValueError("exam.type must be 'academic' (IELTS) or 'none' (General English)")
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
