from __future__ import annotations

import sys
import threading
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.agent_gateway.codex_app_server import (
    CodexAppServerAdapter,
    CodexAppServerClient,
    resolve_codex_executable,
)
from ielts_coach.capabilities import (
    CAPABILITIES_BY_CONTRACT,
    capability_for_contract,
)
from ielts_coach.execution_profiles import (
    default_execution_profile,
    list_execution_profiles,
    update_execution_profile,
)
from ielts_coach.init_home import initialise_home
from ielts_coach.managed_codex import (
    MANAGED_CODEX_VERSION,
    find_managed_codex_executable,
    install_managed_codex_runtime,
    managed_codex_version_root,
)
from ielts_coach.storage import SCHEMA_VERSION, connect
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
    response = client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    )
    assert response.status_code == 200
    return client


def test_schema21_separates_model_providers_without_replacing_sqlite(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    assert SCHEMA_VERSION == 22
    with connect(home) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        run_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(agent_runs)")
        }
    assert "execution_profiles" in tables
    assert "model_providers" in tables
    assert "external_agent_profiles" in tables
    assert {
        "capability_id",
        "execution_profile_id",
        "model_provider_id",
        "backend_kind",
        "transport",
        "auth_mode",
        "skill_hash",
    } <= run_columns
    assert (home / "private" / "codex-managed").is_dir()
    assert (home / "runtime" / "codex-workspace").is_dir()


def test_capabilities_are_product_contracts_not_agent_names():
    assert set(CAPABILITIES_BY_CONTRACT) == {
        "writing-review@1",
        "writing-mock-review@1",
        "reading-review@1",
        "listening-review@1",
        "speaking-evaluation@1",
        "study-plan@1",
        "diagnostic-summary@1",
        "weekly-coaching@1",
        "study-help@1",
    }
    assert capability_for_contract("writing-review@1").capability_id == (
        "writing_review"
    )


