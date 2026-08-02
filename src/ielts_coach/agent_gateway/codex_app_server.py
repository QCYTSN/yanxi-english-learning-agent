from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .. import __version__
from ..agent_contracts import contract_schema_name
from ..managed_codex import (
    find_managed_codex_executable,
    install_managed_codex_runtime,
    managed_codex_runtime_status,
)
from ..media import resolve_media_file
from ..skill_policy import build_provider_prompt, provider_output_schema
from ..validation import load_schema
from .base import AgentCapabilities, AgentIdentity
from .process import _process_environment


class AppServerError(ValueError):
    def __init__(self, message: str, *, code: str = "CODEX_APP_SERVER_ERROR"):
        super().__init__(message)
        self.code = code


_READ_ONLY_SANDBOX_MODES = ("read-only", "readOnly")


def _request_with_read_only_sandbox(
    client: Any,
    method: str,
    params: dict[str, Any],
    *,
    policy_object: bool = False,
) -> dict[str, Any]:
    """Use the current Codex spelling while tolerating older app-servers."""
    for index, mode in enumerate(_READ_ONLY_SANDBOX_MODES):
        candidate = dict(params)
        if policy_object:
            candidate["sandboxPolicy"] = {"type": mode}
        else:
            candidate["sandbox"] = mode
        try:
            return client.request(method, candidate)
        except AppServerError as exc:
            if index == 0 and "unknown variant" in str(exc).casefold():
                continue
            raise
    raise AppServerError("Codex app-server rejected every read-only sandbox variant")


def resolve_codex_executable(
    configured_path: str | None = None,
    *,
    home: Path | None = None,
) -> str | None:
    candidates = (
        configured_path,
        os.environ.get("IELTS_CODEX_EXECUTABLE"),
        find_managed_codex_executable(home) if home else None,
        shutil.which("codex"),
    )
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path.resolve())
    return None


def codex_executable_diagnostics(
    configured_path: str | None = None,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    executable = resolve_codex_executable(configured_path, home=home)
    managed_executable = find_managed_codex_executable(home) if home else None
    configured_executable = (
        str(Path(configured_path).expanduser().resolve())
        if configured_path and Path(configured_path).expanduser().is_file()
        else None
    )
    environment_path = os.environ.get("IELTS_CODEX_EXECUTABLE")
    environment_executable = (
        str(Path(environment_path).expanduser().resolve())
        if environment_path and Path(environment_path).expanduser().is_file()
        else None
    )
    source = (
        "configured"
        if configured_executable and executable == configured_executable
        else "environment"
        if environment_executable and executable == environment_executable
        else "managed"
        if managed_executable and executable == managed_executable
        else "path"
        if executable
        else None
    )
    if not executable:
        return {
            "available": False,
            "executable_path": None,
            "version": None,
            "model_call_test": "not_run",
            "source": None,
            "boundary": (
                "No callable Codex runtime is installed. Install the app-managed "
                "official OpenAI Codex runtime or choose a standalone Codex CLI."
            ),
        }
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            shell=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "executable_path": executable,
            "version": None,
            "error": str(exc),
            "model_call_test": "not_run",
            "source": source,
            "boundary": (
                "The executable was found but Windows would not launch it. "
                "Choose a standalone Codex CLI executable in Settings."
            ),
        }
    version = result.stdout.strip().splitlines()
    available = result.returncode == 0
    return {
        "available": available,
        "executable_path": executable,
        "version": version[0] if available and version else None,
        "error": result.stderr.strip()[-1000:] if not available else None,
        "model_call_test": "not_run",
        "source": source,
        "boundary": (
            "This checks the local Codex CLI and app-server entry point only. "
            "Account status is checked through the isolated managed runtime."
        ),
    }


