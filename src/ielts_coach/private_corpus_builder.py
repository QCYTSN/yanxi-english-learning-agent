from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import yaml

from .content_imports import (
    _build_reading_test_draft,
    _reading_question_header_matches,
    read_import_review_draft,
)
from .storage import get_content_import_job, update_content_import_job


GENERATED_MANIFEST = "manifest.yaml"
GENERATED_PASSAGES = "passages.jsonl"
GENERATED_QUESTIONS = "questions.jsonl"
GENERATED_PACKS = "assessment-packs.jsonl"

_KNOWN_SCOPED_BLOCKERS = {
    "speaking_part3_source_incomplete": "speaking",
    "source_answer_numbering_error": "reading",
}
_QUESTION_TYPE_MAP = {
    "multiple_choice_single": "multiple_choice",
    "multiple_choice_multiple": "multiple_choice",
    "diagram_labelling": "diagram_label_completion",
}
_COMPLETION_TYPES = {
    "sentence_completion",
    "summary_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "diagram_label_completion",
    "short_answer",
}


def build_private_corpus_package(
    home: Path,
    import_id: str,
    *,
    allow_rebuild: bool = False,
) -> dict[str, Any]:
    """Compile a reviewed local draft into a private, provisional corpus package.

    The compiler never turns OCR into a local human approval.  It only emits
    indexed, local-private content after the structural checks below pass.
    Unknown blockers stop the build.  Known source defects are isolated to the
    affected IELTS module and reported in the package summary.
    """

    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    if job["status"] == "imported" and not allow_rebuild:
        raise ValueError("Imported content packages cannot be rebuilt in place")
    if job.get("source_type") != "licensed_private":
        raise ValueError("Draft package generation is limited to licensed_private material")
    if job.get("rights_status") != "local_private":
        raise ValueError("Draft package generation requires local_private rights")

    draft = read_import_review_draft(home, import_id)
    draft = _prefer_embedded_pdf_text_for_reading(
        home,
        import_id,
        draft,
    )
    if draft.get("review_status") == "rejected":
        raise ValueError("Rejected review drafts cannot be compiled")
    blocked_modules, unknown_blockers = _blocker_scope(draft)
    if unknown_blockers:
        raise ValueError(
            "Resolve unclassified source blockers before package generation: "
            + ", ".join(unknown_blockers)
        )

    book_number = _book_number(job, draft)
    corpus_id = _corpus_id(book_number, job["title"])
    passages: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    packs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    reading = _compile_reading(
        draft,
        corpus_id=corpus_id,
        book_number=book_number,
        title=job["title"],
        blocked="reading" in blocked_modules,
    )
    passages.extend(reading["passages"])
    questions.extend(reading["questions"])
    packs.extend(reading["packs"])
    skipped.extend(reading["skipped"])

    writing = _compile_writing(
        draft,
        corpus_id=corpus_id,
        book_number=book_number,
        title=job["title"],
        blocked="writing" in blocked_modules,
    )
    questions.extend(writing["questions"])
    packs.extend(writing["packs"])
    skipped.extend(writing["skipped"])

    speaking = _compile_speaking(
        draft,
        corpus_id=corpus_id,
        book_number=book_number,
        title=job["title"],
        blocked="speaking" in blocked_modules,
    )
    questions.extend(speaking["questions"])
    packs.extend(speaking["packs"])
    skipped.extend(speaking["skipped"])

    if not questions:
        raise ValueError("The reviewed draft contains no structurally safe content to index")

    target = home / "corpus" / "inbox" / import_id
    manifest = {
        "corpus_id": corpus_id,
        "title": f"{job['title']} · local private structured edition",
        "source_type": "licensed_private",
        "authenticity": str(job.get("authenticity") or "unreviewed"),
        "standard_profile": "ielts-academic",
        "standard_version": "2026-07",
        "rights_status": "local_private",
        "storage": {"mode": "managed_local_inbox"},
        "permissions": {
            "bundled_with_project": False,
            "redistribution_allowed": False,
            "local_personal_use_only": True,
        },
        "files": [
            {"kind": "passages", "path": GENERATED_PASSAGES},
            {"kind": "questions", "path": GENERATED_QUESTIONS},
            {"kind": "assessment_packs", "path": GENERATED_PACKS},
        ],
        "generation": {
            "source_import_id": import_id,
            "review_draft_revision": int(draft.get("revision") or 0),
            "review_boundary": "provisional_until_local_human_approval",
            "excluded_source_defects": skipped,
        },
    }
    _write_jsonl(target / GENERATED_PASSAGES, passages)
    _write_jsonl(target / GENERATED_QUESTIONS, questions)
    _write_jsonl(target / GENERATED_PACKS, packs)
    (target / GENERATED_MANIFEST).write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    summary = dict(job.get("summary") or {})
    package_summary = {
        "status": "ready",
        "review_draft_revision": int(draft.get("revision") or 0),
        "corpus_id": corpus_id,
        "passage_count": len(passages),
        "question_count": len(questions),
        "assessment_pack_count": len(packs),
        "module_counts": _module_counts(questions),
        "skipped": skipped,
        "provisional": True,
    }
    summary["manifest_file"] = GENERATED_MANIFEST
    summary["structured_package"] = package_summary
    update_content_import_job(
        home,
        import_id,
        status="ready_to_import",
        error_message=None,
        summary=summary,
    )
    return {
        **package_summary,
        "manifest_file": str(target / GENERATED_MANIFEST),
    }


