from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from filelock import FileLock

MANAGED_CODEX_PACKAGE = "@openai/codex"
MANAGED_CODEX_VERSION = "0.145.0"
MANAGED_CODEX_DOWNLOAD_ESTIMATE_MB = 150
MANAGED_CODEX_INSTALLED_ESTIMATE_MB = 430


_PLATFORM_TARGETS = {
    ("windows", "x64"): (
        "codex-win32-x64",
        "x86_64-pc-windows-msvc",
        "codex.exe",
    ),
    ("windows", "arm64"): (
        "codex-win32-arm64",
        "aarch64-pc-windows-msvc",
        "codex.exe",
    ),
    ("darwin", "x64"): (
        "codex-darwin-x64",
        "x86_64-apple-darwin",
        "codex",
    ),
    ("darwin", "arm64"): (
        "codex-darwin-arm64",
        "aarch64-apple-darwin",
        "codex",
    ),
    ("linux", "x64"): (
        "codex-linux-x64",
        "x86_64-unknown-linux-musl",
        "codex",
    ),
    ("linux", "arm64"): (
        "codex-linux-arm64",
        "aarch64-unknown-linux-musl",
        "codex",
    ),
}


def managed_codex_root(home: Path) -> Path:
    return (home / "private" / "runtimes" / "codex").resolve()


def managed_codex_version_root(home: Path) -> Path:
    return managed_codex_root(home) / MANAGED_CODEX_VERSION


def find_managed_codex_executable(home: Path) -> str | None:
    target = _platform_target()
    if target is None:
        return None
    package, triple, executable_name = target
    executable = (
        managed_codex_version_root(home)
        / "node_modules"
        / "@openai"
        / package
        / "vendor"
        / triple
        / "bin"
        / executable_name
    )
    if executable.is_file():
        return str(executable.resolve())
    return None


def managed_codex_runtime_status(home: Path) -> dict[str, Any]:
    executable = find_managed_codex_executable(home)
    npm = _resolve_npm()
    version: str | None = None
    error: str | None = None
    if executable:
        version, error = _codex_version(executable)
    return {
        "installed": bool(executable and version),
        "available": bool(executable and version),
        "package": MANAGED_CODEX_PACKAGE,
        "pinned_version": MANAGED_CODEX_VERSION,
        "version": version,
        "executable_path": executable,
        "install_root": str(managed_codex_version_root(home)),
        "npm_available": bool(npm),
        "npm_path": npm,
        "download_estimate_mb": MANAGED_CODEX_DOWNLOAD_ESTIMATE_MB,
        "installed_size_estimate_mb": MANAGED_CODEX_INSTALLED_ESTIMATE_MB,
        "source": "official_openai_npm",
        "error": error,
        "isolated_auth_home": str(
            (home / "private" / "codex-managed").resolve()
        ),
        "shares_global_codex_auth": False,
    }


def install_managed_codex_runtime(
    home: Path,
    *,
    npm_executable: str | None = None,
    timeout_seconds: int = 1_200,
) -> dict[str, Any]:
    current = managed_codex_runtime_status(home)
    if current["installed"]:
        return current
    npm = npm_executable or _resolve_npm()
    if not npm:
        raise ValueError(
            "无法安装 OpenAI Codex 运行时：没有找到 npm。"
            "请先安装 Node.js，或在高级设置中选择一个独立 Codex CLI。"
        )
    root = managed_codex_version_root(home)
    root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(managed_codex_root(home) / "install.lock"))
    with lock:
        current = managed_codex_runtime_status(home)
        if current["installed"]:
            return current
        command = [
            npm,
            "install",
            "--prefix",
            str(root),
            "--no-save",
            "--no-audit",
            "--no-fund",
            "--omit=dev",
            "--ignore-scripts",
            "--package-lock=false",
            f"{MANAGED_CODEX_PACKAGE}@{MANAGED_CODEX_VERSION}",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
                env=_process_environment(),
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "OpenAI Codex 运行时安装超时。现有可用版本未被删除，"
                "请检查网络或代理后重试。"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"无法启动 npm 安装程序：{exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-2_000:]
            raise ValueError(
                "OpenAI Codex 运行时安装失败。"
                + (f" npm 返回：{detail}" if detail else "")
            )
        status = managed_codex_runtime_status(home)
        if not status["installed"]:
            raise ValueError(
                "npm 已完成，但没有找到当前系统对应的 Codex 可执行文件。"
                "可能是操作系统或 CPU 架构暂不受此版本支持。"
            )
        return status


def _resolve_npm() -> str | None:
    return shutil.which("npm.cmd") or shutil.which("npm")


def _platform_target() -> tuple[str, str, str] | None:
    system = platform.system().lower()
    raw_machine = platform.machine().lower()
    if raw_machine in {"amd64", "x86_64"}:
        machine = "x64"
    elif raw_machine in {"arm64", "aarch64"}:
        machine = "arm64"
    else:
        machine = raw_machine
    return _PLATFORM_TARGETS.get((system, machine))


def _codex_version(executable: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
            env=_process_environment(),
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    output = result.stdout.strip().splitlines()
    if result.returncode != 0:
        return None, result.stderr.strip()[-1_000:] or "Codex version check failed"
    return (output[0] if output else MANAGED_CODEX_VERSION), None


def _process_environment() -> dict[str, str]:
    # Imported lazily to avoid pulling the Agent registry back into the managed
    # runtime module while CodexAppServerAdapter itself is being imported.
    from .agent_gateway.process import _process_environment as build_environment

    return build_environment({})
