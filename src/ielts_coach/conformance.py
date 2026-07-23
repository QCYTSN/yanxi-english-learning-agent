from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


STANDARD_PROFILE = {
    "profile_id": "ielts-academic",
    "version": "2026-07",
    "label": "IELTS Academic",
    "sources": {
        "listening": "https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-listening",
        "reading": "https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-reading",
        "writing": "https://ielts.org/organisations/ielts-for-organisations/test-types/ielts-academic-test/academic-test-format-in-detail",
        "speaking": "https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-speaking",
    },
}

PRACTICE_MODES = {
    "full_mock",
    "section_practice",
    "question_type_drill",
    "skill_drill",
}

READING_QUESTION_TYPES = {
    "multiple_choice",
    "true_false_not_given",
    "yes_no_not_given",
    "matching_information",
    "matching_headings",
    "matching_features",
    "matching_sentence_endings",
    "sentence_completion",
    "summary_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "diagram_label_completion",
    "short_answer",
}

LISTENING_QUESTION_TYPES = {
    "multiple_choice",
    "matching",
    "plan_labelling",
    "map_labelling",
    "diagram_labelling",
    "form_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "summary_completion",
    "sentence_completion",
    "short_answer",
}

COMPLETION_TYPES = {
    "sentence_completion",
    "summary_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "diagram_label_completion",
    "short_answer",
    "form_completion",
    "plan_labelling",
    "map_labelling",
    "diagram_labelling",
}

VALID_RIGHTS = {"redistributable", "external_reference", "local_private"}


def standard_profile() -> dict[str, Any]:
    """Return a copy so API callers cannot mutate the process-wide contract."""
    return deepcopy(STANDARD_PROFILE)


def infer_practice_mode(item: dict[str, Any]) -> str:
    declared = item.get("practice_mode")
    if declared in PRACTICE_MODES:
        return str(declared)
    module = str(item.get("module", ""))
    if module == "listening" and item.get("question_type") == "high_frequency_expression":
        return "skill_drill"
    if module in {"writing", "speaking"}:
        return "section_practice"
    return "question_type_drill"


def _answer_values(answer: Any) -> set[str]:
    values = answer if isinstance(answer, list) else [answer]
    return {str(value).strip().upper().replace(" ", "_") for value in values if value is not None}


