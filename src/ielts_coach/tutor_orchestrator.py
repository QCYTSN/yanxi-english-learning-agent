from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .agent_contracts import validate_agent_contract
from .learning_model import get_learning_model_snapshot, list_learning_reviews
from .learning_orchestration import list_review_tasks
from .pedagogy import get_active_teaching_cycle
from .question_bank import show_question, show_reading_set
from .session_manager import show_session
from .storage import (
    get_session,
    list_learner_memories,
    list_questions,
    search_learning_history,
)
from .study_context import build_study_context
from .study_threads import get_study_thread_overview, list_study_attachments
from .text_anchor import create_text_anchor
from .tutor_state import get_thread_learning_state
from .validation import load_schema


MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS = 6
MAX_TOOL_RESULT_CHARS = 12_000


@dataclass(frozen=True)
class DomainToolSpec:
    name: str
    description: str
    mode: str
    handler: Callable[..., Any]
    requires_confirmation: bool = False

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class TutorLoopOutcome:
    result: dict[str, Any]
    orchestration: dict[str, Any]


class DomainToolRegistry:
    """Small, typed IELTS tool boundary exposed to the tutor planner."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self._tools = {
            "inspect_thread_material": DomainToolSpec(
                "inspect_thread_material",
                "Inspect locally registered thread attachments and extracted text.",
                "query",
                self._inspect_thread_material,
            ),
            "locate_passage_evidence": DomainToolSpec(
                "locate_passage_evidence",
                "Locate quoted evidence in an attached document or registered passage.",
                "query",
                self._locate_passage_evidence,
            ),
            "get_question_context": DomainToolSpec(
                "get_question_context",
                "Read a learner-visible question and passage without exposing hidden answers.",
                "query",
                self._question_context,
            ),
            "get_learner_snapshot": DomainToolSpec(
                "get_learner_snapshot",
                "Read the deterministic learner profile and recent evidence.",
                "query",
                self._learner_snapshot,
            ),
            "get_due_reviews": DomainToolSpec(
                "get_due_reviews",
                "Read due Runtime review tasks without changing them.",
                "query",
                self._due_reviews,
            ),
            "find_approved_materials": DomainToolSpec(
                "find_approved_materials",
                "Find learner-ready, reviewed and IELTS-conformant materials.",
                "query",
                self._approved_materials,
            ),
            "get_session_status": DomainToolSpec(
                "get_session_status",
                "Read one formal Session state.",
                "query",
                self._session_status,
            ),
            "search_learning_history": DomainToolSpec(
                "search_learning_history",
                "Search local conversations, learner writing and error evidence.",
                "query",
                self._learning_history,
            ),
            "get_learner_memories": DomainToolSpec(
                "get_learner_memories",
                "Read learner-approved teaching preferences and recurring patterns.",
                "query",
                self._learner_memories,
            ),
            "get_teaching_policy": DomainToolSpec(
                "get_teaching_policy",
                "Read deterministic IELTS teaching and answer-disclosure rules.",
                "query",
                self._teaching_policy,
            ),
            "compare_writing_versions": DomainToolSpec(
                "compare_writing_versions",
                "Read learner-authored Writing versions for evidence-based comparison.",
                "query",
                self._compare_writing_versions,
            ),
            "propose_practice_session": DomainToolSpec(
                "propose_practice_session",
                "Propose a formal practice action; learner confirmation is required.",
                "command_proposal",
                self._practice_proposal,
                requires_confirmation=True,
            ),
            "propose_review_item": DomainToolSpec(
                "propose_review_item",
                "Propose a review-queue item; learner confirmation is required.",
                "command_proposal",
                self._review_proposal,
                requires_confirmation=True,
            ),
            "propose_learner_memory": DomainToolSpec(
                "propose_learner_memory",
                "Propose a learner-visible soft memory; learner confirmation is required.",
                "command_proposal",
                self._memory_proposal,
                requires_confirmation=True,
            ),
            "propose_material_promotion": DomainToolSpec(
                "propose_material_promotion",
                "Propose moving attached material into Content Studio for review.",
                "command_proposal",
                self._material_proposal,
                requires_confirmation=True,
            ),
        }

    def descriptors(self) -> list[dict[str, Any]]:
        return [tool.descriptor() for tool in self._tools.values()]

    def spec(self, name: str) -> DomainToolSpec:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tutor domain tool is not allowed: {name}")
        return tool

    def execute(self, name: str, **arguments: Any) -> Any:
        tool = self.spec(name)
        return tool.handler(**{key: value for key, value in arguments.items() if value is not None})

    def _inspect_thread_material(
        self,
        thread_id: str,
        attachment_id: str | None = None,
        query: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        attachments = list_study_attachments(self.home, thread_id)
        results = []
        for item in reversed(attachments):
            if attachment_id and item["attachment_id"] != attachment_id:
                continue
            text = str(item.get("extracted_text") or "")
            excerpt = _evidence_excerpt(text, query) if text else ""
            results.append(
                {
                    "attachment_id": item["attachment_id"],
                    "name": item["original_name"],
                    "file_kind": item["file_kind"],
                    "extraction_status": item["extraction_status"],
                    "text_excerpt": excerpt[:4000],
                    "content_hash": item["sha256"],
                }
            )
            if len(results) >= max(1, min(int(limit), 10)):
                break
        return results

    def _locate_passage_evidence(
        self,
        thread_id: str,
        query: str,
        attachment_id: str | None = None,
        passage_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        documents: list[dict[str, Any]] = []
        if passage_id:
            reading_set = show_reading_set(self.home, passage_id, include_answers=False)
            if reading_set:
                passage = reading_set["passage"]
                documents.append(
                    {
                        "document_kind": "reading_passage",
                        "document_id": passage_id,
                        "title": passage.get("title"),
                        "text": str(passage.get("body") or ""),
                    }
                )
        for item in list_study_attachments(self.home, thread_id):
            if attachment_id and item["attachment_id"] != attachment_id:
                continue
            text = str(item.get("extracted_text") or "")
            if text:
                documents.append(
                    {
                        "document_kind": "thread_attachment",
                        "document_id": item["attachment_id"],
                        "title": item["original_name"],
                        "text": text,
                    }
                )
        matches = []
        for document in documents:
            quote = _best_matching_quote(document["text"], clean_query)
            if not quote:
                continue
            anchor = create_text_anchor(
                document["text"],
                quote,
                document_kind=document["document_kind"],
                document_id=document["document_id"],
            )
            matches.append(
                {
                    "source": document["title"] or document["document_id"],
                    "quote": quote,
                    "anchor": anchor,
                }
            )
            if len(matches) >= max(1, min(int(limit), 10)):
                break
        return matches

    def _question_context(
        self,
        thread_id: str,
        question_id: str | None = None,
        passage_id: str | None = None,
    ) -> dict[str, Any]:
        thread = get_study_thread_overview(self.home, thread_id)
        source = thread.get("source_context") or {}
        question_id = question_id or source.get("question_id")
        passage_id = passage_id or source.get("passage_id")
        question = (
            show_question(self.home, str(question_id), include_answer=False)
            if question_id
            else None
        )
        reading_set = (
            show_reading_set(self.home, str(passage_id), include_answers=False)
            if passage_id
            else None
        )
        return {
            "question": question,
            "passage": reading_set.get("passage") if reading_set else None,
            "answer_key_exposed": False,
        }

    def _learner_snapshot(
        self,
        module: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        snapshot = build_study_context(self.home, module=module)
        learning_model = get_learning_model_snapshot(
            self.home,
            dimension_id=module,
        )
        objectives = [
            {
                "objective_id": item["objective_id"],
                "dimension_id": item["dimension_id"],
                "skill_id": item["skill_id"],
                "title": item["title"],
                "status": item["status"],
                "priority": item["priority"],
                "target_value": item["target_value"],
                "due_at": item["due_at"],
            }
            for item in learning_model["objectives"][:10]
        ]
        observed_skills = [
            {
                "skill_id": item["skill_id"],
                "dimension_id": item["dimension_id"],
                "title": item["title"],
                "mastery": {
                    key: value
                    for key, value in item["mastery"].items()
                    if key != "calculation"
                },
            }
            for item in learning_model["skills"]
            if item["mastery"] is not None
            and int(item["mastery"]["evidence_count"]) > 0
        ]
        observed_skills.sort(
            key=lambda item: (
                float(item["mastery"]["estimate"]),
                -int(item["mastery"]["evidence_count"]),
                str(item["skill_id"]),
            )
        )
        return {
            "context_version": snapshot["context_version"],
            "module": snapshot["module"],
            "profile": snapshot.get("profile"),
            "history": snapshot.get("history"),
            "allocation": snapshot.get("allocation"),
            "next_action": snapshot.get("next_action"),
            "learning_model": {
                "model_version": learning_model["model_version"],
                "summary": learning_model["summary"],
                "objectives": objectives,
                "observed_skills": observed_skills[:12],
            },
            "active_teaching_cycle": (
                get_active_teaching_cycle(self.home, thread_id)
                if thread_id
                else None
            ),
        }

    def _due_reviews(self, module: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 10))
        runtime_reviews = list_review_tasks(
            self.home,
            status="pending",
            module=module,
            limit=bounded,
        )
        learning_reviews = list_learning_reviews(
            self.home,
            dimension_id=module,
            status="pending",
            due_only=True,
            limit=bounded,
        )
        combined = [
            {"queue": "ielts_runtime", **item} for item in runtime_reviews
        ] + [{"queue": "learning_model", **item} for item in learning_reviews]
        combined.sort(
            key=lambda item: (
                str(item.get("due_at") or "9999"),
                -int(item.get("priority") or 0),
                str(item.get("queue") or ""),
            )
        )
        return combined[:bounded]

    def _approved_materials(
        self,
        module: str | None = None,
        query: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in list_questions(
                self.home,
                module=module,
                query=query,
                learner_ready=True,
                exclude_completed=True,
                limit=max(1, min(int(limit), 10)),
            )
        ]

    def _session_status(self, session_id: str) -> dict[str, Any] | None:
        row = get_session(self.home, session_id)
        if not row:
            return None
        return {
            key: row[key]
            for key in (
                "session_id",
                "module",
                "status",
                "revision",
                "question_id",
                "passage_id",
                "assessment_pack_id",
                "occurred_at",
            )
            if key in row.keys()
        }

    def _learning_history(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        return search_learning_history(self.home, query, limit=max(1, min(int(limit), 10)))

    def _learner_memories(self, limit: int = 8) -> list[dict[str, Any]]:
        return list_learner_memories(
            self.home,
            limit=max(1, min(int(limit), 10)),
            touch_access=True,
        )

    def _teaching_policy(
        self,
        module: str | None = None,
        answer_stage: str | None = None,
    ) -> dict[str, Any]:
        module = module if module in _MODULES else "mixed"
        return {
            "module": module,
            "answer_stage": answer_stage or "not_applicable",
            "reading": {
                "during_attempt": "progressive hints; withhold answer",
                "after_attempt": "evidence-grounded explanation is allowed",
                "without_key": "correctness remains unverified",
            },
            "writing": {
                "order": "evidence and priorities, learner revision, model alternative",
                "fragment_score": "forbidden",
            },
            "speaking": {"mock_correction": "forbidden during the mock"},
            "authority": "Runtime validation and learner confirmation",
        }

    def _compare_writing_versions(self, session_id: str) -> dict[str, Any]:
        session = show_session(self.home, session_id)
        if not session or session.get("module") != "writing":
            raise ValueError("Writing Session not found")
        versions = session.get("versions") or []
        return {
            "session_id": session_id,
            "versions": [
                {
                    "label": item.get("label"),
                    "content": item.get("content"),
                    "word_count": item.get("word_count"),
                }
                for item in versions[-3:]
            ],
            "model_alternative_allowed": len(versions) >= 2,
        }

    def _practice_proposal(
        self,
        module: str | None = None,
        title: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        clean_module = module if module in _MODULES else "mixed"
        return {
            "command": "create_practice_session",
            "proposal_type": "practice_session",
            "title": title or "开始一项正式练习",
            "rationale": action or "把当前学习目标转入受规则保护的正式练习。",
            "payload": {
                "module": clean_module,
                "route": f"/practice?module={clean_module}" if clean_module != "mixed" else "/practice",
            },
            "requires_confirmation": True,
        }

    def _review_proposal(
        self,
        module: str | None = None,
        title: str | None = None,
        action: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        clean_module = module if module in _MODULES else "mixed"
        return {
            "command": "create_review_item",
            "proposal_type": "review_item",
            "title": title or "加入复习队列",
            "rationale": action or "稍后重新检查当前问题。",
            "payload": {
                "module": clean_module,
                "title": title,
                "action": action,
                "session_id": session_id,
            },
            "requires_confirmation": True,
        }

    def _memory_proposal(
        self,
        statement: str,
        title: str | None = None,
        memory_type: str | None = None,
        memory_key: str | None = None,
        scope: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        return {
            "command": "save_learner_memory",
            "proposal_type": "learner_memory",
            "title": title or "记住这项学习偏好",
            "rationale": "这只会影响后续教学方式，不会改变答案或分数。",
            "payload": {
                "statement": str(statement)[:1000],
                "memory_type": str(memory_type or "teaching_preference")[:80],
                "memory_key": str(memory_key)[:160] if memory_key else None,
                "scope": str(scope or "teaching_style")[:80],
                "expires_at": str(expires_at)[:80] if expires_at else None,
                "confidence": 0.8,
            },
            "requires_confirmation": True,
        }

    def _material_proposal(
        self,
        title: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        return {
            "command": "promote_material",
            "proposal_type": "material_promotion",
            "title": title or "把材料整理成练习",
            "rationale": action or "材料需要经过内容审核后才能进入正式题库。",
            "payload": {"route": "/content-studio"},
            "requires_confirmation": True,
        }


class TutorOrchestrator:
    """Route simple turns directly and bound complex turns to IELTS tools."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.registry = DomainToolRegistry(home)

    def prepare(self, user_request: str, *, module: str | None = None) -> dict[str, Any]:
        """Compatibility endpoint for an explicit, deterministic context preview."""
        inferred_module = module if module in _MODULES else _infer_module(user_request)
        intent = _infer_intent(user_request)
        tools_used: list[str] = []

        def use(name: str, **arguments: Any) -> Any:
            tools_used.append(name)
            return self.registry.execute(name, **arguments)

        snapshot = use("get_learner_snapshot", module=inferred_module)
        memories = use("get_learner_memories", limit=8)
        history_query = _history_query(user_request)
        history = use("search_learning_history", query=history_query, limit=6) if history_query else []
        due_reviews = use("get_due_reviews", module=inferred_module, limit=5) if intent in {"review", "planning", "general"} else []
        materials = use("find_approved_materials", module=inferred_module, query=None, limit=5) if intent in {"practice", "planning"} and inferred_module else []
        proposal = use("propose_practice_session", module=inferred_module) if intent == "practice" else None
        return {
            "orchestrator_version": 2,
            "intent": intent,
            "module": inferred_module,
            "tools_used": tools_used,
            "tool_policy": {
                "direct_database_access": False,
                "formal_state_mutation": False,
                "command_confirmation_required": True,
            },
            "learner_snapshot": snapshot,
            "learner_memories": memories,
            "history_evidence": history,
            "due_reviews": due_reviews,
            "approved_materials": materials,
            "proposed_action": proposal,
        }

    def initial_context(
        self,
        user_request: str,
        *,
        thread_id: str,
        module: str | None = None,
        source_context: dict[str, Any] | None = None,
        has_material: bool = False,
        conversation_length: int = 0,
    ) -> dict[str, Any]:
        state = get_thread_learning_state(self.home, thread_id)
        thread = get_study_thread_overview(self.home, thread_id)
        thread_track = str(thread.get("track_id") or "ielts-academic")
        memories = [
            {
                "memory_id": item["memory_id"],
                "memory_type": item["memory_type"],
                "memory_key": item["memory_key"],
                "statement": str(item["statement"])[:400],
                "confidence": item["confidence"],
                "scope": item["scope"],
                "revision": item["revision"],
            }
            for item in list_learner_memories(
                self.home,
                track_id=thread_track,
                limit=6,
                touch_access=True,
            )
        ]
        inferred_module = module if module in _MODULES else _infer_module(user_request)
        route = _route_turn(
            user_request,
            has_material=has_material,
            conversation_length=conversation_length,
        )
        latency = _latency_profile(
            user_request,
            route=route,
            module=inferred_module,
            has_material=has_material,
        )
        return {
            "orchestrator_version": 2,
            "route": route,
            "intent": _infer_intent(user_request),
            "module": inferred_module,
            **latency,
            "answer_policy": _answer_policy(user_request, source_context or {}, state["state"]),
            "thread_state": state,
            "learner_memories": memories,
            "tools": self.registry.descriptors(),
            "budgets": {"max_rounds": MAX_TOOL_ROUNDS, "max_tool_calls": MAX_TOOL_CALLS},
            "tool_policy": _tool_policy(),
        }

    def execute(
        self,
        adapter: Any,
        request: dict[str, Any],
        emit: Callable[[str, dict[str, Any]], None],
    ) -> TutorLoopOutcome:
        canonical = dict(request.get("canonical_session") or {})
        initial = dict(canonical.get("tutor_orchestration") or {})
        route = str(initial.get("route") or "direct_response")
        answer_policy = str(initial.get("answer_policy") or "not_applicable")
        observations: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        tools_used: list[str] = []
        teaching_goal = str(canonical.get("user_request") or "IELTS learning support")[:500]
        rounds = 0
        last_plan_status = "not_planned"
        planning_degraded = False

        if route == "bounded_tool_loop":
            for round_number in range(1, MAX_TOOL_ROUNDS + 1):
                rounds = round_number
                emit("tutor_planning", {"stage": "tutor_planning", "round": round_number, "label": "Planning the next teaching step"})
                plan_request = _planner_request(request, initial, observations, round_number)
                try:
                    plan = validate_agent_contract(
                        "tutor-turn-plan@1",
                        _invoke_adapter(self.home, adapter, plan_request, emit),
                    )
                except Exception as exc:
                    # A failed planner must never fail the learner's turn:
                    # degrade to one direct answer and reuse gathered evidence.
                    planning_degraded = True
                    route = "direct_response"
                    emit(
                        "tutor_planning_fallback",
                        {
                            "stage": "tutor_planning",
                            "label": "Skipping tool planning and answering directly",
                            "error": str(exc)[:200],
                        },
                    )
                    break
                last_plan_status = str(plan["status"])
                teaching_goal = str(plan["teaching_goal"])[:500]
                if plan["status"] != "needs_tools":
                    break
                for call in plan["tool_calls"]:
                    if len(tools_used) >= MAX_TOOL_CALLS:
                        break
                    name = str(call["name"])
                    emit("tool_started", {"stage": "tool_execution", "tool": name, "call_id": call["call_id"]})
                    try:
                        arguments = _clean_tool_arguments(call.get("arguments") or {})
                        arguments = _scope_tool_arguments(name, arguments, canonical)
                        spec = self.registry.spec(name)
                        output = self.registry.execute(name, **arguments)
                        observation = {
                            "call_id": call["call_id"],
                            "tool": name,
                            "ok": True,
                            "result": _bounded_json(output),
                        }
                        if spec.requires_confirmation and isinstance(output, dict):
                            proposals.append(output)
                    except Exception as exc:
                        observation = {
                            "call_id": call["call_id"],
                            "tool": name,
                            "ok": False,
                            "error": str(exc)[:1000],
                        }
                    observations.append(observation)
                    tools_used.append(name)
                    emit("tool_completed", {"stage": "tool_execution", "tool": name, "call_id": call["call_id"], "ok": observation["ok"]})
                if len(tools_used) >= MAX_TOOL_CALLS:
                    break

        final_request = dict(request)
        final_request["runtime_hints"] = {
            "latency_profile": initial.get("latency_profile", "deliberate"),
            "reasoning_effort": initial.get("reasoning_effort"),
        }
        final_canonical = dict(canonical)
        final_canonical["tutor_agent"] = {
            "route": route,
            "teaching_goal": teaching_goal,
            "answer_policy": answer_policy,
            "thread_learning_state": initial.get("thread_state"),
            "learner_memories": initial.get("learner_memories") or [],
            "tool_observations": observations,
            "tool_budget_exhausted": (
                len(tools_used) >= MAX_TOOL_CALLS
                or (rounds >= MAX_TOOL_ROUNDS and last_plan_status == "needs_tools")
            ),
            "planning_degraded": planning_degraded,
            "instruction": (
                "Use observations as evidence only. Command proposals are not yet confirmed or executed. "
                + (
                    "For a casual direct turn, respond naturally and briefly; do not manufacture a lesson plan."
                    if initial.get("latency_profile") == "instant"
                    else ""
                )
            ),
        }
        final_request["canonical_session"] = final_canonical
        emit("tutor_answering", {"stage": "tutor_answering", "label": "Composing the IELTS teaching response"})
        result = _invoke_adapter(self.home, adapter, final_request, emit)
        return TutorLoopOutcome(
            result=result,
            orchestration={
                "orchestrator_version": 2,
                "route": route,
                "rounds": rounds,
                "tool_calls": len(tools_used),
                "tools_used": tools_used,
                "planning_degraded": planning_degraded,
                "teaching_goal": teaching_goal,
                "answer_policy": answer_policy,
                "latency_profile": initial.get("latency_profile", "deliberate"),
                "effective_reasoning_effort": initial.get("reasoning_effort"),
                "base_state_revision": (initial.get("thread_state") or {}).get("revision", 0),
                "proposals": proposals,
            },
        )


