from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .locking import runtime_lock
from .conformance import assess_pack
from .question_bank import search_questions, show_question
from .session_io import load_session_file
from .session_manager import persist_session_atomic, start_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def speaking_questions(
    home: Path,
    *,
    part: int | None = None,
    topic: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = search_questions(home, module="speaking", topic=topic, limit=1000)
    result = []
    for row in rows:
        if part is not None and str(row.get("part")) != str(part):
            continue
        item = show_question(home, str(row["question_id"]))
        if item:
            result.append(item)
    return result[: max(1, min(int(limit), 500))]


def _draw_questions(home: Path, mode: str, seed: int | None = None) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_part = {part: speaking_questions(home, part=part, limit=500) for part in (1, 2, 3)}
    if mode == "part1":
        topic_groups: dict[str, list[dict[str, Any]]] = {}
        for question in by_part[1]:
            topic_groups.setdefault(str(question.get("topic") or "other"), []).append(question)
        eligible_topics = [topic for topic, rows in topic_groups.items() if len(rows) >= 3]
        if not eligible_topics:
            raise ValueError("A Part 1 practice requires at least three questions in one topic")
        selected = topic_groups[rng.choice(eligible_topics)]
        return rng.sample(selected, min(4, len(selected)))
    elif mode == "part2":
        return [rng.choice(by_part[2])]
    elif mode == "part3":
        set_groups: dict[str, list[dict[str, Any]]] = {}
        for question in by_part[3]:
            set_groups.setdefault(
                str(question.get("speaking_set_id") or question.get("topic") or "other"),
                [],
            ).append(question)
        eligible_sets = [key for key, rows in set_groups.items() if len(rows) >= 3]
        if not eligible_sets:
            raise ValueError("A Part 3 practice requires at least three linked questions")
        selected = set_groups[rng.choice(eligible_sets)]
        return rng.sample(selected, min(4, len(selected)))
    elif mode == "full_mock":
        topic_groups: dict[str, list[dict[str, Any]]] = {}
        for question in by_part[1]:
            topic_groups.setdefault(str(question.get("topic") or "other"), []).append(question)
        eligible_topics = [topic for topic, rows in topic_groups.items() if len(rows) >= 3]
        if len(eligible_topics) < 2:
            raise ValueError("A Speaking full flow requires at least two Part 1 topic groups")
        part1: list[dict[str, Any]] = []
        for topic in rng.sample(eligible_topics, 2):
            part1.extend(rng.sample(topic_groups[topic], 3))
        part2 = rng.choice(by_part[2])
        set_id = part2.get("speaking_set_id")
        related = [item for item in by_part[3] if item.get("speaking_set_id") == set_id]
        if len(related) < 3:
            raise ValueError("A Speaking full flow requires at least three Part 3 questions linked to Part 2")
        return part1 + [part2] + rng.sample(related, min(4, len(related)))
    else:
        raise ValueError(
            "Speaking handoff mode must be full_mock, part1, part2, or part3"
        )


def _prompt(provider: str, mode: str, questions: list[dict[str, Any]]) -> str:
    lines = [
        "You are hosting an IELTS Academic Speaking practice session.",
        "",
        "NON-NEGOTIABLE MOCK RULES",
        "1. Ask one question at a time and wait for the learner's spoken answer.",
        "2. Do not correct, hint, paraphrase the learner's answer, or give feedback during the mock.",
        "3. Keep the interaction natural, but do not replace the supplied questions.",
        "4. For Part 2, tell the learner they have one minute to prepare and up to two minutes to speak.",
        "5. You may announce time, but state clearly if your interface cannot measure it reliably.",
        "6. After the final answer, provide a transcript or structured observation report for import.",
        "7. Do not claim a Pronunciation score unless you actually observed audio evidence.",
        "8. Part 3 questions are linked to the supplied Part 2 topic; do not substitute unrelated questions.",
        "",
        f"Requested external host: {provider or 'Voice/Live service'}",
        f"Practice mode: {mode}",
        "",
        "QUESTIONS",
    ]
    current_part: str | None = None
    for question in questions:
        part = str(question.get("part"))
        if part != current_part:
            lines.extend(["", f"Part {part}"])
            current_part = part
        lines.append(f"- {question['content']}")
    lines.extend(
        [
            "",
            "REPORT HANDOFF",
            "At the end, return the transcript and distinguish direct audio observations from text-only inference.",
            "The learner will paste that result into a local IELTS learning system.",
        ]
    )
    return "\n".join(lines)


def create_speaking_handoff(
    home: Path,
    *,
    mode: str,
    provider: str = "external_voice_live",
    question_ids: list[str] | None = None,
    seed: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if question_ids:
        questions = []
        for question_id in question_ids:
            question = show_question(home, question_id)
            if not question or question.get("module") != "speaking":
                raise ValueError(f"Unknown Speaking question: {question_id}")
            questions.append(question)
    else:
        questions = _draw_questions(home, mode, seed)
    contract = _speaking_contract(mode, questions)
    path = start_session(
        home,
        "speaking",
        source_id=provider,
        mode=mode,
        assessment_contract=contract,
        idempotency_key=idempotency_key,
    )
    session_id = path.stem
    with runtime_lock(home, f"session:{session_id}"):
        data = load_session_file(path)
        if data.get("speaking_handoff"):
            data.pop("document_body", None)
            return data
        package = {
            "provider": provider,
            "mode": mode,
            "question_ids": [str(item["question_id"]) for item in questions],
            "questions": [
                {
                    "question_id": item["question_id"],
                    "part": item.get("part"),
                    "topic": item.get("topic"),
                    "content": item["content"],
                }
                for item in questions
            ],
            "practice_mode": contract["practice_mode"],
            "conformance_status": contract["conformance_status"],
            "conformance_report": contract["conformance_report"],
            "prompt": _prompt(provider, mode, questions),
            "created_at": _now(),
        }
        data["speaking_handoff"] = package
        data["status"] = "learner_working"
        data["revision"] = int(data.get("revision", 0)) + 1
        saved = persist_session_atomic(home, path, data)
    saved.pop("document_body", None)
    return saved


def _speaking_contract(mode: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    all_verified = bool(questions) and all(
        item.get("conformance_status") == "verified" for item in questions
    )
    part2 = next((item for item in questions if str(item.get("part")) == "2"), None)
    part3 = [item for item in questions if str(item.get("part")) == "3"]
    linked = bool(part2) and bool(part3) and all(
        item.get("speaking_set_id") == part2.get("speaking_set_id") for item in part3
    )
    requested_full = mode == "full_mock"
    requested_parts = [1, 2, 3] if requested_full else [
        int(mode.removeprefix("part"))
    ]
    pack = {
        "pack_id": "runtime-speaking-handoff",
        "module": "speaking",
        "title": "Runtime Speaking handoff",
        "practice_mode": "full_mock" if requested_full and all_verified else "section_practice",
        "standard_profile": "ielts-academic",
        "standard_version": "2026-07",
        "source_type": "project_original",
        "authenticity": "practice_only",
        "rights_status": "redistributable",
        "review_status": "reviewed" if all_verified else "in_review",
        "question_ids": [str(item["question_id"]) for item in questions],
        "structure": {
            "parts": [{"part": part} for part in requested_parts],
            "part1_time_minutes": {"min": 4, "max": 5},
            "part2_time_minutes": {"min": 3, "max": 4},
            "part3_time_minutes": {"min": 4, "max": 5},
            "part2_preparation_seconds": 60,
            "part2_speaking_seconds": {"min": 60, "max": 120},
            "part2_part3_linked": linked,
            "total_time_minutes": {"min": 11, "max": 14},
        },
    }
    report = assess_pack(pack)
    pack["conformance_status"] = report["status"]
    pack["conformance_report"] = report
    return pack
