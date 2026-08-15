from __future__ import annotations


from ielts_coach.capabilities import get_capability
from ielts_coach.skill_policy import compile_skill_envelope


def test_stage_selection_narrows_writing_references() -> None:
    capability = get_capability("writing_review")
    full = compile_skill_envelope(capability)
    diagnose = compile_skill_envelope(capability, stage="diagnose")
    assess = compile_skill_envelope(capability, stage="assess")

    assert len(full.references) > len(diagnose.references)
    assert [item["path"] for item in diagnose.references] == [
        "references/workflow.md"
    ]
    assert {
        item["path"] for item in assess.references
    } == {"references/workflow.md", "references/scoring-policy.md"}
    # Stage-specific envelopes hash differently for provenance tracing.
    assert full.source_hash != diagnose.source_hash


def test_unknown_stage_falls_back_to_full_references() -> None:
    capability = get_capability("writing_review")
    full = compile_skill_envelope(capability)
    unknown = compile_skill_envelope(capability, stage="not-a-phase")
    assert [item["path"] for item in unknown.references] == [
        item["path"] for item in full.references
    ]


def test_skills_without_reference_selection_are_unchanged() -> None:
    # general-* skills have no references directory: stage filtering is a no-op.
    capability = get_capability("writing_feedback")
    plain = compile_skill_envelope(capability)
    staged = compile_skill_envelope(capability, stage="assess")
    assert plain.references == staged.references
    assert plain.source_hash == staged.source_hash
