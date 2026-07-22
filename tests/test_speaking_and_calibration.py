from pathlib import Path

from ielts_coach.calibration import calibration_report, record_calibration
from ielts_coach.init_home import initialise_home
from ielts_coach.speaking_io import import_speaking_report
from ielts_coach.storage import connect


def test_speaking_report_import(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    report = tmp_path / "report.yaml"
    report.write_text(
        "mode: full_mock\nestimated_overall: 6.0\ncriterion_scores:\n  - criterion: FC\n    score: 6.0\n    confidence: medium\nerrors:\n  - tag: FC_LONG_PAUSE\n",
        encoding="utf-8",
    )
    data = import_speaking_report(home, report)
    assert data["module"] == "speaking"
    assert data["band"] is None
    assert data["score_kind"] == "partial_profile"
    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM speaking_reports").fetchone()[0] == 1
        row = conn.execute(
            "SELECT assessment_role FROM criterion_scores WHERE session_id=?",
            (data["session_id"],),
        ).fetchone()
        assert row["assessment_role"] == "source_model"


def test_calibration_framework(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_calibration(home, {
        "case_id": "OFFICIAL-W-001",
        "module": "writing",
        "criterion": "overall",
        "model": "test-model",
        "official_score": 6.0,
        "predicted_score": 6.5,
    })
    report = calibration_report(home)
    assert "test-model" in report
    assert "0.50" in report