def _prefer_embedded_pdf_text_for_reading(
    home: Path,
    import_id: str,
    draft: dict[str, Any],
) -> dict[str, Any]:
    """Use the PDF text layer when it recovers question text missed by OCR.

    RapidOCR is usually better for prose, but it can occasionally drop a whole
    statement in tables or numbered lists.  Cambridge PDFs often retain a text
    layer that recovers those omissions.  We rebuild a candidate test from that
    layer and only use it when its measurable question coverage is better.
    """

    reading_tests = list(draft.get("reading_test_drafts") or [])
    if not reading_tests:
        return draft
    try:
        from pypdf import PdfReader
    except ImportError:
        return draft

    revised = deepcopy(draft)
    readers: dict[str, Any] = {}
    for index, current in enumerate(reading_tests):
        common = {
            key: deepcopy(current.get(key))
            for key in (
                "segment_id",
                "stored_name",
                "page_numbers",
                "source_file_sha256",
                "layout_pages",
                "review_status",
                "eligible_for_import",
            )
        }
        rebuilt_ocr = _build_reading_test_draft(
            str(current.get("raw_text") or ""),
            common,
        )
        rebuilt_ocr = _merge_reviewed_reading_metadata(rebuilt_ocr, current)
        best = (
            rebuilt_ocr
            if _reading_draft_score(rebuilt_ocr) > _reading_draft_score(current)
            else current
        )
        revised["reading_test_drafts"][index] = deepcopy(best)
        stored_name = str(current.get("stored_name") or "")
        page_numbers = [
            int(value)
            for value in (current.get("page_numbers") or [])
            if int(value) > 0
        ]
        source_path = home / "corpus" / "inbox" / import_id / stored_name
        if not stored_name or not page_numbers or not source_path.is_file():
            continue
        try:
            reader = readers.setdefault(stored_name, PdfReader(str(source_path)))
            page_text = "\n\n".join(
                str(reader.pages[number - 1].extract_text() or "")
                for number in page_numbers
                if number <= len(reader.pages)
            ).strip()
        except Exception:
            continue
        if len(page_text.split()) < 1000:
            continue
        candidate = _build_reading_test_draft(page_text, common)
        candidate = _merge_reviewed_reading_metadata(candidate, best)
        if _reading_draft_score(candidate) > _reading_draft_score(best):
            revised["reading_test_drafts"][index] = candidate
    return revised


