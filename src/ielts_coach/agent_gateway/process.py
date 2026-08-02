from __future__ import annotations

import json
import locale
import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import __version__
from ..agent_contracts import contract_schema_name
from ..media import resolve_media_file
from ..validation import load_schema
from .base import AgentCapabilities, AgentIdentity


_PROXY_ENVIRONMENT_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _normalise_proxy_url(value: str, *, socks: bool = False) -> str:
    value = value.strip()
    if not value or "://" in value:
        return value
    return f"{'socks5' if socks else 'http'}://{value}"


def _proxy_environment_from_windows_value(value: str) -> dict[str, str]:
    """Translate the WinINET ProxyServer value into CLI-friendly variables."""
    value = value.strip()
    if not value:
        return {}
    proxies: dict[str, str] = {}
    if "=" not in value:
        proxy = _normalise_proxy_url(value)
        proxies.update({"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy})
    else:
        entries = {}
        for item in value.split(";"):
            protocol, separator, endpoint = item.partition("=")
            if separator and endpoint.strip():
                entries[protocol.strip().lower()] = endpoint.strip()
        if entries.get("http"):
            proxies["HTTP_PROXY"] = _normalise_proxy_url(entries["http"])
        if entries.get("https"):
            proxies["HTTPS_PROXY"] = _normalise_proxy_url(entries["https"])
        if entries.get("socks"):
            proxies["ALL_PROXY"] = _normalise_proxy_url(
                entries["socks"], socks=True
            )
    for key, proxy in list(proxies.items()):
        proxies[key.lower()] = proxy
    return proxies


def _windows_system_proxy_environment() -> dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            value = str(winreg.QueryValueEx(key, "ProxyServer")[0])
    except (ImportError, OSError, TypeError, ValueError):
        return {}
    return _proxy_environment_from_windows_value(value) if enabled else {}


def _process_environment(overrides: dict[str, str]) -> dict[str, str]:
    environment = dict(os.environ)
    system_proxy = _windows_system_proxy_environment()
    for key in _PROXY_ENVIRONMENT_KEYS:
        if system_proxy.get(key):
            environment.setdefault(key, system_proxy[key])
    environment.update(overrides)
    return environment


class LocalProcessAdapter:
    """Explicit, non-shell local CLI adapter with a constrained JSON contract."""

    executable: str
    id: str
    label: str

    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._runtime_identities: dict[str, dict[str, str | None]] = {}
        self._lock = threading.Lock()
        self._version_cache: tuple[float, str | None] | None = None

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
        command, stdin_text, environment, cleanup_paths = self._prepare_invocation(
            home,
            executable,
            prompt,
            request["output_contract"],
            request,
        )
        try:
            creation_flags = (
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            )
            if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                command,
                cwd=home,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_process_environment(environment),
                shell=False,
                creationflags=creation_flags,
                start_new_session=os.name != "nt",
            )
        except BaseException:
            _remove_temporary_paths(cleanup_paths)
            raise
        execution_ref = str(request["request_id"])
        with self._lock:
            self._processes[execution_ref] = process
        try:
            stdout_bytes, stderr_bytes = process.communicate(
                input=stdin_text.encode("utf-8") if stdin_text is not None else None
            )
        finally:
            with self._lock:
                self._processes.pop(execution_ref, None)
            _remove_temporary_paths(cleanup_paths)
        stdout = _decode_process_output(stdout_bytes)
        stderr = _decode_process_output(stderr_bytes)
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
        return _terminate_process_tree(process)

    def resume(
        self, home: Path, execution_ref: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        raise ValueError(f"{self.label} Adapter does not claim session resume support")

    def execution_identity(self, execution_ref: str) -> dict[str, str | None]:
        with self._lock:
            return dict(self._runtime_identities.pop(execution_ref, {}))

    def diagnostics(self) -> dict[str, Any]:
        executable = self._path()
        environment = _process_environment({})
        proxies = {
            key: _safe_proxy_endpoint(environment[key])
            for key in _PROXY_ENVIRONMENT_KEYS
            if environment.get(key)
        }
        return {
            "available": executable is not None,
            "executable_path": executable,
            "version": self._version(),
            "process_mode": "direct_no_shell",
            "proxy_variables": proxies,
            "proxy_configured": bool(proxies),
            "model_call_test": "not_run",
            "boundary": (
                "This preflight verifies local process configuration only. "
                "A real feedback run is still required to verify provider authentication."
            ),
        }

    def _prompt(self, request: dict[str, Any]) -> str:
        contract = request["output_contract"]
        schema = load_schema(contract_schema_name(contract))
        envelope = json.dumps(request, ensure_ascii=False)
        return (
            "You are an IELTS Academic evaluation worker. Return only one JSON "
            "object that validates against every required field and cardinality in "
            "the supplied schema. Never return a readiness or error envelope. If "
            "learner evidence is extremely short, irrelevant, or insufficient, "
            "still populate all required rubric criteria with the lowest justified "
            "values and explicit evidence limitations; never invent positive "
            "evidence and never return an empty required array. For Writing, return "
            "exactly four task-appropriate criteria even for a non-answer. For a "
            "Writing full mock, keep Task 1 and Task 2 separate and never calculate "
            "the final weighted band; the Runtime owns that aggregation. If neither "
            "a delivered image nor structured Task 1 data is available, mark visual "
            "evidence insufficient and leave TA null. Do not "
            "modify local files, do not call tools, and do not reveal answers before "
            "the learning stage encoded in the request permits it.\n\n"
            f"REQUEST:\n{envelope}\n\n"
            f"OUTPUT_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def _version(self) -> str | None:
        cached = self._version_cache
        now = time.monotonic()
        if cached and now - cached[0] < 60:
            return cached[1]
        executable = self._path()
        if not executable:
            self._version_cache = (now, None)
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
            self._version_cache = (now, None)
            return None
        version = result.stdout.strip().splitlines()[0] if result.returncode == 0 else None
        self._version_cache = (now, version)
        return version

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

    def _prepare_invocation(
        self,
        home: Path,
        executable: str,
        prompt: str,
        output_contract: str,
        request: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str], list[Path]]:
        return self._command(executable, prompt, output_contract), None, {}, []

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
        schema_data = dict(load_schema(contract_schema_name(output_contract)))
        schema_data.pop("$schema", None)
        schema = json.dumps(schema_data)
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
            ],
        )

    def _prepare_invocation(
        self,
        home: Path,
        executable: str,
        prompt: str,
        output_contract: str,
        request: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str], list[Path]]:
        return self._command(executable, prompt, output_contract), prompt, {}, []

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
        cleaned_model = _strip_ansi(str(model)) if model else None
        return {
            "agent_provider": "claude",
            "model_id": cleaned_model,
            "model_display_name": cleaned_model,
            "agent_session_id": envelope.get("session_id"),
        }


