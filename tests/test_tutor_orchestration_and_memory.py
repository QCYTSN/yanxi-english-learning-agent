from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.storage import (
    create_learner_memory,
    delete_learner_memory,
    list_learner_memories,
    search_learning_history,
    update_learner_memory,
)
from ielts_coach.study_threads import (
    add_user_message,
    create_study_thread,
    get_study_thread,
    study_thread_agent_context,
)
from ielts_coach.tutor_orchestrator import DomainToolRegistry, TutorOrchestrator
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def test_learner_memories_are_user_manageable_and_soft(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    memory = create_learner_memory(
        home,
        memory_type="learning_preference",
        statement="先解释结构，再给细节。",
        confidence=0.9,
        evidence_refs=["thread:test/message:1"],
    )
    assert memory["status"] == "active"
    assert memory["evidence_refs"] == ["thread:test/message:1"]
    assert list_learner_memories(home)[0]["memory_id"] == memory["memory_id"]

    updated = update_learner_memory(
        home,
        memory["memory_id"],
        statement="先解释整体结构，再逐步分析细节。",
        confidence=0.95,
    )
    assert updated["confidence"] == 0.95
    dismissed = update_learner_memory(
        home, memory["memory_id"], status="dismissed"
    )
    assert dismissed["status"] == "dismissed"
    assert list_learner_memories(home) == []
    assert delete_learner_memory(home, memory["memory_id"]) is True


def test_long_threads_use_a_bounded_summary_and_local_search(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Speaking review", module="speaking")
    message_ids = []
    for index in range(13):
        message = add_user_message(
            home,
            thread["thread_id"],
            content=f"第 {index} 轮：我想复习环境保护这个口语话题。",
            files=[],
        )
        message_ids.append(message["message_id"])

    detail = get_study_thread(home, thread["thread_id"])
    assert detail["conversation_summary"]["message_count"] == 3
    context = study_thread_agent_context(
        home,
        thread_id=thread["thread_id"],
        message_id=message_ids[-1],
    )
    assert context["module"] == "speaking"
    assert len(context["conversation"]) == 10
    assert "环境保护" in context["conversation_summary"]["summary"]
    matches = search_learning_history(home, "环境保护", limit=3)
    assert len(matches) == 3
    assert all(item["source_type"] == "study_message" for item in matches)


def test_tutor_orchestrator_only_uses_allowlisted_domain_tools(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    create_learner_memory(
        home,
        memory_type="teaching_preference",
        statement="一次只给三个重点。",
        confidence=1.0,
    )
    registry = DomainToolRegistry(home)
    with pytest.raises(ValueError, match="not allowed"):
        registry.execute("execute_sql", sql="DROP TABLE sessions")

    prepared = TutorOrchestrator(home).prepare(
        "请根据我最近的阅读错题安排今天的复习。",
        module="reading",
    )
    assert prepared["intent"] == "review"
    assert prepared["module"] == "reading"
    assert prepared["tool_policy"] == {
        "direct_database_access": False,
        "formal_state_mutation": False,
        "command_confirmation_required": True,
    }
    assert "get_learner_snapshot" in prepared["tools_used"]
    assert prepared["learner_memories"][0]["statement"] == "一次只给三个重点。"


def test_tutor_and_memory_api_are_session_scoped(tmp_path: Path) -> None:
    home = tmp_path / "home"
    token = "tutor-memory-test-launch-token"
    app = create_app(
        home=home,
        auth=AuthState(launch_token=token),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    with TestClient(app) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/exchange", json={"token": token}).status_code == 200
        created = client.post(
            "/api/v1/learner-memories",
            json={
                "memory_type": "teaching_preference",
                "statement": "先让我尝试，再指出错误。",
                "confidence": 1,
            },
        )
        assert created.status_code == 200
        context = client.post(
            "/api/v1/tutor/context",
            json={"text": "今天练习雅思口语 Part 2", "module": "speaking"},
        )
        assert context.status_code == 200
        assert context.json()["proposed_action"]["requires_confirmation"] is True
        tools = client.get("/api/v1/tutor/domain-tools").json()
        assert all(tool["name"] != "execute_sql" for tool in tools)
