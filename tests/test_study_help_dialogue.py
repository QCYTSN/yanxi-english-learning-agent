from __future__ import annotations

import pytest

from ielts_coach.agent_contracts import validate_agent_contract


def _teacher_dialogue() -> dict[str, object]:
    return {
        "contract_version": 1,
        "module": "mixed",
        "request_kind": "teacher_dialogue",
        "evidence_status": "not_required",
        "answer_status": "not_applicable",
        "summary": "你好！今天想练阅读、写作、听力还是口语？",
        "sections": [],
        "evidence": [],
        "limitations": [],
        "next_action": None,
    }


def test_teacher_dialogue_does_not_require_uploaded_material() -> None:
    assert validate_agent_contract("study-help@1", _teacher_dialogue())


def test_teacher_dialogue_cannot_claim_source_evidence_is_required() -> None:
    result = _teacher_dialogue()
    result["evidence_status"] = "insufficient"
    with pytest.raises(ValueError, match="not required"):
        validate_agent_contract("study-help@1", result)
