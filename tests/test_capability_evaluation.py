from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ielts_coach.capability_evaluation import (
    list_capability_evaluations,
    provider_reliability_report,
    run_contract_evaluation,
)
from ielts_coach.cli import app
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import connect
from ielts_coach.teaching_quality import run_teaching_quality_evaluation
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


FIXTURES = Path(__file__).parent / "fixtures" / "agent_contracts"


def _client(home: Path) -> TestClient:
    app_instance = create_app(
        home=home,
        auth=AuthState(launch_token="evaluation-test-token-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app_instance)
    client.headers.update({"Origin": "http://testserver"})
    response = client.post(
        "/api/auth/exchange",
        json={"token": "evaluation-test-token-long-enough"},
    )
    assert response.status_code == 200
    return client


def test_contract_evaluation_runs_all_positive_and_negative_cases(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)

    result = run_contract_evaluation(home, FIXTURES)

    assert result["status"] == "passed"
    assert result["case_count"] == 30
    assert result["passed_count"] == 30
    assert {item["case_kind"] for item in result["cases"]} == {"valid", "invalid"}
    assert all(len(item["case_hash"]) == 64 for item in result["cases"])
    history = list_capability_evaluations(home)
    assert history[0]["report_hash"] == result["report_hash"]
    assert history[0]["content_retention"] == "hashes_and_outcomes_only"

    raw_fixture = (FIXTURES / "writing-review.valid.json").read_text(encoding="utf-8")
    with connect(home) as conn:
        stored = conn.execute(
            "SELECT report_json FROM capability_evaluation_runs"
        ).fetchone()[0]
    assert raw_fixture not in stored
    assert "priority_issues" not in stored


def test_reliability_report_distinguishes_contract_gate_from_runtime_sample(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    before = provider_reliability_report(home)
    assert before["release_gate"]["status"] == "evaluation_required"
    assert before["runtime"]["sample_status"] == "insufficient"

    run_contract_evaluation(home, FIXTURES)
    after = provider_reliability_report(home)
    assert after["latest_contract_evaluation"]["status"] == "passed"
    assert after["release_gate"]["status"] == "teaching_evaluation_required"
    run_teaching_quality_evaluation(home)
    complete = provider_reliability_report(home)
    assert (
        complete["release_gate"]["status"]
        == "contract_ready_runtime_observation_needed"
    )
    assert after["privacy"] == "metadata_only_no_prompts_or_responses"


def test_evaluation_cli_returns_machine_readable_report(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "evaluation",
            "contracts",
            "--cases",
            str(FIXTURES),
            "--home",
            str(home),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "passed"
    assert report["case_count"] == 30


def test_release_gate_combines_contract_and_scale_checks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "evaluation",
            "release",
            "--cases",
            str(FIXTURES),
            "--home",
            str(home),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "passed"
    assert report["contract_gate"]["case_count"] == 30
    assert report["teaching_quality_gate"]["case_count"] == 14
    assert report["teaching_quality_gate"]["status"] == "passed"
    assert report["visual_review"] == "separate_human_decision_required"


def test_local_system_api_exposes_evaluation_and_reliability_metadata(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    run_contract_evaluation(home, FIXTURES)
    run_teaching_quality_evaluation(home)
    client = _client(home)

    evaluations = client.get("/api/v1/system/evaluations?limit=1")
    reliability = client.get("/api/v1/system/reliability?days=30")
    teaching = client.get("/api/v1/system/teaching-evaluations?limit=1")

    assert evaluations.status_code == 200
    assert evaluations.json()[0]["status"] == "passed"
    assert evaluations.json()[0]["content_retention"] == "hashes_and_outcomes_only"
    assert reliability.status_code == 200
    assert reliability.json()["latest_contract_evaluation"]["status"] == "passed"
    assert reliability.json()["latest_teaching_evaluation"]["status"] == "passed"
    assert reliability.json()["privacy"] == "metadata_only_no_prompts_or_responses"
    assert teaching.status_code == 200
    assert teaching.json()[0]["content_retention"] == "case_hashes_rule_outcomes_and_scores_only"
