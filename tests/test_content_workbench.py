from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from pypdf import PdfWriter

from ielts_coach.content_imports import (
    _apply_page_text_to_document,
    _answer_key_numbers,
    _has_meaningful_page_text,
    _infer_reading_question_type,
    _layout_answer_candidates,
    _page_role_groups,
    _question_numbers_from_instructions,
    _reading_question_groups,
    _unheaded_reading_question_groups,
    _reading_word_limit,
    build_import_review_draft,
    content_storage_status,
    create_import,
    delete_imports,
    prepare_import,
    process_import,
    queue_import_ocr,
    queue_import_preparation,
    read_import_review_draft,
    record_import_review_issue,
    recover_interrupted_imports,
    run_import_ocr,
    update_import_page_plan,
    update_import_review_annotation,
    update_import_review_segment,
)
from ielts_coach.content_inventory import build_content_readiness, content_requirements
from ielts_coach.content_audio import read_audio_review, update_audio_review
from ielts_coach.assessment_builder import assemble_assessment_pack, review_assessment_pack
from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import show_question
from ielts_coach.ocr_runtime import (
    ocr_runtime_status,
    queue_ocr_runtime_install,
    recover_ocr_runtime_install,
)


def test_content_readiness_reports_explicit_future_gaps(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    report = build_content_readiness(home)
    assert report["modules"]["reading"]["ready_for_varied_practice"] is False
    assert report["modules"]["listening"]["metrics"][0]["key"] == "verified_full_mocks"
    assert report["modules"]["writing"]["metrics"][0]["minimum_gap"] > 0
    assert content_requirements()["note"].startswith("库存数量")


def test_raw_private_pdf_is_staged_without_being_claimed_as_imported(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    job = create_import(
        home,
        title="My owned practice PDF",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("Practice Book.pdf", b"%PDF-1.4\nprivate-test", "application/pdf")],
    )
    assert job["status"] == "needs_structuring"
    assert job["files"][0]["file_kind"] == "pdf"
    assert len(job["files"][0]["sha256"]) == 64
    with pytest.raises(ValueError, match="prepared manifest"):
        process_import(home, job["import_id"])


def test_private_pdf_preparation_creates_page_level_review_draft(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    job = create_import(
        home,
        title="Owned PDF",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("owned.pdf", output.getvalue(), "application/pdf")],
    )

    queued = queue_import_preparation(home, job["import_id"])
    assert queued["status"] == "queued"
    prepared = prepare_import(home, job["import_id"])
    assert prepared["status"] == "ready_for_review"
    assert prepared["summary"]["preparation"]["page_count"] == 1
    assert prepared["summary"]["preparation"]["needs_ocr_pages"] == 1
    assert prepared["summary"]["documents"][0]["pages"][0]["extraction_status"] == "ocr_required"
    assert (home / "corpus" / "inbox" / job["import_id"] / "structure-draft.json").is_file()

    planned = update_import_page_plan(
        home,
        job["import_id"],
        stored_name="owned.pdf",
        pages={"1": "passage"},
    )
    assert planned["summary"]["page_plan"]["owned.pdf"] == {"1": "passage"}


def test_empty_password_permissions_pdf_is_not_blocked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt(user_password="", owner_password="local-owner-password")
    output = BytesIO()
    writer.write(output)
    job = create_import(
        home,
        title="Permission protected PDF",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("permissions.pdf", output.getvalue(), "application/pdf")],
    )

    prepared = prepare_import(home, job["import_id"])
    document = prepared["summary"]["documents"][0]
    assert document["status"] == "prepared"
    assert document["encrypted"] is True
    assert document["password_required"] is False
    assert document["security_status"] == "empty_password_permissions"


def test_watermark_only_text_still_requires_ocr() -> None:
    assert _has_meaningful_page_text("萝卜雅思" * 20) is False
    assert _has_meaningful_page_text(
        "Questions 1-6: Complete the notes below using no more than two words."
    ) is True
    document = {"pages": [{"page_number": 1}]}
    _apply_page_text_to_document(
        document,
        {"1": {"text": "萝卜雅思" * 20, "source": "pdf_text"}},
    )
    assert document["pages"][0]["extraction_status"] == "ocr_required"
    assert document["pages"][0]["text_source"] == "unreliable_pdf_text"


