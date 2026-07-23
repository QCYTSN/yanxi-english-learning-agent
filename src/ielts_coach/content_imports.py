from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Any

from .corpus import import_manifest, load_manifest
from .storage import (
    create_content_import_job,
    get_content_import_job,
    list_content_import_jobs,
    update_content_import_job,
)


ALLOWED_SUFFIXES = {".yaml", ".yml", ".json", ".jsonl", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".m4a"}
STRUCTURED_SUFFIXES = {".yaml", ".yml", ".json", ".jsonl"}
RAW_SUFFIXES = ALLOWED_SUFFIXES - STRUCTURED_SUFFIXES
MAX_FILE_BYTES = 150 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024


def create_import(
    home: Path,
    *,
    title: str,
    source_type: str,
    authenticity: str,
    rights_status: str,
    files: list[tuple[str, bytes, str | None]],
) -> dict[str, Any]:
    if not files:
        raise ValueError("At least one content file is required")
    if source_type not in {"official_external", "licensed_private", "seasonal_reported", "personal", "synthetic", "project_original"}:
        raise ValueError("Unsupported source_type")
    if rights_status not in {"redistributable", "external_reference", "local_private"}:
        raise ValueError("Unsupported rights_status")
    total = sum(len(data) for _, data, _ in files)
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Import exceeds the 500 MB total limit")

    import_id = f"IMP-{secrets.token_hex(6).upper()}"
    target = home / "corpus" / "inbox" / import_id
    target.mkdir(parents=True, exist_ok=False)
    stored: list[dict[str, Any]] = []
    used_names: set[str] = set()
    try:
        for original_name, data, mime_type in files:
            if len(data) > MAX_FILE_BYTES:
                raise ValueError(f"File exceeds the 150 MB limit: {original_name}")
            clean = _safe_name(original_name)
            suffix = Path(clean).suffix.casefold()
            if suffix not in ALLOWED_SUFFIXES:
                raise ValueError(f"Unsupported content file type: {suffix or 'none'}")
            clean = _unique_name(clean, used_names)
            used_names.add(clean.casefold())
            path = target / clean
            path.write_bytes(data)
            stored.append({
                "original_name": original_name,
                "stored_name": clean,
                "file_kind": "structured" if suffix in STRUCTURED_SUFFIXES else _raw_kind(suffix),
                "mime_type": mime_type,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
        manifest = next((item for item in stored if item["stored_name"].casefold() in {"manifest.yaml", "manifest.yml"}), None)
        raw_count = sum(item["file_kind"] != "structured" for item in stored)
        status = "ready_to_import" if manifest else "needs_structuring"
        summary = {"file_count": len(stored), "raw_file_count": raw_count, "manifest_file": manifest["stored_name"] if manifest else None}
        create_content_import_job(home, {
            "import_id": import_id,
            "title": title.strip() or import_id,
            "source_type": source_type,
            "authenticity": authenticity.strip() or "unreviewed",
            "rights_status": rights_status,
            "status": status,
            "summary": summary,
        }, stored)
    except Exception:
        for path in target.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        target.rmdir()
        raise
    return get_content_import_job(home, import_id) or {}


def process_import(home: Path, import_id: str) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    if job["status"] == "imported":
        return job
    manifest_name = (job.get("summary") or {}).get("manifest_file")
    if not manifest_name:
        raise ValueError("This upload needs a prepared manifest and JSONL files before import")
    manifest_path = home / "corpus" / "inbox" / import_id / str(manifest_name)
    try:
        manifest = load_manifest(manifest_path)
        _verify_manifest_matches_job(job, manifest)
        result = import_manifest(home, manifest_path, index=True, force=False)
    except Exception as exc:
        update_content_import_job(home, import_id, status="failed", error_message=str(exc), summary=job.get("summary"))
        raise
    summary = dict(job.get("summary") or {})
    summary["import_result"] = result.get("index") or {}
    summary["corpus_id"] = (result.get("manifest") or {}).get("corpus_id")
    update_content_import_job(home, import_id, status="imported", summary=summary)
    return get_content_import_job(home, import_id) or {}


def imports(home: Path, limit: int = 100) -> list[dict[str, Any]]:
    return list_content_import_jobs(home, limit=limit)


def _safe_name(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        raise ValueError("Invalid file name")
    return name[:180]


def _unique_name(name: str, used: set[str]) -> str:
    if name.casefold() not in used:
        return name
    path = Path(name)
    for index in range(2, 1000):
        candidate = f"{path.stem}-{index}{path.suffix}"
        if candidate.casefold() not in used:
            return candidate
    raise ValueError("Too many files with the same name")


def _raw_kind(suffix: str) -> str:
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".mp3", ".wav", ".m4a"}:
        return "audio"
    return "image"


def _verify_manifest_matches_job(job: dict[str, Any], manifest: dict[str, Any]) -> None:
    expected = {
        "source_type": str(job.get("source_type") or ""),
        "authenticity": str(job.get("authenticity") or ""),
        "rights_status": str(job.get("rights_status") or ""),
    }
    actual = {
        "source_type": str(manifest.get("source_type") or ""),
        "authenticity": str(manifest.get("authenticity") or ""),
        "rights_status": _manifest_rights(manifest),
    }
    mismatches = [
        f"{key}: upload={expected[key]!r}, manifest={actual[key]!r}"
        for key in expected
        if expected[key] != actual[key]
    ]
    if mismatches:
        raise ValueError(
            "Manifest provenance does not match the registered upload: "
            + "; ".join(mismatches)
        )


def _manifest_rights(manifest: dict[str, Any]) -> str:
    declared = manifest.get("rights_status")
    if declared:
        return str(declared)
    permissions = manifest.get("permissions") or {}
    if permissions.get("redistribution_allowed"):
        return "redistributable"
    if permissions.get("local_personal_use_only"):
        return "local_private"
    return "external_reference"
