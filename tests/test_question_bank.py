from pathlib import Path

import pytest

from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import draw_question, search_questions, show_question, show_reading_set
from ielts_coach.session_manager import start_session
from ielts_coach.session_io import load_session_file
from ielts_coach.storage import record_session


def test_starter_questions_are_indexed_and_searchable(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    reading = search_questions(home, module="reading", question_type="multiple_choice")
    assert len(reading) >= 3
    question = show_question(home, reading[0]["question_id"])
    assert question is not None
    assert "passage" in question
    assert "correct_answer" not in question
    answer_view = show_question(home, reading[0]["question_id"], include_answer=True)
    assert answer_view["correct_answer"]


def test_draw_can_exclude_completed_questions(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    first = draw_question(home, module="writing", task="task2", seed=3, exclude_completed=True)
    assert first is not None
    record_session(home, {
        "session_id": "W-20260722-001",
        "module": "writing",
        "status": "completed",
        "question_id": first["question_id"],
        "versions": [{"label": "v1", "content": "A completed practice response."}],
    })
    remaining = search_questions(home, module="writing", task="task2", exclude_completed=True)
    assert first["question_id"] not in {item["question_id"] for item in remaining}


def test_reading_set_is_passage_scoped_and_hides_answers(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    result = show_reading_set(home, "START-RP-001")
    assert result is not None
    assert result["passage"]["passage_id"] == "START-RP-001"
    assert len(result["questions"]) == 4
    assert all("correct_answer" not in item for item in result["questions"])


def test_timed_reading_locks_answers_until_submission(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "reading", passage_id="START-RP-001", mode="timed-practice")
    with pytest.raises(ValueError, match="locked until"):
        show_reading_set(home, "START-RP-001", include_answers=True)
    submitted = load_session_file(path)
    submitted["status"] = "learner_working"
    submitted["submitted_at"] = submitted["started_at"]
    submitted["questions"] = [{"question_type": "multiple_choice", "user_answer": "A"}]
    record_session(home, submitted)
    revealed = show_reading_set(home, "START-RP-001", include_answers=True)
    assert revealed is not None
    assert all(item.get("correct_answer") is not None for item in revealed["questions"])
