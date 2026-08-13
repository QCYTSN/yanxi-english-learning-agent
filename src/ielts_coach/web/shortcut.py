from __future__ import annotations

import base64
import os
import subprocess
import sys
from importlib import resources
from pathlib import Path


SHORTCUT_NAME = "言蹊.lnk"


def _powershell(script: str, environment: dict[str, str]) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **environment},
    )
    return completed.stdout.strip()


def _python_window_executable() -> Path:
    current = Path(sys.executable).resolve()
    if os.name == "nt" and current.name.lower() == "python.exe":
        windowed = current.with_name("pythonw.exe")
        if windowed.is_file():
            return windowed
    return current


def _shortcut_icon(home: Path) -> Path:
    """Materialise the packaged icon at a stable user-owned path."""
    destination = home / "runtime" / "app-icon.ico"
    destination.parent.mkdir(parents=True, exist_ok=True)
    icon = resources.files("ielts_coach.resources").joinpath("assets/app-icon.ico")
    payload = icon.read_bytes()
    if not destination.exists() or destination.read_bytes() != payload:
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    return destination


def install_desktop_shortcut(home: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Desktop shortcut installation is currently supported on Windows only.")
    executable = _python_window_executable()
    icon = _shortcut_icon(home.resolve())
    arguments = subprocess.list2cmdline(
        ["-m", "ielts_coach.web.background", "open", "--home", str(home.resolve())]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop $env:IELTS_SHORTCUT_NAME
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $env:IELTS_SHORTCUT_TARGET
$shortcut.Arguments = $env:IELTS_SHORTCUT_ARGS
$shortcut.WorkingDirectory = $env:IELTS_SHORTCUT_WORKDIR
$shortcut.IconLocation = $env:IELTS_SHORTCUT_ICON
$shortcut.Description = 'Start or reopen the local 言蹊 (Yanxi) study desk'
$shortcut.Save()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output $shortcutPath
"""
    output = _powershell(
        script,
        {
            "IELTS_SHORTCUT_NAME": SHORTCUT_NAME,
            "IELTS_SHORTCUT_TARGET": str(executable),
            "IELTS_SHORTCUT_ARGS": arguments,
            "IELTS_SHORTCUT_WORKDIR": str(home.resolve()),
            "IELTS_SHORTCUT_ICON": f"{icon},0",
        },
    )
    path = Path(output.splitlines()[-1])
    if not path.is_file():
        raise RuntimeError("Windows reported success but the desktop shortcut was not created.")
    return path


def remove_desktop_shortcut() -> Path | None:
    if os.name != "nt":
        raise RuntimeError("Desktop shortcut removal is currently supported on Windows only.")
    script = r"""
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop $env:IELTS_SHORTCUT_NAME
if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $shortcutPath
}
"""
    output = _powershell(script, {"IELTS_SHORTCUT_NAME": SHORTCUT_NAME})
    return Path(output.splitlines()[-1]) if output else None
