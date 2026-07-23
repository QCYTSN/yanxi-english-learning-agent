from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from importlib import resources
from pathlib import Path
from typing import Any

from .. import __version__
from ..agent_contracts import CONTRACT_SCHEMAS
from ..validation import load_schema
from .base import AgentCapabilities, AgentIdentity


class LocalProcessAdapter:
    """Explicit, non-shell local CLI adapter with a constrained JSON contract."""

    executable: str
    id: str
    label: str

    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._runtime_identities: dict[str, dict[str, str | None]] = {}
        self._lock = threading.Lock()

    def _path(self) -> str | None:
        return shutil.which(self.executable)

    def available(self) -> bool:
        return self._path() is not None

    def probe(self) -> AgentCapabilities:
        return AgentCapabilities(
            structured_output=True,
            streaming=False,
            session_resume=False,
            image_input=False,
            audio_input=False,
            tool_execution=False,
            remote_processing=True,
            cancellation=True,
            timeout_control=True,
        )

    def identity(self) -> AgentIdentity:
        return AgentIdentity(
            agent_provider=self.id,
            agent_version=self._version(),
            model_id=None,
            model_display_name=None,
            launcher_kind="local_process",
            calibration_status="unknown",
        )

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        executable = self._path()
        if not executable:
            raise ValueError(f"{self.label} CLI is not installed or not on PATH")
        prompt = self._prompt(request)
        command = self._command(executable, prompt, request["output_contract"])
        process = subprocess.Popen(
            command,
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
        execution_ref = str(request["request_id"])
        with self._lock:
            self._processes[execution_ref] = process
        try:
            stdout, stderr = process.communicate()
        finally:
            with self._lock:
                self._processes.pop(execution_ref, None)
        if process.returncode:
            detail = stderr.strip()[-1500:] or stdout.strip()[-1500:]
            raise RuntimeError(
                f"{self.label} exited with code {process.returncode}: {detail}"
            )
        identity = self._extract_runtime_identity(stdout)
        with self._lock:
            self._runtime_identities[execution_ref] = identity
        return self._parse_output(stdout)

    run = start

    def stream(self, home: Path, execution_ref: str) -> list[dict[str, Any]]:
        return []

    def cancel(self, home: Path, execution_ref: str) -> bool:
        with self._lock:
            process = self._processes.get(execution_ref)
        if not process or process.poll() is not None:
            return False
        process.terminate()
        return True

    def resume(
        self, home: Path, execution_ref: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        raise ValueError(f"{self.label} Adapter does not claim session resume support")

    def execution_identity(self, execution_ref: str) -> dict[str, str | None]:
        with self._lock:
            return dict(self._runtime_identities.pop(execution_ref, {}))

    def _prompt(self, request: dict[str, Any]) -> str:
        contract = request["output_contract"]
        schema = load_schema(CONTRACT_SCHEMAS[contract])
        envelope = json.dumps(request, ensure_ascii=False)
        return (
            "You are an IELTS Academic evaluation worker. Return only one JSON "
            "object that validates against the supplied schema. Do not modify local "
            "files, do not call tools, and do not reveal answers before the learning "
            "stage encoded in the request permits it.\n\n"
            f"REQUEST:\n{envelope}\n\n"
            f"OUTPUT_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def _version(self) -> str | None:
        executable = self._path()
        if not executable:
            return None
        try:
            result = subprocess.run(
                self._wrap_powershell(executable, ["--version"]),
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
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 else None

    @staticmethod
    def _wrap_powershell(executable: str, args: list[str]) -> list[str]:
        if Path(executable).suffix.lower() == ".ps1":
            powershell = shutil.which("powershell") or "powershell"
            return [powershell, "-NoProfile", "-NonInteractive", "-File", executable, *args]
        return [executable, *args]

    def _command(
        self, executable: str, prompt: str, output_contract: str
    ) -> list[str]:
        raise NotImplementedError

    def _parse_output(self, output: str) -> dict[str, Any]:
        raise NotImplementedError

    def _extract_runtime_identity(self, output: str) -> dict[str, str | None]:
        return {}


class ClaudeProcessAdapter(LocalProcessAdapter):
    id = "claude"
    label = "Claude Code CLI"
    executable = "claude"

    def _command(
        self, executable: str, prompt: str, output_contract: str
    ) -> list[str]:
        schema = json.dumps(load_schema(CONTRACT_SCHEMAS[output_contract]))
        return self._wrap_powershell(
            executable,
            [
                "--print",
                "--output-format",
                "json",
                "--json-schema",
                schema,
                "--permission-mode",
                "dontAsk",
                "--tools",
                "",
                prompt,
            ],
        )

    def _parse_output(self, output: str) -> dict[str, Any]:
        envelope = json.loads(output)
        for key in ("structured_output", "result"):
            value = envelope.get(key) if isinstance(envelope, dict) else None
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                return _parse_json_text(value)
        if isinstance(envelope, dict) and "contract_version" in envelope:
            return envelope
        raise ValueError("Claude CLI did not return a structured JSON result")

    def _extract_runtime_identity(self, output: str) -> dict[str, str | None]:
        try:
            envelope = json.loads(output)
        except json.JSONDecodeError:
            return {}
        usage = envelope.get("modelUsage") or envelope.get("model_usage") or {}
        model = next(iter(usage), None) if isinstance(usage, dict) else None
        return {
            "agent_provider": "claude",
            "model_id": str(model) if model else None,
            "model_display_name": str(model) if model else None,
            "agent_session_id": envelope.get("session_id"),
        }


class OpenCodeProcessAdapter(LocalProcessAdapter):
    id = "opencode"
    label = "OpenCode CLI"
    executable = "opencode"

    def _command(
        self, executable: str, prompt: str, output_contract: str
    ) -> list[str]:
        return self._wrap_powershell(
            executable,
            ["run", "--format", "json", "--pure", prompt],
        )

    def _parse_output(self, output: str) -> dict[str, Any]:
        candidates: list[str] = []
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            candidates.extend(_text_values(event))
            if isinstance(event, dict) and "contract_version" in event:
                return event
        for candidate in reversed(candidates):
            try:
                return _parse_json_text(candidate)
            except ValueError:
                continue
        raise ValueError("OpenCode CLI did not return a parseable JSON result")

    def _extract_runtime_identity(self, output: str) -> dict[str, str | None]:
        merged: dict[str, str | None] = {"agent_provider": "opencode"}
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            fields = _identity_fields(event)
            for key, value in fields.items():
                if value and not merged.get(key):
                    merged[key] = value
        if merged.get("model_id") and not merged.get("model_display_name"):
            merged["model_display_name"] = merged["model_id"]
        return merged


def _text_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content", "result"} and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_text_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_text_values(item))
    return found


def _identity_fields(value: Any) -> dict[str, str]:
    aliases = {
        "modelID": "model_id",
        "model_id": "model_id",
        "providerID": "agent_provider",
        "provider_id": "agent_provider",
        "sessionID": "agent_session_id",
        "session_id": "agent_session_id",
    }
    found: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            target = aliases.get(str(key))
            if target and isinstance(item, str) and item:
                found.setdefault(target, item)
            elif isinstance(item, (dict, list)):
                nested = _identity_fields(item)
                for nested_key, nested_value in nested.items():
                    found.setdefault(nested_key, nested_value)
    elif isinstance(value, list):
        for item in value:
            nested = _identity_fields(item)
            for nested_key, nested_value in nested.items():
                found.setdefault(nested_key, nested_value)
    return found


def _parse_json_text(value: str) -> dict[str, Any]:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Agent output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Agent output must be one JSON object")
    return parsed
