from pathlib import Path

from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import draw_question, search_questions, show_question
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
