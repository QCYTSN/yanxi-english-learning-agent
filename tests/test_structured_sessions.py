from pathlib import Path

import pytest

from ielts_coach.init_home import initialise_home
from ielts_coach.profiles import build_learning_profile
from ielts_coach.session_manager import finish_session, start_session
from ielts_coach.storage import connect, record_session


def test_reading_answers_and_writing_versions_are_structured(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(home, {
        "session_id": "R-20260722-001",
        "module": "reading",
        "status": "completed",
        "score": {"correct": 1, "total": 2},
        "questions": [
            {"question_id": "START-R-001", "question_type": "true_false_not_given", "user_answer": "TRUE", "correct_answer": "TRUE", "is_correct": True, "duration_seconds": 40},
            {"question_id": "START-R-002", "question_type": "true_false_not_given", "user_answer": "NOT GIVEN", "correct_answer": "FALSE", "is_correct": False, "duration_seconds": 80, "error_tags": ["R_TFNG_FALSE_NOT_GIVEN"]},
        ],
        "errors": [{"tag": "R_TFNG_FALSE_NOT_GIVEN", "count": 1}],
    })
    record_session(home, {
        "session_id": "W-20260722-001",
        "module": "writing",
        "status": "completed",
        "band": 6.5,
        "versions": [
            {"label": "v1", "content": "A short first version."},
            {"label": "v2", "content": "A more developed second version."},
        ],
        "criterion_scores": [
            {"version": "v1", "criterion": "TR", "score": 6.0, "confidence": "medium", "evidence": ["underdeveloped"]},
            {"version": "v2", "criterion": "TR", "score": 6.5, "confidence": "medium", "evidence": ["developed"]},
        ],
    })
    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_answers").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM writing_versions").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM criterion_scores").fetchone()[0] == 2
    profile = build_learning_profile(home)
    assert "阅读题型正确率" in profile
    assert "错误画像" in profile and "行为画像" in profile


def test_session_start_rejects_empty_finish_then_records_evidence(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    path = start_session(home, "reading", question_id="START-R-001")
    assert path.exists()
    with pytest.raises(ValueError, match="contains no score"):
        finish_session(home, path)
    path.write_text(
        "---\n"
        f"session_id: {path.stem}\n"
        "module: reading\nstatus: draft\n"
        "questions:\n"
        "  - question_id: START-R-001\n"
        "    question_type: true_false_not_given\n"
        "    user_answer: TRUE\n"
        "    correct_answer: TRUE\n"
        "    is_correct: true\n"
        "---\n\n# Review\n",
        encoding="utf-8",
    )
    data = finish_session(home, path)
    assert data["status"] == "completed"
    with connect(home) as conn:
        assert conn.execute("SELECT status FROM sessions WHERE session_id=?", (data["session_id"],)).fetchone()[0] == "completed"


def test_strict_session_validation_rejects_invalid_band(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    with pytest.raises(Exception):
        record_session(home, {"session_id": "W-1", "module": "writing", "band": 6.3})
