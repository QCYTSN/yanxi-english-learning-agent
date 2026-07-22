from pathlib import Path

import pytest
import yaml

from ielts_coach.init_home import initialise_home
from ielts_coach.onboarding import complete_onboarding, onboarding_status
from ielts_coach.reports import build_summary
from ielts_coach.speaking_io import import_speaking_report
from ielts_coach.storage import connect, recent_bands, recent_criterion_average, record_session


WRITING_RUBRIC = {
    "publisher": "IELTS",
    "standard": "IELTS Writing Band Descriptors",
    "version": "2023",
    "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf",
}
SPEAKING_RUBRIC = {
    "publisher": "IELTS",
    "standard": "IELTS Speaking Band Descriptors",
    "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-speaking-band-descriptors.pdf",
}


def _write_report(path: Path, report: dict) -> None:
    path.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_text_only_speaking_is_partial_and_cannot_score_pronunciation(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    report = {
        "report_version": 2,
        "mode": "full_mock",
        "source_observations": {
            "evidence_types": ["transcript"],
            "transcript": "A transcript without audio evidence.",
        },
        "local_evaluation": {
            "status": "partial",
            "confidence": "medium",
            "criterion_scores": [
                {"criterion": "FC", "score": 6.0, "evidence_source": "transcript"},
                {"criterion": "LR", "score": 6.5, "evidence_source": "transcript"},
                {"criterion": "GRA", "score": 6.0, "evidence_source": "transcript"},
            ],
            "rubric": SPEAKING_RUBRIC,
        },
    }
    path = tmp_path / "partial.yaml"
    _write_report(path, report)
    data = import_speaking_report(home, path)
    assert data["band"] is None
    assert data["score_kind"] == "partial_profile"

    report["local_evaluation"]["criterion_scores"].append(
        {"criterion": "PRON", "score": 6.0, "evidence_source": "transcript"}
    )
    invalid_path = tmp_path / "invalid-pron.yaml"
    _write_report(invalid_path, report)
    with pytest.raises(ValueError, match="PRON"):
        import_speaking_report(home, invalid_path)


def test_complete_speaking_uses_local_equal_weighted_official_result(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    report = {
        "report_version": 2,
        "mode": "full_mock",
        "source_observations": {
            "evidence_types": ["transcript", "voice_model_observation"],
            "transcript": "Transcript",
            "pronunciation_observations": ["Final consonants sometimes reduce intelligibility."],
        },
        "source_model_estimate": {"estimated_overall": 7.5, "criterion_scores": []},
        "local_evaluation": {
            "status": "completed",
            "confidence": "medium",
            "estimated_overall": 6.5,
            "criterion_scores": [
                {"criterion": "FC", "score": 6.5, "evidence_source": "mixed"},
                {"criterion": "LR", "score": 6.5, "evidence_source": "transcript"},
                {"criterion": "GRA", "score": 6.0, "evidence_source": "transcript"},
                {"criterion": "PRON", "score": 6.5, "evidence_source": "voice_model_observation"},
            ],
            "rubric": SPEAKING_RUBRIC,
        },
    }
    path = tmp_path / "complete.yaml"
    _write_report(path, report)
    data = import_speaking_report(home, path)
    assert data["band"] == 6.5
    assert data["score_kind"] == "ai_training_estimate"
    with connect(home) as conn:
        stored = conn.execute(
            "SELECT source_model_estimate_json,local_evaluation_json FROM speaking_reports WHERE session_id=?",
            (data["session_id"],),
        ).fetchone()
        assert '7.5' in stored["source_model_estimate_json"]
        assert '6.5' in stored["local_evaluation_json"]

    report["local_evaluation"]["estimated_overall"] = 7.0
    bad_path = tmp_path / "bad-overall.yaml"
    _write_report(bad_path, report)
    with pytest.raises(ValueError, match="equally weighted"):
        import_speaking_report(home, bad_path)


def test_new_writing_estimates_require_official_rubric_and_consistent_weighting(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    base = {
        "session_id": "W-20260721-900",
        "module": "writing",
        "status": "completed",
        "task": "task2",
        "scored_version": "v1",
        "band": 6.5,
        "score_kind": "ai_training_estimate",
        "score_confidence": "medium",
        "versions": [{"label": "v1", "content": "Learner response"}],
        "criterion_scores": [
            {"version": "v1", "criterion": "TR", "score": 6.5, "assessment_role": "local_rubric"},
            {"version": "v1", "criterion": "CC", "score": 6.5, "assessment_role": "local_rubric"},
            {"version": "v1", "criterion": "LR", "score": 6.0, "assessment_role": "local_rubric"},
            {"version": "v1", "criterion": "GRA", "score": 6.5, "assessment_role": "local_rubric"},
        ],
    }
    with pytest.raises(ValueError, match="official IELTS Writing"):
        record_session(home, base)
    base["rubric"] = WRITING_RUBRIC
    record_session(home, base)

    inconsistent = dict(base)
    inconsistent["session_id"] = "W-20260721-901"
    inconsistent["band"] = 7.0
    with pytest.raises(ValueError, match="equally weighted"):
        record_session(home, inconsistent)


def test_planning_excludes_partial_low_confidence_and_source_scores(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(home, {
        "session_id": "S-PARTIAL", "module": "speaking", "status": "completed",
        "score_kind": "partial_profile", "score_confidence": "high",
        "errors": [{"tag": "FC_LONG_PAUSE"}],
    })
    record_session(home, {
        "session_id": "S-LOW", "module": "speaking", "status": "completed",
        "band": 7.5, "score_kind": "ai_training_estimate", "score_confidence": "low",
        "rubric": SPEAKING_RUBRIC,
        "criterion_scores": [
            {"criterion": "FC", "score": 7.5, "confidence": "low", "assessment_role": "local_rubric", "evidence_source": "timing"},
            {"criterion": "LR", "score": 7.5, "confidence": "low", "assessment_role": "local_rubric", "evidence_source": "transcript"},
            {"criterion": "GRA", "score": 7.5, "confidence": "low", "assessment_role": "local_rubric", "evidence_source": "transcript"},
            {"criterion": "PRON", "score": 7.5, "confidence": "low", "assessment_role": "local_rubric", "evidence_source": "voice_model_observation"},
        ],
    })
    record_session(home, {
        "session_id": "S-USABLE", "module": "speaking", "status": "completed",
        "band": 6.0, "score_kind": "official_result", "score_confidence": "high",
        "criterion_scores": [
            {"criterion": "FC", "score": 6.0, "confidence": "medium", "assessment_role": "source_model"},
            {"criterion": "LR", "score": 5.5, "confidence": "medium", "assessment_role": "local_rubric"},
        ],
    })
    assert recent_bands(home, "speaking", 10) == [6.0]
    assert recent_criterion_average(home, "speaking", "FC") is None
    assert recent_criterion_average(home, "speaking", "LR") == 5.5


def test_unverified_reading_answers_do_not_count_as_wrong(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(home, {
        "session_id": "R-VERIFY", "module": "reading", "status": "completed",
        "questions": [
            {"question_type": "summary_completion", "is_correct": True},
            {"question_type": "summary_completion", "is_correct": None},
        ],
    })
    summary = build_summary(home, 10000)
    assert "summary_completion: 100%（1题）" in summary


def test_answer_key_scores_require_key_and_conversion_provenance(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    data = {
        "session_id": "L-KEY", "module": "listening", "status": "completed",
        "raw_score": 32, "band": 7.5, "score_kind": "answer_key_estimate",
    }
    with pytest.raises(ValueError, match="answer_key_source"):
        record_session(home, data)
    data["answer_key_source"] = "User-owned verified key"
    with pytest.raises(ValueError, match="band_conversion_source"):
        record_session(home, data)
    data["band_conversion_source"] = "Conversion table supplied with the practice source"
    record_session(home, data)


def test_onboarding_state_is_persisted_without_inventing_baseline(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert onboarding_status(home)["status"] == "pending"
    result = complete_onboarding(home, {
        "target": {"writing": 7.0},
        "minimum_required": {"writing": 6.5},
        "current": {"listening": 7.0},
    })
    assert result["status"] == "ready"
    assert result["baseline_status"] == "partial"
    assert result["baseline_modules"] == ["listening"]

    with pytest.raises(ValueError, match="Unsupported onboarding fields"):
        complete_onboarding(home, {"private_unknown_field": True})
    with pytest.raises(ValueError, match="Academic only"):
        complete_onboarding(home, {"exam": {"type": "general_training"}})
