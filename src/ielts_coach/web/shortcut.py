from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path


SHORTCUT_NAME = "IELTS Study Desk.lnk"


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


def install_desktop_shortcut(home: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Desktop shortcut installation is currently supported on Windows only.")
    executable = _python_window_executable()
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
$shortcut.Description = 'Start or reopen the local IELTS Study Desk'
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
            "IELTS_SHORTCUT_ICON": f"{sys.executable},0",
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
