from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .learning_orchestration import list_review_tasks
from .storage import (
    get_session,
    list_learner_memories,
    list_questions,
    search_learning_history,
)
from .study_context import build_study_context


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


class DomainToolRegistry:
    """Allowlisted IELTS application queries exposed to the tutor layer."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self._tools = {
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
            "propose_practice_session": DomainToolSpec(
                "propose_practice_session",
                "Propose a practice action; Runtime creation still requires user confirmation.",
                "command_proposal",
                self._practice_proposal,
                requires_confirmation=True,
            ),
        }

    def descriptors(self) -> list[dict[str, Any]]:
        return [tool.descriptor() for tool in self._tools.values()]

    def execute(self, name: str, **arguments: Any) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tutor domain tool is not allowed: {name}")
        return tool.handler(**arguments)

    def _learner_snapshot(self, module: str | None = None) -> dict[str, Any]:
        snapshot = build_study_context(self.home, module=module)
        return {
            "context_version": snapshot["context_version"],
            "module": snapshot["module"],
            "profile": snapshot.get("profile"),
            "history": snapshot.get("history"),
            "allocation": snapshot.get("allocation"),
            "next_action": snapshot.get("next_action"),
        }

    def _due_reviews(self, module: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        return list_review_tasks(
            self.home,
            status="pending",
            module=module,
            limit=max(1, min(int(limit), 10)),
        )

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
        return search_learning_history(self.home, query, limit=limit)

    def _learner_memories(self, limit: int = 8) -> list[dict[str, Any]]:
        return list_learner_memories(self.home, limit=limit)

    def _practice_proposal(self, module: str | None = None) -> dict[str, Any]:
        return {
            "command": "create_practice_session",
            "module": module,
            "requires_confirmation": True,
            "route": f"/practice?module={module}" if module else "/practice",
        }


class TutorOrchestrator:
    """Build a bounded teaching context; never mutate formal learning state."""

    def __init__(self, home: Path) -> None:
        self.registry = DomainToolRegistry(home)

    def prepare(
        self,
        user_request: str,
        *,
        module: str | None = None,
    ) -> dict[str, Any]:
        inferred_module = module if module in _MODULES else _infer_module(user_request)
        intent = _infer_intent(user_request)
        tools_used: list[str] = []

        def use(name: str, **arguments: Any) -> Any:
            tools_used.append(name)
            return self.registry.execute(name, **arguments)

        snapshot = use("get_learner_snapshot", module=inferred_module)
        memories = use("get_learner_memories", limit=8)
        history_query = _history_query(user_request)
        history = (
            use("search_learning_history", query=history_query, limit=6)
            if history_query
            else []
        )
        due_reviews = (
            use("get_due_reviews", module=inferred_module, limit=5)
            if intent in {"review", "planning", "general"}
            else []
        )
        materials = (
            use(
                "find_approved_materials",
                module=inferred_module,
                query=None,
                limit=5,
            )
            if intent in {"practice", "planning"} and inferred_module
            else []
        )
        proposal = (
            use("propose_practice_session", module=inferred_module)
            if intent == "practice"
            else None
        )
        return {
            "orchestrator_version": 1,
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


_MODULES = {"listening", "reading", "writing", "speaking"}
_MODULE_WORDS = {
    "listening": ("听力", "听写", "listening", "audio", "transcript"),
    "reading": ("阅读", "reading", "passage", "true false", "not given"),
    "writing": ("写作", "作文", "writing", "task 1", "task 2", "essay"),
    "speaking": ("口语", "speaking", "part 1", "part 2", "part 3", "cue card"),
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


def _history_query(text: str) -> str | None:
    quoted = re.search(r"[\"“](.{2,80}?)[\"”]", text)
    if quoted:
        return quoted.group(1).strip()
    english = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text) if word.casefold() not in {"what", "this", "that", "please", "could", "would", "ielts"}]
    if english:
        return english[-1]
    chinese = [
        item
        for item in re.findall(r"[\u4e00-\u9fff]{2,12}", text)
        if item not in {"今天想学", "帮我看看", "可以解释", "我想练习"}
    ]
    return chinese[-1] if chinese else None
