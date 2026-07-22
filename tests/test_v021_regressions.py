import json
from pathlib import Path

import pytest
import yaml

from ielts_coach.allocation import recommend_allocation
from ielts_coach.calibration import calibration_report, record_calibration
from ielts_coach.config import load_profile, load_settings
from ielts_coach.corpus import import_manifest
from ielts_coach.init_home import initialise_home
from ielts_coach.profiles import build_learning_profile
from ielts_coach.question_bank import content_hash, show_question
from ielts_coach.storage import (
    connect,
    recent_criterion_average,
    record_session,
    update_error_status,
    upsert_passage,
    upsert_question,
)


def test_v01_starter_manifest_is_safely_upgraded_and_indexed(tmp_path: Path):
    home = tmp_path / "home"
    starter = home / "corpus" / "starter-open"
    starter.mkdir(parents=True)
    old_manifest = {
        "corpus_id": "ielts-ai-coach-starter",
        "title": "IELTS AI Coach Starter Corpus",
        "source_type": "project_original",
        "authenticity": "practice_only",
        "storage": {"mode": "bundled"},
        "permissions": {
            "bundled_with_project": True,
            "redistribution_allowed": True,
            "local_personal_use_only": False,
        },
        "content": {"writing_task1": True, "writing_task2": True, "speaking": True},
    }
    (starter / "manifest.yaml").write_text(
        yaml.safe_dump(old_manifest, sort_keys=False), encoding="utf-8"
    )

    initialise_home(home)

    upgraded = yaml.safe_load((starter / "manifest.yaml").read_text(encoding="utf-8"))
    assert upgraded["corpus_version"] == 2
    assert upgraded["files"]
    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 41
        assert conn.execute(
            "SELECT COUNT(*) FROM questions WHERE module='reading'"
        ).fetchone()[0] == 16
        assert conn.execute("SELECT COUNT(*) FROM question_passages").fetchone()[0] == 4
    assert load_profile(home)["profile_version"] == 3
    assert load_settings(home)["question_draw_limit"] == 100000


def test_global_ids_cannot_silently_overwrite_another_corpus(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    upsert_passage(home, {
        "passage_id": "SHARED-P-001", "corpus_id": "ielts-ai-coach-starter",
        "source_type": "project_original", "body": "First corpus passage.",
    })
    with pytest.raises(ValueError, match="already belongs to corpus"):
        upsert_passage(home, {
            "passage_id": "SHARED-P-001", "corpus_id": "other-corpus",
            "source_type": "personal", "body": "Second corpus passage.",
        })


def test_item_provenance_must_match_manifest(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    corpus_dir = tmp_path / "private"
    corpus_dir.mkdir()
    (corpus_dir / "questions.jsonl").write_text(
        json.dumps({
            "question_id": "private-corpus:Q-001",
            "module": "writing",
            "content": "A private practice question.",
            "source_type": "synthetic",
        }) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "corpus_id": "private-corpus",
        "title": "Private corpus",
        "source_type": "personal",
        "permissions": {"bundled_with_project": False, "redistribution_allowed": False},
        "storage": {"local_path": str(corpus_dir)},
        "files": [{"kind": "questions", "path": "questions.jsonl"}],
    }
    manifest_path = corpus_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="declares source_type"):
        import_manifest(home, manifest_path)
    with connect(home) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM corpora WHERE corpus_id='private-corpus'"
        ).fetchone()[0] == 0


def test_criteria_are_kept_separate_by_module_and_resolved_errors_are_hidden(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(home, {
        "session_id": "W-20260722-101", "module": "writing", "status": "completed",
        "criterion_scores": [{"criterion": "LR", "score": 5.0}],
        "errors": [{"tag": "LR_COLLOCATION"}],
    })
    record_session(home, {
        "session_id": "S-20260722-101", "module": "speaking", "status": "completed",
        "criterion_scores": [{"criterion": "LR", "score": 8.0}],
    })
    assert recent_criterion_average(home, "writing", "LR") == 5.0
    assert recent_criterion_average(home, "speaking", "LR") == 8.0
    profile = build_learning_profile(home)
    assert "Writing LR: 5.00" in profile
    assert "Speaking LR: 8.00" in profile
    update_error_status(home, "LR_COLLOCATION", "resolved")
    assert "LR_COLLOCATION" not in build_learning_profile(home)


def test_allocation_is_idempotent_within_one_planning_period(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    for index in range(3):
        record_session(home, {
            "session_id": f"W-2026072{index}-201", "module": "writing",
            "status": "completed", "band": 5.0,
        })
    first = recommend_allocation(home, persist=True)
    second = recommend_allocation(home, persist=True)
    assert first.allocation == second.allocation
    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM allocation_history").fetchone()[0] == 1


def test_answer_redaction_is_recursive(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    question = {
        "question_id": "CUSTOM-REDACTION-001",
        "corpus_id": "ielts-ai-coach-starter",
        "module": "reading",
        "question_type": "multiple_choice",
        "content": "Choose one option.",
        "options": {"A": "One", "B": "Two"},
        "correct_answer": "B",
        "source_type": "project_original",
        "authenticity": "practice_only",
        "review_status": "reviewed",
        "metadata": {"answer_key": "B", "solution": {"rationale": "Hidden"}},
    }
    question["content_hash"] = content_hash(question)
    upsert_question(home, question)
    public = show_question(home, question["question_id"], include_answer=False)
    rendered = json.dumps(public)
    assert "answer_key" not in rendered
    assert "rationale" not in rendered
    assert "correct_answer" not in rendered


def test_calibration_report_uses_recorded_tolerance(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_calibration(home, {
        "case_id": "CASE-1", "module": "writing", "model": "test-model",
        "official_score": 6.0, "predicted_score": 7.0, "tolerance": 1.0,
    })
    report = calibration_report(home)
    assert "±1.00" in report
    assert "100%" in report
