from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AgentCapabilities, AgentIdentity
from .. import __version__
from ..question_bank import show_question
from ..session_manager import show_session
from ..text_anchor import create_text_anchor


class MockAdapter:
    id = "mock"
    label = "Mock feedback"

    def identity(self) -> AgentIdentity:
        return AgentIdentity(
            agent_provider="ielts-ai-coach",
            agent_version=__version__,
            model_id=None,
            model_display_name=None,
            launcher_kind="deterministic_local",
            calibration_status="not_applicable",
        )

    def probe(self) -> AgentCapabilities:
        return AgentCapabilities(
            structured_output=True,
            streaming=True,
            session_resume=False,
            image_input=False,
            audio_input=False,
            tool_execution=False,
            remote_processing=False,
            cancellation=True,
            timeout_control=True,
        )

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        contract = request["output_contract"]
        if contract == "tutor-turn-plan@1":
            return {
                "contract_version": 1,
                "status": "ready",
                "module": "mixed",
                "teaching_goal": "Verify the bounded tutor pipeline without model inference.",
                "answer_policy": "not_applicable",
                "tool_calls": [],
                "missing_context": [],
            }
        if contract == "study-help@1":
            if request.get("material_evidence_sufficient"):
                return {
                    "contract_version": 1,
                    "module": "mixed",
                    "request_kind": "material_orientation",
                    "evidence_status": "insufficient",
                    "answer_status": "unverified",
                    "summary": "本地管线自检通过；没有调用模型，也没有分析附件。",
                    "sections": [
                        {
                            "title": "管线状态",
                            "content": "学习线程、结构化合同与保存流程可以正常工作。",
                        }
                    ],
                    "evidence": [],
                    "limitations": ["Mock Adapter 不读取图片或判断英语内容。"],
                    "next_action": "选择已连接且支持当前材料的模型。",
                }
            return {
                "contract_version": 1,
                "module": "mixed",
                "request_kind": "teacher_dialogue",
                "evidence_status": "not_required",
                "answer_status": "not_applicable",
                "summary": "你好！本地对话管线自检通过。今天想练阅读、写作、听力还是口语？",
                "sections": [
                    {
                        "title": "管线状态",
                        "content": "学习线程、结构化合同与保存流程可以正常工作；本次没有调用真实模型。",
                    }
                ],
                "evidence": [],
                "limitations": ["Mock Adapter 只验证工程管线，不会判断英语内容。"],
                "next_action": "选择已连接且支持当前材料的模型。",
            }
        if contract.startswith("general-"):
            # General English contracts share the conversation pipeline: the
            # mock returns a valid conversation-shaped result for the
            # deterministic pipeline test.
            module = "mixed"
            request_kind = "teacher_dialogue"
            if contract == "general-writing-feedback@1":
                return {
                    "contract_version": 1,
                    "feedback_summary": "本地管线自检通过，未调用模型。",
                    "priority_issues": [
                        {
                            "issue": "管线自检",
                            "evidence": "Mock Adapter 未读取学习者文本。",
                            "learner_action": "连接模型后重新提交。",
                        }
                    ],
                    "strengths": [],
                    "revised_example": "Pipeline test only.",
                    "check_question": "连接模型后，试着改一版再发回来。",
                    "limitations": ["Mock Adapter 只验证工程管线。"],
                }
            if contract == "general-speaking-prompt@1":
                return {
                    "contract_version": 1,
                    "mode": "practice_prompt",
                    "scenario": "Pipeline test",
                    "role": "Examiner",
                    "prompt": "Mock Adapter 只验证工程管线。",
                    "follow_ups": [],
                    "evaluation_dimensions": [],
                    "limitations": ["Mock Adapter 只验证工程管线。"],
                }
            if contract == "general-vocabulary@1":
                return {
                    "contract_version": 1,
                    "word": "pipeline",
                    "meaning": "管线",
                    "usage": "pipeline test",
                    "example": "This is a pipeline test.",
                    "collocations": [],
                    "review_suggestion": {"suggested": False, "kind": "none"},
                    "limitations": ["Mock Adapter 只验证工程管线。"],
                }
            if contract == "general-reading-coach@1":
                return {
                    "contract_version": 1,
                    "summary": "管线自检。",
                    "explanation": "Mock Adapter 未读取材料。",
                    "evidence_quotes": [],
                    "check_question": "连接模型后重试。",
                    "limitations": ["Mock Adapter 只验证工程管线。"],
                }
            if contract == "general-grammar@1":
                return {
                    "contract_version": 1,
                    "grammar_point": "pipeline",
                    "rule": "Mock 不判断语法。",
                    "correct_example": "The pipeline works.",
                    "incorrect_example": "The pipeline work.",
                    "check_question": "连接模型后重试。",
                    "limitations": ["Mock Adapter 只验证工程管线。"],
                }
            return {
                "contract_version": 1,
                "module": module,
                "request_kind": request_kind,
                "summary": "你好！本地对话管线自检通过。",
                "sections": [
                    {
                        "title": "管线状态",
                        "content": "学习线程、结构化合同与保存流程可以正常工作；本次没有调用真实模型。",
                    }
                ],
                "check_question": "连接模型后，试着用英语回答一个问题。",
                "limitations": ["Mock Adapter 只验证工程管线。"],
                "next_action": "选择已连接且支持当前材料的模型。",
            }
        session_id = str(request["study_session_id"])
        session = show_session(home, session_id)
        if not session:
            raise ValueError(f"Unknown Session: {session_id}")
        if contract == "writing-review@1":
            return self._writing_review(home, session)
        if contract == "writing-mock-review@1":
            return self._writing_mock_review(session)
        if contract == "reading-review@1":
            return self._reading_review(session)
        if contract == "listening-review@1":
            return self._listening_review(session)
        if contract == "speaking-evaluation@1":
            return self._speaking_evaluation(session)
        if contract == "study-plan@1":
            return {
                "contract_version": 1,
                "period": "current-week",
                "allocation": {
                    "listening": 0.35,
                    "reading": 0.35,
                    "writing": 0.20,
                    "speaking": 0.10,
                },
                "tasks": [
                    {
                        "module": "reading",
                        "title": "Complete one evidence-based reading drill",
                        "minutes": 30,
                        "reason": "Deterministic contract fixture",
                    }
                ],
                "evidence_summary": ["No model inference was used."],
            }
        if contract == "diagnostic-summary@1":
            return {
                "contract_version": 1,
                "diagnostic_id": f"diagnostic:{session_id}",
                "module_status": {
                    module: {"status": "missing", "evidence": []}
                    for module in ("listening", "reading", "writing", "speaking")
                },
                "evidence_gaps": ["Complete one Session in each module."],
                "recommended_next_steps": ["Start the deterministic diagnostic."],
            }
        if contract == "weekly-coaching@1":
            return {
                "contract_version": 1,
                "period": "current-week",
                "wins": [],
                "risks": ["Not enough eligible evidence."],
                "next_week_focus": ["Collect one verified objective result."],
                "evidence_limits": ["MockAdapter does not infer learning gains."],
            }
        raise ValueError(f"MockAdapter does not support {contract}")

    run = start

    def stream(self, home: Path, execution_ref: str) -> list[dict[str, Any]]:
        return []

    def cancel(self, home: Path, execution_ref: str) -> bool:
        return True

    def resume(
        self, home: Path, execution_ref: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        return self.start(home, request)

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
                "score_low": 0.0,
                "score_high": 0.0,
                "evidence_support": [
                    "Mock pipeline fixture: no IELTS judgment was performed."
                ],
                "evidence_limit": [
                    "No model was called, so this value is not a learner score."
                ],
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
            "score_kind": "mock_fixture",
            "confidence": "low",
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
                    "tag": "MOCK_ONLY",
                    "evidence": "The local UI-to-Runtime contract pipeline completed.",
                    "learner_action": "Choose Claude Code, OpenCode, or Manual for real feedback.",
                    "anchor": anchor,
                }
            ],
            "full_model_answer": None,
            "next_action": "Choose a real Agent or Manual handoff for IELTS feedback.",
        }

    def _writing_mock_review(self, session: dict[str, Any]) -> dict[str, Any]:
        def task(task_name: str, first_criterion: str) -> dict[str, Any]:
            return {
                "task": task_name,
                "confidence": "low",
                "criteria": [
                    {
                        "criterion": name,
                        "score": None if name == "TA" else 0.0,
                        "evidence_support": [
                            "Mock pipeline fixture: no IELTS judgment was performed."
                        ],
                        "evidence_limit": [
                            "No model or Task 1 visual analysis was used."
                        ],
                    }
                    for name in (first_criterion, "CC", "LR", "GRA")
                ],
                "priority_issues": [
                    {
                        "tag": "MOCK_ONLY",
                        "evidence": "The dual-task contract validated.",
                        "learner_action": "Choose a real Agent for IELTS feedback.",
                    }
                ],
            }

        return {
            "contract_version": 1,
            "session_id": session["session_id"],
            "assessment_run_id": session["assessment_run_id"],
            "score_kind": "mock_fixture",
            "confidence": "low",
            "rubric": {
                "rubric_id": "ielts-writing-public-descriptors",
                "publisher": "IELTS",
                "standard": "IELTS Writing Band Descriptors",
                "version": "updated-2023",
                "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf",
            },
            "visual_evidence": {
                "status": "insufficient",
                "sources": [],
                "media_ids": [],
                "limitations": [
                    "MockAdapter does not inspect Task 1 visual evidence."
                ],
            },
            "task1": task("task1", "TA"),
            "task2": task("task2", "TR"),
            "next_action": "Choose Claude Code, OpenCode, or Manual for real feedback.",
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

    def _listening_review(self, session: dict[str, Any]) -> dict[str, Any]:
        items = [
            {
                "question_number": item.get("question_number", index),
                "user_answer": item.get("user_answer"),
                "correct_answer": item.get("correct_answer"),
                "evidence_location": item.get("evidence_location")
                or "Registered audio evidence",
                "error_tags": item.get("error_tags") or [],
                "explanation": "Deterministic review fixture; verify against authorised audio evidence.",
                "distractor": None,
            }
            for index, item in enumerate(session.get("questions") or [], start=1)
        ]
        return {
            "contract_version": 1,
            "session_id": session["session_id"],
            "items": items,
            "priority_patterns": ["Verify spelling and segmentation."],
            "next_action": "Replay only in a non-mock review context.",
        }

    def _speaking_evaluation(self, session: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "session_id": session["session_id"],
            "score_kind": "partial_profile",
            "confidence": "low",
            "band": None,
            "rubric": {
                "publisher": "IELTS",
                "standard": "IELTS Speaking Band Descriptors",
                "version": "current-public",
                "source_reference": "https://ielts.org/",
            },
            "criteria": [
                {
                    "criterion": name,
                    "score": 6.0,
                    "evidence": ["Deterministic transcript-only fixture."],
                    "evidence_source": "transcript",
                }
                for name in ("FC", "LR", "GRA")
            ],
            "evidence_types": ["transcript"],
            "priorities": ["Collect audio evidence before evaluating Pronunciation."],
            "next_action": "Import a Voice / Live report with audio observations.",
        }
