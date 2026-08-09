from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ielts_coach.agent_contracts import persist_agent_contract
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import connect
from ielts_coach.validation import validate_data
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    authenticated = client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    )
    assert authenticated.status_code == 200
    return client


def _wait(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/agent-runs/{run_id}").json()
        if run["status"] in {"test_passed", "failed", "persisted"}:
            return run
        time.sleep(0.03)
    raise AssertionError("Study-help run did not finish")


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_material_dialogue_keeps_attachments_out_of_formal_sessions(
    tmp_path: Path,
):
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        thread = client.post(
            "/api/v1/study-threads",
            json={
                "title": "解释这道阅读题",
                "module": "reading",
                "source_context": {},
            },
        )
        assert thread.status_code == 200
        thread_id = thread.json()["thread_id"]
        message = client.post(
            f"/api/v1/study-threads/{thread_id}/messages",
            data={
                "content": "请先解释定位方法，不要直接给答案。",
                "context_json": "{}",
            },
            files=[
                ("files", ("question.png", _png(), "image/png")),
                ("files", ("notes.txt", b"Paragraph A mentions migration.", "text/plain")),
            ],
        )
        assert message.status_code == 200
        assert len(message.json()["attachments"]) == 2
        page = client.get(
            f"/api/v1/study-threads/{thread_id}/messages?limit=30"
        )
        assert page.status_code == 200
        assert len(page.json()["items"]) == 1
        assert "extracted_text" not in page.json()["items"][0]["attachments"][1]
        recent = client.get("/api/v1/study-threads?limit=5")
        assert recent.status_code == 200
        summary = recent.json()[0]
        assert summary["thread_id"] == thread_id
        assert summary["message_count"] == 1
        assert summary["attachment_count"] == 2
        assert summary["last_message_preview"] == "请先解释定位方法，不要直接给答案。"

        run = client.post(
            "/api/v1/agent-runs",
            headers={"Idempotency-Key": "study-help-pipeline-test"},
            json={
                "adapter_id": "mock",
                "study_thread_id": thread_id,
                "user_message_id": message.json()["message_id"],
                "action": "material_dialogue",
                "output_contract": "study-help@1",
            },
        )
        assert run.status_code == 200
        finished = _wait(client, run.json()["run_id"])
        assert finished["status"] == "test_passed"
        assert finished["result"]["answer_status"] == "unverified"

        attachment = message.json()["attachments"][0]
        content = client.get(
            f"/api/v1/study-threads/{thread_id}/attachments/"
            f"{attachment['attachment_id']}/content"
        )
        assert content.status_code == 200

        promoted = client.post(f"/api/v1/study-threads/{thread_id}/promote")
        assert promoted.status_code == 200
        assert promoted.json()["status"] == "queued"
        assert len(promoted.json()["files"]) == 2

    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_validated_study_help_is_saved_as_thread_message(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        thread = client.post(
            "/api/v1/study-threads",
            json={"title": "精读", "module": "reading"},
        ).json()
        message = client.post(
            f"/api/v1/study-threads/{thread['thread_id']}/messages",
            data={"content": "这个词在上下文中是什么意思？", "context_json": "{}"},
        ).json()

    run = {
        "run_id": "run-study-help-direct",
        "output_contract": "study-help@1",
        "request": {
            "study_thread_id": thread["thread_id"],
            "user_message_id": message["message_id"],
        },
        "study_session_id": None,
        "base_revision": None,
    }
    result = {
        "contract_version": 1,
        "module": "reading",
        "request_kind": "context_analysis",
        "evidence_status": "partial",
        "answer_status": "not_applicable",
        "summary": "这里表示在既定范围内逐渐发生变化。",
        "sections": [
            {"title": "上下文含义", "content": "先结合前后句理解，再回到常见本义。"}
        ],
        "evidence": [
            {"claim": "含义受上下文限定", "source": "用户提供的句子", "quote": None}
        ],
        "limitations": ["当前只提供了一个句子。"],
        "next_action": "补充前后各一句可以进一步确认。",
    }
    # Agent runs normally exist before persistence; the direct fixture creates
    # the minimum durable run row needed by the coaching-artifact foreign key.
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO agent_runs(
              run_id,adapter_id,backend_kind,launcher_kind,action,output_contract,
              status,request_json,usage_json,created_at,timeout_seconds
            ) VALUES(?,?,'mock','deterministic_local',?,?,'persisting',?,'{}',?,120)
            """,
            (
                run["run_id"],
                "mock",
                "material_dialogue",
                "study-help@1",
                '{"study_thread_id": "%s"}' % thread["thread_id"],
                "2026-01-01T00:00:00+00:00",
            ),
        )
    persisted = persist_agent_contract(home, run, result)
    assert persisted["message_id"]
    saved = _client(home)
    thread_detail = saved.get(
        f"/api/v1/study-threads/{thread['thread_id']}"
    ).json()
    assert [item["role"] for item in thread_detail["messages"]] == [
        "user",
        "assistant",
    ]
    assert thread_detail["messages"][-1]["context"]["result"]["summary"] == result["summary"]


def test_study_thread_can_be_renamed_and_deleted(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        created = client.post(
            "/api/v1/study-threads",
            json={"title": "Initial title", "module": "mixed"},
        )
        assert created.status_code == 200
        thread_id = created.json()["thread_id"]
        message = client.post(
            f"/api/v1/study-threads/{thread_id}/messages",
            data={"content": "Keep this material with the conversation.", "context_json": "{}"},
            files=[("files", ("notes.txt", b"local notes", "text/plain"))],
        )
        assert message.status_code == 200
        thread_storage = home / "study-threads" / thread_id
        assert thread_storage.is_dir()

        renamed = client.patch(
            f"/api/v1/study-threads/{thread_id}",
            json={"title": "  Reading   vocabulary review  "},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Reading vocabulary review"

        deleted = client.delete(f"/api/v1/study-threads/{thread_id}")
        assert deleted.status_code == 200
        assert deleted.json() == {"thread_id": thread_id, "deleted": True}
        assert client.get("/api/v1/study-threads").json() == []
        assert not thread_storage.exists()

    with connect(home) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM study_messages WHERE thread_id=?",
            (thread_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM study_thread_attachments WHERE thread_id=?",
            (thread_id,),
        ).fetchone()[0] == 0


def test_study_messages_use_stable_keyset_pages(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        thread = client.post(
            "/api/v1/study-threads",
            json={"title": "Long reading review", "module": "reading"},
        ).json()
        thread_id = thread["thread_id"]
        with connect(home) as conn:
            conn.executemany(
                """
                INSERT INTO study_messages(
                  message_id,thread_id,role,content,status,context_json,created_at
                ) VALUES(?,?,?,?,'complete','{}',?)
                """,
                [
                    (
                        f"message-{index:03d}",
                        thread_id,
                        "user" if index % 2 == 0 else "assistant",
                        f"Turn {index}",
                        "2026-01-01T00:00:00+00:00",
                    )
                    for index in range(65)
                ],
            )

        overview = client.get(
            f"/api/v1/study-threads/{thread_id}/overview"
        ).json()
        assert overview["message_count"] == 65
        assert overview["messages"] == []

        collected: list[str] = []
        cursor = None
        while True:
            suffix = f"&before={cursor}" if cursor else ""
            response = client.get(
                f"/api/v1/study-threads/{thread_id}/messages?limit=30{suffix}"
            )
            assert response.status_code == 200
            payload = response.json()
            collected = [item["message_id"] for item in payload["items"]] + collected
            cursor = payload["next_cursor"]
            if not payload["has_more"]:
                break

        assert collected == [f"message-{index:03d}" for index in range(65)]
        assert len(collected) == len(set(collected))


def test_study_help_semantics_preserve_reading_answer_integrity() -> None:
    result = {
        "contract_version": 1,
        "module": "reading",
        "request_kind": "guided_hint",
        "evidence_status": "partial",
        "answer_status": "verified",
        "summary": "A hint.",
        "sections": [],
        "evidence": [],
        "limitations": [],
        "next_action": None,
    }
    with pytest.raises(ValueError, match="answer withheld"):
        validate_data(result, "study-help")
