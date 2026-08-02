from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .conformance import LISTENING_QUESTION_TYPES, READING_QUESTION_TYPES, assess_reading_set
from .storage import connect, initialise_database, list_content_import_jobs


# These are product inventory targets, not claims about the IELTS test format.
# "minimum" supports useful variety; "recommended" reduces repetition for a
# sustained personal study programme.
CONTENT_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "reading": {
        "label": "Academic Reading",
        "targets": [
            {"key": "verified_full_mocks", "label": "人工复核完整套题", "minimum": 8, "recommended": 20, "unit": "套"},
            {"key": "verified_passages", "label": "人工复核篇章", "minimum": 24, "recommended": 60, "unit": "篇"},
            {"key": "verified_questions", "label": "带答案与原文证据的客观题", "minimum": 320, "recommended": 800, "unit": "题"},
        ],
        "coverage": sorted(READING_QUESTION_TYPES),
        "quality_fields": ["passage", "instructions", "options", "answer_key", "evidence_location", "explanation", "word_limit"],
    },
    "listening": {
        "label": "Listening",
        "targets": [
            {"key": "verified_full_mocks", "label": "人工复核完整套题", "minimum": 8, "recommended": 20, "unit": "套"},
            {"key": "audio_backed_parts", "label": "有音频、文本与答案的 Part", "minimum": 32, "recommended": 80, "unit": "个"},
            {"key": "verified_questions", "label": "人工复核客观题", "minimum": 320, "recommended": 800, "unit": "题"},
        ],
        "coverage": sorted(LISTENING_QUESTION_TYPES),
        "quality_fields": ["audio", "transcript", "instructions", "answer_key", "timestamps", "word_limit"],
    },
    "writing": {
        "label": "Academic Writing",
        "targets": [
            {"key": "task1_prompts", "label": "完整可读 Task 1 图表题", "minimum": 56, "recommended": 105, "unit": "题"},
            {"key": "task2_prompts", "label": "人工复核 Task 2 题目", "minimum": 100, "recommended": 200, "unit": "题"},
        ],
        "coverage": ["line", "bar", "pie", "table", "map", "process", "mixed", "opinion", "discussion_opinion", "problem_solution", "advantages_disadvantages", "two_part"],
        "quality_fields": ["complete_prompt", "readable_visual", "minimum_words", "topic_tags", "review_status"],
    },
    "speaking": {
        "label": "Speaking",
        "targets": [
            {"key": "part1_topics", "label": "Part 1 主题组", "minimum": 30, "recommended": 60, "unit": "组"},
            {"key": "linked_part2_part3_sets", "label": "Part 2–3 关联题组", "minimum": 60, "recommended": 120, "unit": "组"},
            {"key": "part2_cards", "label": "结构化 Cue Cards", "minimum": 60, "recommended": 120, "unit": "张"},
        ],
        "coverage": ["home", "study", "work", "people", "places", "objects", "events", "activities", "technology", "society", "education", "environment"],
        "quality_fields": ["part", "topic", "cue_points", "speaking_set_id", "part3_link", "review_status"],
    },
}


def content_requirements() -> dict[str, Any]:
    return {"version": 1, "note": "库存数量是产品规划目标，不是 IELTS 官方规定。", "modules": CONTENT_REQUIREMENTS}