def test_consecutive_question_pages_remain_separate_review_segments() -> None:
    groups = _page_role_groups(
        {
            "1": "questions",
            "2": "questions",
            "3": "passage",
            "4": "passage",
        }
    )
    assert groups == [
        {"role": "questions", "pages": [1]},
        {"role": "questions", "pages": [2]},
        {"role": "passage", "pages": [3, 4]},
    ]


def test_interrupted_pdf_preparation_is_recoverable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    job = create_import(
        home,
        title="Interrupted PDF",
        source_type="licensed_private",
        authenticity="unreviewed",
        rights_status="local_private",
        files=[("owned.pdf", b"%PDF-1.4\n", "application/pdf")],
    )
    queue_import_preparation(home, job["import_id"])

    assert recover_interrupted_imports(home) == 1
    recovered = recover_interrupted_imports(home)
    assert recovered == 0
    from ielts_coach.storage import get_content_import_job

    current = get_content_import_job(home, job["import_id"])
    assert current is not None
    assert current["status"] == "failed"
    assert current["summary"]["preparation"]["recovery_action"] == "retry_preparation"


def test_isolated_ocr_runtime_install_state_is_recoverable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    assert ocr_runtime_status(home)["status"] == "not_installed"
    assert queue_ocr_runtime_install(home)["status"] == "queued"
    assert recover_ocr_runtime_install(home) is True
    recovered = ocr_runtime_status(home)
    assert recovered["status"] == "failed"
    assert recovered["recovery_action"] == "retry_install"
    assert recover_ocr_runtime_install(home) is False


def test_screenshot_can_be_ocr_reviewed_as_a_single_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
        "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )
    job = create_import(
        home,
        title="Reading screenshot",
        source_type="personal",
        authenticity="unreviewed",
        rights_status="local_private",
        files=[("reading-question.png", png, "image/png")],
    )
    prepared = prepare_import(home, job["import_id"])
    document = prepared["summary"]["documents"][0]
    stored_name = document["stored_name"]
    assert document["file_kind"] == "image"
    assert document["page_count"] == 1
    assert document["needs_ocr_pages"] == 1

    update_import_page_plan(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages={"1": "reading_test"},
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.ocr_runtime_status",
        lambda _: {"engine_id": "rapidocr-local", "available": True},
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.execute_ocr",
        lambda *_args, **_kwargs: {
            1: {
                "text": "Reading passage. Questions 1-3.",
                "confidence": 0.96,
                "layout_lines": [],
            }
        },
    )
    queued = queue_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1],
    )
    assert queued["status"] == "ocr_queued"
    completed = run_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1],
    )
    assert completed["status"] == "ready_for_review"
    assert completed["summary"]["preparation"]["needs_ocr_pages"] == 0
    assert (
        completed["summary"]["documents"][0]["pages"][0]["extraction_status"]
        == "ocr_available"
    )


