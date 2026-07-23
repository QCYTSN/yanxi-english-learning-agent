from __future__ import annotations

from pathlib import Path

import pytest

from ielts_coach.assessment_builder import assemble_assessment_pack
from ielts_coach.conformance import enrich_question_conformance
from ielts_coach.content_reviews import (
    get_target_review,
    list_content_reviews,
    record_content_review,
    refresh_target_status,
)
from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import content_hash
from ielts_coach.storage import (
    get_assessment_pack,
    get_question_for_grading,
    upsert_question,
)


def test_local_review_is_hashed_auditable_and_invalidates_dependent_pack(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    question_id = "START-WT2-001"

    initial = get_target_review(home, "question", question_id, include_material=False)
    assert initial["local_review_status"] == "approved"
    initial_hash = initial["content_hash"]

    pack = assemble_assessment_pack(
        home,
        module="writing",
        title="Audited writing pair",
        question_ids=["START-WT1-001", question_id],
    )
    pack_target = get_target_review(home, "assessment_pack", pack["pack_id"])
    record_content_review(
        home,
        target_type="assessment_pack",
        target_id=pack["pack_id"],
        reviewer="Test reviewer",
        decision="approved",
        checklist={key: True for key in pack_target["required_checklist"]},
    )
    assert get_assessment_pack(home, pack["pack_id"])["conformance_status"] == "verified"

    changed = dict(get_question_for_grading(home, question_id) or {})
    changed["content"] = str(changed["content"]) + " Give reasons and relevant examples."
    changed["review_status"] = "unreviewed"
    changed.pop("conformance_status", None)
    changed.pop("conformance_report", None)
    changed = enrich_question_conformance(changed)
    changed["content_hash"] = content_hash(changed)
    assert upsert_question(home, changed, force=True) is True
    refresh_target_status(home, "question", question_id)

    stale = get_target_review(home, "question", question_id, include_material=False)
    assert stale["content_hash"] != initial_hash
    assert stale["local_review_status"] == "stale"
    assert stale["stale_review_count"] >= 1
    assert get_question_for_grading(home, question_id)["conformance_status"] == "provisional"
    invalidated_pack = get_assessment_pack(home, pack["pack_id"])
    assert invalidated_pack["conformance_status"] == "provisional"

    target = get_target_review(home, "question", question_id)
    with pytest.raises(ValueError, match="every checklist item"):
        record_content_review(
            home,
            target_type="question",
            target_id=question_id,
            reviewer="Test reviewer",
            decision="approved",
            checklist={},
        )
    approved = record_content_review(
        home,
        target_type="question",
        target_id=question_id,
        reviewer="Test reviewer",
        decision="approved",
        checklist={key: True for key in target["required_checklist"]},
        notes="Prompt change checked.",
    )
    assert approved["local_review_status"] == "approved"
    history = list_content_reviews(home, target_type="question", target_id=question_id)
    assert {item["reviewer"] for item in history} >= {
        "IELTS AI Coach bundled-content review",
        "Test reviewer",
    }
