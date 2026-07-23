from __future__ import annotations

import re
import secrets
from collections import defaultdict
from pathlib import Path
from typing import Any

from .conformance import assess_pack
from .content_reviews import record_content_review
from .storage import (
    connect,
    get_assessment_pack,
    get_question_for_grading,
    initialise_database,
    upsert_assessment_pack,
)


def assemble_assessment_pack(
    home: Path,
    *,
    module: str,
    title: str,
    question_ids: list[str],
) -> dict[str, Any]:
    if module not in {"listening", "reading", "writing", "speaking"}:
        raise ValueError("Unsupported IELTS module")
    unique_ids = list(dict.fromkeys(str(value) for value in question_ids if str(value).strip()))
    if not unique_ids:
        raise ValueError("Select at least one indexed question")
    questions = [_required_question(home, question_id, module) for question_id in unique_ids]
    corpus_ids = {str(item.get("corpus_id") or "") for item in questions}
    source_types = {str(item.get("source_type") or "") for item in questions}
    if len(corpus_ids) != 1 or len(source_types) != 1:
        raise ValueError("An assessment pack cannot silently mix corpora or source types")
    rights = {str(item.get("rights_status") or "external_reference") for item in questions}
    rights_status = "local_private" if "local_private" in rights else ("external_reference" if "external_reference" in rights else "redistributable")
    pack = {
        "pack_id": _pack_id(module, title),
        "corpus_id": next(iter(corpus_ids)) or None,
        "module": module,
        "title": title.strip(),
        "practice_mode": "full_mock",
        "standard_profile": "ielts-academic",
        "standard_version": "2026-07",
        "source_type": next(iter(source_types)),
        "authenticity": _single_or_mixed(questions, "authenticity"),
        "rights_status": rights_status,
        "review_status": "in_review",
        "question_ids": unique_ids,
        "structure": _derive_structure(home, module, questions),
    }
    if module == "reading":
        pack["passage_ids"] = [item["passage_id"] for item in pack["structure"]["passages"]]
    report = assess_pack(pack)
    pack["conformance_status"] = report["status"]
    pack["conformance_report"] = report
    upsert_assessment_pack(home, pack)
    return pack


def review_assessment_pack(
    home: Path,
    pack_id: str,
    *,
    reviewer: str | None = None,
    checklist: dict[str, bool] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for explicit, auditable pack review."""
    pack = get_assessment_pack(home, pack_id)
    if not pack:
        raise ValueError(f"Unknown assessment pack: {pack_id}")
    if not reviewer or checklist is None:
        raise ValueError("Pack review requires a reviewer and completed checklist")
    record_content_review(
        home,
        target_type="assessment_pack",
        target_id=pack_id,
        reviewer=reviewer,
        decision="approved",
        checklist=checklist,
        notes=notes,
    )
    reviewed = get_assessment_pack(home, pack_id)
    if not reviewed:
        raise ValueError(f"Unknown assessment pack: {pack_id}")
    return reviewed


def _required_question(home: Path, question_id: str, module: str) -> dict[str, Any]:
    item = get_question_for_grading(home, question_id)
    if not item:
        raise ValueError(f"Unknown question: {question_id}")
    if item.get("module") != module:
        raise ValueError(f"Question {question_id} does not belong to {module}")
    return item


def _derive_structure(home: Path, module: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    if module == "reading":
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in questions:
            passage_id = str(item.get("passage_id") or "")
            if not passage_id:
                raise ValueError(f"Reading question {item['question_id']} has no passage_id")
            grouped[passage_id].append(item)
        initialise_database(home)
        passages = []
        with connect(home) as conn:
            for passage_id, rows in grouped.items():
                passage = conn.execute(
                    "SELECT body FROM question_passages WHERE passage_id=?", (passage_id,)
                ).fetchone()
                if not passage:
                    raise ValueError(f"Unknown Reading passage: {passage_id}")
                passages.append({
                    "passage_id": passage_id,
                    "question_count": len(rows),
                    "word_count": len(str(passage["body"]).split()),
                })
        return {"time_limit_minutes": 60, "passages": passages}
    if module == "listening":
        grouped = defaultdict(list)
        for item in questions:
            grouped[str(item.get("part") or "")].append(item)
        parts = []
        for part in ("1", "2", "3", "4"):
            rows = grouped.get(part, [])
            media = {str(item.get("audio_media_id") or "") for item in rows if item.get("audio_media_id")}
            parts.append({
                "part": int(part),
                "question_count": len(rows),
                "audio_media_id": next(iter(media)) if len(media) == 1 else None,
            })
        return {"audio_play_count": 1, "parts": parts}
    if module == "writing":
        rows = {str(item.get("task")): item for item in questions}
        return {"time_limit_minutes": 60, "tasks": [
            {"task": "task1", "question_id": rows.get("task1", {}).get("question_id"), "minimum_words": 150, "score_weight": 1},
            {"task": "task2", "question_id": rows.get("task2", {}).get("question_id"), "minimum_words": 250, "score_weight": 2},
        ]}
    parts = defaultdict(list)
    for item in questions:
        parts[str(item.get("part") or "")].append(item)
    part2_sets = {str(item.get("speaking_set_id")) for item in parts.get("2", []) if item.get("speaking_set_id")}
    part3_sets = {str(item.get("speaking_set_id")) for item in parts.get("3", []) if item.get("speaking_set_id")}
    return {
        "parts": [{"part": part, "question_count": len(parts.get(part, []))} for part in ("1", "2", "3")],
        "part2_part3_linked": bool(part2_sets & part3_sets),
        "part2_preparation_seconds": 60,
        "part2_speaking_seconds": {"min": 60, "max": 120},
        "total_time_minutes": {"min": 11, "max": 14},
    }


def _pack_id(module: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:48] or module
    return f"PACK-{module.upper()}-{slug}-{secrets.token_hex(3)}"


def _single_or_mixed(rows: list[dict[str, Any]], key: str) -> str:
    values = {str(item.get(key) or "unreviewed") for item in rows}
    return next(iter(values)) if len(values) == 1 else "mixed"