def test_execution_profile_default_is_explicit_and_secret_free(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    profiles = list_execution_profiles(home)
    assert {profile["profile_id"] for profile in profiles} >= {
        "codex-managed",
        "claude-cli",
        "opencode-cli",
        "manual-handoff",
        "pipeline-test",
    }
    assert default_execution_profile(home) is None
    updated = update_execution_profile(
        home,
        "codex-managed",
        model_id="gpt-test",
        reasoning_effort="medium",
        is_default=True,
        config={"executable_path": "C:/tools/codex.exe"},
    )
    assert updated["is_default"] is True
    assert updated["model_id"] == "gpt-test"
    assert "api_key" not in updated["config"]
    assert default_execution_profile(home)["profile_id"] == "codex-managed"
    with pytest.raises(ValueError, match="Unsupported execution profile setting"):
        update_execution_profile(
            home,
            "codex-managed",
            config={"api_key": "must-not-be-stored"},
        )


def test_architecture_endpoints_expose_capabilities_and_profiles(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        capabilities = client.get("/api/v1/capabilities")
        profiles = client.get("/api/v1/execution-profiles?diagnostics=false")
        bootstrap = client.get("/api/v1/bootstrap")
    assert capabilities.status_code == 200
    assert len(capabilities.json()) == 9
    assert profiles.status_code == 200
    assert any(
        item["profile_id"] == "codex-managed" for item in profiles.json()
    )
    assert len(bootstrap.json()["capabilities"]) == 9
    assert bootstrap.json()["execution_profiles"]


def test_codex_app_server_jsonl_handshake_and_requests(tmp_path: Path):
    fake = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"
    client = CodexAppServerClient(
        sys.executable,
        tmp_path / "codex-home",
        command=[sys.executable, str(fake)],
    )
    try:
        account = client.request("account/read", {"refreshToken": False})
        models = client.request("model/list", {"includeHidden": False})
        thread = client.request("thread/start", {"ephemeral": True})
        turn = client.request(
            "turn/start",
            {
                "threadId": thread["thread"]["id"],
                "input": [{"type": "text", "text": "test"}],
            },
        )
        assert account["account"]["type"] == "chatgpt"
        assert models["data"][0]["id"] == "test-codex"
        assert turn["turn"]["id"] == "turn_test"
        assert client.next_notification(1)["method"] == "item/completed"
        assert client.next_notification(1)["method"] == "turn/completed"
    finally:
        client.close()


def test_managed_codex_uses_current_read_only_sandbox_variant(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.turn_lock = threading.Lock()
            self.calls: list[tuple[str, dict[str, object]]] = []
            self.notifications = iter(
                [
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": "thread_test",
                            "turnId": "turn_test",
                            "item": {"type": "agentMessage", "text": "{}"},
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread_test",
                            "turnId": "turn_test",
                            "turn": {"status": "completed"},
                        },
                    },
                ]
            )

        def request(
            self,
            method: str,
            params: dict[str, object] | None = None,
            timeout: int = 30,
        ) -> dict[str, object]:
            del timeout
            values = dict(params or {})
            self.calls.append((method, values))
            if method == "account/read":
                return {"requiresOpenaiAuth": False, "account": {"type": "chatgpt"}}
            if method == "thread/start":
                assert values["sandbox"] == "read-only"
                return {"thread": {"id": "thread_test", "model": "gpt-test"}}
            if method == "turn/start":
                assert values["sandboxPolicy"] == {"type": "read-only"}
                return {"turn": {"id": "turn_test"}}
            raise AssertionError(f"Unexpected method: {method}")

        def next_notification(self, timeout: int = 1) -> dict[str, object]:
            del timeout
            return next(self.notifications)

    fake = FakeClient()
    adapter = CodexAppServerAdapter()
    adapter._client = lambda home, profile: fake  # type: ignore[method-assign]

    result = adapter.start(
        tmp_path,
        {
            "request_id": "run_test",
            "output_contract": "study-help@1",
            "execution_profile": {"model_id": "gpt-test"},
        },
    )

    assert result == {}
    assert [method for method, _ in fake.calls] == [
        "account/read",
        "thread/start",
        "turn/start",
    ]


def test_managed_codex_runtime_installs_into_private_versioned_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    home = tmp_path / "home"
    initialise_home(home)
    monkeypatch.setattr(
        "ielts_coach.managed_codex._platform_target",
        lambda: (
            "codex-win32-x64",
            "x86_64-pc-windows-msvc",
            "codex.exe",
        ),
    )
    executable = (
        managed_codex_version_root(home)
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "bin"
        / "codex.exe"
    )

    def fake_run(command, **kwargs):
        del kwargs
        assert command[0] == "npm"
        assert "--ignore-scripts" in command
        assert f"@openai/codex@{MANAGED_CODEX_VERSION}" in command
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
        return SimpleNamespace(returncode=0, stdout="added 2 packages", stderr="")

    monkeypatch.setattr("ielts_coach.managed_codex.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ielts_coach.managed_codex._codex_version",
        lambda _: (f"codex-cli {MANAGED_CODEX_VERSION}", None),
    )

    result = install_managed_codex_runtime(home, npm_executable="npm")

    assert result["installed"] is True
    assert result["shares_global_codex_auth"] is False
    assert Path(result["executable_path"]) == executable
    assert find_managed_codex_executable(home) == str(executable.resolve())
    assert resolve_codex_executable(home=home) == str(executable.resolve())
    assert str(executable).startswith(str(home / "private" / "runtimes"))


def test_managed_codex_runtime_endpoints_are_session_protected_and_installable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    home = tmp_path / "home"
    initialise_home(home)
    installed = {
        "installed": True,
        "available": True,
        "package": "@openai/codex",
        "pinned_version": MANAGED_CODEX_VERSION,
        "version": f"codex-cli {MANAGED_CODEX_VERSION}",
        "executable_path": "C:/private/codex.exe",
        "install_root": "C:/private",
        "npm_available": True,
        "download_estimate_mb": 150,
        "installed_size_estimate_mb": 430,
        "source": "official_openai_npm",
        "error": None,
        "isolated_auth_home": "C:/private/auth",
        "shares_global_codex_auth": False,
    }
    monkeypatch.setattr(
        CodexAppServerAdapter,
        "install_runtime",
        lambda self, target: dict(installed),
    )
    with _client(home) as client:
        status = client.get(
            "/api/v1/execution-profiles/codex-managed/runtime"
        )
        install = client.post(
            "/api/v1/execution-profiles/codex-managed/runtime/install"
        )

    assert status.status_code == 200
    assert status.json()["shares_global_codex_auth"] is False
    assert install.status_code == 200
    assert install.json() == installed