def _merge_reviewed_reading_metadata(
    candidate: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Retain human-reviewed group metadata while replacing inferior OCR text."""

    current_groups: dict[tuple[int, int, int], dict[str, Any]] = {}
    for passage in current.get("passages") or []:
        passage_number = int(passage.get("passage_number") or 0)
        for group in passage.get("question_groups") or []:
            key = (
                passage_number,
                int(group.get("question_start") or 0),
                int(group.get("question_end") or 0),
            )
            current_groups[key] = group
    for passage in candidate.get("passages") or []:
        passage_number = int(passage.get("passage_number") or 0)
        for group in passage.get("question_groups") or []:
            key = (
                passage_number,
                int(group.get("question_start") or 0),
                int(group.get("question_end") or 0),
            )
            reviewed = current_groups.get(key)
            if not reviewed:
                continue
            if _reading_group_text_score(reviewed) > _reading_group_text_score(group):
                group["raw_text"] = str(reviewed.get("raw_text") or "")
            for field in ("question_type", "word_limit"):
                if reviewed.get(field):
                    group[field] = reviewed[field]
    for field in (
        "answer_key_segment_ids",
        "review_status",
        "eligible_for_import",
    ):
        if field in current:
            candidate[field] = deepcopy(current[field])
    return candidate


def _reading_group_text_score(group: dict[str, Any]) -> int:
    raw = str(group.get("raw_text") or "")
    question_type = _QUESTION_TYPE_MAP.get(
        str(group.get("question_type") or ""),
        str(group.get("question_type") or ""),
    )
    start = int(group.get("question_start") or 0)
    end = int(group.get("question_end") or 0)
    score = 0
    for number in range(start, end + 1):
        if _individual_question_text(
            raw,
            number,
            start=start,
            end=end,
            question_type=question_type,
        ) != f"Question {number}":
            score += 5
    score += 2 * len(re.findall(r"(?m)^\s*(?:[A-H]|i{1,3}|iv|v|vi{0,3}|ix|x)\s*$", raw, re.I))
    return score


def _reading_draft_score(reading_test: dict[str, Any]) -> int:
    passages = reading_test.get("passages") or []
    score = 100 if len(passages) == 3 else -500
    detected = {
        int(value)
        for value in (reading_test.get("detected_question_numbers") or [])
        if str(value).isdigit()
    }
    score += len(detected) * 5
    for passage in passages:
        for group in passage.get("question_groups") or []:
            question_type = _QUESTION_TYPE_MAP.get(
                str(group.get("question_type") or ""),
                str(group.get("question_type") or ""),
            )
            start = int(group.get("question_start") or 0)
            end = int(group.get("question_end") or 0)
            raw = str(group.get("raw_text") or "")
            for number in range(start, end + 1):
                content = _individual_question_text(
                    raw,
                    number,
                    start=start,
                    end=end,
                    question_type=question_type,
                )
                if content != f"Question {number}":
                    score += 3
            if question_type == "multiple_choice":
                score += sum(
                    2
                    for number in range(start, end + 1)
                    if _question_options(raw, question_type, question_number=number)
                )
    return score


def _compile_reading(
    draft: dict[str, Any],
    *,
    corpus_id: str,
    book_number: int,
    title: str,
    blocked: bool,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "passages": [],
        "questions": [],
        "packs": [],
        "skipped": [],
    }
    reading_tests = draft.get("reading_test_drafts") or []
    answer_keys = draft.get("answer_key_drafts") or []
    question_override_sets = (
        draft.get("review_annotations") or {}
    ).get("reading_question_overrides") or {}
    for index, reading_test in enumerate(reading_tests, 1):
        test_number = _test_number(title, index)
        label = f"C{book_number}-T{test_number}"
        reviewed_question_overrides = (
            question_override_sets.get(str(reading_test.get("segment_id") or ""))
            or {}
        ).get("questions") or {}
        if blocked:
            result["skipped"].append({
                "module": "reading",
                "test": test_number,
                "reason": "source_blocker",
            })
            continue
        if index > len(answer_keys):
            result["skipped"].append({
                "module": "reading",
                "test": test_number,
                "reason": "answer_key_missing",
            })
            continue
        answer_key = answer_keys[index - 1]
        if not answer_key.get("candidate_answer_mapping_complete"):
            result["skipped"].append({
                "module": "reading",
                "test": test_number,
                "reason": "answer_mapping_incomplete",
            })
            continue
        passages = reading_test.get("passages") or []
        if len(passages) != 3:
            result["skipped"].append({
                "module": "reading",
                "test": test_number,
                "reason": "passage_structure_incomplete",
            })
            continue

        answer_map = _answer_map(answer_key)
        test_passage_ids: list[str] = []
        test_question_ids: list[str] = []
        compiled_passages: list[dict[str, Any]] = []
        compiled_questions: list[dict[str, Any]] = []
        failed_reason: str | None = None
        for passage in passages:
            passage_number = int(passage.get("passage_number") or 0)
            body = _extract_passage_body(str(passage.get("raw_section") or ""))
            word_count = len(body.split())
            if passage_number not in {1, 2, 3} or not 500 <= word_count <= 1200:
                failed_reason = (
                    f"passage_{passage_number or 'unknown'}_text_unreliable"
                )
                break
            passage_id = f"{label}-R-P{passage_number}"
            test_passage_ids.append(passage_id)
            passage_title, passage_body = _passage_title_and_body(
                body,
                fallback=f"{label} Reading Passage {passage_number}",
            )
            compiled_passages.append({
                "passage_id": passage_id,
                "title": passage_title,
                "body": passage_body,
                "source_type": "licensed_private",
                "rights_status": "local_private",
                "authenticity": draft.get("authenticity"),
                "review_status": "unreviewed",
                "topics": ["academic-reading", f"book-{book_number}", f"test-{test_number}"],
                "source_import_id": draft["import_id"],
                "source_segment_id": reading_test.get("segment_id"),
                "passage_number": passage_number,
                "ocr_review_status": "structure_reviewed",
            })
            groups = passage.get("question_groups") or []
            for group_index, group in enumerate(groups, 1):
                group_id = f"{passage_id}-G{group_index:02d}"
                source_group_text = _clean_group_text(
                    str(group.get("raw_text") or ""),
                    passage_body,
                )
                question_type = _QUESTION_TYPE_MAP.get(
                    str(group.get("question_type") or ""),
                    str(group.get("question_type") or ""),
                )
                start = int(group.get("question_start") or 0)
                end = int(group.get("question_end") or 0)
                group_display_text = _question_group_display_text(
                    source_group_text,
                    question_type=question_type,
                    start=start,
                    end=end,
                )
                if not (1 <= start <= end <= 40):
                    failed_reason = "question_group_range_invalid"
                    break
                for number in range(start, end + 1):
                    answer = answer_map.get(number)
                    if not answer:
                        failed_reason = f"answer_{number}_missing"
                        break
                    question_id = f"{label}-R-Q{number:02d}"
                    test_question_ids.append(question_id)
                    content = _individual_question_text(
                        source_group_text,
                        number,
                        start=start,
                        end=end,
                        question_type=question_type,
                    )
                    reviewed_override = dict(
                        reviewed_question_overrides.get(str(number)) or {}
                    )
                    if reviewed_override.get("content"):
                        content = str(reviewed_override["content"]).strip()
                    if (
                        content == f"Question {number}"
                        and question_type not in _COMPLETION_TYPES
                    ):
                        failed_reason = f"question_{number}_prompt_missing"
                        break
                    options = _question_options(
                        source_group_text,
                        question_type,
                        question_number=number,
                    )
                    if reviewed_override.get("options"):
                        options = [
                            {
                                "key": str(item["key"]).strip(),
                                "text": str(item["text"]).strip(),
                            }
                            for item in reviewed_override["options"]
                        ]
                    if question_type == "multiple_choice" and not options:
                        failed_reason = f"question_{number}_options_missing"
                        break
                    constraints: dict[str, Any] = {}
                    word_limit = (
                        _word_limit_value(group.get("word_limit"))
                        or _word_limit_value(source_group_text)
                    )
                    if question_type in _COMPLETION_TYPES:
                        if not word_limit and not options:
                            failed_reason = f"question_{number}_word_limit_missing"
                            break
                        if word_limit:
                            constraints["word_limit"] = word_limit
                            constraints["words_from_passage"] = bool(
                                re.search(r"(?i)from the passage", source_group_text)
                            )
                    if answer.get("option_reuse_allowed") is False:
                        constraints["option_reuse_allowed"] = False
                        constraints["option_bank_id"] = answer["option_bank_id"]
                    question: dict[str, Any] = {
                        "question_id": question_id,
                        "module": "reading",
                        "question_number": number,
                        "question_type": question_type,
                        "content": content,
                        "passage_id": passage_id,
                        "source_type": "licensed_private",
                        "rights_status": "local_private",
                        "authenticity": draft.get("authenticity"),
                        "review_status": "unreviewed",
                        "practice_mode": "full_mock",
                        "standard_profile": "ielts-academic",
                        "standard_version": "2026-07",
                        "correct_answer": answer["correct_answer"],
                        "accepted_variants": answer["accepted_variants"],
                        "source_group_text": source_group_text,
                        "question_group_display_text": group_display_text,
                        "question_group_id": group_id,
                        "question_group_start": start,
                        "question_group_end": end,
                        "source_import_id": draft["import_id"],
                        "source_segment_id": reading_test.get("segment_id"),
                        "answer_source_segment_id": answer_key.get("segment_id"),
                        "topics": ["academic-reading", question_type],
                    }
                    if reviewed_override:
                        question["source_review"] = {
                            "method": str(
                                reviewed_override.get("review_method")
                                or "visual_pdf_review"
                            ),
                            "evidence_pages": [
                                int(value)
                                for value in reviewed_override.get(
                                    "evidence_pages"
                                ) or []
                            ],
                            "evidence": str(
                                reviewed_override.get("evidence") or ""
                            ).strip(),
                        }
                    evidence_location = _reading_evidence_location(
                        answer=answer,
                        passage_body=passage_body,
                        question_type=question_type,
                        content=content,
                        options=options,
                    )
                    if reviewed_override.get("evidence_location"):
                        evidence_location = str(
                            reviewed_override["evidence_location"]
                        )
                    if evidence_location:
                        question["evidence_location"] = evidence_location
                    if constraints:
                        question["answer_constraints"] = constraints
                    if options:
                        question["options"] = options
                    if answer.get("option_bank_id"):
                        question["option_bank_id"] = answer["option_bank_id"]
                    compiled_questions.append(question)
                if failed_reason:
                    break
            if failed_reason:
                break

        if failed_reason or len(test_question_ids) != 40:
            result["skipped"].append({
                "module": "reading",
                "test": test_number,
                "reason": failed_reason or "question_count_not_40",
            })
            continue
        total_words = sum(
            len("\n\n".join(item["body"]).split())
            for item in compiled_passages
        )
        practice_mode = (
            "full_mock" if 2150 <= total_words <= 2750 else "section_practice"
        )
        for question in compiled_questions:
            question["practice_mode"] = practice_mode
        result["passages"].extend(compiled_passages)
        result["questions"].extend(compiled_questions)
        result["packs"].append({
            "pack_id": f"{label}-READING",
            "module": "reading",
            "title": f"{label} Academic Reading",
            "practice_mode": practice_mode,
            "standard_profile": "ielts-academic",
            "standard_version": "2026-07",
            "source_type": "licensed_private",
            "rights_status": "local_private",
            "authenticity": draft.get("authenticity"),
            "review_status": "in_review",
            "question_ids": test_question_ids,
            "passage_ids": test_passage_ids,
            "structure": {
                "time_limit_minutes": 60,
                "source_quality_boundary": (
                    None
                    if practice_mode == "full_mock"
                    else "OCR passage word count falls outside the complete-test profile"
                ),
                "passages": [
                    {
                        "passage_id": item["passage_id"],
                        "question_count": 13 if position < 3 else 14,
                        "word_count": len(
                            "\n\n".join(item["body"]).split()
                        ),
                    }
                    for position, item in enumerate(compiled_passages, 1)
                ],
            },
        })
    return result


def _compile_writing(
    draft: dict[str, Any],
    *,
    corpus_id: str,
    book_number: int,
    title: str,
    blocked: bool,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "questions": [],
        "packs": [],
        "skipped": [],
    }
    tasks = draft.get("writing_task_drafts") or []
    for pair_index in range(0, len(tasks), 2):
        pair = tasks[pair_index:pair_index + 2]
        test_number = _test_number(title, pair_index // 2 + 1)
        label = f"C{book_number}-T{test_number}"
        if blocked or len(pair) != 2:
            result["skipped"].append({
                "module": "writing",
                "test": test_number,
                "reason": "source_blocker" if blocked else "task_pair_incomplete",
            })
            continue
        by_task = {int(item.get("task_number") or 0): item for item in pair}
        if set(by_task) != {1, 2}:
            result["skipped"].append({
                "module": "writing",
                "test": test_number,
                "reason": "task_pair_invalid",
            })
            continue
        if any(
            not str(item.get("reviewed_prompt_text") or "").strip()
            or item.get("needs_prompt_review")
            for item in by_task.values()
        ):
            result["skipped"].append({
                "module": "writing",
                "test": test_number,
                "reason": "prompt_review_incomplete",
            })
            continue
        if not by_task[1].get("media_id"):
            result["skipped"].append({
                "module": "writing",
                "test": test_number,
                "reason": "task1_visual_missing",
            })
            continue

        question_ids: list[str] = []
        for task_number in (1, 2):
            item = by_task[task_number]
            question_id = f"{label}-W-T{task_number}"
            question_ids.append(question_id)
            question: dict[str, Any] = {
                "question_id": question_id,
                "module": "writing",
                "task": f"task{task_number}",
                "question_type": f"academic_writing_task_{task_number}",
                "content": str(item["reviewed_prompt_text"]).strip(),
                "source_type": "licensed_private",
                "rights_status": "local_private",
                "authenticity": draft.get("authenticity"),
                "review_status": "unreviewed",
                "practice_mode": "full_mock",
                "standard_profile": "ielts-academic",
                "standard_version": "2026-07",
                "minimum_words": 150 if task_number == 1 else 250,
                "source_import_id": draft["import_id"],
                "source_segment_id": item.get("segment_id"),
                "prompt_review_status": item.get("prompt_review_status"),
                "topics": ["academic-writing", f"task-{task_number}"],
            }
            if task_number == 1:
                question["media_id"] = item["media_id"]
                question["media_ids"] = [item["media_id"]]
            result["questions"].append(question)
        result["packs"].append({
            "pack_id": f"{label}-WRITING",
            "module": "writing",
            "title": f"{label} Academic Writing",
            "practice_mode": "full_mock",
            "standard_profile": "ielts-academic",
            "standard_version": "2026-07",
            "source_type": "licensed_private",
            "rights_status": "local_private",
            "authenticity": draft.get("authenticity"),
            "review_status": "in_review",
            "question_ids": question_ids,
            "media_ids": [by_task[1]["media_id"]],
            "structure": {
                "time_limit_minutes": 60,
                "tasks": [
                    {
                        "task": "task1",
                        "question_id": question_ids[0],
                        "minimum_words": 150,
                        "score_weight": 1,
                    },
                    {
                        "task": "task2",
                        "question_id": question_ids[1],
                        "minimum_words": 250,
                        "score_weight": 2,
                    },
                ],
            },
        })
    return result


def _compile_speaking(
    draft: dict[str, Any],
    *,
    corpus_id: str,
    book_number: int,
    title: str,
    blocked: bool,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "questions": [],
        "packs": [],
        "skipped": [],
    }
    for index, speaking_test in enumerate(draft.get("speaking_test_drafts") or [], 1):
        test_number = _test_number(title, index)
        label = f"C{book_number}-T{test_number}"
        if blocked:
            result["skipped"].append({
                "module": "speaking",
                "test": test_number,
                "reason": "source_blocker",
            })
            continue
        parts = {
            int(item.get("part_number") or 0): item
            for item in speaking_test.get("parts") or []
        }
        if set(parts) != {1, 2, 3} or speaking_test.get("needs_question_review"):
            result["skipped"].append({
                "module": "speaking",
                "test": test_number,
                "reason": "part_structure_incomplete",
            })
            continue
        cue_card = parts[2].get("cue_card") or {}
        cue_points = [
            str(value).strip()
            for value in (
                cue_card.get("cue_points")
                or cue_card.get("prompts")
                or []
            )
            if str(value).strip()
        ]
        cue_topic = str(cue_card.get("topic") or "").strip()
        if not cue_topic or len(cue_points) < 3:
            result["skipped"].append({
                "module": "speaking",
                "test": test_number,
                "reason": "cue_card_incomplete",
            })
            continue
        set_id = f"{label}-S-SET"
        question_ids: list[str] = []
        compiled_questions: list[dict[str, Any]] = []
        for part_number in (1, 2, 3):
            part = parts[part_number]
            if part_number == 2:
                prompts = [cue_topic]
            else:
                prompts = [
                    str(value).strip()
                    for value in part.get("questions") or []
                    if str(value).strip()
                ]
            if part_number in {1, 3} and len(prompts) < 3:
                result["skipped"].append({
                    "module": "speaking",
                    "test": test_number,
                    "reason": f"part_{part_number}_question_count_incomplete",
                })
                question_ids = []
                break
            topic = _speaking_topic(part, cue_topic)
            for question_index, prompt in enumerate(prompts, 1):
                question_id = f"{label}-S-P{part_number}-Q{question_index:02d}"
                question_ids.append(question_id)
                question: dict[str, Any] = {
                    "question_id": question_id,
                    "module": "speaking",
                    "part": part_number,
                    "question_number": question_index,
                    "question_type": (
                        "cue_card" if part_number == 2 else "interview_question"
                    ),
                    "content": (
                        _cue_card_text(cue_topic, cue_points)
                        if part_number == 2
                        else prompt
                    ),
                    "topic": topic,
                    "topics": ["academic-speaking", topic],
                    "speaking_set_id": set_id,
                    "source_type": "licensed_private",
                    "rights_status": "local_private",
                    "authenticity": draft.get("authenticity"),
                    "review_status": "unreviewed",
                    "practice_mode": "full_mock",
                    "standard_profile": "ielts-academic",
                    "standard_version": "2026-07",
                    "source_import_id": draft["import_id"],
                    "source_segment_id": speaking_test.get("segment_id"),
                    "correction_during_mock": False,
                }
                if part_number == 2:
                    question["task_data"] = {
                        "topic": cue_topic,
                        "cue_points": cue_points,
                        "preparation_seconds": 60,
                        "speaking_seconds": {"min": 60, "max": 120},
                    }
                if part_number == 3:
                    question["related_part2_topic"] = cue_topic
                compiled_questions.append(question)
        if not question_ids:
            continue
        result["questions"].extend(compiled_questions)
        result["packs"].append({
            "pack_id": f"{label}-SPEAKING",
            "module": "speaking",
            "title": f"{label} Academic Speaking",
            "practice_mode": "full_mock",
            "standard_profile": "ielts-academic",
            "standard_version": "2026-07",
            "source_type": "licensed_private",
            "rights_status": "local_private",
            "authenticity": draft.get("authenticity"),
            "review_status": "in_review",
            "question_ids": question_ids,
            "structure": {
                "parts": [
                    {
                        "part": part_number,
                        "question_count": sum(
                            1
                            for question_id in question_ids
                            if f"-P{part_number}-" in question_id
                        ),
                    }
                    for part_number in (1, 2, 3)
                ],
                "part2_part3_linked": True,
                "part2_preparation_seconds": 60,
                "part2_speaking_seconds": {"min": 60, "max": 120},
                "total_time_minutes": {"min": 11, "max": 14},
            },
        })
    return result


def _answer_map(answer_key: dict[str, Any]) -> dict[int, dict[str, Any]]:
    values: dict[int, dict[str, Any]] = {}
    for item in answer_key.get("layout_answer_candidates") or []:
        number = int(item["question_number"])
        correct, variants = _answer_text_and_variants(str(item["answer_text"]))
        values[number] = {
            "correct_answer": correct,
            "accepted_variants": variants,
        }
    for item in answer_key.get("reviewed_answer_overrides") or []:
        number = int(item["question_number"])
        correct, inferred = _answer_text_and_variants(str(item["answer_text"]))
        variants = [
            *inferred,
            *[
                str(value).strip()
                for value in item.get("accepted_variants") or []
                if str(value).strip()
            ],
        ]
        values[number] = {
            "correct_answer": correct,
            "accepted_variants": list(dict.fromkeys(variants)),
        }
        if item.get("option_bank_id"):
            values[number]["option_bank_id"] = str(item["option_bank_id"])
        if item.get("option_reuse_allowed") is False:
            values[number]["option_reuse_allowed"] = False
    return values


def _answer_text_and_variants(value: str) -> tuple[str, list[str]]:
    value = " ".join(value.strip().split())
    upper = value.upper().replace("_", " ")
    if upper == "NOTGIVEN":
        return "NOT GIVEN", []
    if upper in {"TRUE", "FALSE", "YES", "NO", "NOT GIVEN"}:
        return upper, []

    variants: list[str] = []
    optional = re.fullmatch(r"\(([^()]+)\)\s+(.+)", value)
    if optional:
        prefixes = [
            part.strip()
            for part in optional.group(1).split("/")
            if part.strip()
        ]
        suffix = optional.group(2).strip()
        variants.extend([suffix, *[f"{prefix} {suffix}" for prefix in prefixes]])
        return variants[-1] if prefixes else suffix, list(dict.fromkeys(variants[:-1]))

    inline_optional = re.sub(r"\(([^()]+)\)", r"\1", value).strip()
    without_optional = re.sub(r"\([^()]+\)", "", value).strip()
    if inline_optional != value:
        variants.append(without_optional)
        value = inline_optional
    if " / " in value:
        choices = [item.strip() for item in value.split(" / ") if item.strip()]
        if choices:
            return choices[0], list(dict.fromkeys([*choices[1:], *variants]))
    return value, list(dict.fromkeys(item for item in variants if item))


def _word_limit_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").upper()
    direct = re.search(r"\b([1-5])\b", text)
    if direct:
        return int(direct.group(1))
    words = {
        "ONE": 1,
        "TWO": 2,
        "THREE": 3,
        "FOUR": 4,
        "FIVE": 5,
    }
    for word, number in words.items():
        if re.search(rf"\b{word}\b", text):
            return number
    return None


def _extract_passage_body(raw_section: str) -> str:
    text = _normalise_ocr_text(raw_section)
    candidates: list[str] = []
    matches = _reading_question_header_matches(
        text,
        minimum_question_number=1,
        maximum_question_number=40,
    )
    if matches:
        prefix = text[:matches[0][0].start()].strip()
        if prefix:
            candidates.append(prefix)
    candidates.extend(_reading_marker_candidates(text))
    candidates.extend(_labelled_passage_candidates(text))
    if not candidates:
        candidates.append(text)
    viable = [
        _strip_passage_noise(value)
        for value in candidates
        if len(value.split()) >= 350
    ]
    if not viable:
        viable = [_strip_passage_noise(max(candidates, key=lambda item: len(item.split())))]
    return max(viable, key=lambda item: len(item.split())).strip()


def _reading_marker_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"(?im)^\s*Reading\s*$", text):
        tail = text[match.end():].strip()
        next_question = _reading_question_header_matches(
            tail,
            minimum_question_number=1,
            maximum_question_number=40,
        )
        if next_question:
            tail = tail[:next_question[0][0].start()]
        if tail:
            candidates.append(tail)
    return candidates


def _labelled_passage_candidates(text: str) -> list[str]:
    labels = list(re.finditer(r"(?m)^\s*([A-I])\s*$", text))
    if len(labels) < 4:
        return []
    candidates: list[str] = []
    for start_index in range(len(labels)):
        expected = ord(labels[start_index].group(1))
        end_index = start_index
        while (
            end_index + 1 < len(labels)
            and ord(labels[end_index + 1].group(1)) == expected + 1
        ):
            expected += 1
            end_index += 1
        if end_index - start_index + 1 < 4:
            continue
        start = labels[start_index].start()
        end = (
            labels[end_index + 1].start()
            if end_index + 1 < len(labels)
            else len(text)
        )
        value = text[start:end]
        next_question = _reading_question_header_matches(
            value,
            minimum_question_number=1,
            maximum_question_number=40,
        )
        if next_question:
            value = value[:next_question[0][0].start()]
        candidates.append(value)
    return candidates


def _strip_passage_noise(text: str) -> str:
    text = re.sub(
        r"(?is)^\s*(?:READING[\s-]*PASSAGE\s*\d+|reading-passage\d+)\s*",
        "",
        text,
        count=1,
    )
    text = re.sub(
        r"(?is)^\s*You should spend about 20 minutes on Questions.*?"
        r"Passage\s*\d+(?:\s+(?:below|on pages?[^.]*))?\.\s*",
        "",
        text,
        count=1,
    )
    lines = [line.strip() for line in text.splitlines()]
    ignored = re.compile(
        r"(?i)^(reading passage \d|you should spend about 20 minutes|"
        r"questions \d|test \d|reading|p\.\s*\d+)$"
    )
    lines = [
        line
        for line in lines
        if not (
            ignored.fullmatch(line)
            or re.fullmatch(r"\d{1,3}", line)
        )
    ]
    while lines and (not lines[0] or ignored.match(lines[0])):
        lines.pop(0)
    while lines and (
        not lines[-1]
        or re.fullmatch(r"\d{1,3}", lines[-1])
        or re.fullmatch(r"(?i)test \d", lines[-1])
    ):
        lines.pop()
    return "\n".join(lines)


def _passage_title_and_body(text: str, *, fallback: str) -> tuple[str, list[str]]:
    lines = [
        line.strip()
        for line in text.splitlines()
        if not (
            re.fullmatch(r"\s*\d{1,3}\s*", line)
            or re.fullmatch(r"(?i)\s*(?:reading|test \d|p\.\s*\d+)\s*", line)
        )
    ]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    title = fallback
    if lines:
        candidate = lines[0]
        if (
            3 <= len(candidate) <= 140
            and len(candidate.split()) <= 16
            and not re.fullmatch(r"[A-I]", candidate)
        ):
            title = candidate
            lines = lines[1:]
    body_text = "\n".join(lines).strip() or text.strip()
    labelled = re.split(r"(?m)^\s*([A-I])\s*$", body_text)
    if len(labelled) >= 9:
        paragraphs: list[str] = []
        prefix = _join_wrapped_lines(labelled[0].splitlines())
        if prefix:
            paragraphs.append(prefix)
        for index in range(1, len(labelled), 2):
            label = labelled[index].strip()
            value = (
                _join_wrapped_lines(labelled[index + 1].splitlines())
                if index + 1 < len(labelled)
                else ""
            )
            if value:
                paragraphs.append(f"{label}. {value}")
        return title, paragraphs
    paragraphs = _reflow_passage_paragraphs(body_text)
    return title, paragraphs or [body_text]


def _reflow_passage_paragraphs(body_text: str) -> list[str]:
    lines = [line.strip() for line in body_text.splitlines()]
    lengths = [len(line) for line in lines if len(line) >= 30]
    typical = float(median(lengths)) if lengths else 80.0
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current and _line_ends_sentence(current[-1]):
                paragraphs.append(_join_wrapped_lines(current))
                current = []
            continue
        if (
            current
            and _line_ends_sentence(current[-1])
            and len(current[-1]) <= typical * 0.90
            and re.match(r"^[\"'‘“(]?[A-Z0-9]", line)
        ):
            paragraphs.append(_join_wrapped_lines(current))
            current = []
        current.append(line)
    if current:
        paragraphs.append(_join_wrapped_lines(current))
    return [value for value in paragraphs if value]


def _line_ends_sentence(value: str) -> bool:
    return bool(re.search(r"[.!?][\"'’”)]?$", value.strip()))


def _join_wrapped_lines(lines: Iterable[str]) -> str:
    result = ""
    for raw in lines:
        line = str(raw).strip()
        if not line:
            continue
        if result.endswith("-") and re.match(r"^[a-z]", line):
            result = result[:-1] + line
        else:
            result = f"{result} {line}".strip()
    result = re.sub(r"\s+([,.;:?!])", r"\1", result)
    result = re.sub(r"([(\[]) +", r"\1", result)
    return result.strip()


def _clean_group_text(group_text: str, passage_body: Iterable[str] | str) -> str:
    text = _normalise_ocr_text(group_text).strip()
    embedded_passage_candidates = [
        *_reading_marker_candidates(text),
        *_labelled_passage_candidates(text),
    ]
    passage_starts = [
        text.find(candidate)
        for candidate in embedded_passage_candidates
        if len(candidate.split()) >= 400 and text.find(candidate) > 0
    ]
    if passage_starts:
        text = text[:min(passage_starts)].strip()
    body = (
        "\n\n".join(str(item) for item in passage_body)
        if not isinstance(passage_body, str)
        else passage_body
    )
    if body and body in text:
        text = text.replace(body, "", 1).strip()
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _individual_question_text(
    group_text: str,
    question_number: int,
    *,
    start: int,
    end: int,
    question_type: str,
) -> str:
    if question_type in {
        "true_false_not_given",
        "yes_no_not_given",
        "matching_information",
        "matching_features",
        "matching_sentence_endings",
    }:
        statements = _numbered_statement_items(group_text, start=start, end=end)
        if question_number in statements:
            return statements[question_number]
    if question_type == "matching_headings" and end - start <= 8:
        return f"Paragraph {chr(ord('A') + question_number - start)}"
    if (
        question_type == "multiple_choice"
        and re.search(r"(?i)Choose\s+(?:TWO|THREE)\s+letters", group_text)
    ):
        stem = re.search(
            r"(?im)^\s*((?:Which|What)\s+(?:TWO|THREE)\b[^\n]*"
            r"(?:\n(?!\s*[A-H]\s*$).*)?)",
            group_text,
        )
        if stem:
            return _clean_question_fragment(stem.group(1))
    starts: list[tuple[int, int]] = []
    for number in range(start, end + 1):
        match = re.search(
            rf"(?m)^\s*{number}\s*(?:[.)]\s*|\s+)(?=\S)",
            group_text,
        )
        if match:
            starts.append((number, match.start()))
    positions = {number: position for number, position in starts}
    if question_number in positions:
        position = positions[question_number]
        later = [
            next_position
            for number, next_position in starts
            if number > question_number and next_position > position
        ]
        value = group_text[position:min(later) if later else len(group_text)]
        value = re.sub(
            rf"^\s*{question_number}\s*[.)]?\s*",
            "",
            value,
        ).strip()
        value = _trim_option_bank(value)
        if value and len(value) <= 1200:
            return _clean_question_fragment(value)
    if question_type in _COMPLETION_TYPES:
        lines = [
            line.strip()
            for line in group_text.splitlines()
            if line.strip()
            and not re.match(
                r"(?i)^(questions?\b|complete\b|choose\b|write your answers?\b|"
                r"in boxes?\b)",
                line.strip(),
            )
        ]
        for index, line in enumerate(lines):
            if not re.search(rf"(?<!\d){question_number}(?!\d)", line):
                continue
            collected = [line]
            if len(line.split()) < 7:
                for following in lines[index + 1:index + 3]:
                    if re.search(r"(?<!\d)(?:[1-9]|[1-3]\d|40)(?!\d)", following):
                        break
                    collected.append(following)
                    if _line_ends_sentence(following):
                        break
            value = _clean_question_fragment(" ".join(collected))
            if value:
                return value
    return f"Question {question_number}"


def _numbered_statement_items(
    group_text: str,
    *,
    start: int,
    end: int,
) -> dict[int, str]:
    marker = re.compile(r"(?m)^\s*(\d{1,2})\s*(?:[.)]\s*|\s+)?$")
    inline = re.compile(r"(?m)^\s*(\d{1,2})\s+(?=[A-Z\"'‘“])")
    matches = sorted(
        [*marker.finditer(group_text), *inline.finditer(group_text)],
        key=lambda item: item.start(),
    )
    matches = [
        match
        for match in matches
        if start <= int(match.group(1)) <= end
    ]
    result: dict[int, str] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        limit = matches[index + 1].start() if index + 1 < len(matches) else len(group_text)
        value = group_text[match.end():limit]
        value = re.sub(r"(?im)^\s*(?:reading|test \d|\d{1,3})\s*$", "", value)
        joined = _join_wrapped_lines(value.splitlines())
        units = [
            _clean_question_fragment(item)
            for item in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'‘“])", joined)
            if _clean_question_fragment(item)
        ]
        if not units:
            continue
        result[number] = units[0]
        next_number = number + 1
        for extra in units[1:]:
            while next_number in result and next_number <= end:
                next_number += 1
            if next_number <= end and next_number not in {int(item.group(1)) for item in matches}:
                result[next_number] = extra
                next_number += 1
    return result


def _clean_question_fragment(value: str) -> str:
    value = re.sub(r"[.…·_]{3,}", " ______ ", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:?!])", r"\1", value)
    return value.strip(" -")


def _trim_option_bank(value: str) -> str:
    match = re.search(r"(?m)^\s*A\s*$", value)
    return value[:match.start()].strip() if match else value.strip()


def _question_options(
    group_text: str,
    question_type: str,
    *,
    question_number: int | None = None,
) -> list[dict[str, str]]:
    if question_type in {"true_false_not_given", "yes_no_not_given"}:
        return []
    if question_type not in {
        "multiple_choice",
        "matching_information",
        "matching_headings",
        "matching_features",
        "matching_sentence_endings",
        *_COMPLETION_TYPES,
    }:
        return []
    option_source = (
        _question_segment(group_text, question_number)
        if question_type == "multiple_choice" and question_number is not None
        else group_text
    )
    roman_options = _parse_roman_options(option_source)
    if roman_options and question_type == "matching_headings":
        return roman_options
    letter_options = _parse_letter_options(option_source)
    if letter_options:
        return letter_options
    roman = re.search(
        r"(?i)\bi\s*[—–-]\s*(i{1,3}|iv|v|vi{0,3}|ix|x)\b",
        group_text,
    )
    if roman and question_type == "matching_headings":
        end = _roman_to_int(roman.group(1))
        return [
            {"key": _int_to_roman(value), "text": _int_to_roman(value)}
            for value in range(1, end + 1)
        ]
    letter_range = re.search(r"\bA\s*[—–-]\s*([A-Z])\b", group_text)
    if question_type in _COMPLETION_TYPES and not (
        letter_range
        or re.search(r"(?i)using the list of (?:words|phrases)", group_text)
    ):
        return []
    end = letter_range.group(1) if letter_range else (
        "E" if re.search(r"(?i)\bA\s*,\s*B\s*,\s*C\s*,\s*D\s+or\s+E", group_text)
        else "D"
    )
    return [
        {"key": chr(value), "text": chr(value)}
        for value in range(ord("A"), ord(end) + 1)
    ]


def _question_segment(group_text: str, question_number: int | None) -> str:
    if question_number is None:
        return group_text
    marker = re.search(
        rf"(?m)^[ \t]*{question_number}[ \t]*(?:[.)][ \t]*|[ \t]+)(?=\S)",
        group_text,
    )
    if not marker:
        return group_text
    following = re.search(
        rf"(?m)^[ \t]*(?:{question_number + 1})[ \t]*"
        rf"(?:[.)][ \t]*|[ \t]+)(?=\S)",
        group_text[marker.end():],
    )
    end = marker.end() + following.start() if following else len(group_text)
    return group_text[marker.start():end]


def _question_group_display_text(
    group_text: str,
    *,
    question_type: str,
    start: int,
    end: int,
) -> str:
    """Keep task instructions/context while avoiding duplicated question lists."""

    text = group_text.strip()
    if not text:
        return ""
    text = re.sub(
        r"(?im)(?:\n|\A)[ \t]*(?:reading|test[ \t]+\d+|p\.[ \t]*\d+|"
        r"[鈫→]\s*p\.[ \t]*\d+)[ \t]*(?=\n|\Z)",
        "\n",
        text,
    ).strip()
    text = re.sub(r"(?m)\n[ \t]*\d{1,3}[ \t]*\Z", "", text).strip()
    if question_type in _COMPLETION_TYPES:
        return text

    markers: list[int] = []
    for number in range(start, end + 1):
        match = re.search(
            rf"(?m)^[ \t]*{number}(?:[ \t]+|[.)][ \t]*)(?=\S)",
            text,
        )
        if match:
            markers.append(match.start())
    if markers:
        return text[:min(markers)].strip()

    if question_type == "multiple_choice":
        first_option = re.search(r"(?m)^[ \t]*A[ \t]*$", text)
        if first_option:
            return text[:first_option.start()].strip()
    return text


def _parse_letter_options(value: str) -> list[dict[str, str]]:
    separate = _parse_separate_option_lines(value, roman=False)
    if separate:
        return separate
    matches = list(
        re.finditer(
            r"(?m)^\s*([A-H])\s*(?:[.)]\s*|\s+)(\S.*)$",
            value,
        )
    )
    options: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        text = match.group(2).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        continuation = value[match.end():end].strip()
        if continuation and not re.search(r"(?m)^\s*\d+\s", continuation):
            text = _join_wrapped_lines([text, continuation])
        text = _clean_question_fragment(text)
        if text:
            options.append({"key": match.group(1), "text": text})
    unique = {item["key"]: item for item in options}
    return list(unique.values()) if len(unique) >= 2 else []


def _parse_roman_options(value: str) -> list[dict[str, str]]:
    separate = _parse_separate_option_lines(value, roman=True)
    if separate:
        return separate
    matches = list(
        re.finditer(
            r"(?im)^\s*(i{1,3}|iv|v|vi{0,3}|ix|x)\s+(?![—–-])(\S.*)$",
            value,
        )
    )
    options: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        text = match.group(2).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        continuation = value[match.end():end].strip()
        if continuation and not re.search(r"(?m)^\s*\d+\s", continuation):
            text = _join_wrapped_lines([text, continuation])
        text = _clean_question_fragment(text)
        if text:
            options.append({"key": match.group(1).lower(), "text": text})
    unique = {item["key"]: item for item in options}
    return list(unique.values()) if len(unique) >= 2 else []


def _parse_separate_option_lines(
    value: str,
    *,
    roman: bool,
) -> list[dict[str, str]]:
    key_pattern = (
        re.compile(r"(?i)^(i{1,3}|iv|v|vi{0,3}|ix|x)$")
        if roman
        else re.compile(r"^([A-H])$")
    )
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    options: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        match = key_pattern.fullmatch(lines[index])
        if not match:
            index += 1
            continue
        key = match.group(1).lower() if roman else match.group(1)
        collected: list[str] = []
        index += 1
        while index < len(lines) and not key_pattern.fullmatch(lines[index]):
            if re.match(r"^\d{1,2}\s*(?:[.)]|\s)", lines[index]):
                break
            collected.append(lines[index])
            index += 1
        text = _clean_question_fragment(_join_wrapped_lines(collected))
        if text:
            options.append({"key": key, "text": text})
    unique = {item["key"]: item for item in options}
    return list(unique.values()) if len(unique) >= 2 else []


def _reading_evidence_location(
    *,
    answer: dict[str, Any],
    passage_body: list[str],
    question_type: str,
    content: str,
    options: list[dict[str, str]],
) -> str | None:
    correct = str(answer.get("correct_answer") or "").strip()
    if not correct:
        return None
    if question_type == "matching_information" and re.fullmatch(r"[A-I]", correct.upper()):
        return f"Paragraph {correct.upper()}"
    if question_type == "matching_headings":
        paragraph = re.search(r"(?i)\bparagraph\s+([A-I])\b", content)
        if paragraph:
            return f"Paragraph {paragraph.group(1).upper()}"

    candidates = [
        correct,
        *[
            str(value)
            for value in (answer.get("accepted_variants") or [])
            if str(value).strip()
        ],
    ]
    for index, paragraph in enumerate(passage_body, 1):
        for candidate in candidates:
            if len(candidate) < 2 or re.fullmatch(r"[A-Z]|[ivx]+", candidate, re.I):
                continue
            if re.search(rf"(?i)(?<!\w){re.escape(candidate)}(?!\w)", paragraph):
                return _paragraph_location(paragraph, index)

    option_text = next(
        (
            item["text"]
            for item in options
            if str(item["key"]).casefold() == correct.casefold()
        ),
        "",
    )
    query_tokens = _evidence_tokens(f"{content} {option_text}")
    if not query_tokens:
        return None
    scored: list[tuple[int, int, str]] = []
    for index, paragraph in enumerate(passage_body, 1):
        paragraph_tokens = _evidence_tokens(paragraph)
        overlap = len(query_tokens & paragraph_tokens)
        scored.append((overlap, index, paragraph))
    overlap, index, paragraph = max(scored, default=(0, 0, ""))
    return _paragraph_location(paragraph, index) if overlap >= 2 else None


def _paragraph_location(paragraph: str, index: int) -> str:
    labelled = re.match(r"^\s*([A-I])\.\s+", paragraph)
    return f"Paragraph {labelled.group(1)}" if labelled else f"Paragraph {index}"


def _evidence_tokens(value: str) -> set[str]:
    stop = {
        "about", "after", "before", "below", "choose", "correct", "from",
        "given", "information", "into", "most", "only", "passage", "question",
        "statement", "that", "their", "there", "these", "they", "this", "what",
        "when", "where", "which", "with", "would",
    }
    return {
        token
        for token in re.findall(r"[A-Za-z]{3,}", value.casefold())
        if token not in stop
    }


def _speaking_topic(part: dict[str, Any], fallback: str) -> str:
    raw = str(part.get("raw_text") or "")
    match = re.search(r"(?i)PART\s+[13]\s*[—–-]\s*([^\n]+)", raw)
    return (match.group(1).strip() if match else fallback).strip()


def _cue_card_text(topic: str, points: list[str]) -> str:
    return "\n".join([
        topic,
        "You should say:",
        *[f"• {point}" for point in points],
    ])


def _blocker_scope(draft: dict[str, Any]) -> tuple[set[str], list[str]]:
    modules: set[str] = set()
    unknown: list[str] = []
    for issue in draft.get("review_issues") or []:
        if issue.get("severity") != "blocker" or issue.get("status") == "resolved":
            continue
        code = str(issue.get("code") or "unknown")
        module = _KNOWN_SCOPED_BLOCKERS.get(code)
        if module:
            modules.add(module)
        else:
            unknown.append(code)
    return modules, unknown


def _book_number(job: dict[str, Any], draft: dict[str, Any]) -> int:
    combined = f"{job.get('title', '')} {draft.get('title', '')}"
    match = re.search(r"(?i)(?:cambridge|book|c)\s*(1[5-9]|20|21)\b", combined)
    if match:
        return int(match.group(1))
    segment = next(iter(draft.get("segments") or []), {})
    match = re.match(r"(1[5-9]|20|21)", str(segment.get("segment_id") or ""))
    if not match:
        raise ValueError("Could not determine Cambridge book number from the local draft")
    return int(match.group(1))


def _test_number(title: str, fallback: int) -> int:
    match = re.search(r"(?i)\btest\s*([1-4])\b", title)
    return int(match.group(1)) if match else fallback


def _corpus_id(book_number: int, title: str) -> str:
    test_match = re.search(r"(?i)\btest\s*([1-4])\b", title)
    suffix = f"-test-{test_match.group(1)}" if test_match else ""
    return f"cambridge-{book_number}-private{suffix}"


def _module_counts(questions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in questions:
        module = str(item.get("module") or "unknown")
        counts[module] = counts.get(module, 0) + 1
    return counts


def _normalise_ocr_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _roman_to_int(value: str) -> int:
    values = {"I": 1, "V": 5, "X": 10}
    total = 0
    previous = 0
    for character in reversed(value.upper()):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def _int_to_roman(value: int) -> str:
    numerals = [
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ]
    result = ""
    for number, numeral in numerals:
        while value >= number:
            result += numeral
            value -= number
    return result


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
