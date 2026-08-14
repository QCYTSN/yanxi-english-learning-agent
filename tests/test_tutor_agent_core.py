from __future__ import annotations

from pathlib import Path
from typing import Any

from ielts_coach.init_home import initialise_home
from ielts_coach.storage import create_agent_run
from ielts_coach.study_threads import add_user_message, create_study_thread
from ielts_coach.tutor_orchestrator import TutorOrchestrator
from ielts_coach.tutor_state import (
    get_thread_learning_state,
    list_tutor_proposals,
    persist_tutor_turn_effects,
    resolve_tutor_proposal,
)


def _arguments(**updates: Any) -> dict[str, Any]:
    result = {
        "thread_id": None,
        "attachment_id": None,
        "query": None,
        "module": None,
        "limit": None,
        "session_id": None,
        "passage_id": None,
        "question_id": None,
        "answer_stage": None,
        "title": None,
        "action": None,
        "statement": None,
        "memory_type": None,
        "memory_key": None,
        "scope": None,
        "expires_at": None,
    }
    result.update(updates)
    return result


class PlanningAdapter:
    def __init__(self) -> None:
        self.plans = 0

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        del home
        if request["output_contract"] == "tutor-turn-plan@1":
            self.plans += 1
            if self.plans == 1:
                return {
                    "contract_version": 1,
                    "status": "needs_tools",
                    "module": "reading",
                    "teaching_goal": "Locate the learner's passage evidence before explaining.",
                    "answer_policy": "progressive_hint",
                    "tool_calls": [
                        {
                            "call_id": "material-1",
                            "name": "inspect_thread_material",
                            "arguments": _arguments(query="solar heat"),
                        },
                        {
                            "call_id": "review-1",
                            "name": "propose_review_item",
                            "arguments": _arguments(
                                module="reading",
                                title="复习这道阅读题",
                                action="重新定位原文证据。",
                            ),
                        },
                    ],
                    "missing_context": [],
                }
            return {
                "contract_version": 1,
                "status": "ready",
                "module": "reading",
                "teaching_goal": "Give a passage-grounded progressive hint.",
                "answer_policy": "progressive_hint",
                "tool_calls": [],
                "missing_context": [],
            }
        assert request["canonical_session"]["tutor_agent"]["tool_observations"]
        return {
            "contract_version": 1,
            "module": "reading",
            "request_kind": "guided_hint",
            "evidence_status": "partial",
            "answer_status": "withheld",
            "summary": "先定位提到 solar heat 的句子，再判断题干是否改写了因果关系。",
            "sections": [],
            "evidence": [],
            "limitations": ["当前材料只提供了局部文字。"],
            "next_action": "标出题干中的限定词。",
        }


