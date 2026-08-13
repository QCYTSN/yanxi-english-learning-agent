from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.vocabulary import (
    add_vocabulary_item,
    due_vocabulary_reviews,
    list_vocabulary_items,
    schedule_vocabulary_review,
    set_vocabulary_status,
)
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="vocab-test-token-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    response = client.post(
        "/api/auth/exchange",
        json={"token": "vocab-test-token-long-enough"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    client.headers.update({CSRF_HEADER_NAME: csrf})
    return client


def test_vocabulary_item_lifecycle(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)

    added = client.post(
        "/api/v1/vocabulary",
        json={
            "word": "schedule",
            "meaning": "时间安排",
            "usage": "schedule a meeting for Friday",
            "example": "I have a busy schedule this week.",
            "collocations": ["busy schedule", "on schedule"],
            "review_kind": "sentence_recall",
        },
    )
    assert added.status_code == 200
    item = added.json()
    assert item["word"] == "schedule"
    assert item["status"] == "learning"
    assert item["collocations"] == ["busy schedule", "on schedule"]

    # Idempotent re-add keeps one row and enriches it.
    again = client.post("/api/v1/vocabulary", json={"word": "schedule"})
    assert again.json()["item_id"] == item["item_id"]

    due = client.get("/api/v1/vocabulary/due").json()
    assert any(entry["word"] == "schedule" for entry in due)

    scheduled = client.patch(
        f"/api/v1/vocabulary/{item['item_id']}/review",
        json={"days": 3},
    ).json()
    assert scheduled["review_count"] == 1
    assert scheduled["next_review_at"] is not None
    assert not any(
        entry["word"] == "schedule"
        for entry in client.get("/api/v1/vocabulary/due").json()
    )

    mastered = client.patch(
        f"/api/v1/vocabulary/{item['item_id']}/status",
        json={"status": "mastered"},
    ).json()
    assert mastered["status"] == "mastered"


def test_vocabulary_functions_and_track_isolation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)

    item = add_vocabulary_item(
        home,
        word="deadline",
        meaning="截止时间",
        review_kind="fill_context",
        track_id="general-english",
    )
    assert item["track_id"] == "general-english"
    assert len(list_vocabulary_items(home)) == 1
    assert len(list_vocabulary_items(home, track_id="ielts-academic")) == 0

    scheduled = schedule_vocabulary_review(home, item["item_id"], days=1)
    assert scheduled["next_review_at"] is not None
    assert scheduled["review_count"] == 1

    assert due_vocabulary_reviews(home, now="2000-01-01T00:00:00+00:00") == []
    assert len(due_vocabulary_reviews(home)) >= 0

    with pytest.raises(ValueError):
        add_vocabulary_item(home, word="")

    with pytest.raises(ValueError):
        set_vocabulary_status(home, "missing-item", status="learning")


def test_onboarding_goal_sets_track_and_exam(tmp_path: Path) -> None:
    from ielts_coach.onboarding import update_profile
    from ielts_coach.config import load_profile

    home = tmp_path / "home"
    initialise_home(home)

    # general goal: track general-english, exam none
    result = update_profile(
        home,
        {
            "active_learning_track_id": "general-english",
            "exam": {"type": "none", "test_date": None},
        },
        mark_ready=True,
    )
    assert result["onboarding"]["status"] == "ready"
    profile = load_profile(home)
    assert profile["active_learning_track_id"] == "general-english"
    assert profile["exam"]["type"] == "none"

    # ielts goal: track ielts-academic, exam academic
    result = update_profile(
        home,
        {
            "active_learning_track_id": "ielts-academic",
            "exam": {"type": "academic", "test_date": "2026-12-12"},
        },
    )
    profile = load_profile(home)
    assert profile["active_learning_track_id"] == "ielts-academic"
    assert profile["exam"]["type"] == "academic"
    assert profile["exam"]["test_date"] == "2026-12-12"