def build_content_readiness(home: Path) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        question_rows = conn.execute(
            "SELECT module,task,part,question_type,topics_text,review_status,conformance_status,payload_json FROM questions"
        ).fetchall()
        passage_rows = conn.execute("SELECT payload_json FROM question_passages").fetchall()
        pack_rows = conn.execute("SELECT module,conformance_status,payload_json FROM assessment_packs").fetchall()

    questions = [dict(row) | {"payload": json.loads(row["payload_json"])} for row in question_rows]
    packs = [dict(row) | {"payload": json.loads(row["payload_json"])} for row in pack_rows]
    passages = [json.loads(row["payload_json"]) for row in passage_rows]
    actual = {
        "reading": _reading_actual(questions, passages, packs),
        "listening": _listening_actual(questions, packs),
        "writing": _writing_actual(questions, packs),
        "speaking": _speaking_actual(questions, packs),
    }
    modules: dict[str, Any] = {}
    for module, requirement in CONTENT_REQUIREMENTS.items():
        metrics = []
        for target in requirement["targets"]:
            current = int(actual[module].get(target["key"], 0))
            minimum = int(target["minimum"])
            recommended = int(target["recommended"])
            metrics.append({
                **target,
                "current": current,
                "minimum_gap": max(0, minimum - current),
                "recommended_gap": max(0, recommended - current),
                "status": "ready" if current >= minimum else ("building" if current else "missing"),
            })
        coverage_counts = actual[module].get("coverage_counts") or {}
        missing_coverage = [value for value in requirement["coverage"] if not coverage_counts.get(value)]
        modules[module] = {
            "label": requirement["label"],
            "metrics": metrics,
            "coverage_counts": coverage_counts,
            "missing_coverage": missing_coverage,
            "quality_fields": requirement["quality_fields"],
            "ready_for_varied_practice": all(item["status"] == "ready" for item in metrics) and not missing_coverage,
        }
    imports = list_content_import_jobs(home, limit=20)
    return {
        "version": 1,
        "modules": modules,
        "imports": {
            "total": len(imports),
            "needs_structuring": sum(item["status"] == "needs_structuring" for item in imports),
            "ready_to_import": sum(item["status"] == "ready_to_import" for item in imports),
            "failed": sum(item["status"] == "failed" for item in imports),
        },
        "band_ready_pack_count": sum(
            item["conformance_status"] == "verified" and item["payload"].get("practice_mode") == "full_mock"
            for item in packs
        ),
    }


def _verified(question: dict[str, Any]) -> bool:
    return question.get("review_status") == "reviewed" and question.get("conformance_status") == "verified"


def _full_packs(packs: list[dict[str, Any]], module: str) -> list[dict[str, Any]]:
    return [item for item in packs if item["module"] == module and item["conformance_status"] == "verified" and item["payload"].get("practice_mode") == "full_mock"]


def _reading_actual(questions: list[dict[str, Any]], passages: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in questions if item["module"] == "reading"]
    verified = [item for item in rows if _verified(item)]
    passage_by_id = {str(item.get("passage_id")): item for item in passages if item.get("passage_id")}
    questions_by_passage: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        passage_id = str(item["payload"].get("passage_id") or "")
        if passage_id:
            questions_by_passage.setdefault(passage_id, []).append(item["payload"])
    verified_passage_ids = {
        passage_id
        for passage_id, passage in passage_by_id.items()
        if assess_reading_set(
            passage,
            questions_by_passage.get(passage_id, []),
        )["status"] == "verified"
    }
    return {
        "verified_full_mocks": len(_full_packs(packs, "reading")),
        "verified_passages": len(verified_passage_ids),
        "verified_questions": len(verified),
        "coverage_counts": dict(Counter(str(item.get("question_type") or "unknown") for item in verified)),
        "all_passages": len(passages),
    }


def _listening_actual(questions: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in questions if item["module"] == "listening"]
    verified = [item for item in rows if _verified(item)]
    full = _full_packs(packs, "listening")
    return {
        "verified_full_mocks": len(full),
        "audio_backed_parts": sum(len(item["payload"].get("structure", {}).get("parts") or []) for item in full),
        "verified_questions": len(verified),
        "coverage_counts": dict(Counter(str(item.get("question_type") or "unknown") for item in verified)),
    }


def _writing_actual(questions: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in questions if item["module"] == "writing" and _verified(item)]
    return {
        "task1_prompts": sum(item.get("task") == "task1" for item in rows),
        "task2_prompts": sum(item.get("task") == "task2" for item in rows),
        "verified_full_mocks": len(_full_packs(packs, "writing")),
        "coverage_counts": dict(Counter(str(item.get("question_type") or "unknown") for item in rows)),
    }


def _speaking_actual(questions: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in questions if item["module"] == "speaking" and _verified(item)]
    part1_topics = {topic for item in rows if str(item.get("part")) == "1" for topic in (item["payload"].get("topics") or [])}
    part2 = [item for item in rows if str(item.get("part")) == "2"]
    part3_sets = {str(item["payload"].get("speaking_set_id")) for item in rows if str(item.get("part")) == "3" and item["payload"].get("speaking_set_id")}
    linked = {str(item["payload"].get("speaking_set_id")) for item in part2 if item["payload"].get("speaking_set_id")} & part3_sets
    coverage = Counter(topic for item in rows for topic in (item["payload"].get("topics") or []))
    return {
        "part1_topics": len(part1_topics),
        "linked_part2_part3_sets": len(linked),
        "part2_cards": len(part2),
        "verified_full_mocks": len(_full_packs(packs, "speaking")),
        "coverage_counts": dict(coverage),
    }
