from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .validation import normalise_json_value, validate_data


def _parse_markdown_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        raise ValueError("Markdown files must begin with YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Unclosed YAML frontmatter")
    data = yaml.safe_load(parts[1]) or {}
    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a mapping")
    data["document_body"] = parts[2].strip()
    return normalise_json_value(data)


def load_data_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix in {".md", ".markdown"}:
        data = _parse_markdown_frontmatter(text)
    else:
        raise ValueError("Supported formats: .json, .yaml, .yml, .md")
    if not isinstance(data, dict):
        raise ValueError("File must contain an object/mapping")
    return normalise_json_value(data)


def load_session_file(path: Path) -> dict[str, Any]:
    return validate_data(load_data_file(path), "session")
