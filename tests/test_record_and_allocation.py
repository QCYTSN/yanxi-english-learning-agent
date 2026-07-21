from pathlib import Path

from ielts_coach.allocation import recommend_allocation
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import record_session


def test_record_and_allocation(tmp_path: Path):
    home = tmp_path / "ielts-home"
    initialise_home(home)
    for i, band in enumerate([7.0, 7.5, 7.5], start=1):
        record_session(home, {
            "session_id": f"L-TEST-{i}",
            "module": "listening",
            "occurred_at": f"2026-07-{10+i:02d}T10:00:00",
            "band": band,
            "error_tags": ["L_DISTRACTOR"],
        })
    for i, band in enumerate([5.5, 5.5, 6.0], start=1):
        record_session(home, {
            "session_id": f"W-TEST-{i}",
            "module": "writing",
            "occurred_at": f"2026-07-{10+i:02d}T11:00:00",
            "band": band,
            "error_tags": ["GRA_ARTICLE"],
        })
    result = recommend_allocation(home)
    assert abs(sum(result.allocation.values()) - 1.0) < 1e-9
    assert result.allocation["writing"] >= result.allocation["speaking"]
    assert 0.60 <= result.allocation["listening"] + result.allocation["reading"] <= 0.80
