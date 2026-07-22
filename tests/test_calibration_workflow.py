from pathlib import Path

import pytest

from ielts_coach.calibration import (
    calibration_report,
    import_calibration_case,
    import_calibration_run,
    list_calibration_cases,
    prepare_calibration_run,
)
from ielts_coach.init_home import initialise_home


def _case(input_path: Path) -> dict:
    return {
        "case_id": "CAL-W-T2-001",
        "module": "writing",
        "task": "task2",
        "criterion": "overall",
        "official_score": 6.5,
        "reference_kind": "official_scored_sample",
        "source_reference": "Authorised official scored sample",
        "input_path": str(input_path),
        "permissions": {
            "user_confirms_legal_use": True,
            "redistribution_allowed": False,
        },
    }


def test_blind_calibration_workflow_hides_official_score(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    sample = tmp_path / "neutral-sample.md"
    sample.write_text("Candidate response", encoding="utf-8")
    imported = import_calibration_case(home, _case(sample))
    assert imported["content_hash"]
    assert len(list_calibration_cases(home)) == 1

    worksheet = tmp_path / "blind-run.yaml"
    run = prepare_calibration_run(home, "test-model", worksheet)
    assert "official_score" not in worksheet.read_text(encoding="utf-8")
    prediction = run["predictions"][0]
    prediction["predicted_score"] = 6.0
    assert import_calibration_run(home, run) == 1
    report = calibration_report(home)
    assert "test-model" in report
    assert "0.50" in report


def test_calibration_detects_changed_input(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    sample = tmp_path / "neutral-sample.md"
    sample.write_text("Original", encoding="utf-8")
    import_calibration_case(home, _case(sample))
    run = prepare_calibration_run(home, "test-model", tmp_path / "run.yaml")
    run["predictions"][0]["predicted_score"] = 6.5
    run["predictions"][0]["content_hash"] = "changed"
    with pytest.raises(ValueError, match="input changed"):
        import_calibration_run(home, run)


def test_calibration_rejects_task_criterion_mismatch(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    sample = tmp_path / "neutral-sample.md"
    sample.write_text("Candidate response", encoding="utf-8")
    data = _case(sample)
    data["criterion"] = "TA"
    with pytest.raises(ValueError, match="Invalid task2"):
        import_calibration_case(home, data)