def assess_question(question: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assess item-level IELTS compatibility without claiming whole-test authenticity."""
    errors: list[str] = []
    warnings: list[str] = []
    module = str(question.get("module", ""))
    question_type = str(question.get("question_type") or "")
    practice_mode = infer_practice_mode(question)
    source_type = str(question.get("source_type") or (manifest or {}).get("source_type") or "")
    rights = str(
        question.get("rights_status")
        or (manifest or {}).get("rights_status")
        or _rights_from_manifest(manifest)
    )

    if practice_mode not in PRACTICE_MODES:
        errors.append(f"Unsupported practice_mode: {practice_mode}")
    if module not in {"listening", "reading", "writing", "speaking"}:
        errors.append(f"Unsupported IELTS module: {module or 'missing'}")
    if not source_type:
        errors.append("source_type is required")
    if rights not in VALID_RIGHTS:
        errors.append("rights_status must declare redistributable, external_reference, or local_private")

    if practice_mode == "skill_drill":
        if question.get("band_conversion_source") or question.get("score_kind") == "answer_key_estimate":
            errors.append("Skill drills cannot claim an IELTS Band conversion")
    elif module == "reading":
        _assess_objective_question(question, question_type, READING_QUESTION_TYPES, errors, warnings)
    elif module == "listening":
        _assess_objective_question(question, question_type, LISTENING_QUESTION_TYPES, errors, warnings)
    elif module == "writing":
        _assess_writing_question(question, errors, warnings)
    elif module == "speaking":
        _assess_speaking_question(question, errors, warnings)

    review_status = str(question.get("review_status") or "unreviewed")
    if errors:
        status = "rejected"
    elif practice_mode == "skill_drill":
        status = "skill_only"
    elif review_status == "reviewed":
        status = "verified"
    else:
        status = "provisional"
        warnings.append("Human review is required before this item enters a verified pool")

    return {
        "standard_profile": STANDARD_PROFILE["profile_id"],
        "standard_version": STANDARD_PROFILE["version"],
        "practice_mode": practice_mode,
        "status": status,
        "eligible_for_band_score": practice_mode == "full_mock" and status == "verified",
        "errors": errors,
        "warnings": warnings,
    }


def enrich_question_conformance(
    question: dict[str, Any], manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    item = deepcopy(question)
    item.setdefault("practice_mode", infer_practice_mode(item))
    item.setdefault("standard_profile", STANDARD_PROFILE["profile_id"])
    item.setdefault("standard_version", STANDARD_PROFILE["version"])
    item.setdefault("rights_status", _rights_from_manifest(manifest))
    report = assess_question(item, manifest)
    declared = item.get("conformance_status")
    if declared == "verified" and report["status"] != "verified":
        raise ValueError(
            f"Question {item.get('question_id')} claims verified IELTS conformance but failed: "
            + "; ".join(report["errors"] or report["warnings"])
        )
    item["conformance_status"] = report["status"]
    item["conformance_report"] = report
    return item


def assess_reading_set(passage: dict[str, Any], questions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(questions)
    body = passage.get("body") or ""
    if isinstance(body, list):
        body = " ".join(str(value) for value in body)
    word_count = len(str(body).split())
    errors: list[str] = []
    warnings: list[str] = []
    if not 600 <= word_count <= 1100:
        errors.append(f"IELTS-style passage practice requires 600-1100 words; found {word_count}")
    if not 11 <= len(rows) <= 14:
        errors.append(f"IELTS-style passage practice requires 11-14 questions; found {len(rows)}")
    for question in rows:
        report = assess_question(question)
        errors.extend(f"{question.get('question_id')}: {message}" for message in report["errors"])
    return {
        "standard_profile": STANDARD_PROFILE["profile_id"],
        "standard_version": STANDARD_PROFILE["version"],
        "practice_mode": "section_practice",
        "status": "verified" if not errors else "provisional",
        "word_count": word_count,
        "question_count": len(rows),
        "eligible_for_band_score": False,
        "errors": errors,
        "warnings": warnings,
    }


def assess_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """Validate whole-test structure. Only verified full mocks may yield Band estimates."""
    errors: list[str] = []
    warnings: list[str] = []
    module = str(pack.get("module", ""))
    mode = str(pack.get("practice_mode", ""))
    structure = pack.get("structure") or {}
    if mode not in PRACTICE_MODES:
        errors.append(f"Unsupported practice_mode: {mode or 'missing'}")
    if str(pack.get("standard_profile")) != STANDARD_PROFILE["profile_id"]:
        errors.append("Assessment packs must use the ielts-academic standard profile")
    if mode == "full_mock":
        if module == "listening":
            parts = structure.get("parts") or []
            counts = [int(item.get("question_count", 0)) for item in parts]
            if len(parts) != 4 or counts != [10, 10, 10, 10]:
                errors.append("Listening full mock requires four 10-question parts")
            if structure.get("audio_play_count") != 1:
                errors.append("Listening full mock audio must play once only")
            if any(not item.get("audio_media_id") for item in parts):
                errors.append("Each Listening part requires a registered audio_media_id")
            if len(pack.get("question_ids") or []) != 40:
                errors.append("Listening full mock must reference exactly 40 indexed questions")
        elif module == "reading":
            passages = structure.get("passages") or []
            total_questions = sum(int(item.get("question_count", 0)) for item in passages)
            total_words = sum(int(item.get("word_count", 0)) for item in passages)
            if len(passages) != 3 or total_questions != 40:
                errors.append("Academic Reading full mock requires three passages and 40 questions")
            if not 2150 <= total_words <= 2750:
                errors.append("Academic Reading full mock requires 2150-2750 total words")
            if float(structure.get("time_limit_minutes", 0)) != 60:
                errors.append("Academic Reading full mock requires a 60-minute limit")
            if len(pack.get("passage_ids") or []) != 3 or len(pack.get("question_ids") or []) != 40:
                errors.append("Academic Reading full mock must reference three passages and 40 indexed questions")
        elif module == "writing":
            tasks = {str(item.get("task")): item for item in (structure.get("tasks") or [])}
            if set(tasks) != {"task1", "task2"}:
                errors.append("Academic Writing full mock requires Task 1 and Task 2")
            else:
                if int(tasks["task1"].get("minimum_words", 0)) != 150:
                    errors.append("Writing Task 1 requires a 150-word minimum")
                if int(tasks["task2"].get("minimum_words", 0)) != 250:
                    errors.append("Writing Task 2 requires a 250-word minimum")
                if float(tasks["task2"].get("score_weight", 0)) != 2:
                    errors.append("Writing Task 2 must carry twice the Task 1 weight")
            if float(structure.get("time_limit_minutes", 0)) != 60:
                errors.append("Academic Writing full mock requires a 60-minute limit")
            if len(pack.get("question_ids") or []) != 2:
                errors.append("Academic Writing full mock must reference exactly two indexed tasks")
        elif module == "speaking":
            parts = structure.get("parts") or []
            if [str(item.get("part")) for item in parts] != ["1", "2", "3"]:
                errors.append("Speaking full mock requires Parts 1, 2, and 3 in order")
            if not structure.get("part2_part3_linked"):
                errors.append("Speaking Part 3 must be thematically linked to Part 2")
            if int(structure.get("part2_preparation_seconds", 0)) != 60:
                errors.append("Speaking Part 2 requires 60 seconds of preparation")
            total = structure.get("total_time_minutes") or {}
            if float(total.get("min", 0)) != 11 or float(total.get("max", 0)) != 14:
                errors.append("Speaking full mock must target 11-14 minutes")
        else:
            errors.append(f"Unsupported IELTS module: {module or 'missing'}")

    rights = str(pack.get("rights_status") or "")
    if rights not in VALID_RIGHTS:
        errors.append("Assessment pack must declare a valid rights_status")
    if pack.get("review_status") != "reviewed":
        warnings.append("Assessment pack requires human review before verification")
    status = "verified" if not errors and not warnings else ("rejected" if errors else "provisional")
    return {
        "standard_profile": STANDARD_PROFILE["profile_id"],
        "standard_version": STANDARD_PROFILE["version"],
        "practice_mode": mode,
        "status": status,
        "eligible_for_band_score": mode == "full_mock" and status == "verified",
        "errors": errors,
        "warnings": warnings,
    }


def _rights_from_manifest(manifest: dict[str, Any] | None) -> str:
    if not manifest:
        return "external_reference"
    permissions = manifest.get("permissions") or {}
    if permissions.get("redistribution_allowed"):
        return "redistributable"
    if permissions.get("local_personal_use_only"):
        return "local_private"
    return str(manifest.get("rights_status") or "external_reference")


def _assess_objective_question(
    question: dict[str, Any],
    question_type: str,
    allowed: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    if question_type not in allowed:
        errors.append(f"Unsupported official question_type: {question_type or 'missing'}")
        return
    answer = question.get("correct_answer")
    if answer in {None, ""}:
        errors.append("A verified objective item requires a correct_answer")
    if question_type == "true_false_not_given":
        if not _answer_values(answer).issubset({"TRUE", "FALSE", "NOT_GIVEN"}):
            errors.append("True/False/Not Given answers must use TRUE, FALSE, or NOT GIVEN")
    if question_type == "yes_no_not_given":
        if not _answer_values(answer).issubset({"YES", "NO", "NOT_GIVEN"}):
            errors.append("Yes/No/Not Given answers must use YES, NO, or NOT GIVEN")
    if question_type == "multiple_choice" and not question.get("options"):
        errors.append("Multiple-choice items require options")
    if question_type in {"matching_headings", "matching_features", "matching_sentence_endings"} and not question.get("options"):
        errors.append(f"{question_type} requires a shared or item-level option bank")
    if question_type in COMPLETION_TYPES:
        constraints = question.get("answer_constraints") or {}
        if not constraints.get("word_limit") and not question.get("word_limit"):
            errors.append(f"{question_type} requires an explicit word limit")
    if not question.get("evidence_location"):
        warnings.append("Verified review quality requires an evidence location")


def _assess_writing_question(
    question: dict[str, Any], errors: list[str], warnings: list[str]
) -> None:
    task = str(question.get("task") or "")
    if task not in {"task1", "task2"}:
        errors.append("Academic Writing items must declare task1 or task2")
        return
    if task == "task1":
        visual = question.get("media_id") or question.get("media_ids") or question.get("task_data")
        if not visual:
            errors.append("Academic Writing Task 1 requires complete readable visual or structured data")
        if question.get("minimum_words", 150) != 150:
            errors.append("Academic Writing Task 1 minimum_words must be 150")
    else:
        if question.get("minimum_words", 250) != 250:
            errors.append("Academic Writing Task 2 minimum_words must be 250")
    if not question.get("content"):
        errors.append("Writing task prompt is required")


def _assess_speaking_question(
    question: dict[str, Any], errors: list[str], warnings: list[str]
) -> None:
    part = str(question.get("part") or "")
    if part not in {"1", "2", "3"}:
        errors.append("Speaking items must declare Part 1, 2, or 3")
        return
    if part == "2":
        task_data = question.get("task_data") or {}
        if len(task_data.get("cue_points") or []) < 3:
            warnings.append("Speaking Part 2 should store cue-card points structurally")
    if part == "3" and not (question.get("speaking_set_id") or question.get("related_part2_topic")):
        errors.append("Speaking Part 3 requires an explicit link to a Part 2 topic set")
