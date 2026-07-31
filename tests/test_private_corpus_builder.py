from __future__ import annotations

import json
from pathlib import Path

import pytest

from ielts_coach.conformance import assess_question
from ielts_coach.content_imports import (
    _validate_review_annotation,
    create_import,
    process_import,
)
from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import show_reading_set
from ielts_coach.private_corpus_builder import (
    _answer_text_and_variants,
    _extract_passage_body,
    _individual_question_text,
    _passage_title_and_body,
    _question_group_display_text,
    _question_options,
    build_private_corpus_package,
)
from ielts_coach.storage import (
    get_content_import_job,
    upsert_passage,
    upsert_question,
)


def test_passage_compiler_removes_timing_header_but_keeps_source_text() -> None:
    body = _extract_passage_body(
        "\n".join([
            "READING PASSAGE 1",
            "You should spend about 20 minutes on Questions 1-13, which are based on Reading",
            "Passage 1 below.",
            "A useful title",
            *["This is passage evidence with enough words to remain intact."] * 90,
            "Questions 1-4",
            "Complete the notes below.",
        ])
    )

    assert body.startswith("A useful title")
    assert "You should spend about 20 minutes" not in body
    assert "Questions 1-4" not in body


def test_answer_compiler_preserves_optional_and_alternative_forms() -> None:
    answer, variants = _answer_text_and_variants("(its / huarango / the) branches")
    assert answer == "the branches"
    assert {"branches", "its branches", "huarango branches"}.issubset(set(variants))
    assert _answer_text_and_variants("NOTGIVEN") == ("NOT GIVEN", [])


def test_passage_compiler_reflows_pdf_lines_into_real_paragraphs() -> None:
    title, paragraphs = _passage_title_and_body(
        "\n".join([
            "A useful title",
            "The first paragraph begins here and continues across a deliberately long PDF line that",
            "wraps onto the next extracted line before reaching its conclusion.",
            "A second paragraph starts with a capital letter and also continues across a long line that",
            "wraps before it reaches the final sentence.",
            "17",
            "Reading",
        ]),
        fallback="Fallback",
    )
    assert title == "A useful title"
    assert paragraphs == [
        (
            "The first paragraph begins here and continues across a deliberately long "
            "PDF line that wraps onto the next extracted line before reaching its conclusion."
        ),
        (
            "A second paragraph starts with a capital letter and also continues across a "
            "long line that wraps before it reaches the final sentence."
        ),
    ]


def test_question_compiler_recovers_statement_and_option_text() -> None:
    block = "\n".join([
        "Questions 5-7",
        "Do the following statements agree with the passage?",
        "5 In the Middle Ages, most Europeans knew where nutmeg was grown.",
        "6 The VOC was the world's first major trading company.",
        "7 Following the treaty, the Dutch controlled every island.",
    ])
    assert _individual_question_text(
        block,
        5,
        start=5,
        end=7,
        question_type="true_false_not_given",
    ) == "In the Middle Ages, most Europeans knew where nutmeg was grown."

    multiple_choice = "\n".join([
        "Questions 14-15",
        "14 What is the writer's main point?",
        "A The original plan was too expensive.",
        "B The revised plan had wider support.",
        "C No plan was ever proposed.",
        "15 What happened next?",
        "A Funding stopped.",
        "B Research continued.",
        "C The site closed.",
    ])
    assert _question_options(
        multiple_choice,
        "multiple_choice",
        question_number=14,
    ) == [
        {"key": "A", "text": "The original plan was too expensive."},
        {"key": "B", "text": "The revised plan had wider support."},
        {"key": "C", "text": "No plan was ever proposed."},
    ]


def test_reading_question_override_requires_source_evidence_page() -> None:
    cleaned = _validate_review_annotation(
        "reading_question_overrides",
        {
            "questions": {
                "2": {
                    "content": "A visually recovered statement.",
                    "evidence_pages": [63],
                    "evidence_location": "Paragraph 2",
                    "evidence": "Compared with the source PDF.",
                }
            }
        },
        page_numbers={62, 63, 64},
    )
    assert cleaned["questions"]["2"]["content"] == (
        "A visually recovered statement."
    )
    assert cleaned["questions"]["2"]["evidence_pages"] == [63]
    assert cleaned["questions"]["2"]["evidence_location"] == "Paragraph 2"


def test_question_group_display_does_not_repeat_non_completion_items() -> None:
    raw = "\n".join([
        "Questions 1-2",
        "Do the following statements agree with the passage?",
        "1 First statement.",
        "2 Second statement.",
    ])
    assert _question_group_display_text(
        raw,
        question_type="true_false_not_given",
        start=1,
        end=2,
    ) == (
        "Questions 1-2\n"
        "Do the following statements agree with the passage?"
    )


