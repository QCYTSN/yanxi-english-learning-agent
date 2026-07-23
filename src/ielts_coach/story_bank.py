from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .session_io import load_data_file
from .validation import validate_data


def add_story(home: Path, path: Path) -> dict[str, Any]:
    return save_story(home, load_data_file(path))


def save_story(home: Path, value: dict[str, Any]) -> dict[str, Any]:
    data = validate_data(value, "story")
    target = home / "story-bank" / f"{data['story_id']}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def list_stories(home: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted((home / "story-bank").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            result.append(data)
    return result


def show_story(home: Path, story_id: str) -> dict[str, Any] | None:
    path = home / "story-bank" / f"{story_id}.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None
