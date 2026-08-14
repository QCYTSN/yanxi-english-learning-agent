from __future__ import annotations

import os
from pathlib import Path


def resolve_home(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    value = os.environ.get("IELTS_HOME")
    if value:
        return Path(value).expanduser().resolve()
    legacy = Path.home() / ".ielts"
    if legacy.exists():
        return legacy.resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return (
            Path(os.environ["LOCALAPPDATA"])
            / "Yanxi"
            / "data"
        ).resolve()
    return (Path.home() / ".local" / "share" / "yanxi").resolve()


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "skills-source").exists():
            return candidate
    raise FileNotFoundError(
        "Could not find the Yanxi project root. Run this command from "
        "the cloned repository or pass --project-root."
    )