def test_completion_from_supplied_list_does_not_require_word_limit() -> None:
    report = assess_question({
        "question_id": "Q1",
        "module": "reading",
        "question_type": "summary_completion",
        "content": "Choose from the supplied list.",
        "correct_answer": "A",
        "options": [{"key": "A", "text": "A"}, {"key": "B", "text": "B"}],
        "source_type": "licensed_private",
        "rights_status": "local_private",
        "practice_mode": "question_type_drill",
    })
    assert not report["errors"]


def test_reading_api_shape_normalises_passage_paragraph_list(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    upsert_passage(home, {
        "passage_id": "P-LIST-BODY",
        "title": "Passage",
        "body": ["Paragraph A.", "Paragraph B."],
        "source_type": "licensed_private",
    })
    upsert_question(home, {
        "question_id": "Q-LIST-BODY",
        "module": "reading",
        "passage_id": "P-LIST-BODY",
        "question_number": 1,
        "question_type": "short_answer",
        "content": "Question",
        "correct_answer": "answer",
        "source_type": "licensed_private",
        "content_hash": "a" * 64,
    })

    reading_set = show_reading_set(home, "P-LIST-BODY")
    assert reading_set is not None
    assert reading_set["passage"]["body"] == "Paragraph A.\n\nParagraph B."


def test_reviewed_private_draft_builds_and_imports_provisional_package(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    job = create_import(
        home,
        title="Cambridge IELTS 15 Academic PDF",
        source_type="licensed_private",
        authenticity="unreviewed_official_practice_book",
        rights_status="local_private",
        files=[("15.pdf", b"%PDF-1.4\n", "application/pdf")],
    )
    draft = {
        "draft_version": 1,
        "revision": 4,
        "import_id": job["import_id"],
        "title": job["title"],
        "source_type": "licensed_private",
        "authenticity": "unreviewed_official_practice_book",
        "rights_status": "local_private",
        "review_status": "in_review",
        "eligible_for_import": False,
        "review_issues": [],
        "segments": [{"segment_id": "15:writing_task_1:1-1:1"}],
        "reading_test_drafts": [],
        "answer_key_drafts": [],
        "writing_task_drafts": [
            {
                "segment_id": "15:writing_task_1:1-1:1",
                "task_number": 1,
                "reviewed_prompt_text": "WRITING TASK 1\nSummarise the chart.\nWrite at least 150 words.",
                "needs_prompt_review": False,
                "prompt_review_status": "visually_confirmed",
                "media_id": "media-local-task1",
            },
            {
                "segment_id": "15:writing_task_2:2-2:2",
                "task_number": 2,
                "reviewed_prompt_text": "WRITING TASK 2\nDiscuss both views.\nWrite at least 250 words.",
                "needs_prompt_review": False,
                "prompt_review_status": "visually_confirmed",
                "media_id": None,
            },
        ],
        "speaking_test_drafts": [],
    }
    draft_path = (
        home / "corpus" / "inbox" / job["import_id"] / "review-draft.json"
    )
    draft_path.write_text(json.dumps(draft), encoding="utf-8")

    package = build_private_corpus_package(home, job["import_id"])
    assert package["question_count"] == 2
    assert package["module_counts"] == {"writing": 2}
    assert package["provisional"] is True
    assert get_content_import_job(home, job["import_id"])["status"] == "ready_to_import"

    imported = process_import(home, job["import_id"])
    assert imported["status"] == "imported"
    assert imported["summary"]["import_result"]["questions"] == 2
    assert imported["summary"]["import_result"]["assessment_packs"] == 1


def test_unknown_source_blocker_stops_private_package_generation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    job = create_import(
        home,
        title="Cambridge IELTS 15 Academic PDF",
        source_type="licensed_private",
        authenticity="unreviewed_official_practice_book",
        rights_status="local_private",
        files=[("15.pdf", b"%PDF-1.4\n", "application/pdf")],
    )
    draft = {
        "draft_version": 1,
        "revision": 1,
        "import_id": job["import_id"],
        "title": job["title"],
        "review_status": "in_review",
        "review_issues": [{
            "code": "unclassified_source_defect",
            "severity": "blocker",
            "status": "open",
        }],
        "segments": [{"segment_id": "15:writing_task_1:1-1:1"}],
        "reading_test_drafts": [],
        "answer_key_drafts": [],
        "writing_task_drafts": [],
        "speaking_test_drafts": [],
    }
    (
        home / "corpus" / "inbox" / job["import_id"] / "review-draft.json"
    ).write_text(json.dumps(draft), encoding="utf-8")

    with pytest.raises(ValueError, match="unclassified_source_defect"):
        build_private_corpus_package(home, job["import_id"])