class OpenCodeProcessAdapter(LocalProcessAdapter):
    id = "opencode"
    label = "OpenCode CLI"
    executable = "opencode"

    def probe(self) -> AgentCapabilities:
        capabilities = super().probe()
        return AgentCapabilities(
            **{
                **capabilities.__dict__,
                "image_input": True,
            }
        )

    def _command(
        self, executable: str, prompt: str, output_contract: str
    ) -> list[str]:
        return self._wrap_powershell(
            executable,
            ["run", "--format", "json", "--pure", prompt],
        )

    def _prepare_invocation(
        self,
        home: Path,
        executable: str,
        prompt: str,
        output_contract: str,
        request: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str], list[Path]]:
        runtime = home / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        request_fd, request_name = tempfile.mkstemp(
            prefix="agent-request-", suffix=".txt", dir=runtime
        )
        config_fd, config_name = tempfile.mkstemp(
            prefix="opencode-locked-", suffix=".json", dir=runtime
        )
        os.close(request_fd)
        os.close(config_fd)
        request_path = Path(request_name)
        config_path = Path(config_name)
        request_path.write_text(prompt, encoding="utf-8")
        config_path.write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "permission": "deny",
                }
            ),
            encoding="utf-8",
        )
        attachment_paths, attachment_cleanup = _materialise_media_attachments(
            home, request or {}, media_type="image"
        )
        instruction = (
            "The attached UTF-8 text file is the complete IELTS evaluation "
            "request and output schema. Any additional attached image is a "
            "registered Task 1 visual named by media_id in the request. Follow "
            "the request exactly and return only the required JSON object."
        )
        args = [
            "run",
            instruction,
            "--format",
            "json",
            "--pure",
            "--file",
            str(request_path),
        ]
        for attachment_path in attachment_paths:
            args.extend(["--file", str(attachment_path)])
        command = self._wrap_powershell(executable, args)
        return (
            command,
            None,
            {"OPENCODE_CONFIG": str(config_path)},
            [request_path, config_path, *attachment_cleanup],
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
                return _normalise_opencode_result(event)
        for candidate in reversed(candidates):
            try:
                return _normalise_opencode_result(_parse_json_text(candidate))
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


def _safe_proxy_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value if "://" in value else f"http://{value}")
        host = parsed.hostname or "configured"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme or 'http'}://{host}{port}"
    except ValueError:
        return "configured (invalid URL syntax)"


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
                found.setdefault(target, _strip_ansi(item))
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


