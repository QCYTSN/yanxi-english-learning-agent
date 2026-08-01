from __future__ import annotations

from pathlib import Path

from ielts_coach.question_bank import draw_question
from ielts_coach.scale_benchmark import benchmark_scale_fixture, seed_scale_fixture


def test_scale_fixture_and_lazy_random_draw(tmp_path: Path) -> None:
    home = tmp_path / "scale-home"
    seeded = seed_scale_fixture(home, session_count=1_000, question_count=10_000)
    assert seeded["session_count"] == 1_000
    assert seeded["question_count"] == 10_000

    first = draw_question(home, module="reading", seed=7)
    second = draw_question(home, module="reading", seed=7)
    assert first is not None
    assert first["question_id"] == second["question_id"]

    report = benchmark_scale_fixture(
        home,
        session_count=1_000,
        question_count=10_000,
        repeats=1,
    )
    assert report["passed"] is True
    assert all(report["query_plan_checks"].values())
    assert report["fixture"]["actual_counts"] == {
        "sessions": 1_000,
        "questions": 10_000,
    }
    assert report["question_random_draw_peak_kib"] < 2_048