def test_complex_tutor_turn_uses_bounded_tools_and_creates_only_a_proposal(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Reading help", module="reading")
    message = add_user_message(
        home,
        thread["thread_id"],
        content="请根据这段材料提示我怎么做，不要直接说答案。",
        files=[("passage.txt", b"Plants convert solar heat into stored energy.", "text/plain")],
    )
    context = TutorOrchestrator(home).initial_context(
        message["content"],
        thread_id=thread["thread_id"],
        module="reading",
        has_material=True,
    )
    request = {
        "request_id": "run_tutor_loop",
        "output_contract": "study-help@1",
        "skill_envelope": {
            "skill": "ielts-study-help",
            "instructions": "Preserve Reading answer integrity.",
            "references": [],
            "context_policy": {},
            "output_schema": {},
        },
        "canonical_session": {
            "thread_id": thread["thread_id"],
            "module": "reading",
            "user_request": message["content"],
            "source_context": {},
            "tutor_orchestration": context,
        },
    }
    events: list[str] = []
    outcome = TutorOrchestrator(home).execute(
        PlanningAdapter(),
        request,
        lambda event_type, payload: events.append(event_type),
    )
    assert outcome.result["answer_status"] == "withheld"
    assert outcome.orchestration["rounds"] == 2
    assert outcome.orchestration["tool_calls"] == 2
    assert outcome.orchestration["proposals"][0]["requires_confirmation"] is True
    assert "tool_started" in events


class FailingPlannerAdapter:
    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        del home
        if request["output_contract"] == "tutor-turn-plan@1":
            raise RuntimeError("provider down during planning")
        return {
            "contract_version": 1,
            "module": "reading",
            "request_kind": "guided_hint",
            "evidence_status": "partial",
            "answer_status": "withheld",
            "summary": "先自己定位关键词，再看题干是否改写因果。",
            "sections": [],
            "evidence": [],
            "limitations": ["本轮未能查阅材料。"],
            "next_action": "圈出题干限定词。",
        }


class BadThreadPlanAdapter:
    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        del home
        if request["output_contract"] == "tutor-turn-plan@1":
            return {
                "contract_version": 1,
                "status": "needs_tools",
                "module": "reading",
                "teaching_goal": "Inspect the thread material.",
                "answer_policy": "progressive_hint",
                "tool_calls": [
                    {
                        "call_id": "material-x",
                        "name": "inspect_thread_material",
                        "arguments": _arguments(thread_id="another-thread"),
                    }
                ],
                "missing_context": [],
            }
        return {
            "contract_version": 1,
            "module": "reading",
            "request_kind": "guided_hint",
            "evidence_status": "partial",
            "answer_status": "withheld",
            "summary": "按原文顺序定位信息。",
            "sections": [],
            "evidence": [],
            "limitations": [],
            "next_action": "重读题干。",
        }


def _turn_request(home: Path, thread_id: str, content: str) -> dict[str, Any]:
    context = TutorOrchestrator(home).initial_context(
        content,
        thread_id=thread_id,
        module="reading",
        has_material=True,
    )
    return {
        "request_id": "run_tutor_loop",
        "output_contract": "study-help@1",
        "skill_envelope": {
            "skill": "ielts-study-help",
            "instructions": "Preserve Reading answer integrity.",
            "references": [],
            "context_policy": {},
            "output_schema": {},
        },
        "canonical_session": {
            "thread_id": thread_id,
            "module": "reading",
            "user_request": content,
            "source_context": {},
            "tutor_orchestration": context,
        },
    }


def test_tutor_turn_degrades_to_direct_response_when_planning_fails(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Degraded turn", module="reading")
    message = add_user_message(
        home,
        thread["thread_id"],
        content="请根据材料给我一个提示。",
        files=[("passage.txt", b"Solar heat is stored energy.", "text/plain")],
    )
    request = _turn_request(home, thread["thread_id"], str(message["content"]))
    events: list[str] = []
    outcome = TutorOrchestrator(home).execute(
        FailingPlannerAdapter(),
        request,
        lambda event_type, payload: events.append(event_type),
    )
    assert outcome.orchestration["planning_degraded"] is True
    assert outcome.orchestration["route"] == "direct_response"
    assert outcome.result["answer_status"] == "withheld"
    assert "tutor_planning_fallback" in events


def test_tutor_turn_contains_escaping_tool_arguments_as_failed_observation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Tool containment", module="reading")
    message = add_user_message(
        home,
        thread["thread_id"],
        content="提示我一下。",
        files=[("passage.txt", b"Plants store energy.", "text/plain")],
    )
    request = _turn_request(home, thread["thread_id"], str(message["content"]))
    events: list[tuple[str, dict[str, Any]]] = []
    outcome = TutorOrchestrator(home).execute(
        BadThreadPlanAdapter(),
        request,
        lambda event_type, payload: events.append((event_type, payload)),
    )
    assert outcome.result["answer_status"] == "withheld"
    completed = [payload for event_type, payload in events if event_type == "tool_completed"]
    assert completed and completed[0]["ok"] is False


def test_tutor_turn_effort_is_light_for_chat_and_preserved_for_complex_work(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Effort routing", module="mixed")
    orchestrator = TutorOrchestrator(home)

    greeting = orchestrator.initial_context(
        "hallo",
        thread_id=thread["thread_id"],
    )
    focused = orchestrator.initial_context(
        "请解释一下 IELTS Writing Task 2 的主题句应该怎样写。",
        thread_id=thread["thread_id"],
    )
    material = orchestrator.initial_context(
        "请根据这份材料讲解。",
        thread_id=thread["thread_id"],
        has_material=True,
    )

    assert greeting["latency_profile"] == "instant"
    assert greeting["reasoning_effort"] == "low"
    assert focused["latency_profile"] == "focused"
    assert focused["reasoning_effort"] == "medium"
    assert material["latency_profile"] == "deliberate"
    assert material["reasoning_effort"] is None


def test_tutor_state_and_review_proposal_are_idempotent_and_confirmed_by_user(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Reading state", module="reading")
    message = add_user_message(
        home,
        thread["thread_id"],
        content="给我一个提示。",
        files=[],
        context={"learner_answer": "B", "learner_reasoning": "第二段提到了原因。"},
    )
    request = {
        "study_thread_id": thread["thread_id"],
        "user_message_id": message["message_id"],
        "canonical_session": {
            "thread_id": thread["thread_id"],
            "module": "reading",
            "source_context": message["context"],
        },
    }
    run = create_agent_run(
        home,
        {
            "run_id": "run_state_commit",
            "study_session_id": None,
            "adapter_id": "mock",
            "capability_id": "study_material_help",
            "backend_kind": "mock",
            "action": "teacher_dialogue",
            "output_contract": "study-help@1",
            "status": "persisted",
            "request": request,
        },
    )
    result = {
        "contract_version": 1,
        "module": "reading",
        "request_kind": "guided_hint",
        "evidence_status": "partial",
        "answer_status": "withheld",
        "summary": "先核对题干限定词。",
        "sections": [],
        "evidence": [],
        "limitations": ["尚未核对答案键。"],
        "next_action": "重新定位第二段。",
    }
    orchestration = {
        "teaching_goal": "帮助学习者定位证据",
        "answer_policy": "progressive_hint",
        "proposals": [
            {
                "proposal_type": "review_item",
                "title": "复习这道阅读题",
                "rationale": "重新定位第二段证据。",
                "payload": {"module": "reading"},
            }
        ],
    }
    first = persist_tutor_turn_effects(
        home, run=run, result=result, orchestration=orchestration
    )
    second = persist_tutor_turn_effects(
        home, run=run, result=result, orchestration=orchestration
    )
    assert first["learning_state"]["revision"] == 1
    assert second["learning_state"]["revision"] == 1
    state = get_thread_learning_state(home, thread["thread_id"])
    assert state["state"]["learner_answer"] == "B"
    assert state["state"]["hint_level"] == 1
    proposals = list_tutor_proposals(home, thread_id=thread["thread_id"])
    assert len(proposals) == 1
    confirmed = resolve_tutor_proposal(
        home, proposals[0]["proposal_id"], decision="confirm"
    )
    assert confirmed["status"] == "executed", confirmed["result"]
    assert confirmed["result"]["review_task_id"].startswith("RT-tutor-")