def _normalise_opencode_result(value: dict[str, Any]) -> dict[str, Any]:
    """Translate common provider field aliases without weakening validation."""
    for key in ("task1", "task2"):
        nested = value.get(key)
        if isinstance(nested, dict):
            _normalise_opencode_result(nested)
    criterion_aliases = {
        "task_achievement": "TA",
        "task_response": "TR",
        "coherence_cohesion": "CC",
        "coherence_and_cohesion": "CC",
        "lexical_resource": "LR",
        "grammatical_range_accuracy": "GRA",
        "grammatical_range_and_accuracy": "GRA",
    }
    criteria = value.get("criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if not isinstance(criterion, dict):
                continue
            criterion_id = str(
                criterion.get("criterion") or criterion.get("criterion_id") or ""
            )
            criterion["criterion"] = criterion_aliases.get(
                criterion_id.lower(), criterion_id.upper()
            )
            exact_score = criterion.get("band", criterion.get("score"))
            if "score" not in criterion and criterion.get("band") is not None:
                criterion["score"] = criterion["band"]
            if "score_low" not in criterion and exact_score is not None:
                criterion["score_low"] = exact_score
            if "score_high" not in criterion and exact_score is not None:
                criterion["score_high"] = exact_score
            evidence = criterion.get("evidence")
            narrative = (
                criterion.get("rationale")
                or criterion.get("feedback")
                or criterion.get("reason")
                or criterion.get("explanation")
            )
            if not criterion.get("evidence_support") and narrative:
                criterion["evidence_support"] = [str(narrative)]
            if (
                not criterion.get("evidence_support")
                and isinstance(evidence, list)
                and evidence
                and all(isinstance(item, str) for item in evidence)
            ):
                criterion["evidence_support"] = evidence
            if not criterion.get("evidence_limit"):
                limitations = criterion.get("evidence_limitations") or criterion.get(
                    "limitations"
                )
                if isinstance(limitations, list) and limitations:
                    criterion["evidence_limit"] = [
                        str(item) for item in limitations
                    ]
                elif narrative:
                    criterion["evidence_limit"] = [str(narrative)]
            if (
                not criterion.get("anchors")
                and isinstance(evidence, list)
                and all(isinstance(item, dict) for item in evidence)
            ):
                criterion["anchors"] = evidence
    issues = value.get("priority_issues")
    if isinstance(issues, list):
        for index, issue in enumerate(issues):
            if isinstance(issue, str) and issue.strip():
                issues[index] = {
                    "tag": f"AGENT_PRIORITY_{index + 1}",
                    "evidence": issue.strip(),
                    "learner_action": issue.strip(),
                }
                continue
            if not isinstance(issue, dict):
                continue
            if not issue.get("tag"):
                issue["tag"] = (
                    issue.get("issue_id")
                    or issue.get("criterion_id")
                    or issue.get("id")
                    or issue.get("category")
                )
            if not issue.get("evidence"):
                issue["evidence"] = (
                    issue.get("description")
                    or issue.get("rationale")
                    or issue.get("issue")
                )
            if not issue.get("learner_action"):
                issue["learner_action"] = (
                    issue.get("action")
                    or issue.get("recommendation")
                    or issue.get("next_step")
                )
        del issues[3:]
    return value


def _remove_temporary_paths(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _materialise_media_attachments(
    home: Path,
    request: dict[str, Any],
    *,
    media_type: str,
) -> tuple[list[Path], list[Path]]:
    refs = [
        item
        for item in request.get("media_refs") or []
        if item.get("available_to_agent") and item.get("media_type") == media_type
    ]
    if not refs:
        return [], []
    root = (home / "runtime" / "agent-media").resolve()
    root.mkdir(parents=True, exist_ok=True)
    folder = (
        root / f"{request['request_id']}-{uuid.uuid4().hex}"
    ).resolve()
    if root not in folder.parents:
        raise ValueError("Invalid Agent attachment request id")
    folder.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    cleanup: list[Path] = [folder]
    try:
        for index, ref in enumerate(refs, start=1):
            asset, source = resolve_media_file(home, str(ref["media_id"]))
            if asset["media_type"] != media_type:
                raise ValueError("Agent attachment media type changed after validation")
            target = folder / f"{ref['media_id']}-{index}{source.suffix.lower()}"
            shutil.copy2(source, target)
            paths.append(target)
            cleanup.append(target)
    except BaseException:
        _remove_temporary_paths(cleanup)
        raise
    return paths, cleanup


def _decode_process_output(value: bytes) -> str:
    encodings = ["utf-8", locale.getpreferredencoding(False), "gb18030"]
    for encoding in dict.fromkeys(encodings):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def _strip_ansi(value: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    return re.sub(r"\[[0-9;]*m\]?", "", cleaned).strip()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> bool:
    try:
        if os.name == "nt":
            completed = subprocess.run(
                [
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
            stopped = completed.returncode == 0
        else:
            os.killpg(process.pid, signal.SIGTERM)
            stopped = True
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return stopped or process.poll() is not None
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
            process.wait(timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            return False
