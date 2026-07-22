from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AgentCapabilities
from ..question_bank import show_question
from ..session_manager import show_session
from ..text_anchor import create_text_anchor


class MockAdapter:
    id = "mock"
    label = "Mock feedback"

    def probe(self) -> AgentCapabilities:
        return AgentCapabilities(
            structured_output=True,
            streaming=True,
            session_resume=False,
            image_input=False,
            audio_input=False,
            tool_execution=False,
            remote_processing=False,
        )

    def run(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        session_id = str(request["study_session_id"])
        session = show_session(home, session_id)
        if not session:
            raise ValueError(f"Unknown Session: {session_id}")
        contract = request["output_contract"]
        if contract == "writing-review@1":
            return self._writing_review(home, session)
        if contract == "reading-review@1":
            return self._reading_review(session)
        raise ValueError(f"MockAdapter does not support {contract}")

    def _writing_review(self, home: Path, session: dict[str, Any]) -> dict[str, Any]:
        versions = session.get("versions") or []
        if not versions:
            raise ValueError("Writing feedback requires a submitted version")
        version = versions[-1]
        content = str(version["content"])
        quote = content[: min(80, len(content))]
        anchor = create_text_anchor(
            content,
            quote,
            document_kind="writing_version",
            document_id=f"{session['session_id']}:{version['label']}",
        )
        question = (
            show_question(home, str(session["question_id"]), include_answer=False)
            if session.get("question_id")
            else None
        )
        task = str(session.get("task") or (question or {}).get("task") or "task2")
        names = ("TA", "CC", "LR", "GRA") if task == "task1" else ("TR", "CC", "LR", "GRA")
        criteria = [
            {
                "criterion": name,
                "score_low": 6.0,
                "score_high": 6.5,
                "evidence_support": ["The response presents a clear attempt to address the task."],
                "evidence_limit": ["Development and precision are not yet consistent throughout."],
                "anchors": [anchor],
            }
            for name in names
        ]
        return {
            "review_version": 1,
            "session_id": session["session_id"],
            "stage": "first_review" if version["label"] == "v1" else "version_comparison",
            "task": task,
            "version_label": version["label"],
            "score_kind": "ai_training_estimate",
            "confidence": "low",
            "estimated_band": {"low": 6.0, "high": 6.5},
            "rubric": {
                "rubric_id": "ielts-writing-public-descriptors",
                "publisher": "IELTS",
                "standard": "IELTS Writing Band Descriptors",
                "version": "updated-2023",
                "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf",
            },
            "criteria": criteria,
            "priority_issues": [
                {
                    "tag": "TR_DEVELOPMENT",
                    "evidence": "One central idea needs fuller explanation and a concrete example.",
                    "learner_action": "Add one reason and one specific example before changing wording.",
                    "anchor": anchor,
                }
            ],
            "full_model_answer": None,
            "next_action": "Revise the response using the priority issue before requesting an alternative.",
        }

    def _reading_review(self, session: dict[str, Any]) -> dict[str, Any]:
        items = []
        for index, answer in enumerate(session.get("questions") or [], start=1):
            user_answer = answer.get("user_answer")
            items.append(
                {
                    "question_id": answer.get("question_id"),
                    "question_number": answer.get("question_number") or index,
                    "question_type": answer["question_type"],
                    "user_answer": user_answer,
                    "correct_answer": answer.get("correct_answer") or user_answer,
                    "evidence_location": "Mock evidence location",
                    "evidence": "This deterministic fixture confirms the review and persistence flow.",
                    "reasoning": "MockAdapter does not make a substantive IELTS answer judgment.",
                    "distractors": [],
                    "error_tags": [],
                    "next_rule": "Use an authorised key or a real Agent before treating this as learning evidence.",
                }
            )
        return {
            "review_version": 1,
            "session_id": session["session_id"],
            "mode": "wrong_answer_review",
            "answer_revealed": True,
            "items": items,
            "next_action": "Review the evidence with an authorised key.",
        }