def test_ocr_page_roles_build_a_locally_reviewable_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    job = create_import(
        home,
        title="Owned scan",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("扫描练习.pdf", output.getvalue(), "application/pdf")],
    )
    prepared = prepare_import(home, job["import_id"])
    stored_name = prepared["files"][0]["stored_name"]
    update_import_page_plan(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages={"1": "passage", "2": "questions", "3": "answer_key"},
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.ocr_runtime_status",
        lambda _: {
            "engine_id": "rapidocr-local",
            "available": True,
        },
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.execute_ocr",
        lambda *_args, **_kwargs: {
            1: {"text": "Reading passage text.", "confidence": 0.95},
            2: {"text": "Questions 1-13.", "confidence": 0.94},
            3: {"text": "Answer key and explanations.", "confidence": 0.93},
        },
    )
    queued = queue_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1, 2, 3],
    )
    assert queued["status"] == "ocr_queued"
    ocr_done = run_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1, 2, 3],
    )
    assert ocr_done["status"] == "ready_for_review"
    assert ocr_done["summary"]["preparation"]["needs_ocr_pages"] == 0
    assert {
        page["extraction_status"]
        for page in ocr_done["summary"]["documents"][0]["pages"]
    } == {"ocr_available"}

    draft = build_import_review_draft(home, job["import_id"])
    assert [segment["role"] for segment in draft["segments"]] == [
        "passage",
        "questions",
        "answer_key",
    ]
    assert draft["passage_drafts"][0]["body_text"] == "Reading passage text."
    assert draft["question_drafts"][0]["needs_manual_split"] is True
    assert draft["answer_key_drafts"][0]["needs_answer_mapping"] is True
    assert draft["eligible_for_import"] is False
    updated = update_import_review_segment(
        home,
        job["import_id"],
        segment_id=draft["segments"][0]["segment_id"],
        text="Corrected passage text.",
        review_status="reviewed",
        expected_revision=1,
    )
    assert updated["revision"] == 2
    assert updated["segments"][0]["review_status"] == "reviewed"
    assert updated["passage_drafts"][0]["body_text"] == "Corrected passage text."
    assert read_import_review_draft(home, job["import_id"])["revision"] == 2


def test_module_specific_page_roles_create_separate_review_drafts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    job = create_import(
        home,
        title="Owned IELTS test",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("test.pdf", output.getvalue(), "application/pdf")],
    )
    prepared = prepare_import(home, job["import_id"])
    stored_name = prepared["files"][0]["stored_name"]
    update_import_page_plan(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages={
            "1": "reading_passage",
            "2": "reading_questions",
            "3": "writing_task_1",
            "4": "writing_task_2",
            "5": "speaking_test",
        },
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.ocr_runtime_status",
        lambda _: {"engine_id": "rapidocr-local", "available": True},
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.execute_ocr",
        lambda *_args, **_kwargs: {
            1: {"text": "READING PASSAGE 1\nA useful passage.", "confidence": 0.98},
            2: {"text": "Questions 1-13\n1. First question.", "confidence": 0.97},
            3: {
                "text": "WRITING TASK 1\nThe chart shows...\nWrite at least 150 words.",
                "confidence": 0.96,
            },
            4: {
                "text": "WRITING TASK 2\nDiscuss both views.\nWrite at least 250 words.",
                "confidence": 0.95,
            },
            5: {
                "text": "SPEAKING\nPART 1\nHome\nPART 2\nDescribe...\nPART 3\nDiscuss...",
                "confidence": 0.94,
            },
        },
    )
    run_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1, 2, 3, 4, 5],
    )

    draft = build_import_review_draft(home, job["import_id"])

    assert draft["passage_drafts"][0]["module"] == "reading"
    assert draft["question_drafts"][0]["module"] == "reading"
    assert [item["task_number"] for item in draft["writing_task_drafts"]] == [1, 2]
    assert draft["writing_task_drafts"][0]["minimum_words"] == 150
    assert draft["writing_task_drafts"][0]["needs_visual_review"] is True
    assert draft["writing_task_drafts"][0]["passes_marker_check"] is True
    assert draft["writing_task_drafts"][1]["minimum_words"] == 250
    assert draft["speaking_test_drafts"][0]["needs_part_split"] is False
    assert [
        item["part_number"]
        for item in draft["speaking_test_drafts"][0]["parts"]
    ] == [1, 2, 3]
    assert draft["speaking_test_drafts"][0]["passes_marker_check"] is True
    assert (
        draft["speaking_test_drafts"][0]["mock_policy"]["correction_during_mock"]
        is False
    )
    writing_segment = next(
        item
        for item in draft["segments"]
        if item["role"] == "writing_task_2"
    )
    reviewed = update_import_review_annotation(
        home,
        job["import_id"],
        annotation_type="writing_prompt_overrides",
        segment_id=writing_segment["segment_id"],
        payload={
            "task_number": 2,
            "prompt_text": (
                "WRITING TASK 2\nDiscuss both views.\n"
                "Write at least 250 words."
            ),
            "evidence_pages": [4],
            "evidence": "Visual PDF review",
        },
        expected_revision=draft["revision"],
    )
    reviewed_task = next(
        item
        for item in reviewed["writing_task_drafts"]
        if item["task_number"] == 2
    )
    assert reviewed_task["prompt_review_status"] == "visually_confirmed"
    assert reviewed_task["needs_prompt_review"] is False
    assert reviewed_task["reviewed_prompt_text"].startswith("WRITING TASK 2")
    assert reviewed_task["reviewed_prompt_passes_marker_check"] is True
    speaking_segment = next(
        item
        for item in reviewed["segments"]
        if item["role"] == "speaking_test"
    )
    reviewed_speaking = update_import_review_annotation(
        home,
        job["import_id"],
        annotation_type="speaking_prompt_overrides",
        segment_id=speaking_segment["segment_id"],
        payload={
            "prompt_text": (
                "PART 1\nDo you like your home?\n"
                "PART 2\nDescribe a place you enjoy visiting.\n"
                "PART 3\nWhy do people visit new places?"
            ),
            "evidence_pages": [5],
            "evidence": "Visual PDF review",
        },
        expected_revision=reviewed["revision"],
    )
    speaking_draft = reviewed_speaking["speaking_test_drafts"][0]
    assert speaking_draft["prompt_review_status"] == "visually_confirmed"
    assert speaking_draft["needs_question_review"] is False
    assert [item["part_number"] for item in speaking_draft["parts"]] == [1, 2, 3]
    part_2 = next(
        item for item in speaking_draft["parts"] if item["part_number"] == 2
    )
    assert part_2["cue_card"]["topic"] == "Describe a place you enjoy visiting."