class CodexAppServerClient:
    """Small synchronous JSONL client for the official Codex app-server."""

    def __init__(
        self,
        executable: str,
        codex_home: Path,
        *,
        command: list[str] | None = None,
    ) -> None:
        self.executable = executable
        self.codex_home = codex_home.resolve()
        self.codex_home.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._turn_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=50)
        self._next_id = 1
        environment = _process_environment({})
        environment["CODEX_HOME"] = str(self.codex_home)
        environment.setdefault("RUST_LOG", "warn")
        environment.setdefault("LOG_FORMAT", "json")
        try:
            self._process = subprocess.Popen(
                command or [executable, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                shell=False,
                bufsize=1,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
        except OSError as exc:
            raise AppServerError(
                f"Unable to start Codex app-server: {exc}",
                code="CODEX_EXECUTABLE_UNAVAILABLE",
            ) from exc
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="ielts-codex-app-server-reader",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            name="ielts-codex-app-server-stderr",
            daemon=True,
        )
        self._stderr_reader.start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "ielts_ai_coach",
                    "title": "IELTS AI Coach",
                    "version": __version__,
                }
            },
            timeout=15,
        )
        self.notify("initialized", {})

    @property
    def turn_lock(self) -> threading.Lock:
        return self._turn_lock

    def alive(self) -> bool:
        return self._process.poll() is None

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30,
    ) -> dict[str, Any]:
        if not self.alive():
            raise AppServerError(
                self._terminated_message(), code="CODEX_APP_SERVER_STOPPED"
            )
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        self._send(
            {
                "id": request_id,
                "method": method,
                **({"params": params} if params is not None else {}),
            }
        )
        try:
            response = response_queue.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            raise AppServerError(
                f"Codex app-server did not answer {method!r} within {timeout:g}s",
                code="CODEX_APP_SERVER_TIMEOUT",
            ) from exc
        finally:
            with self._request_lock:
                self._pending.pop(request_id, None)
        if response.get("error"):
            error = response["error"]
            message = (
                error.get("message") if isinstance(error, dict) else str(error)
            )
            raise AppServerError(
                f"Codex app-server rejected {method}: {message}",
                code="CODEX_APP_SERVER_REQUEST_FAILED",
            )
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send(
            {
                "method": method,
                **({"params": params} if params is not None else {}),
            }
        )

    def next_notification(self, timeout: float = 1) -> dict[str, Any] | None:
        try:
            return self._notifications.get(timeout=max(0.01, timeout))
        except queue.Empty:
            if not self.alive():
                raise AppServerError(
                    self._terminated_message(), code="CODEX_APP_SERVER_STOPPED"
                )
            return None

    def close(self) -> None:
        if self.alive():
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def _send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            if not self._process.stdin:
                raise AppServerError(
                    "Codex app-server stdin is unavailable",
                    code="CODEX_APP_SERVER_STOPPED",
                )
            try:
                self._process.stdin.write(payload + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise AppServerError(
                    self._terminated_message(),
                    code="CODEX_APP_SERVER_STOPPED",
                ) from exc

    def _read_stdout(self) -> None:
        if not self._process.stdout:
            return
        for raw_line in self._process.stdout:
            try:
                message = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            if request_id is not None and (
                "result" in message or "error" in message
            ):
                with self._request_lock:
                    response_queue = self._pending.get(int(request_id))
                if response_queue:
                    response_queue.put(message)
                continue
            if message.get("method"):
                self._notifications.put(message)
        with self._request_lock:
            pending = list(self._pending.values())
        for response_queue in pending:
            try:
                response_queue.put_nowait(
                    {
                        "error": {
                            "message": self._terminated_message(),
                        }
                    }
                )
            except queue.Full:
                pass

    def _read_stderr(self) -> None:
        if not self._process.stderr:
            return
        for line in self._process.stderr:
            if line.strip():
                self._stderr.append(line.strip())

    def _terminated_message(self) -> str:
        detail = self._stderr[-1] if self._stderr else "no diagnostic output"
        return f"Codex app-server stopped unexpectedly: {detail}"


class CodexAppServerAdapter:
    id = "codex-managed"
    label = "Codex managed runtime"

    def __init__(self) -> None:
        self._clients: dict[tuple[str, str], CodexAppServerClient] = {}
        self._clients_lock = threading.Lock()
        self._active_turns: dict[str, tuple[CodexAppServerClient, str, str]] = {}
        self._runtime_identity: dict[str, dict[str, Any]] = {}
        self._runtime_usage: dict[str, dict[str, Any]] = {}
        self._diagnostic_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def probe(self) -> AgentCapabilities:
        return AgentCapabilities(
            structured_output=True,
            streaming=True,
            session_resume=True,
            image_input=True,
            audio_input=True,
            tool_execution=False,
            remote_processing=True,
            cancellation=True,
            timeout_control=True,
        )

    def identity(self) -> AgentIdentity:
        return AgentIdentity(
            agent_provider="openai",
            agent_version=None,
            model_id=None,
            model_display_name=None,
            launcher_kind="managed_app_server",
            calibration_status="unknown",
        )

    def available(self) -> bool:
        return bool(self.diagnostics().get("available"))

    def diagnostics(
        self, home: Path | None = None, profile: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        configured = str((profile or {}).get("config", {}).get("executable_path") or "")
        cache_key = f"{home.resolve() if home else '<no-home>'}|{configured or '<path>'}"
        cached = self._diagnostic_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 60:
            details = dict(cached[1])
        else:
            details = codex_executable_diagnostics(
                configured or None,
                home=home,
            )
            self._diagnostic_cache[cache_key] = (
                time.monotonic(),
                dict(details),
            )
        details["isolated_codex_home"] = (
            str((home / "private" / "codex-managed").resolve()) if home else None
        )
        details["shares_global_codex_auth"] = False
        if home:
            details["managed_runtime"] = managed_codex_runtime_status(home)
        return details

    def runtime_status(self, home: Path) -> dict[str, Any]:
        return managed_codex_runtime_status(home)

    def install_runtime(self, home: Path) -> dict[str, Any]:
        status = install_managed_codex_runtime(home)
        self._diagnostic_cache.clear()
        return status

    def account(
        self, home: Path, profile: dict[str, Any]
    ) -> dict[str, Any]:
        return self._client(home, profile).request(
            "account/read", {"refreshToken": False}
        )

    def models(
        self, home: Path, profile: dict[str, Any]
    ) -> dict[str, Any]:
        return self._client(home, profile).request(
            "model/list", {"includeHidden": False}
        )

    def rate_limits(
        self, home: Path, profile: dict[str, Any]
    ) -> dict[str, Any]:
        return self._client(home, profile).request("account/rateLimits/read")

    def login(
        self,
        home: Path,
        profile: dict[str, Any],
        *,
        login_type: str,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"type": login_type}
        if login_type == "apiKey":
            if not api_key or not api_key.strip():
                raise ValueError("An API key is required")
            params["apiKey"] = api_key.strip()
        return self._client(home, profile).request(
            "account/login/start", params, timeout=60
        )

    def logout(self, home: Path, profile: dict[str, Any]) -> dict[str, Any]:
        return self._client(home, profile).request("account/logout")

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        return self._start(home, request, emit=None)

    def start_with_events(
        self,
        home: Path,
        request: dict[str, Any],
        emit: Any,
    ) -> dict[str, Any]:
        return self._start(home, request, emit=emit)

    def _start(
        self,
        home: Path,
        request: dict[str, Any],
        *,
        emit: Any | None,
    ) -> dict[str, Any]:
        profile = dict(request.get("execution_profile") or {})
        client = self._client(home, profile)
        execution_ref = str(request["request_id"])
        with client.turn_lock:
            account = client.request("account/read", {"refreshToken": False})
            if account.get("requiresOpenaiAuth") and not account.get("account"):
                raise AppServerError(
                    "Codex managed runtime is not signed in. Connect ChatGPT or "
                    "an API key in Settings first.",
                    code="CODEX_AUTH_REQUIRED",
                )
            workspace = (home / "runtime" / "codex-workspace").resolve()
            workspace.mkdir(parents=True, exist_ok=True)
            thread_params: dict[str, Any] = {
                "cwd": str(workspace),
                "approvalPolicy": "never",
                "ephemeral": True,
                "serviceName": "ielts_ai_coach",
            }
            if profile.get("model_id"):
                thread_params["model"] = profile["model_id"]
            thread_result = _request_with_read_only_sandbox(
                client, "thread/start", thread_params
            )
            thread = thread_result.get("thread") or {}
            thread_id = str(thread.get("id") or "")
            if not thread_id:
                raise AppServerError("Codex app-server returned no thread id")
            turn_input: list[dict[str, Any]] = [
                {"type": "text", "text": _build_prompt(request)}
            ]
            for media in request.get("media_refs") or []:
                if not media.get("available_to_agent"):
                    continue
                _, path = resolve_media_file(home, str(media["media_id"]))
                if media.get("media_type") == "image":
                    turn_input.append({"type": "localImage", "path": str(path)})
                elif media.get("media_type") == "audio":
                    turn_input.append({"type": "localAudio", "path": str(path)})
            schema = provider_output_schema(
                dict(load_schema(contract_schema_name(request["output_contract"])))
            )
            turn_params: dict[str, Any] = {
                "threadId": thread_id,
                "input": turn_input,
                "cwd": str(workspace),
                "approvalPolicy": "never",
                "outputSchema": schema,
            }
            if profile.get("model_id"):
                turn_params["model"] = profile["model_id"]
            if profile.get("reasoning_effort"):
                turn_params["effort"] = profile["reasoning_effort"]
            turn_result = _request_with_read_only_sandbox(
                client,
                "turn/start",
                turn_params,
                policy_object=True,
            )
            turn = turn_result.get("turn") or {}
            turn_id = str(turn.get("id") or "")
            if not turn_id:
                raise AppServerError("Codex app-server returned no turn id")
            self._active_turns[execution_ref] = (
                client,
                thread_id,
                turn_id,
            )
            try:
                text, usage = self._wait_for_turn(
                    client,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    emit=emit,
                )
            finally:
                self._active_turns.pop(execution_ref, None)
            self._runtime_identity[execution_ref] = {
                "agent_provider": "openai",
                "model_id": profile.get("model_id") or thread.get("model"),
                "model_display_name": profile.get("model_id") or thread.get("model"),
                "agent_session_id": thread_id,
                "launcher_kind": "managed_app_server",
            }
            self._runtime_usage[execution_ref] = usage
            return _parse_json_object(text)

    def stream(self, home: Path, execution_ref: str) -> list[dict[str, Any]]:
        return []

    def cancel(self, home: Path, execution_ref: str) -> bool:
        active = self._active_turns.get(execution_ref)
        if not active:
            return False
        client, thread_id, turn_id = active
        client.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=10,
        )
        return True

    def resume(
        self, home: Path, execution_ref: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        return self.start(home, request)

    def execution_identity(self, execution_ref: str) -> dict[str, Any]:
        return dict(self._runtime_identity.pop(execution_ref, {}))

    def execution_usage(self, execution_ref: str) -> dict[str, Any]:
        return dict(self._runtime_usage.pop(execution_ref, {}))

    def shutdown(self) -> None:
        with self._clients_lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()

    def _client(
        self, home: Path, profile: dict[str, Any]
    ) -> CodexAppServerClient:
        configured = str(profile.get("config", {}).get("executable_path") or "")
        executable = resolve_codex_executable(configured or None, home=home)
        if not executable:
            raise AppServerError(
                "Codex runtime is not installed. Install the official managed "
                "runtime or configure a standalone Codex CLI in Settings.",
                code="CODEX_EXECUTABLE_UNAVAILABLE",
            )
        diagnostic = codex_executable_diagnostics(
            configured or None,
            home=home,
        )
        if not diagnostic["available"]:
            raise AppServerError(
                str(diagnostic.get("boundary") or "Codex CLI is not launchable"),
                code="CODEX_EXECUTABLE_UNAVAILABLE",
            )
        codex_home = (home / "private" / "codex-managed").resolve()
        key = (str(codex_home), executable)
        with self._clients_lock:
            client = self._clients.get(key)
            if client and client.alive():
                return client
            if client:
                client.close()
            client = CodexAppServerClient(executable, codex_home)
            self._clients[key] = client
            return client

    @staticmethod
    def _wait_for_turn(
        client: CodexAppServerClient,
        *,
        thread_id: str,
        turn_id: str,
        emit: Any | None = None,
    ) -> tuple[str, dict[str, Any]]:
        deltas: list[str] = []
        final_text: str | None = None
        usage: dict[str, Any] = {}
        next_progress_chars = 250
        while True:
            event = client.next_notification(timeout=1)
            if not event:
                continue
            method = str(event.get("method") or "")
            params = event.get("params") or {}
            if params.get("threadId") not in {None, thread_id}:
                continue
            if params.get("turnId") not in {None, turn_id}:
                continue
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if isinstance(delta, str):
                    deltas.append(delta)
                    total_chars = sum(len(item) for item in deltas)
                    if emit and total_chars >= next_progress_chars:
                        emit(
                            {
                                "stage": "generating",
                                "label": "Codex is producing structured feedback",
                                "generated_characters": total_chars,
                            }
                        )
                        next_progress_chars = total_chars + 250
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and isinstance(
                    item.get("text"), str
                ):
                    final_text = item["text"]
            elif method == "thread/tokenUsage/updated":
                token_usage = params.get("tokenUsage")
                if isinstance(token_usage, dict):
                    usage = token_usage
            elif method == "turn/completed":
                completed = params.get("turn") or {}
                status = completed.get("status")
                if status not in {"completed", "interrupted"}:
                    error = completed.get("error") or "unknown turn failure"
                    raise AppServerError(f"Codex turn failed: {error}")
                if status == "interrupted":
                    raise AppServerError(
                        "Codex turn was cancelled", code="AGENT_CANCELLED"
                    )
                return final_text or "".join(deltas), usage


def _build_prompt(request: dict[str, Any]) -> str:
    system, user = build_provider_prompt(request)
    return system + "\n\n# Capability request\n" + user


def _parse_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Codex output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Codex output must be one JSON object")
    return parsed