def validate_tutor_result_against_policy(
    result: dict[str, Any], orchestration: dict[str, Any]
) -> dict[str, Any]:
    policy = str(orchestration.get("answer_policy") or "not_applicable")
    if policy in {"progressive_hint", "locked"} and result.get("answer_status") == "verified":
        raise ValueError("Tutor answer policy forbids revealing or verifying the answer in this turn")
    if policy == "locked" and result.get("request_kind") == "question_explanation":
        raise ValueError("Formal mock integrity forbids question explanation during the attempt")
    return result


def _planner_request(
    request: dict[str, Any],
    initial: dict[str, Any],
    observations: list[dict[str, Any]],
    round_number: int,
) -> dict[str, Any]:
    skill = dict(request.get("skill_envelope") or {})
    policy = dict(skill.get("context_policy") or {})
    policy.update(
        {
            "response_mode": "tool_plan",
            "allowed_tools": initial.get("tools") or [],
            "max_tool_calls_this_round": 3,
            "formal_state_mutation": False,
            "command_tools_create_unconfirmed_proposals": True,
        }
    )
    skill.update(
        {
            "output_contract": "tutor-turn-plan@1",
            "output_schema": load_schema("tutor-turn-plan"),
            "allowed_tools": [item["name"] for item in initial.get("tools") or []],
            "context_policy": policy,
        }
    )
    canonical = dict(request.get("canonical_session") or {})
    canonical["tutor_planning"] = {
        "round": round_number,
        "runtime_answer_policy": initial.get("answer_policy"),
        "thread_learning_state": initial.get("thread_state"),
        "previous_observations": observations,
    }
    return {
        **request,
        "capability_id": "tutor_turn_planning",
        "output_contract": "tutor-turn-plan@1",
        "skill_envelope": skill,
        "canonical_session": canonical,
        "runtime_hints": {
            "latency_profile": "planner",
            "reasoning_effort": "low",
        },
        # Planning needs material metadata, not duplicate image/audio payloads.
        "media_refs": [],
    }