def test_reading_test_role_preserves_mixed_pages_and_audits_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    job = create_import(
        home,
        title="Owned reading test",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("reading.pdf", output.getvalue(), "application/pdf")],
    )
    prepared = prepare_import(home, job["import_id"])
    stored_name = prepared["files"][0]["stored_name"]
    update_import_page_plan(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages={"1": "reading_test", "2": "reading_test", "3": "reading_test"},
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.execute_ocr",
        lambda *_args, **_kwargs: {
            1: {
                "text": "READING PASSAGE 1\nText\nQuestions 1-13",
                "confidence": 0.98,
            },
            2: {
                "text": "READING PASSAGE 2\nText\nQuestions 14-26",
                "confidence": 0.97,
            },
            3: {
                "text": "READING PASSAGE 3\nText\nQuestions 27-40",
                "confidence": 0.96,
            },
        },
    )
    run_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1, 2, 3],
    )

    draft = build_import_review_draft(home, job["import_id"])
    reading = draft["reading_test_drafts"][0]

    assert reading["detected_passage_count"] == 3
    assert reading["detected_question_number_count"] == 40
    assert reading["missing_question_numbers"] == []
    assert reading["passes_marker_check"] is True
    assert reading["needs_structural_review"] is True


def test_reading_question_marker_parser_supports_paired_questions() -> None:
    assert _question_numbers_from_instructions(
        "Questions 20 and 21\nQuestions22and23\nQuestion 40"
    ) == {20, 21, 22, 23, 40}


def test_reading_question_type_and_word_limit_are_inferred() -> None:
    text = (
        "Questions 1-6\nComplete the summary below.\n"
        "Choose NO MORE THAN TWO WORDS from the passage for each answer."
    )
    assert _infer_reading_question_type(text) == "summary_completion"
    assert _reading_word_limit(text) == "NO MORE THAN TWO WORDS"


def test_reading_question_groups_ignore_inline_and_nested_range_repeats() -> None:
    text = (
        "Questions 14-20\n"
        "Choose the correct heading for each paragraph from the list of headings.\n"
        "Look at the following statements (Questions 14-20) and the list below.\n"
        "questions\n14\nParagraph A\n15\nParagraph B\n"
        "Questions 21-24\nChoose the correct letter, A, B, C or D."
    )
    groups = _reading_question_groups(text)
    assert [
        (group["question_start"], group["question_end"])
        for group in groups
    ] == [(14, 20), (21, 24)]
    assert groups[0]["question_type"] == "matching_headings"
    assert groups[1]["question_type"] == "multiple_choice_single"


