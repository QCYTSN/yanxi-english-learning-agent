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


def install_starter_corpus(home: Path, force: bool = False) -> bool:
    """Install the opt-in project-owned development fixture corpus.

    Public initialisation never calls this function. It exists so automated
    tests and explicit development homes can exercise complete learning flows.
    """
    target = home / "corpus" / "starter-open"
    target.mkdir(parents=True, exist_ok=True)
    source_dir = _resource_file("starter-corpus")
    changed = False
    for item in source_dir.iterdir():
        if not item.is_file():
            continue
        destination = target / item.name
        with resources.as_file(item) as source_path:
            if force or not destination.exists() or source_path.read_bytes() != destination.read_bytes():
                shutil.copy2(source_path, destination)
                changed = True
    return changed


def install_original_mock_corpus(home: Path, force: bool = False) -> bool:
    """Install the reviewed project-original full-mock corpus."""
    target = home / "corpus" / "original-mocks"
    target.mkdir(parents=True, exist_ok=True)
    source_dir = _resource_file("original-mocks")
    changed = False
    for item in source_dir.iterdir():
        if not item.is_file():
            continue
        destination = target / item.name
        with resources.as_file(item) as source_path:
            if force or not destination.exists() or source_path.read_bytes() != destination.read_bytes():
                shutil.copy2(source_path, destination)
                changed = True
    return changed


def corpus_index_is_complete(home: Path, manifest_path: Path) -> bool:
    """Cheap launch guard that avoids re-indexing an unchanged managed corpus."""
    if not manifest_path.exists():
        return False
    manifest = load_manifest(manifest_path)
    corpus_id = str(manifest["corpus_id"])
    base = _resolve_base(manifest, manifest_path)
    expected = {"passages": 0, "questions": 0, "assessment_packs": 0}
    for file_spec in manifest.get("files") or []:
        kind = str(file_spec.get("kind") or "questions")
        if kind not in expected or not file_spec.get("path"):
            continue
        path = (base / str(file_spec["path"])).resolve()
        if not path.exists():
            return False
        with path.open("r", encoding="utf-8") as handle:
            expected[kind] += sum(1 for line in handle if line.strip())
    with connect(home) as conn:
        registered = conn.execute(
            "SELECT 1 FROM corpora WHERE corpus_id=?", (corpus_id,)
        ).fetchone()
        if not registered:
            return False
        actual = {
            "passages": int(
                conn.execute(
                    "SELECT COUNT(*) FROM question_passages WHERE corpus_id=?",
                    (corpus_id,),
                ).fetchone()[0]
            ),
            "questions": int(
                conn.execute(
                    "SELECT COUNT(*) FROM questions WHERE corpus_id=?",
                    (corpus_id,),
                ).fetchone()[0]
            ),
            "assessment_packs": int(
                conn.execute(
                    "SELECT COUNT(*) FROM assessment_packs WHERE corpus_id=?",
                    (corpus_id,),
                ).fetchone()[0]
            ),
        }
    return actual == expected


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Corpus manifest must be a YAML mapping")
    return validate_data(data, "corpus-manifest")


def _resolve_base(manifest: dict[str, Any], manifest_path: Path) -> Path:
    storage = manifest.get("storage") or {}
    value = storage.get("resolved_base_path") or storage.get("local_path")
    return Path(str(value)).expanduser().resolve() if value else manifest_path.parent.resolve()


def import_manifest(
    home: Path,
    path: Path,
    *,
    index: bool = True,
    force: bool = False,
    refresh_reviews: bool = True,
) -> dict[str, Any]:
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
            manifest=stored,
        )
    target = home / "corpus" / "manifests" / f"{data['corpus_id']}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(stored, allow_unicode=True, sort_keys=False), encoding="utf-8")
    upsert_corpus(home, stored)
    result: dict[str, Any] = {"manifest": stored, "index": {"passages": 0, "questions": 0, "assessment_packs": 0, "duplicates": 0}}
    if index and files:
        result["index"] = import_question_files(
            home,
            stored["corpus_id"],
            base,
            files,
            source_type=stored["source_type"],
            authenticity=stored.get("authenticity"),
            manifest=stored,
            force=force,
            refresh_reviews=refresh_reviews,
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
        manifest=data,
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
