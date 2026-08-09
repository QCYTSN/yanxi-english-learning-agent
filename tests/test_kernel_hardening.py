from __future__ import annotations

import io
import json
import time
import urllib.error
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from ielts_coach import model_providers
from ielts_coach.agent_jobs import AgentJobManager
from ielts_coach.background_jobs import (
    LocalBackgroundJobManager,
    get_background_job,
)
from ielts_coach.backups import create_backup
from ielts_coach.content_imports import (
    create_import,
    get_content_import_job,
    queue_import_preparation,
)
from ielts_coach.data_lifecycle import delete_study_thread_data
from ielts_coach.init_home import initialise_home
from ielts_coach.model_providers import ModelProviderError, create_model_provider
from ielts_coach.storage import (
    compact_agent_run_request,
    connect,
    create_agent_run,
    get_agent_run,
    search_learning_history,
)
from ielts_coach.study_threads import (
    add_user_message,
    create_study_thread,
    study_thread_agent_context,
)
from ielts_coach.support_diagnostics import create_support_bundle


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(output, format="PNG")
    return output.getvalue()


def test_thread_deletion_removes_private_media_runs_and_artifacts(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Private reading material")
    message = add_user_message(
        home,
        thread["thread_id"],
        content="Explain this private passage.",
        files=[("passage.png", _png(), "image/png")],
    )
    media_id = message["attachments"][0]["media_id"]
    with connect(home) as conn:
        media_path = Path(
            conn.execute(
                "SELECT local_path FROM media_assets WHERE media_id=?", (media_id,)
            ).fetchone()["local_path"]
        )
    create_agent_run(
        home,
        {
            "run_id": "run-private-thread",
            "study_thread_id": thread["thread_id"],
            "adapter_id": "mock",
            "action": "material_dialogue",
            "output_contract": "study-help@1",
            "status": "persisted",
            "request": {
                "study_thread_id": thread["thread_id"],
                "canonical_session": {"private_text": "do not retain"},
            },
        },
    )
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO coaching_artifacts(
              artifact_id,artifact_type,contract_version,agent_run_id,
              payload_json,created_at
            ) VALUES('artifact-private','study_help',1,'run-private-thread','{}',?)
            """,
            ("2026-08-01T00:00:00+00:00",),
        )

    assert delete_study_thread_data(home, thread["thread_id"])["deleted"] is True
    assert not media_path.exists()
    assert not (home / "study-threads" / thread["thread_id"]).exists()
    with connect(home) as conn:
        assert conn.execute(
            "SELECT 1 FROM media_assets WHERE media_id=?", (media_id,)
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM agent_runs WHERE run_id='run-private-thread'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM coaching_artifacts WHERE artifact_id='artifact-private'"
        ).fetchone() is None


def test_thread_run_cancellation_precedes_lifecycle_deletion(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Active thread")
    create_agent_run(
        home,
        {
            "run_id": "run-active-thread",
            "study_thread_id": thread["thread_id"],
            "adapter_id": "mock",
            "action": "material_dialogue",
            "output_contract": "study-help@1",
            "status": "queued",
        },
    )
    manager = AgentJobManager(home)
    try:
        assert manager.cancel_for_study_thread(thread["thread_id"]) == [
            "run-active-thread"
        ]
        assert get_agent_run(home, "run-active-thread")["status"] == "cancelled"
        assert delete_study_thread_data(home, thread["thread_id"])["deleted"] is True
    finally:
        manager.shutdown()


def test_backup_includes_study_thread_files(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Backup material")
    add_user_message(
        home,
        thread["thread_id"],
        content="Keep this note.",
        files=[("notes.txt", b"private local note", "text/plain")],
    )
    backup = create_backup(home, kind="thread-backup-test")
    with zipfile.ZipFile(backup["path"]) as archive:
        names = archive.namelist()
    assert any(
        name.startswith(f"payload/study-threads/{thread['thread_id']}/attachments/")
        for name in names
    )


def test_context_engine_is_bounded_traceable_and_search_is_indexed(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    thread = create_study_thread(home, title="Pyramid reading")
    message = add_user_message(
        home,
        thread["thread_id"],
        content="How does the pyramid evidence support the claim?",
        files=[("notes.txt", b"The pyramid evidence comes from stone records.", "text/plain")],
    )
    context = study_thread_agent_context(
        home,
        thread_id=thread["thread_id"],
        message_id=message["message_id"],
    )
    assert context["context_version"] == 3
    assert len(context["context_trace"]["context_fingerprint"]) == 64
    assert context["context_trace"]["selected_attachment_ids"]
    matches = search_learning_history(home, "pyramid", limit=5)
    assert any(item["source_id"] == message["message_id"] for item in matches)


def test_terminal_agent_request_is_compacted(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    create_agent_run(
        home,
        {
            "run_id": "run-compact",
            "adapter_id": "mock",
            "action": "review",
            "output_contract": "study-help@1",
            "status": "test_passed",
            "request": {
                "request_id": "run-compact",
                "study_thread_id": "thread-ref",
                "canonical_session": {"essay": "private learner content"},
                "media_refs": [{"media_id": "m1", "content_hash": "abc"}],
            },
        },
    )
    compacted = compact_agent_run_request(home, "run-compact")
    assert compacted["request"]["compacted"] is True
    assert "canonical_session" not in compacted["request"]
    assert compacted["request_compacted_at"]


def test_local_background_supervisor_completes_content_preparation(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    imported = create_import(
        home,
        title="Worker test",
        source_type="personal",
        authenticity="user_owned",
        rights_status="local_private",
        files=[("notes.txt", b"A short IELTS note.", "text/plain")],
    )
    queue_import_preparation(home, imported["import_id"])
    manager = LocalBackgroundJobManager(home, workers=1)
    try:
        manager.recover()
        submitted = manager.submit(
            "content_prepare",
            {"import_id": imported["import_id"]},
            dedupe_key=f"content-prepare:{imported['import_id']}",
        )
        deadline = time.monotonic() + 20
        current = submitted
        while current["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.1)
            current = get_background_job(home, submitted["job_id"]) or current
        assert current["status"] == "completed", current
        assert get_content_import_job(home, imported["import_id"])["status"] != "failed"
    finally:
        manager.shutdown()


class _JsonResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _StreamResponse:
    def __init__(self, lines: list[dict]):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        for line in self.lines:
            yield f"data: {json.dumps(line)}\n".encode("utf-8")
        yield b"data: [DONE]\n"


def test_http_provider_retries_then_resets_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    initialise_home(home)
    provider = create_model_provider(
        home,
        provider_id="retry-provider",
        display_name="Retry provider",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        api_key="secret",
        config={"max_retries": 2},
    )
    calls = 0

    def urlopen(*_, **__):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise urllib.error.URLError("temporary")
        return _JsonResponse({"data": []})

    monkeypatch.setattr(model_providers.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(model_providers.time, "sleep", lambda _: None)
    result = model_providers._http_json(
        home,
        provider,
        method="GET",
        endpoint="models",
        payload=None,
        timeout=5,
    )
    assert result == {"data": []}
    assert calls == 3
    assert model_providers.provider_health_status(home, provider["provider_id"])[
        "status"
    ] == "healthy"


def test_provider_circuit_opens_after_repeated_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    initialise_home(home)
    provider = create_model_provider(
        home,
        provider_id="circuit-provider",
        display_name="Circuit provider",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        api_key="secret",
        config={"max_retries": 0},
    )
    calls = 0

    def urlopen(*_, **__):
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(model_providers.urllib.request, "urlopen", urlopen)
    for _ in range(3):
        with pytest.raises(ModelProviderError):
            model_providers._http_json(
                home,
                provider,
                method="GET",
                endpoint="models",
                payload=None,
                timeout=5,
            )
    with pytest.raises(ModelProviderError) as error:
        model_providers._http_json(
            home,
            provider,
            method="GET",
            endpoint="models",
            payload=None,
            timeout=5,
        )
    assert error.value.code == "MODEL_PROVIDER_CIRCUIT_OPEN"
    assert calls == 3


def test_http_streaming_accumulates_json_and_emits_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    initialise_home(home)
    provider = create_model_provider(
        home,
        provider_id="stream-provider",
        display_name="Stream provider",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        api_key="secret",
        config={"streaming": True},
    )
    chunks = ["{" + "x" * 400, "\"done\":true}"]
    monkeypatch.setattr(
        model_providers.urllib.request,
        "urlopen",
        lambda *_, **__: _StreamResponse(
            [
                {"choices": [{"delta": {"content": chunks[0]}}]},
                {
                    "choices": [{"delta": {"content": chunks[1]}}],
                    "usage": {"total_tokens": 12},
                },
            ]
        ),
    )
    events: list[dict] = []
    response = model_providers._http_stream_completion(
        home,
        provider,
        method="POST",
        endpoint="chat/completions",
        payload={"stream": True},
        timeout=5,
        emit=events.append,
    )
    assert response["choices"][0]["message"]["content"] == "".join(chunks)
    assert response["usage"]["total_tokens"] == 12
    assert any(event["stage"] == "streaming" for event in events)


def test_support_bundle_excludes_learner_content_and_credentials(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    provider = create_model_provider(
        home,
        provider_id="diagnostic-provider",
        display_name="Diagnostic provider",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        api_key="super-secret-key",
    )
    thread = create_study_thread(home, title="Private title")
    add_user_message(
        home,
        thread["thread_id"],
        content="private learner sentence that must not be exported",
        files=[],
    )
    bundle = create_support_bundle(home)
    with zipfile.ZipFile(bundle) as archive:
        content = archive.read("diagnostics.json").decode("utf-8")
        payload = json.loads(content)
    assert "private learner sentence" not in content
    assert "super-secret-key" not in content
    assert str(home.resolve()) not in content
    assert payload["privacy"]["contains_learner_content"] is False
    assert any(
        item["provider_id"] == provider["provider_id"]
        for item in payload["providers"]
    )