def _invoke_adapter(
    home: Path,
    adapter: Any,
    request: dict[str, Any],
    emit: Callable[[str, dict[str, Any]], None],
) -> dict[str, Any]:
    start_with_events = getattr(adapter, "start_with_events", None)
    if callable(start_with_events):
        return start_with_events(
            home,
            request,
            lambda payload: emit("provider_progress", payload),
        )
    return adapter.start(home, request)


def _scope_tool_arguments(
    name: str,
    arguments: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, Any]:
    thread_id = str(canonical.get("thread_id") or "")
    thread_tools = {
        "inspect_thread_material",
        "locate_passage_evidence",
        "get_question_context",
        "get_learner_snapshot",
    }
    if name in thread_tools:
        requested = str(arguments.get("thread_id") or thread_id)
        if not thread_id or requested != thread_id:
            raise ValueError("Tutor tools cannot access another learning thread")
        arguments["thread_id"] = thread_id
    if name == "get_question_context":
        source = canonical.get("source_context") or {}
        arguments["question_id"] = arguments.get("question_id") or source.get("question_id")
        arguments["passage_id"] = arguments.get("passage_id") or source.get("passage_id")
    return arguments


def _clean_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if value is not None and value != ""}


def _bounded_json(value: Any) -> Any:
    """Bound a tool result while preserving its head and structural tail.

    Pure head truncation can silently drop the final entries of long tool
    results (passages, history lists). Keeping a tail slice preserves more of
    the structure the final teaching model needs to stay grounded.
    """
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= MAX_TOOL_RESULT_CHARS:
        return value
    head_bytes = int(MAX_TOOL_RESULT_CHARS * 0.6)
    tail_bytes = MAX_TOOL_RESULT_CHARS - head_bytes
    return {
        "truncated": True,
        "content": encoded[:head_bytes],
        "tail": encoded[-tail_bytes:],
        "original_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def _tool_policy() -> dict[str, Any]:
    return {
        "direct_database_access": False,
        "formal_state_mutation": False,
        "filesystem_or_shell_access": False,
        "command_confirmation_required": True,
        "read_tools_execute_inside_runtime": True,
    }


_MODULES = {"listening", "reading", "writing", "speaking"}
_MODULE_WORDS = {
    "listening": ("听力", "听写", "listening", "audio", "transcript"),
    "reading": ("阅读", "reading", "passage", "true false", "not given"),
    "writing": ("写作", "作文", "writing", "task 1", "task 2", "essay", "邮件", "email"),
    "speaking": ("口语", "speaking", "part 1", "part 2", "part 3", "cue card"),
    "vocabulary": ("词汇", "单词", "vocabulary", "word", "phrase"),
    "grammar": ("语法", "grammar", "时态", "主谓一致"),
}


def _infer_module(text: str) -> str | None:
    lowered = text.casefold()
    for module, words in _MODULE_WORDS.items():
        if any(word in lowered for word in words):
            return module
    return None


def _infer_intent(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("复习", "错题", "review", "又错", "薄弱")):
        return "review"
    if any(word in lowered for word in ("计划", "今天学", "安排", "plan", "下一步")):
        return "planning"
    if any(word in lowered for word in ("练习", "做题", "来一套", "practice", "mock")):
        return "practice"
    if any(word in lowered for word in ("解释", "为什么", "什么意思", "explain", "讲解")):
        return "explanation"
    return "general"


def _route_turn(text: str, *, has_material: bool, conversation_length: int) -> str:
    lowered = text.casefold().strip()
    if has_material:
        return "bounded_tool_loop"
    if _infer_intent(text) in {"review", "planning", "practice"}:
        return "bounded_tool_loop"
    if any(word in lowered for word in ("之前", "上次", "历史", "错题", "记住", "加入复习", "根据原文", "这篇文章")):
        return "bounded_tool_loop"
    if conversation_length > 4 and any(word in lowered for word in ("继续", "刚才", "那个", "它", "this", "that")):
        return "bounded_tool_loop"
    return "direct_response"


def _latency_profile(
    text: str,
    *,
    route: str,
    module: str | None,
    has_material: bool,
) -> dict[str, str | None]:
    """Choose per-turn effort without mutating the user's model settings."""
    if route == "bounded_tool_loop" or has_material:
        return {"latency_profile": "deliberate", "reasoning_effort": None}
    clean = " ".join(text.split())
    if module is None and len(clean) <= 80 and _infer_intent(clean) == "general":
        return {"latency_profile": "instant", "reasoning_effort": "low"}
    return {"latency_profile": "focused", "reasoning_effort": "medium"}


def _answer_policy(text: str, source: dict[str, Any], state: dict[str, Any]) -> str:
    if str(source.get("practice_mode") or "") in {"full_mock", "timed_mock"}:
        return "locked"
    module = source.get("module") or state.get("module") or _infer_module(text)
    if module != "reading" and not source.get("passage_id"):
        return "not_applicable"
    lowered = text.casefold()
    if any(word in lowered for word in ("为什么错", "why is", "错在哪里", "我的答案", "复盘")):
        return "review_allowed"
    if any(word in lowered for word in ("直接告诉", "公布答案", "正确答案", "reveal", "give me the answer")):
        return "explicit_reveal"
    if source.get("learner_answer") is not None or state.get("answer_stage") in {"attempted", "reviewed"}:
        return "review_allowed"
    return "progressive_hint"


def _history_query(text: str) -> str | None:
    quoted = re.search(r"[\"“](.{2,80}?)[\"”]", text)
    if quoted:
        return quoted.group(1).strip()
    english = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text) if word.casefold() not in {"what", "this", "that", "please", "could", "would", "ielts"}]
    if english:
        return english[-1]
    chinese = [item for item in re.findall(r"[\u4e00-\u9fff]{2,12}", text) if item not in {"今天想学", "帮我看看", "可以解释", "我想练习"}]
    return chinese[-1] if chinese else None


def _evidence_excerpt(text: str, query: str | None) -> str:
    if not text:
        return ""
    if not query:
        return text[:4000]
    lowered = text.casefold()
    terms = [item.casefold() for item in re.findall(r"[A-Za-z][A-Za-z'-]{2,}|[\u4e00-\u9fff]{2,}", query)]
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, min(positions) - 500) if positions else 0
    return text[start : start + 4000]


def _best_matching_quote(text: str, query: str) -> str | None:
    excerpt = _evidence_excerpt(text, query).strip()
    if not excerpt:
        return None
    sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+|\n+", excerpt) if item.strip()]
    terms = {item.casefold() for item in re.findall(r"[A-Za-z][A-Za-z'-]{2,}|[\u4e00-\u9fff]{2,}", query)}
    if not sentences:
        return excerpt[:800]
    return max(sentences, key=lambda item: sum(term in item.casefold() for term in terms))[:1200]