def test_reading_question_groups_support_ocr_compacted_ranges() -> None:
    passage_one = (
        "READING PASSAGE 1\n"
        "You should spend about 20 minutes on Questions 113, "
        "which are based on Reading Passage 1 below.\n"
        "Questions 16\nComplete the notes below.\n"
        "Questions 713\nChoose the correct letter, A, B, C or D."
    )
    groups = _reading_question_groups(
        passage_one,
        minimum_question_number=1,
        maximum_question_number=13,
    )
    assert [
        (group["question_start"], group["question_end"])
        for group in groups
    ] == [(1, 6), (7, 13)]
    assert _question_numbers_from_instructions(
        passage_one,
        minimum_question_number=1,
        maximum_question_number=13,
    ) == set(range(1, 14))

    passage_three = (
        "Questions 2731\nChoose the correct heading.\n"
        "Questions 3240\nChoose the correct letter."
    )
    assert [
        (group["question_start"], group["question_end"])
        for group in _reading_question_groups(
            passage_three,
            minimum_question_number=27,
            maximum_question_number=40,
        )
    ] == [(27, 31), (32, 40)]


def test_unheaded_reading_question_groups_use_numbered_layout_and_nearest_instruction() -> None:
    text = (
        "Complete each sentence with the correct ending, A-D, below.\n"
        "34. First statement\n35. Second statement\n36. Third statement\n"
        "Questions 37-40\nChoose the correct letter, A, B, C or D."
    )
    groups = _unheaded_reading_question_groups(text, {37, 38, 39, 40})
    assert len(groups) == 1
    assert groups[0]["question_numbers"] == [34, 35, 36]
    assert groups[0]["question_type"] == "matching_sentence_endings"
    assert groups[0]["inferred_from_numbered_layout"] is True


def test_answer_key_marker_parser_detects_complete_coverage() -> None:
    assert _answer_key_numbers(" ".join(str(value) for value in range(1, 41))) == set(
        range(1, 41)
    )


def test_layout_answer_candidates_pair_numbers_with_same_row_text() -> None:
    layout = [{
        "page_number": 7,
        "lines": [
            {"text": "1", "box": [[10, 10], [20, 10], [20, 20], [10, 20]]},
            {"text": "TRUE", "box": [[40, 10], [90, 10], [90, 20], [40, 20]]},
            {"text": "2", "box": [[10, 30], [20, 30], [20, 40], [10, 40]]},
            {"text": "FALSE", "box": [[40, 30], [95, 30], [95, 40], [40, 40]]},
        ],
    }]
    result = _layout_answer_candidates(layout)
    assert result["answers"] == [
        {
            "question_number": 1,
            "answer_text": "TRUE",
            "page_number": 7,
            "confidence": "layout_row_candidate",
        },
        {
            "question_number": 2,
            "answer_text": "FALSE",
            "page_number": 7,
            "confidence": "layout_row_candidate",
        },
    ]
    assert result["duplicate_numbers"] == []


def test_layout_answer_candidates_support_inline_and_either_order_pairs() -> None:
    layout = [{
        "page_number": 12,
        "lines": [
            {"text": "22mileage", "box": [[600, 10], [700, 10], [700, 20], [600, 20]]},
            {"text": "23&24 IN EITHER ORDER", "box": [[600, 30], [780, 30], [780, 40], [600, 40]]},
            {"text": "B", "box": [[650, 50], [670, 50], [670, 60], [650, 60]]},
            {"text": "D", "box": [[650, 70], [670, 70], [670, 80], [650, 80]]},
        ],
    }]
    result = _layout_answer_candidates(layout)
    assert {
        item["question_number"]: item["answer_text"]
        for item in result["answers"]
    } == {22: "mileage", 23: "B", 24: "D"}
    assert result["duplicate_numbers"] == []


