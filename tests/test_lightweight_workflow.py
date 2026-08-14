from pathlib import Path

import yaml

from ielts_coach.init_home import initialise_home
from ielts_coach.onboarding import complete_onboarding
from ielts_coach.storage import record_session
from ielts_coach.study_context import build_study_context


def test_module_context_omits_global_planning_and_filters_history(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(home, {
        "session_id": "W-CONTEXT", "module": "writing", "status": "completed",
        "band": 6.0, "errors": [{"tag": "GRA_ARTICLE", "count": 2}],
    })
    record_session(home, {
        "session_id": "R-CONTEXT", "module": "reading", "status": "completed",
        "errors": [{"tag": "R_PARAPHRASE_MISS", "count": 3}],
    })

    context = build_study_context(home, module="writing")

    assert context["route"] == "ielts-writing"
    assert set(context["history"]["sessions"]) == {"writing"}
    assert context["history"]["active_errors"] == [{"tag": "GRA_ARTICLE", "count": 2}]
    assert "allocation" not in context
    assert "diagnostic" not in context
    assert "minimum_required" in context["profile"]


def test_generic_context_contains_one_compact_planning_snapshot(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    complete_onboarding(home, {"current": {"reading": 7.0}})

    context = build_study_context(home)

    assert context["route"] == "ielts"
    assert context["onboarding"]["status"] == "ready"
    assert context["diagnostic"]["status"] == "not_started"
    assert set(context["allocation"]) == {"listening", "reading", "writing", "speaking"}
    assert len(context["allocation_reasons"]) <= 3
    assert context["next_action"] == "recommend_one_primary_task"


def test_skill_metadata_and_runtime_contract_stay_lightweight():
    root = Path(__file__).resolve().parents[1] / "skills-source"
    total_body_chars = 0
    for skill_dir in root.iterdir():
        path = skill_dir / "SKILL.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        _, frontmatter, body = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert set(metadata) == {"name", "description"}
        total_body_chars += len(body)

    router = (root / "ielts" / "SKILL.md").read_text(encoding="utf-8")
    assert "xiyan study-context" in router
    assert "Do not separately run summary" in router
    for name in ("ielts-writing", "ielts-reading"):
        specialist = (root / name / "SKILL.md").read_text(encoding="utf-8")
        assert "begin immediately" in specialist.lower()
        assert "study-context --module" in specialist
    speaking = (root / "ielts-speaking" / "SKILL.md").read_text(encoding="utf-8")
    assert "begin immediately" in speaking.lower()
    assert "study-context --module" in speaking.lower()
    assert "two-step" in speaking.lower()
    assert "voice tool" in speaking.lower()

    # Prevent gradual prompt bloat across the thirteen focused Skill bodies
    # (six General English, seven IELTS). The dialogue Skills stay
    # capability-loaded rather than router preflight.
    assert total_body_chars < 30_000
