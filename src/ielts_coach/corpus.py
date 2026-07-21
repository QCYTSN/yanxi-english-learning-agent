from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .question_bank import import_question_files, preflight_question_files
from .storage import connect, upsert_corpus
from .validation import validate_data


def _resource_file(relative: str):
    return resources.files("ielts_coach.resources").joinpath(relative)


def install_starter_corpus(home: Path, force: bool = False) -> None:
    """Install the project-owned corpus, upgrading stale bundled files safely.

    The starter corpus is managed by the application rather than user-owned.
    Refreshing these files is therefore safe and is required for V0.1 homes,
    whose manifest did not contain the V0.2 question-file index.
    """
    target = home / "corpus" / "starter-open"
    target.mkdir(parents=True, exist_ok=True)
    source_dir = _resource_file("starter-corpus")
    for item in source_dir.iterdir():
        if not item.is_file():
            continue
        destination = target / item.name
        with resources.as_file(item) as source_path:
            if force or not destination.exists() or source_path.read_bytes() != destination.read_bytes():
                shutil.copy2(source_path, destination)


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Corpus manifest must be a YAML mapping")
    return validate_data(data, "corpus-manifest")


def _resolve_base(manifest: dict[str, Any], manifest_path: Path) -> Path:
    storage = manifest.get("storage") or {}
    value = storage.get("resolved_base_path") or storage.get("local_path")
    return Path(str(value)).expanduser().resolve() if value else manifest_path.parent.resolve()


def import_manifest(home: Path, path: Path, *, index: bool = True, force: bool = False) -> dict[str, Any]:
    data = load_manifest(path)
    base = _resolve_base(data, path)
    stored = dict(data)
    stored["storage"] = dict(data.get("storage") or {})
    stored["storage"]["resolved_base_path"] = str(base)
    files = stored.get("files") or []
    if index and files:
        preflight_question_files(
            home,
            stored["corpus_id"],
            base,
            files,
            source_type=stored["source_type"],
            authenticity=stored.get("authenticity"),
        )
    target = home / "corpus" / "manifests" / f"{data['corpus_id']}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(stored, allow_unicode=True, sort_keys=False), encoding="utf-8")
    upsert_corpus(home, stored)
    result: dict[str, Any] = {"manifest": stored, "index": {"passages": 0, "questions": 0, "duplicates": 0}}
    if index and files:
        result["index"] = import_question_files(
            home,
            stored["corpus_id"],
            base,
            files,
            source_type=stored["source_type"],
            authenticity=stored.get("authenticity"),
            force=force,
        )
    return result


def reindex_corpus(home: Path, corpus_id: str, *, force: bool = False) -> dict[str, int]:
    manifest_path = home / "corpus" / "manifests" / f"{corpus_id}.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Unknown corpus manifest: {corpus_id}")
    data = load_manifest(manifest_path)
    return import_question_files(
        home,
        corpus_id,
        _resolve_base(data, manifest_path),
        data.get("files") or [],
        source_type=data["source_type"],
        authenticity=data.get("authenticity"),
        force=force,
    )


def corpus_stats(home: Path, corpus_id: str | None = None) -> list[dict[str, Any]]:
    clauses = " WHERE corpus_id=?" if corpus_id else ""
    params = (corpus_id,) if corpus_id else ()
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT corpus_id,module,COUNT(*) questions,
                   COUNT(DISTINCT passage_id) passages,
                   COUNT(DISTINCT question_type) question_types
            FROM questions{clauses}
            GROUP BY corpus_id,module ORDER BY corpus_id,module
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]
