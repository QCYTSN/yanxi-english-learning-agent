from __future__ import annotations

from pathlib import Path

from ielts_coach.conformance import (
    assess_pack,
    assess_question,
    assess_reading_set,
)
from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import show_question, show_reading_set
from ielts_coach.session_manager import start_session
from ielts_coach.study_runtime import submit_reading_answers


def test_true_false_answer_labels_cannot_use_yes_no() -> None:
    report = assess_question({
        "module": "reading",
        "question_type": "true_false_not_given",
        "content": "A statement.",
        "correct_answer": "YES",
        "source_type": "project_original",
        "rights_status": "redistributable",
        "review_status": "reviewed",
    })
    assert report["status"] == "rejected"
    assert any("TRUE, FALSE" in message for message in report["errors"])


def test_completion_question_requires_word_limit() -> None:
    report = assess_question({
        "module": "listening",
        "question_type": "note_completion",
        "content": "Complete the note.",
        "correct_answer": "library",
        "source_type": "project_original",
        "rights_status": "redistributable",
        "review_status": "reviewed",
    })
    assert report["status"] == "rejected"
    assert any("word limit" in message for message in report["errors"])


def test_verified_reading_full_mock_requires_three_passages_and_40_questions() -> None:
    base = {
        "pack_id": "mock-reading",
        "module": "reading",
        "practice_mode": "full_mock",
        "standard_profile": "ielts-academic",
        "source_type": "project_original",
        "rights_status": "redistributable",
        "review_status": "reviewed",
        "passage_ids": ["p1", "p2", "p3"],
        "question_ids": [f"q{i}" for i in range(40)],
        "structure": {
            "time_limit_minutes": 60,
            "passages": [
                {"word_count": 750, "question_count": 13},
                {"word_count": 800, "question_count": 13},
                {"word_count": 850, "question_count": 14},
            ],
        },
    }
    assert assess_pack(base)["status"] == "verified"
    broken = {**base, "structure": {"time_limit_minutes": 60, "passages": base["structure"]["passages"][:2]}}
    assert assess_pack(broken)["status"] == "rejected"


def test_full_mock_contracts_cover_other_three_modules() -> None:
    listening = assess_pack({
        "module": "listening", "practice_mode": "full_mock", "standard_profile": "ielts-academic",
        "rights_status": "redistributable", "review_status": "reviewed",
        "question_ids": [f"l{i}" for i in range(40)],
        "structure": {"audio_play_count": 1, "parts": [{"question_count": 10, "audio_media_id": f"audio-{index}"} for index in range(4)]},
    })
    writing = assess_pack({
        "module": "writing", "practice_mode": "full_mock", "standard_profile": "ielts-academic",
        "rights_status": "redistributable", "review_status": "reviewed",
        "question_ids": ["w1", "w2"],
        "structure": {"time_limit_minutes": 60, "tasks": [
            {"task": "task1", "minimum_words": 150, "score_weight": 1},
            {"task": "task2", "minimum_words": 250, "score_weight": 2},
        ]},
    })
    speaking = assess_pack({
        "module": "speaking", "practice_mode": "full_mock", "standard_profile": "ielts-academic",
        "rights_status": "redistributable", "review_status": "reviewed",
        "structure": {
            "parts": [{"part": 1}, {"part": 2}, {"part": 3}],
            "part2_part3_linked": True,
            "part2_preparation_seconds": 60,
            "total_time_minutes": {"min": 11, "max": 14},
        },
    })
    assert listening["status"] == writing["status"] == speaking["status"] == "verified"


def test_starter_content_is_explicitly_classified(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    writing = show_question(home, "START-WT2-001")
    assert writing is not None
    assert writing["practice_mode"] == "section_practice"
    assert writing["review_status"] == "reviewed"
    assert writing["conformance_status"] == "verified"
    reading = show_reading_set(home, "START-RP-001")
    assert reading is not None
    assert reading["conformance"]["status"] == "provisional"
    assert reading["conformance"]["eligible_for_band_score"] is False


def test_reading_submission_uses_local_answer_key_without_band_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(
        home,
        "reading",
        question_id="START-R-001",
        passage_id="START-RP-001",
        mode="timed-practice",
    )
    result = submit_reading_answers(home, path.stem, [{
        "question_id": "START-R-001",
        "question_number": 1,
        "question_type": "true_false_not_given",
        "user_answer": "true",
    }])
    assert result["score"] == {"correct": 1, "total": 1}
    assert result["score_kind"] == "answer_key_estimate"
    assert result["answer_key_source"] == "local-corpus-validated-key"
    assert result["band"] is None
