from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.learning_orchestration import materialise_progress_action
from ielts_coach.progress_dashboard import (
    build_progress_dashboard,
    build_structured_weekly_report,
    list_weekly_reports,
)
from ielts_coach.storage import SCHEMA_VERSION, connect, record_session
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    assert client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    ).status_code == 200
    return client


def _session(
    session_id: str,
    module: str,
    band: float,
    occurred_at: datetime,
    *,
    score_kind: str = "official_result",
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "module": module,
        "status": "completed",
        "occurred_at": occurred_at.isoformat(),
        "band": band,
        "score_kind": score_kind,
        "score_confidence": "low" if score_kind == "unspecified" else "high",
    }


def test_current_schema_persists_structured_weekly_reports(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert SCHEMA_VERSION == 30
    with connect(home) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "weekly_reports" in tables


def test_dashboard_trend_separates_eligible_scores_from_observations(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    now = datetime.now(timezone.utc)
    record_session(home, _session("R-V13-1", "reading", 6.0, now - timedelta(days=18)))
    record_session(home, _session("R-V13-2", "reading", 6.5, now - timedelta(days=9)))
    record_session(home, _session("R-V13-3", "reading", 7.0, now - timedelta(days=2)))
    record_session(
        home,
        _session(
            "R-V13-OBS",
            "reading",
            9.0,
            now - timedelta(days=1),
            score_kind="unspecified",
        ),
    )

    dashboard = build_progress_dashboard(home, days=30)
    reading = dashboard["modules"]["reading"]
    assert dashboard["dashboard_version"] == 2
    assert reading["average_band"] == 6.5
    assert reading["eligible_samples"] == 3
    assert reading["observation_samples"] == 1
    assert reading["trend_summary"]["direction"] == "improving"
    assert reading["trend_summary"]["delta"] == 0.75
    assert sum(item["eligible_samples"] for item in reading["trend_buckets"]) == 3
    assert sum(item["observation_samples"] for item in reading["trend_buckets"]) == 1


def test_weekly_report_is_evidence_bounded_and_upserts_period(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    now = datetime.now(timezone.utc)
    record_session(home, _session("L-V13-1", "listening", 6.5, now - timedelta(days=2)))
    record_session(
        home,
        _session(
            "W-V13-OBS",
            "writing",
            8.0,
            now - timedelta(days=1),
            score_kind="unspecified",
        ),
    )

    first = build_structured_weekly_report(home, ending_at=now)
    second = build_structured_weekly_report(home, ending_at=now)
    history = list_weekly_reports(home)
    assert first["report_id"] == second["report_id"]
    assert len(history) == 1
    assert first["modules"]["listening"]["average_band"] == 6.5
    assert first["modules"]["writing"]["average_band"] is None
    assert first["modules"]["writing"]["observation_samples"] == 1
    assert any("训练观察" in risk for risk in first["risks"])
    assert first["source_hash"] == second["source_hash"]


def test_progress_practice_action_materialises_idempotent_unit(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    dashboard = build_progress_dashboard(home)
    action = next(
        item for item in dashboard["next_actions"] if item["action_kind"] == "practice"
    )
    first = materialise_progress_action(home, action["action_id"])
    second = materialise_progress_action(home, action["action_id"])
    assert first["unit_id"] == second["unit_id"]
    assert first["source_type"] == "progress_action"
    assert first["launch_url"].startswith("/practice")


def test_v13_progress_http_exposes_report_and_starts_action(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    dashboard = client.get("/api/v1/progress/dashboard?days=30")
    assert dashboard.status_code == 200
    action = next(
        item
        for item in dashboard.json()["next_actions"]
        if item["action_kind"] == "practice"
    )
    weekly = client.get("/api/v1/progress/weekly")
    assert weekly.status_code == 200
    assert weekly.json()["report_version"] == 1
    history = client.get("/api/v1/progress/weekly/history")
    assert history.status_code == 200
    assert len(history.json()) == 1
    started = client.post(
        f"/api/v1/progress/actions/{action['action_id']}/start"
    )
    assert started.status_code == 200
    assert started.json()["source_type"] == "progress_action"