def test_review_issue_is_revisioned_and_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    job = create_import(
        home,
        title="Owned review source",
        source_type="licensed_private",
        authenticity="unreviewed_official_practice_book",
        rights_status="local_private",
        files=[("review.pdf", output.getvalue(), "application/pdf")],
    )
    prepared = prepare_import(home, job["import_id"])
    stored_name = prepared["files"][0]["stored_name"]
    update_import_page_plan(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages={"1": "reading_test"},
    )
    monkeypatch.setattr(
        "ielts_coach.content_imports.execute_ocr",
        lambda *_args, **_kwargs: {
            1: {"text": "READING PASSAGE 1", "confidence": 0.9}
        },
    )
    run_import_ocr(
        home,
        job["import_id"],
        stored_name=stored_name,
        pages=[1],
    )
    build_import_review_draft(home, job["import_id"])

    first = record_import_review_issue(
        home,
        job["import_id"],
        code="source_numbering_error",
        severity="blocker",
        message="The source duplicates one question number.",
        page_numbers=[1],
        evidence="Visual page review",
    )
    second = record_import_review_issue(
        home,
        job["import_id"],
        code="source_numbering_error",
        severity="blocker",
        message="The source duplicates one question number.",
        page_numbers=[1],
        evidence="Visual page review",
    )

    assert len(first["review_issues"]) == 1
    assert len(second["review_issues"]) == 1
    assert second["revision"] == first["revision"] + 1

    annotated = update_import_review_annotation(
        home,
        job["import_id"],
        annotation_type="reading_group_overrides",
        segment_id=second["segments"][0]["segment_id"],
        payload={
            "groups": [{
                "passage_number": 1,
                "question_start": 1,
                "question_end": 13,
                "question_type": "true_false_not_given",
                "evidence_pages": [1],
                "evidence": "Visual PDF review",
            }],
        },
        expected_revision=second["revision"],
    )
    assert annotated["reading_test_drafts"][0][
        "manual_structure_overrides_applied"
    ] == 1
    assert annotated["review_annotations"]["reading_group_overrides"]


def test_audio_transcript_and_timestamp_review_is_revisioned(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    job = create_import(
        home,
        title="Owned listening audio",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("part-1.wav", b"RIFF-test-audio", "audio/wav")],
    )
    prepared = prepare_import(home, job["import_id"])
    stored_name = prepared["files"][0]["stored_name"]
    draft = read_audio_review(home, job["import_id"], stored_name)
    assert draft["revision"] == 0
    assert draft["eligible_for_import"] is False

    saved = update_audio_review(
        home,
        job["import_id"],
        stored_name=stored_name,
        transcript="Good morning. How can I help?",
        cues=[
            {
                "cue_id": "cue-0001",
                "start_seconds": 0,
                "end_seconds": 2.5,
                "text": "Good morning.",
            },
            {
                "cue_id": "cue-0002",
                "start_seconds": 2.5,
                "end_seconds": 4.8,
                "text": "How can I help?",
            },
        ],
        duration_seconds=5.0,
        review_status="reviewed",
        expected_revision=0,
    )
    assert saved["revision"] == 1
    assert saved["review_status"] == "reviewed"
    assert saved["eligible_for_import"] is False
    with pytest.raises(ValueError, match="revision conflict"):
        update_audio_review(
            home,
            job["import_id"],
            stored_name=stored_name,
            transcript="stale",
            cues=[],
            duration_seconds=5.0,
            review_status="needs_review",
            expected_revision=0,
        )


def test_content_inbox_quota_and_confirmed_batch_delete(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    first = create_import(
        home,
        title="Delete one",
        source_type="personal",
        authenticity="self_created",
        rights_status="local_private",
        files=[("one.pdf", b"%PDF-delete-one", "application/pdf")],
    )
    second = create_import(
        home,
        title="Delete two",
        source_type="personal",
        authenticity="self_created",
        rights_status="local_private",
        files=[("two.pdf", b"%PDF-delete-two", "application/pdf")],
    )
    before = content_storage_status(home)
    assert before["used_bytes"] > 0
    with pytest.raises(ValueError, match="explicit confirmation"):
        delete_imports(
            home,
            [first["import_id"]],
            confirmed=False,
        )
    result = delete_imports(
        home,
        [first["import_id"], second["import_id"]],
        confirmed=True,
    )
    assert len(result["deleted"]) == 2
    assert result["failed"] == []
    assert result["storage"]["used_bytes"] == 0
    assert not (home / "corpus" / "inbox" / first["import_id"]).exists()


def test_prepared_manifest_package_can_be_validated_and_imported(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    manifest = {
        "corpus_id": "my-private-set",
        "title": "My private structured set",
        "source_type": "licensed_private",
        "authenticity": "practice_only",
        "rights_status": "local_private",
        "permissions": {
            "bundled_with_project": False,
            "redistribution_allowed": False,
            "local_personal_use_only": True,
        },
        "files": [{"kind": "questions", "path": "questions.jsonl"}],
    }
    question = {
        "question_id": "PRIVATE-W-001",
        "module": "writing",
        "task": "task2",
        "question_type": "opinion",
        "minimum_words": 250,
        "content": "Some people prefer to work in small organisations. To what extent do you agree?",
        "source_type": "licensed_private",
        "authenticity": "practice_only",
        "review_status": "reviewed",
        "conformance_status": "verified",
    }
    job = create_import(
        home,
        title="Structured set",
        source_type="licensed_private",
        authenticity="practice_only",
        rights_status="local_private",
        files=[
            ("manifest.yaml", yaml.safe_dump(manifest, sort_keys=False).encode(), "application/yaml"),
            ("questions.jsonl", (json.dumps(question) + "\n").encode(), "application/x-ndjson"),
        ],
    )
    assert job["status"] == "ready_to_import"
    imported = process_import(home, job["import_id"])
    assert imported["status"] == "imported"
    assert imported["summary"]["import_result"]["questions"] == 1
    stored = show_question(home, "PRIVATE-W-001")
    assert stored is not None
    assert stored["source_review_status"] == "reviewed"
    assert stored["review_status"] == "unreviewed"
    assert stored["conformance_status"] == "provisional"


def test_content_upload_rejects_unsafe_file_types(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    with pytest.raises(ValueError, match="Unsupported content file type"):
        create_import(
            home,
            title="Bad upload",
            source_type="personal",
            authenticity="unreviewed",
            rights_status="local_private",
            files=[("run.exe", b"not allowed", "application/octet-stream")],
        )


def test_import_manifest_cannot_override_registered_provenance(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    manifest = {
        "corpus_id": "mismatched-set",
        "title": "Mismatched set",
        "source_type": "personal",
        "authenticity": "self_created",
        "rights_status": "redistributable",
        "permissions": {
            "bundled_with_project": False,
            "redistribution_allowed": True,
            "local_personal_use_only": False,
        },
        "files": [{"kind": "questions", "path": "questions.jsonl"}],
    }
    job = create_import(
        home,
        title="Registered private source",
        source_type="licensed_private",
        authenticity="practice_only",
        rights_status="local_private",
        files=[
            ("manifest.yaml", yaml.safe_dump(manifest, sort_keys=False).encode(), "application/yaml"),
            ("questions.jsonl", b"", "application/x-ndjson"),
        ],
    )
    with pytest.raises(ValueError, match="provenance does not match"):
        process_import(home, job["import_id"])


def test_assessment_pack_builder_derives_structure_and_requires_item_review(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    pack = assemble_assessment_pack(
        home,
        module="writing",
        title="Starter writing pair",
        question_ids=["START-WT1-001", "START-WT2-001"],
    )
    assert pack["practice_mode"] == "full_mock"
    assert {item["task"] for item in pack["structure"]["tasks"]} == {"task1", "task2"}
    assert pack["conformance_status"] == "provisional"
    with pytest.raises(ValueError, match="reviewer and completed checklist"):
        review_assessment_pack(home, pack["pack_id"])

    with pytest.raises(ValueError, match="does not belong"):
        assemble_assessment_pack(
            home,
            module="writing",
            title="Mixed modules",
            question_ids=["START-WT2-001", "START-R-001"],
        )
