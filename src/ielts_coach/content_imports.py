from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .config import load_settings
from .corpus import import_manifest, load_manifest
from .ocr_runtime import execute_ocr, ocr_runtime_status
from .storage import (
    create_content_import_job,
    content_import_storage_bytes,
    delete_content_import_job,
    get_content_import_job,
    list_content_import_jobs,
    update_content_import_job,
)
from .uploads import StagedUpload, copy_file_atomic, read_zip_member
from .storage_quota import assert_local_storage_capacity, invalidate_storage_usage


ALLOWED_SUFFIXES = {
    ".yaml", ".yml", ".json", ".jsonl", ".pdf", ".png", ".jpg", ".jpeg",
    ".webp", ".mp3", ".wav", ".m4a", ".txt", ".md", ".docx",
}
STRUCTURED_SUFFIXES = {".yaml", ".yml", ".json", ".jsonl"}
RAW_SUFFIXES = ALLOWED_SUFFIXES - STRUCTURED_SUFFIXES
MAX_FILE_BYTES = 150 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
PAGE_ROLES = {
    "unassigned",
    "passage",
    "questions",
    "reading_test",
    "reading_passage",
    "reading_questions",
    "writing_task_1",
    "writing_task_2",
    "answer_key_with_writing_task_1",
    "writing_task_2_with_task_1_visual",
    "speaking_test",
    "speaking_test_with_sample_answers",
    "answer_key",
    "task_visual",
    "transcript",
    "instructions",
    "exclude",
}
PREPARATION_ACTIVE_STATUSES = {
    "queued",
    "preparing",
    "ocr_queued",
    "ocr_running",
    "draft_building",
}
MAX_OCR_PAGES_PER_RUN = 50
PAGE_TEXT_VERSION = 1
REVIEW_DRAFT_VERSION = 1
PAGE_DOCUMENT_KINDS = {"pdf", "image", "text", "document"}
OCR_DOCUMENT_KINDS = {"pdf", "image"}


def create_import(
    home: Path,
    *,
    title: str,
    source_type: str,
    authenticity: str,
    rights_status: str,
    files: list[tuple[str, bytes, str | None]],
) -> dict[str, Any]:
    prepared = [
        (
            original_name,
            data,
            mime_type,
            len(data),
            hashlib.sha256(data).hexdigest(),
        )
        for original_name, data, mime_type in files
    ]
    return _create_import_sources(
        home,
        title=title,
        source_type=source_type,
        authenticity=authenticity,
        rights_status=rights_status,
        files=prepared,
    )


def create_import_from_staged(
    home: Path,
    *,
    title: str,
    source_type: str,
    authenticity: str,
    rights_status: str,
    files: list[StagedUpload],
) -> dict[str, Any]:
    return _create_import_sources(
        home,
        title=title,
        source_type=source_type,
        authenticity=authenticity,
        rights_status=rights_status,
        files=[
            (
                item.original_name,
                item.path,
                item.mime_type,
                item.size_bytes,
                item.sha256,
            )
            for item in files
        ],
    )


def _create_import_sources(
    home: Path,
    *,
    title: str,
    source_type: str,
    authenticity: str,
    rights_status: str,
    files: list[tuple[str, bytes | Path, str | None, int, str]],
) -> dict[str, Any]:
    if not files:
        raise ValueError("At least one content file is required")
    if source_type not in {"official_external", "licensed_private", "seasonal_reported", "personal", "synthetic", "project_original"}:
        raise ValueError("Unsupported source_type")
    if rights_status not in {"redistributable", "external_reference", "local_private"}:
        raise ValueError("Unsupported rights_status")
    total = sum(size for _, _, _, size, _ in files)
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Import exceeds the 500 MB total limit")
    storage = content_storage_status(home)
    if total > storage["remaining_bytes"]:
        raise ValueError(
            "The local content inbox does not have enough quota for this upload"
        )
    assert_local_storage_capacity(home, total)

    import_id = f"IMP-{secrets.token_hex(6).upper()}"
    target = home / "corpus" / "inbox" / import_id
    target.mkdir(parents=True, exist_ok=False)
    stored: list[dict[str, Any]] = []
    used_names: set[str] = set()
    try:
        for original_name, source, mime_type, size_bytes, sha256 in files:
            if size_bytes > MAX_FILE_BYTES:
                raise ValueError(f"File exceeds the 150 MB limit: {original_name}")
            clean = _safe_name(original_name)
            suffix = Path(clean).suffix.casefold()
            if suffix not in ALLOWED_SUFFIXES:
                raise ValueError(f"Unsupported content file type: {suffix or 'none'}")
            clean = _unique_name(clean, used_names)
            used_names.add(clean.casefold())
            path = target / clean
            if isinstance(source, Path):
                copy_file_atomic(source, path)
            else:
                path.write_bytes(source)
            stored.append({
                "original_name": original_name,
                "stored_name": clean,
                "file_kind": "structured" if suffix in STRUCTURED_SUFFIXES else _raw_kind(suffix),
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "sha256": sha256,
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
        invalidate_storage_usage(home)
    except Exception:
        for path in target.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        target.rmdir()
        invalidate_storage_usage(home)
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
        # Fresh uploads have no local approval records yet.  The importer
        # already computes provisional conformance and stores review_status as
        # unreviewed/in_review, so refreshing every item and every dependent
        # pack here only repeats work and becomes quadratic for large books.
        # Local status is still computed on demand, and explicit review actions
        # continue to refresh the affected dependency graph.
        result = import_manifest(
            home,
            manifest_path,
            index=True,
            force=False,
            refresh_reviews=False,
        )
    except Exception as exc:
        update_content_import_job(home, import_id, status="failed", error_message=str(exc), summary=job.get("summary"))
        raise
    summary = dict(job.get("summary") or {})
    summary["import_result"] = result.get("index") or {}
    summary["corpus_id"] = (result.get("manifest") or {}).get("corpus_id")
    update_content_import_job(home, import_id, status="imported", summary=summary)
    return get_content_import_job(home, import_id) or {}


def queue_import_preparation(home: Path, import_id: str) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    if job["status"] in PREPARATION_ACTIVE_STATUSES:
        return job
    if job["status"] in {"ready_to_import", "imported"}:
        return job
    summary = dict(job.get("summary") or {})
    summary["preparation"] = {
        "status": "queued",
        "progress": 0,
        "recovery_action": None,
    }
    update_content_import_job(
        home,
        import_id,
        status="queued",
        summary=summary,
    )
    return get_content_import_job(home, import_id) or {}


def prepare_import(home: Path, import_id: str) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    if job["status"] in {"ready_to_import", "imported"}:
        return job
    summary = dict(job.get("summary") or {})
    summary["preparation"] = {
        "status": "preparing",
        "progress": 5,
        "recovery_action": None,
    }
    update_content_import_job(
        home,
        import_id,
        status="preparing",
        summary=summary,
    )
    try:
        documents: list[dict[str, Any]] = []
        page_text_store = _read_page_text_store(home, import_id)
        total_pages = 0
        needs_ocr_pages = 0
        for file in job.get("files") or []:
            stored_name = str(file["stored_name"])
            path = import_file_path(home, job, stored_name)
            if file["file_kind"] == "pdf":
                document, extracted_text = _analyse_pdf_with_text(path, stored_name)
                existing_text = (
                    page_text_store.get("documents", {}).get(stored_name, {})
                )
                merged_text = dict(extracted_text)
                for page_number, record in existing_text.items():
                    if record.get("source") == "ocr" and record.get("text"):
                        merged_text[page_number] = record
                page_text_store.setdefault("documents", {})[stored_name] = merged_text
                _apply_page_text_to_document(document, merged_text)
                documents.append(document)
                total_pages += int(document.get("page_count") or 0)
                needs_ocr_pages += int(document.get("needs_ocr_pages") or 0)
            elif file["file_kind"] in {"text", "document"}:
                text, extraction_status = _extract_document_text(
                    path, Path(stored_name).suffix.casefold()
                )
                page_text_store.setdefault("documents", {})[stored_name] = {
                    "1": {
                        "text": text,
                        "source": file["file_kind"],
                        "confidence": 1.0 if text else None,
                        "text_hash": _text_hash(text),
                        "updated_at": _now(),
                    }
                }
                documents.append({
                    "stored_name": stored_name,
                    "file_kind": file["file_kind"],
                    "page_count": 1,
                    "status": extraction_status,
                    "needs_ocr_pages": 0,
                    "pages": [{
                        "page_number": 1,
                        "text_chars": len(text),
                        "text_preview": re.sub(r"\s+", " ", text).strip()[:360],
                        "extraction_status": extraction_status,
                        "error": None,
                    }],
                })
                total_pages += 1
            elif file["file_kind"] == "image":
                existing_text = (
                    page_text_store.get("documents", {}).get(stored_name, {})
                )
                page_text_store.setdefault("documents", {})[stored_name] = dict(
                    existing_text
                )
                document = {
                    "stored_name": stored_name,
                    "file_kind": "image",
                    "page_count": 1,
                    "status": "prepared",
                    "needs_ocr_pages": 1,
                    "pages": [{
                        "page_number": 1,
                        "text_chars": 0,
                        "text_preview": "",
                        "extraction_status": "ocr_required",
                        "text_source": "none",
                        "error": None,
                    }],
                }
                _apply_page_text_to_document(document, existing_text)
                documents.append(document)
                total_pages += 1
                needs_ocr_pages += int(document.get("needs_ocr_pages") or 0)
            elif file["file_kind"] == "audio":
                documents.append({
                    "stored_name": stored_name,
                    "file_kind": file["file_kind"],
                    "page_count": 0,
                    "status": "registered",
                })
        summary["documents"] = documents
        summary.setdefault("page_plan", {})
        summary["preparation"] = {
            "status": "ready_for_review",
            "progress": 100,
            "document_count": len(documents),
            "page_count": total_pages,
            "needs_ocr_pages": needs_ocr_pages,
            "recovery_action": None,
        }
        _write_page_text_store(home, import_id, page_text_store)
        _write_structure_draft(home, import_id, summary)
        update_content_import_job(
            home,
            import_id,
            status="ready_for_review",
            summary=summary,
        )
    except Exception as exc:
        summary["preparation"] = {
            "status": "failed",
            "progress": 0,
            "recovery_action": "retry_preparation",
        }
        update_content_import_job(
            home,
            import_id,
            status="failed",
            error_message=str(exc),
            summary=summary,
        )
        raise
    return get_content_import_job(home, import_id) or {}


def ocr_capability(home: Path) -> dict[str, Any]:
    status = ocr_runtime_status(home)
    status["max_pages_per_run"] = MAX_OCR_PAGES_PER_RUN
    return status


def queue_import_ocr(
    home: Path,
    import_id: str,
    *,
    stored_name: str,
    pages: list[int],
) -> dict[str, Any]:
    capability = ocr_capability(home)
    if not capability["available"]:
        raise ValueError(
            "The isolated local OCR runtime is not ready"
        )
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    if job["status"] in {"ocr_queued", "ocr_running"}:
        return job
    document = _prepared_ocr_document(job, stored_name)
    page_count = int(document.get("page_count") or 0)
    normalised = sorted(set(int(page) for page in pages))
    if not normalised:
        raise ValueError("Select at least one document page for OCR")
    if len(normalised) > MAX_OCR_PAGES_PER_RUN:
        raise ValueError(
            f"OCR is limited to {MAX_OCR_PAGES_PER_RUN} pages per run"
        )
    invalid = [page for page in normalised if page < 1 or page > page_count]
    if invalid:
        raise ValueError(f"Document page number out of range: {invalid[0]}")
    summary = dict(job.get("summary") or {})
    summary["ocr"] = {
        "status": "queued",
        "engine_id": capability["engine_id"],
        "stored_name": stored_name,
        "pages": normalised,
        "progress": 0,
        "recovery_action": None,
    }
    update_content_import_job(
        home,
        import_id,
        status="ocr_queued",
        error_message=None,
        summary=summary,
    )
    return get_content_import_job(home, import_id) or {}


def run_import_ocr(
    home: Path,
    import_id: str,
    *,
    stored_name: str,
    pages: list[int],
    timeout_seconds: int = 1800,
    render_scale: float = 2.2,
) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    document = _prepared_ocr_document(job, stored_name)
    normalised = sorted(set(int(page) for page in pages))
    if not normalised:
        raise ValueError("Select at least one document page for OCR")
    page_count = int(document.get("page_count") or 0)
    invalid = [page for page in normalised if page < 1 or page > page_count]
    if invalid:
        raise ValueError(f"Document page number out of range: {invalid[0]}")
    summary = dict(job.get("summary") or {})
    summary["ocr"] = {
        "status": "running",
        "engine_id": "rapidocr-local",
        "stored_name": stored_name,
        "pages": normalised,
        "progress": 5,
        "recovery_action": None,
    }
    update_content_import_job(
        home,
        import_id,
        status="ocr_running",
        error_message=None,
        summary=summary,
    )
    try:
        path = import_file_path(home, job, stored_name)
        results = execute_ocr(
            home,
            path,
            normalised,
            timeout_seconds=timeout_seconds,
            render_scale=render_scale,
        )
        page_text_store = _read_page_text_store(home, import_id)
        document_text = page_text_store.setdefault("documents", {}).setdefault(
            stored_name, {}
        )
        for page_number, result in results.items():
            document_text[str(page_number)] = {
                "text": result["text"],
                "source": "ocr",
                "confidence": result["confidence"],
                "layout_lines": list(result.get("layout_lines") or []),
                "text_hash": _text_hash(result["text"]),
                "updated_at": _now(),
            }
        _write_page_text_store(home, import_id, page_text_store)

        summary = dict((get_content_import_job(home, import_id) or job).get("summary") or {})
        documents = summary.get("documents") or []
        document = next(
            item
            for item in documents
            if item.get("stored_name") == stored_name
        )
        _apply_page_text_to_document(document, document_text)
        total_needs_ocr = sum(
            int(item.get("needs_ocr_pages") or 0)
            for item in documents
            if item.get("file_kind") in OCR_DOCUMENT_KINDS
        )
        preparation = dict(summary.get("preparation") or {})
        preparation["needs_ocr_pages"] = total_needs_ocr
        summary["preparation"] = preparation
        summary["ocr"] = {
            "status": "completed",
            "engine_id": "rapidocr-local",
            "stored_name": stored_name,
            "pages": normalised,
            "processed_pages": len(results),
            "empty_pages": [
                page for page, result in results.items() if not result["text"]
            ],
            "progress": 100,
            "recovery_action": None,
        }
        _invalidate_review_draft(summary, reason="page_text_changed")
        _write_structure_draft(home, import_id, summary)
        update_content_import_job(
            home,
            import_id,
            status="ready_for_review",
            error_message=None,
            summary=summary,
        )
    except Exception as exc:
        current = get_content_import_job(home, import_id) or job
        summary = dict(current.get("summary") or {})
        summary["ocr"] = {
            "status": "failed",
            "engine_id": "rapidocr-local",
            "stored_name": stored_name,
            "pages": normalised,
            "progress": 0,
            "recovery_action": "retry_ocr",
        }
        update_content_import_job(
            home,
            import_id,
            status="failed",
            error_message=str(exc),
            summary=summary,
        )
        raise
    return get_content_import_job(home, import_id) or {}


def build_import_review_draft(home: Path, import_id: str) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    summary = dict(job.get("summary") or {})
    page_plan = summary.get("page_plan") or {}
    if not any(page_plan.values()):
        raise ValueError("Assign at least one document page role before building a draft")
    summary["review_draft"] = {
        "status": "building",
        "progress": 5,
        "recovery_action": None,
    }
    update_content_import_job(
        home,
        import_id,
        status="draft_building",
        error_message=None,
        summary=summary,
    )
    try:
        page_text_store = _read_page_text_store(home, import_id)
        segments: list[dict[str, Any]] = []
        missing_text: list[str] = []
        files = {
            str(item["stored_name"]): item
            for item in job.get("files") or []
        }
        for document in summary.get("documents") or []:
            if document.get("file_kind") not in PAGE_DOCUMENT_KINDS:
                continue
            stored_name = str(document["stored_name"])
            planned = page_plan.get(stored_name) or {}
            text_records = (
                page_text_store.get("documents", {}).get(stored_name, {})
            )
            groups = _page_role_groups(planned)
            for index, group in enumerate(groups, start=1):
                role = group["role"]
                page_numbers = group["pages"]
                page_texts = [
                    str((text_records.get(str(page)) or {}).get("text") or "").strip()
                    for page in page_numbers
                ]
                layout_pages = [
                    {
                        "page_number": page,
                        "lines": list(
                            (text_records.get(str(page)) or {}).get("layout_lines") or []
                        ),
                    }
                    for page in page_numbers
                    if (text_records.get(str(page)) or {}).get("layout_lines")
                ]
                if role != "task_visual":
                    for page, text in zip(page_numbers, page_texts):
                        if not text:
                            missing_text.append(f"{stored_name} 第 {page} 页")
                text = "\n\n".join(item for item in page_texts if item)
                segment_id = (
                    f"{Path(stored_name).stem}:{role}:"
                    f"{page_numbers[0]}-{page_numbers[-1]}:{index}"
                )
                segments.append({
                    "segment_id": segment_id,
                    "role": role,
                    "stored_name": stored_name,
                    "page_start": page_numbers[0],
                    "page_end": page_numbers[-1],
                    "page_numbers": page_numbers,
                    "source_file_sha256": files[stored_name]["sha256"],
                    "text": text,
                    "text_hash": _text_hash(text),
                    "layout_pages": layout_pages,
                    "review_status": "needs_review",
                    "eligible_for_import": False,
                })
        if missing_text:
            preview = "、".join(missing_text[:6])
            suffix = " 等" if len(missing_text) > 6 else ""
            raise ValueError(
                f"These planned pages still need OCR or manual text: {preview}{suffix}"
            )
        if not segments:
            raise ValueError("The page plan contains no importable page roles")
        existing_issues: list[dict[str, Any]] = []
        existing_annotations: dict[str, Any] = {}
        next_revision = 1
        created_at = _now()
        existing_path = _import_sidecar_path(home, import_id, "review-draft.json")
        if existing_path.is_file():
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            existing_issues = list(existing.get("review_issues") or [])
            existing_annotations = dict(existing.get("review_annotations") or {})
            next_revision = int(existing.get("revision") or 0) + 1
            created_at = str(existing.get("created_at") or created_at)
        draft = {
            "draft_version": REVIEW_DRAFT_VERSION,
            "revision": next_revision,
            "import_id": import_id,
            "title": job["title"],
            "source_type": job["source_type"],
            "authenticity": job["authenticity"],
            "rights_status": job["rights_status"],
            "review_status": "needs_review",
            "eligible_for_import": False,
            "review_issues": existing_issues,
            "review_annotations": existing_annotations,
            "created_at": created_at,
            "updated_at": _now(),
            "segments": segments,
        }
        draft.update(_build_typed_drafts(segments, existing_annotations))
        _write_review_draft(home, import_id, draft)
        current = get_content_import_job(home, import_id) or job
        summary = dict(current.get("summary") or {})
        summary["review_draft"] = {
            "status": "ready",
            "progress": 100,
            "segment_count": len(segments),
            "reviewed_segment_count": 0,
            "revision": next_revision,
            "issue_count": len(existing_issues),
            "blocker_count": sum(
                item.get("severity") == "blocker" and item.get("status") == "open"
                for item in existing_issues
            ),
            "file": "review-draft.json",
            "recovery_action": None,
        }
        update_content_import_job(
            home,
            import_id,
            status="draft_ready",
            error_message=None,
            summary=summary,
        )
    except Exception as exc:
        current = get_content_import_job(home, import_id) or job
        summary = dict(current.get("summary") or {})
        summary["review_draft"] = {
            "status": "failed",
            "progress": 0,
            "recovery_action": "retry_draft",
        }
        update_content_import_job(
            home,
            import_id,
            status="failed",
            error_message=str(exc),
            summary=summary,
        )
        raise
    return read_import_review_draft(home, import_id)


def read_import_review_draft(home: Path, import_id: str) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    path = _import_sidecar_path(home, import_id, "review-draft.json")
    if not path.is_file():
        raise ValueError("This content import does not have a review draft yet")
    return json.loads(path.read_text(encoding="utf-8"))


def update_import_review_segment(
    home: Path,
    import_id: str,
    *,
    segment_id: str,
    text: str,
    review_status: str,
    expected_revision: int,
) -> dict[str, Any]:
    if review_status not in {"needs_review", "reviewed", "excluded"}:
        raise ValueError("Unsupported draft segment review status")
    draft = read_import_review_draft(home, import_id)
    if int(draft.get("revision") or 0) != expected_revision:
        raise ValueError("Review draft revision conflict; reload the latest draft")
    segment = next(
        (
            item
            for item in draft.get("segments") or []
            if item.get("segment_id") == segment_id
        ),
        None,
    )
    if not segment:
        raise ValueError("Unknown review draft segment")
    clean_text = text.strip()
    if segment.get("role") != "task_visual" and review_status != "excluded" and not clean_text:
        raise ValueError("A reviewed text segment cannot be empty")
    segment["text"] = clean_text
    segment["text_hash"] = _text_hash(clean_text)
    segment["review_status"] = review_status
    segment["reviewed_at"] = _now() if review_status == "reviewed" else None
    segment["eligible_for_import"] = False
    draft.update(
        _build_typed_drafts(
            draft.get("segments") or [],
            draft.get("review_annotations") or {},
        )
    )
    draft["revision"] = expected_revision + 1
    draft["updated_at"] = _now()
    reviewed = sum(
        item.get("review_status") in {"reviewed", "excluded"}
        for item in draft.get("segments") or []
    )
    draft["review_status"] = (
        "locally_reviewed"
        if reviewed == len(draft.get("segments") or [])
        else "needs_review"
    )
    draft["eligible_for_import"] = False
    _write_review_draft(home, import_id, draft)
    job = get_content_import_job(home, import_id) or {}
    summary = dict(job.get("summary") or {})
    draft_summary = dict(summary.get("review_draft") or {})
    draft_summary.update({
        "status": "ready",
        "reviewed_segment_count": reviewed,
        "revision": draft["revision"],
    })
    summary["review_draft"] = draft_summary
    update_content_import_job(
        home,
        import_id,
        status="draft_ready",
        error_message=None,
        summary=summary,
    )
    return draft


def record_import_review_issue(
    home: Path,
    import_id: str,
    *,
    code: str,
    severity: str,
    message: str,
    page_numbers: list[int],
    evidence: str,
) -> dict[str, Any]:
    if severity not in {"info", "warning", "blocker"}:
        raise ValueError("Unsupported review issue severity")
    clean_code = re.sub(r"[^a-z0-9_]+", "_", code.strip().lower()).strip("_")
    if not clean_code:
        raise ValueError("Review issue code is required")
    clean_message = message.strip()
    if not clean_message:
        raise ValueError("Review issue message is required")
    pages = sorted({int(page) for page in page_numbers if int(page) > 0})
    draft = read_import_review_draft(home, import_id)
    issues = list(draft.get("review_issues") or [])
    issue_id = (
        f"ISS-{hashlib.sha256(f'{clean_code}:{pages}'.encode()).hexdigest()[:12].upper()}"
    )
    issue = {
        "issue_id": issue_id,
        "code": clean_code,
        "severity": severity,
        "message": clean_message,
        "page_numbers": pages,
        "evidence": evidence.strip(),
        "status": "open",
        "created_at": _now(),
    }
    existing = next(
        (item for item in issues if item.get("issue_id") == issue_id),
        None,
    )
    if existing:
        existing.update(issue)
    else:
        issues.append(issue)
    draft["review_issues"] = issues
    draft["revision"] = int(draft.get("revision") or 0) + 1
    draft["updated_at"] = _now()
    _write_review_draft(home, import_id, draft)

    job = get_content_import_job(home, import_id) or {}
    summary = dict(job.get("summary") or {})
    draft_summary = dict(summary.get("review_draft") or {})
    draft_summary.update({
        "status": "ready",
        "issue_count": len(issues),
        "blocker_count": sum(
            item.get("severity") == "blocker" and item.get("status") == "open"
            for item in issues
        ),
        "revision": draft["revision"],
    })
    summary["review_draft"] = draft_summary
    update_content_import_job(
        home,
        import_id,
        status="draft_ready",
        error_message=None,
        summary=summary,
    )
    return draft


def update_import_review_annotation(
    home: Path,
    import_id: str,
    *,
    annotation_type: str,
    segment_id: str,
    payload: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    if annotation_type not in {
        "answer_key_overrides",
        "reading_group_overrides",
        "reading_question_overrides",
        "speaking_prompt_overrides",
        "writing_prompt_overrides",
    }:
        raise ValueError("Unsupported review annotation type")
    draft = read_import_review_draft(home, import_id)
    if int(draft.get("revision") or 0) != expected_revision:
        raise ValueError("Review draft revision conflict; reload the latest draft")
    segment = next(
        (
            item
            for item in draft.get("segments") or []
            if item.get("segment_id") == segment_id
        ),
        None,
    )
    if not segment:
        raise ValueError("Unknown review draft segment")
    clean_payload = _validate_review_annotation(
        annotation_type,
        payload,
        page_numbers=set(int(value) for value in segment.get("page_numbers") or []),
    )
    annotations = dict(draft.get("review_annotations") or {})
    typed_annotations = dict(annotations.get(annotation_type) or {})
    typed_annotations[segment_id] = {
        **clean_payload,
        "updated_at": _now(),
    }
    annotations[annotation_type] = typed_annotations
    draft["review_annotations"] = annotations
    draft.update(
        _build_typed_drafts(
            draft.get("segments") or [],
            annotations,
        )
    )
    draft["revision"] = expected_revision + 1
    draft["updated_at"] = _now()
    draft["eligible_for_import"] = False
    _write_review_draft(home, import_id, draft)

    job = get_content_import_job(home, import_id) or {}
    summary = dict(job.get("summary") or {})
    draft_summary = dict(summary.get("review_draft") or {})
    draft_summary.update({
        "status": "ready",
        "revision": draft["revision"],
    })
    summary["review_draft"] = draft_summary
    update_content_import_job(
        home,
        import_id,
        status="draft_ready",
        error_message=None,
        summary=summary,
    )
    return draft


def _validate_review_annotation(
    annotation_type: str,
    payload: dict[str, Any],
    *,
    page_numbers: set[int],
) -> dict[str, Any]:
    if annotation_type == "answer_key_overrides":
        answers = payload.get("answers")
        if not isinstance(answers, dict) or not answers:
            raise ValueError("Answer overrides require a non-empty answers map")
        clean_answers: dict[str, dict[str, Any]] = {}
        for raw_number, raw_answer in answers.items():
            number = int(raw_number)
            if not 1 <= number <= 40:
                raise ValueError("Answer override question numbers must be 1-40")
            item = (
                {"answer_text": raw_answer}
                if isinstance(raw_answer, str)
                else dict(raw_answer)
            )
            answer_text = str(item.get("answer_text") or "").strip()
            if not answer_text:
                raise ValueError("Answer override text cannot be empty")
            page_number = int(item.get("page_number") or 0)
            if page_number and page_number not in page_numbers:
                raise ValueError(
                    "Answer override evidence page must belong to the answer-key segment"
                )
            accepted_variants = item.get("accepted_variants") or []
            if isinstance(accepted_variants, str):
                accepted_variants = [accepted_variants]
            if not isinstance(accepted_variants, list):
                raise ValueError("Accepted answer variants must be a list")
            clean_item: dict[str, Any] = {
                "answer_text": answer_text,
                "page_number": page_number or None,
                "review_method": str(
                    item.get("review_method") or "visual_pdf_review"
                ),
                "evidence": str(item.get("evidence") or "").strip(),
            }
            clean_variants = [
                str(value).strip()
                for value in accepted_variants
                if str(value).strip()
            ]
            if clean_variants:
                clean_item["accepted_variants"] = clean_variants
            option_bank_id = str(item.get("option_bank_id") or "").strip()
            if option_bank_id:
                clean_item["option_bank_id"] = option_bank_id
            if "option_reuse_allowed" in item:
                clean_item["option_reuse_allowed"] = bool(
                    item["option_reuse_allowed"]
                )
            clean_answers[str(number)] = clean_item
        return {"answers": clean_answers}

    if annotation_type == "writing_prompt_overrides":
        task_number = int(payload.get("task_number") or 0)
        if task_number not in {1, 2}:
            raise ValueError("Writing prompt override task_number must be 1 or 2")
        prompt_text = str(payload.get("prompt_text") or "").strip()
        if not prompt_text:
            raise ValueError("Writing prompt override text cannot be empty")
        evidence_pages = sorted({
            int(value)
            for value in payload.get("evidence_pages") or []
            if int(value) > 0
        })
        if page_numbers and any(value not in page_numbers for value in evidence_pages):
            raise ValueError("Writing override evidence page is outside the source segment")
        media_id = str(payload.get("media_id") or "").strip() or None
        if task_number == 2 and media_id:
            raise ValueError("Only Writing Task 1 can reference a task visual")
        return {
            "task_number": task_number,
            "prompt_text": prompt_text,
            "evidence_pages": evidence_pages,
            "media_id": media_id,
            "visual_alt_text": str(payload.get("visual_alt_text") or "").strip(),
            "review_method": str(
                payload.get("review_method") or "visual_pdf_review"
            ),
            "evidence": str(payload.get("evidence") or "").strip(),
        }

    if annotation_type == "speaking_prompt_overrides":
        prompt_text = str(payload.get("prompt_text") or "").strip()
        if not prompt_text:
            raise ValueError("Speaking prompt override text cannot be empty")
        evidence_pages = sorted({
            int(value)
            for value in payload.get("evidence_pages") or []
            if int(value) > 0
        })
        if page_numbers and any(value not in page_numbers for value in evidence_pages):
            raise ValueError("Speaking override evidence page is outside the source segment")
        return {
            "prompt_text": prompt_text,
            "evidence_pages": evidence_pages,
            "review_method": str(
                payload.get("review_method") or "visual_pdf_review"
            ),
            "evidence": str(payload.get("evidence") or "").strip(),
        }

    if annotation_type == "reading_question_overrides":
        questions = payload.get("questions")
        if not isinstance(questions, dict) or not questions:
            raise ValueError("Reading question overrides require a questions map")
        clean_questions: dict[str, dict[str, Any]] = {}
        for raw_number, raw_question in questions.items():
            number = int(raw_number)
            if not 1 <= number <= 40:
                raise ValueError("Reading question numbers must be 1-40")
            item = (
                {"content": raw_question}
                if isinstance(raw_question, str)
                else dict(raw_question)
            )
            content = str(item.get("content") or "").strip()
            if not content:
                raise ValueError("Reading question override content cannot be empty")
            evidence_pages = sorted({
                int(value)
                for value in item.get("evidence_pages") or []
                if int(value) > 0
            })
            if page_numbers and any(
                value not in page_numbers for value in evidence_pages
            ):
                raise ValueError(
                    "Reading question override evidence page is outside the source segment"
                )
            clean_item: dict[str, Any] = {
                "content": content,
                "evidence_pages": evidence_pages,
                "review_method": str(
                    item.get("review_method") or "visual_pdf_review"
                ),
                "evidence": str(item.get("evidence") or "").strip(),
            }
            evidence_location = str(
                item.get("evidence_location") or ""
            ).strip()
            if evidence_location:
                if not re.fullmatch(
                    r"Paragraph (?:[A-I]|\d{1,2})",
                    evidence_location,
                ):
                    raise ValueError(
                        "Reading evidence_location must identify a paragraph"
                    )
                clean_item["evidence_location"] = evidence_location
            options = item.get("options")
            if options is not None:
                if not isinstance(options, list) or len(options) < 2:
                    raise ValueError(
                        "Reading question override options must contain at least two items"
                    )
                clean_options: list[dict[str, str]] = []
                for raw_option in options:
                    option = dict(raw_option)
                    key = str(option.get("key") or "").strip()
                    text = str(option.get("text") or "").strip()
                    if not key or not text:
                        raise ValueError(
                            "Reading question option overrides require key and text"
                        )
                    clean_options.append({"key": key, "text": text})
                clean_item["options"] = clean_options
            clean_questions[str(number)] = clean_item
        return {"questions": clean_questions}

    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Reading overrides require a non-empty groups list")
    clean_groups: list[dict[str, Any]] = []
    for raw_group in groups:
        group = dict(raw_group)
        passage_number = int(group.get("passage_number") or 0)
        start = int(group.get("question_start") or 0)
        end = int(group.get("question_end") or 0)
        question_type = str(group.get("question_type") or "").strip()
        if passage_number not in {1, 2, 3} or not (1 <= start <= end <= 40):
            raise ValueError("Reading override passage or question range is invalid")
        if not question_type:
            raise ValueError("Reading override question_type is required")
        evidence_pages = sorted({
            int(value)
            for value in group.get("evidence_pages") or []
            if int(value) > 0
        })
        if page_numbers and any(value not in page_numbers for value in evidence_pages):
            raise ValueError("Reading override evidence page is outside the source segment")
        clean_groups.append({
            "passage_number": passage_number,
            "question_start": start,
            "question_end": end,
            "question_type": question_type,
            "word_limit": group.get("word_limit"),
            "evidence_pages": evidence_pages,
            "review_method": str(
                group.get("review_method") or "visual_pdf_review"
            ),
            "evidence": str(group.get("evidence") or "").strip(),
        })
    return {"groups": clean_groups}


def update_import_page_plan(
    home: Path,
    import_id: str,
    *,
    stored_name: str,
    pages: dict[str, str],
) -> dict[str, Any]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    documents = {
        str(item.get("stored_name")): item
        for item in (job.get("summary") or {}).get("documents") or []
        if isinstance(item, dict)
    }
    document = documents.get(stored_name)
    if not document or document.get("file_kind") not in PAGE_DOCUMENT_KINDS:
        raise ValueError(
            "Page plan can only target a prepared page document in this import"
        )
    page_count = int(document.get("page_count") or 0)
    normalised: dict[str, str] = {}
    for raw_page, role in pages.items():
        try:
            page_number = int(raw_page)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid document page number: {raw_page}") from exc
        if page_number < 1 or page_number > page_count:
            raise ValueError(f"Document page number out of range: {page_number}")
        if role not in PAGE_ROLES:
            raise ValueError(f"Unsupported page role: {role}")
        normalised[str(page_number)] = role
    summary = dict(job.get("summary") or {})
    page_plan = dict(summary.get("page_plan") or {})
    page_plan[stored_name] = normalised
    summary["page_plan"] = page_plan
    _invalidate_review_draft(summary, reason="page_plan_changed")
    _write_structure_draft(home, import_id, summary)
    update_content_import_job(
        home,
        import_id,
        status=(
            "ready_for_review"
            if job["status"] == "draft_ready"
            else job["status"]
        ),
        error_message=job.get("error_message"),
        summary=summary,
    )
    return get_content_import_job(home, import_id) or {}


def recover_interrupted_imports(home: Path) -> int:
    recovered = 0
    for job in list_content_import_jobs(home, limit=500):
        if job["status"] not in PREPARATION_ACTIVE_STATUSES:
            continue
        summary = dict(job.get("summary") or {})
        if job["status"] in {"ocr_queued", "ocr_running"}:
            operation = "ocr"
            recovery_action = "retry_ocr"
            message = "The local service stopped before document OCR completed."
        elif job["status"] == "draft_building":
            operation = "review_draft"
            recovery_action = "retry_draft"
            message = "The local service stopped before the review draft completed."
        else:
            operation = "preparation"
            recovery_action = "retry_preparation"
            message = "The local service stopped before material preparation completed."
        operation_summary = dict(summary.get(operation) or {})
        operation_summary.update({
            "status": "failed",
            "progress": 0,
            "recovery_action": recovery_action,
        })
        summary[operation] = operation_summary
        update_content_import_job(
            home,
            job["import_id"],
            status="failed",
            error_message=message,
            summary=summary,
        )
        recovered += 1
    return recovered


def import_file_path(home: Path, job: dict[str, Any], stored_name: str) -> Path:
    file_record = next(
        (
            item
            for item in job.get("files") or []
            if str(item.get("stored_name")) == stored_name
        ),
        None,
    )
    if not file_record:
        raise ValueError("Unknown file in content import")
    target = (home / "corpus" / "inbox" / str(job["import_id"])).resolve()
    path = (target / stored_name).resolve()
    if path.parent != target or not path.is_file():
        raise ValueError("Content import file is missing or outside the local inbox")
    return path


def imports(home: Path, limit: int = 100) -> list[dict[str, Any]]:
    return list_content_import_jobs(home, limit=limit)


def content_storage_status(home: Path) -> dict[str, Any]:
    settings = load_settings(home)
    quota = max(
        MAX_TOTAL_BYTES,
        int(settings.get("content_inbox_quota_bytes") or 0),
    )
    used = content_import_storage_bytes(home)
    return {
        "quota_bytes": quota,
        "used_bytes": used,
        "remaining_bytes": max(0, quota - used),
        "usage_ratio": round(used / quota, 6) if quota else 1.0,
        "over_quota": used > quota,
        "max_file_bytes": MAX_FILE_BYTES,
        "max_import_bytes": MAX_TOTAL_BYTES,
    }


def delete_import(
    home: Path,
    import_id: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("Deleting a content import requires explicit confirmation")
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    if job["status"] in PREPARATION_ACTIVE_STATUSES:
        raise ValueError("An active content import cannot be deleted")
    if job["status"] == "imported":
        raise ValueError(
            "Imported corpus content must be removed through corpus governance"
        )
    inbox_root = (home / "corpus" / "inbox").resolve()
    target = (inbox_root / import_id).resolve()
    if target.parent != inbox_root or not target.is_dir():
        raise ValueError("Content import inbox is missing or outside the data home")
    staging = (inbox_root / f".deleting-{import_id}").resolve()
    if staging.parent != inbox_root or staging.exists():
        raise ValueError("Content import deletion staging path is unavailable")
    target.replace(staging)
    try:
        delete_content_import_job(home, import_id)
    except Exception:
        staging.replace(target)
        raise
    shutil.rmtree(staging)
    invalidate_storage_usage(home)
    return {
        "import_id": import_id,
        "deleted": True,
        "released_bytes": sum(
            int(item.get("size_bytes") or 0)
            for item in job.get("files") or []
        ),
    }


def delete_imports(
    home: Path,
    import_ids: list[str],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("Deleting content imports requires explicit confirmation")
    unique_ids = list(dict.fromkeys(import_ids))
    if not unique_ids:
        raise ValueError("Select at least one content import")
    if len(unique_ids) > 100:
        raise ValueError("At most 100 content imports can be deleted at once")
    deleted: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for import_id in unique_ids:
        try:
            deleted.append(delete_import(home, import_id, confirmed=confirmed))
        except Exception as exc:
            failed.append({"import_id": import_id, "error": str(exc)})
    return {
        "deleted": deleted,
        "failed": failed,
        "storage": content_storage_status(home),
    }


def _safe_name(value: str) -> str:
    original = Path(value.replace("\\", "/")).name.strip()
    if not original:
        raise ValueError("Invalid file name")
    suffix = Path(original).suffix.casefold()
    stem = original[: -len(suffix)] if suffix else original
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")
    if not safe_stem:
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:10]
        safe_stem = f"file-{digest}"
    safe_suffix = re.sub(r"[^a-z0-9.]+", "", suffix)
    max_stem = max(1, 180 - len(safe_suffix))
    return f"{safe_stem[:max_stem]}{safe_suffix}"


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
    if suffix in {".txt", ".md"}:
        return "text"
    if suffix == ".docx":
        return "document"
    if suffix in {".mp3", ".wav", ".m4a"}:
        return "audio"
    return "image"


def _extract_document_text(path: Path, suffix: str) -> tuple[str, str]:
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, "text_available" if text.strip() else "text_unavailable"
    if suffix == ".docx":
        xml = read_zip_member(path, "word/document.xml")
        root = ElementTree.fromstring(xml)
        text = "\n".join(
            item.text or ""
            for item in root.iter()
            if item.tag.endswith("}t")
        )
        return text, "text_available" if text.strip() else "text_unavailable"
    return "", "text_unavailable"


def _analyse_pdf(path: Path, stored_name: str) -> dict[str, Any]:
    document, _ = _analyse_pdf_with_text(path, stored_name)
    return document


def _analyse_pdf_with_text(
    path: Path,
    stored_name: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF preparation requires the UI dependency pypdf. "
            "Reinstall with: pip install 'ielts-ai-coach[ui]'"
        ) from exc

    reader = PdfReader(str(path), strict=False)
    encrypted = bool(reader.is_encrypted)
    if encrypted and reader.decrypt("") == 0:
        return {
            "stored_name": stored_name,
            "file_kind": "pdf",
            "status": "password_required",
            "encrypted": True,
            "password_required": True,
            "security_status": "password_required",
            "page_count": 0,
            "needs_ocr_pages": 0,
            "metadata": {},
            "pages": [],
        }, {}
    metadata = {
        str(key).lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
        if value not in (None, "")
    }
    pages: list[dict[str, Any]] = []
    page_text: dict[str, dict[str, Any]] = {}
    needs_ocr_pages = 0
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
            extraction_error = None
        except Exception as exc:
            text = ""
            extraction_error = str(exc)
        compact = re.sub(r"\s+", " ", text).strip()
        needs_ocr = not _has_meaningful_page_text(compact)
        if needs_ocr:
            needs_ocr_pages += 1
        pages.append({
            "page_number": index,
            "text_chars": len(compact),
            "text_preview": compact[:360],
            "extraction_status": (
                "error" if extraction_error else "ocr_required" if needs_ocr else "text_available"
            ),
            "error": extraction_error,
        })
        page_text[str(index)] = {
            "text": text.strip(),
            "source": "pdf_text" if compact else "none",
            "confidence": 1.0 if compact else None,
            "text_hash": _text_hash(text.strip()),
            "updated_at": _now(),
        }
    return {
        "stored_name": stored_name,
        "file_kind": "pdf",
        "status": "prepared",
        "encrypted": encrypted,
        "password_required": False,
        "security_status": (
            "empty_password_permissions" if encrypted else "not_encrypted"
        ),
        "page_count": len(pages),
        "needs_ocr_pages": needs_ocr_pages,
        "metadata": metadata,
        "pages": pages,
    }, page_text


def _has_meaningful_page_text(text: str) -> bool:
    """Reject blank and watermark-only extraction without judging page content."""
    substantive = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text.casefold())
    if len(substantive) < 24:
        return False
    unique_characters = len(set(substantive))
    if len(substantive) < 120 and unique_characters < 12:
        return False
    return unique_characters >= 8


def _apply_page_text_to_document(
    document: dict[str, Any],
    text_records: dict[str, dict[str, Any]],
) -> None:
    needs_ocr_pages = 0
    for page in document.get("pages") or []:
        page_number = str(page["page_number"])
        record = text_records.get(page_number) or {}
        text = str(record.get("text") or "")
        compact = re.sub(r"\s+", " ", text).strip()
        source = str(record.get("source") or "pdf_text")
        usable_text = bool(compact) and (
            source == "ocr" or _has_meaningful_page_text(compact)
        )
        if usable_text:
            page["text_chars"] = len(compact)
            page["text_preview"] = compact[:360]
            page["extraction_status"] = (
                "ocr_available" if source == "ocr" else "text_available"
            )
            page["text_source"] = source
            page["ocr_confidence"] = (
                record.get("confidence") if source == "ocr" else None
            )
            page["error"] = None
        else:
            page["extraction_status"] = "ocr_required"
            page["text_source"] = "unreliable_pdf_text" if compact else "none"
            page["ocr_confidence"] = None
            needs_ocr_pages += 1
    document["needs_ocr_pages"] = needs_ocr_pages


def _prepared_ocr_document(
    job: dict[str, Any], stored_name: str
) -> dict[str, Any]:
    document = next(
        (
            item
            for item in (job.get("summary") or {}).get("documents") or []
            if item.get("stored_name") == stored_name
        ),
        None,
    )
    if not document or document.get("file_kind") not in OCR_DOCUMENT_KINDS:
        raise ValueError(
            "OCR can only target a prepared PDF or image in this import"
        )
    if document.get("status") == "password_required":
        raise ValueError("The selected PDF requires a password")
    return document


def _read_page_text_store(home: Path, import_id: str) -> dict[str, Any]:
    path = _import_sidecar_path(home, import_id, "page-text.json")
    if not path.is_file():
        return {
            "page_text_version": PAGE_TEXT_VERSION,
            "import_id": import_id,
            "documents": {},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("page_text_version") != PAGE_TEXT_VERSION:
        raise ValueError("Unsupported page text sidecar version")
    return payload


def _write_page_text_store(
    home: Path,
    import_id: str,
    payload: dict[str, Any],
) -> None:
    payload["page_text_version"] = PAGE_TEXT_VERSION
    payload["import_id"] = import_id
    payload["updated_at"] = _now()
    _write_json_atomic(
        _import_sidecar_path(home, import_id, "page-text.json"),
        payload,
    )


def _page_role_groups(page_plan: dict[str, str]) -> list[dict[str, Any]]:
    planned = sorted(
        (
            (int(page), role)
            for page, role in page_plan.items()
            if role not in {"unassigned", "exclude"}
        ),
        key=lambda item: item[0],
    )
    groups: list[dict[str, Any]] = []
    mergeable_roles = {
        "passage",
        "reading_test",
        "reading_passage",
        "writing_task_2_with_task_1_visual",
        "answer_key",
        "transcript",
        "instructions",
    }
    for page, role in planned:
        if (
            groups
            and role in mergeable_roles
            and groups[-1]["role"] == role
            and groups[-1]["pages"][-1] + 1 == page
        ):
            groups[-1]["pages"].append(page)
        else:
            groups.append({"role": role, "pages": [page]})
    return groups


def _build_typed_drafts(
    segments: list[dict[str, Any]],
    annotations: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    annotations = annotations or {}
    typed: dict[str, list[dict[str, Any]]] = {
        "passage_drafts": [],
        "question_drafts": [],
        "reading_test_drafts": [],
        "writing_task_drafts": [],
        "speaking_test_drafts": [],
        "answer_key_drafts": [],
        "task_visual_drafts": [],
        "transcript_drafts": [],
        "instruction_drafts": [],
    }
    for segment in segments:
        source = {
            "segment_id": segment["segment_id"],
            "stored_name": segment["stored_name"],
            "page_numbers": segment["page_numbers"],
            "source_file_sha256": segment["source_file_sha256"],
            "layout_pages": list(segment.get("layout_pages") or []),
        }
        common = {
            **source,
            "review_status": "needs_review",
            "eligible_for_import": False,
        }
        role = segment["role"]
        if role == "reading_test":
            reading = _build_reading_test_draft(segment["text"], common)
            typed["reading_test_drafts"].append(
                _apply_reading_group_overrides(
                    reading,
                    (
                        annotations.get("reading_group_overrides") or {}
                    ).get(segment["segment_id"]),
                )
            )
        elif role in {"passage", "reading_passage"}:
            typed["passage_drafts"].append({
                **common,
                "module": "reading",
                "passage_id": None,
                "title": None,
                "body_text": segment["text"],
                "needs_paragraph_labelling": True,
            })
        elif role in {"questions", "reading_questions"}:
            questions = _split_question_drafts(segment["text"], common)
            for question in questions:
                question["module"] = "reading"
            typed["question_drafts"].extend(questions)
        elif role in {"writing_task_1", "writing_task_2"}:
            task_number = 1 if role == "writing_task_1" else 2
            typed["writing_task_drafts"].append(
                _apply_writing_prompt_override(
                    _build_writing_task_draft(
                        segment["text"],
                        common,
                        task_number=task_number,
                    ),
                    (
                        annotations.get("writing_prompt_overrides") or {}
                    ).get(segment["segment_id"]),
                )
            )
        elif role == "answer_key_with_writing_task_1":
            answer_key = _build_answer_key_draft(segment["text"], common)
            answer_key = _apply_answer_key_overrides(
                answer_key,
                (
                    annotations.get("answer_key_overrides") or {}
                ).get(segment["segment_id"]),
            )
            answer_key["needs_manual_text_split"] = True
            typed["answer_key_drafts"].append(answer_key)
            writing = _apply_writing_prompt_override(
                _build_writing_task_draft(
                    segment["text"],
                    common,
                    task_number=1,
                ),
                (
                    annotations.get("writing_prompt_overrides") or {}
                ).get(segment["segment_id"]),
            )
            writing["needs_manual_text_split"] = True
            typed["writing_task_drafts"].append(writing)
        elif role == "writing_task_2_with_task_1_visual":
            writing = _apply_writing_prompt_override(
                _build_writing_task_draft(
                    segment["text"],
                    common,
                    task_number=2,
                ),
                (
                    annotations.get("writing_prompt_overrides") or {}
                ).get(segment["segment_id"]),
            )
            writing["needs_manual_text_split"] = True
            typed["writing_task_drafts"].append(writing)
            typed["task_visual_drafts"].append({
                **common,
                "alt_text": segment["text"],
                "media_id": None,
                "needs_visual_registration": True,
                "needs_manual_text_split": True,
            })
        elif role in {"speaking_test", "speaking_test_with_sample_answers"}:
            speaking = _apply_speaking_prompt_override(
                _build_speaking_test_draft(segment["text"], common),
                (
                    annotations.get("speaking_prompt_overrides") or {}
                ).get(segment["segment_id"]),
            )
            if role == "speaking_test_with_sample_answers":
                speaking["needs_manual_text_split"] = True
                speaking["contains_sample_answers"] = True
            typed["speaking_test_drafts"].append(speaking)
        elif role == "answer_key":
            answer_key = _build_answer_key_draft(segment["text"], common)
            typed["answer_key_drafts"].append(
                _apply_answer_key_overrides(
                    answer_key,
                    (
                        annotations.get("answer_key_overrides") or {}
                    ).get(segment["segment_id"]),
                )
            )
        elif role == "task_visual":
            typed["task_visual_drafts"].append({
                **common,
                "alt_text": segment["text"],
                "media_id": None,
                "needs_visual_registration": True,
            })
        elif role == "transcript":
            typed["transcript_drafts"].append({
                **common,
                "raw_text": segment["text"],
                "timestamped_cues": [],
                "needs_timestamp_review": True,
            })
        elif role == "instructions":
            typed["instruction_drafts"].append({
                **common,
                "raw_text": segment["text"],
            })
    return typed


def _build_writing_task_draft(
    text: str,
    common: dict[str, Any],
    *,
    task_number: int,
) -> dict[str, Any]:
    minimum_words = 150 if task_number == 1 else 250
    marker_checks = _writing_prompt_marker_checks(text, task_number)
    return {
        **common,
        "module": "writing",
        "task_number": task_number,
        "raw_prompt": text,
        "minimum_words": minimum_words,
        "recommended_minutes": 20 if task_number == 1 else 40,
        "needs_visual_review": task_number == 1,
        "media_id": None,
        "prompt_marker_checks": marker_checks,
        "passes_marker_check": all(marker_checks.values()),
        "needs_prompt_review": True,
    }


def _writing_prompt_marker_checks(
    text: str,
    task_number: int,
) -> dict[str, bool]:
    minimum_words = 150 if task_number == 1 else 250
    compact = re.sub(r"\s+", "", text).lower()
    return {
        "task_marker": bool(
            re.search(
                rf"(?i)\bWRITING[\s-]*TASK\s*{task_number}\b",
                text,
            )
        ),
        "minimum_word_marker": (
            f"atleast{minimum_words}words" in compact
            or f"atleast{minimum_words}word" in compact
        ),
    }


def _build_speaking_test_draft(
    text: str,
    common: dict[str, Any],
) -> dict[str, Any]:
    official_text, sample_text = _split_speaking_sample_answers(text)
    detected_parts = {
        int(value)
        for value in re.findall(
            r"(?i)\bPART\s*([123])\b",
            official_text,
        )
    }
    compact = re.sub(r"\s+", "", official_text).lower()
    if (
        1 not in detected_parts
        and "pleaseanswerthequestions1-4" in compact
        and {2, 3}.issubset(detected_parts)
    ):
        detected_parts.add(1)
    ordered_parts = sorted(detected_parts)
    parts = _split_speaking_parts(official_text)
    return {
        **common,
        "module": "speaking",
        "raw_text": text,
        "official_prompt_text": official_text,
        "sample_answer_text": sample_text or None,
        "parts": parts,
        "detected_parts": ordered_parts,
        "expected_parts": [1, 2, 3],
        "passes_marker_check": (
            ordered_parts == [1, 2, 3]
            and [item["part_number"] for item in parts] == [1, 2, 3]
        ),
        "needs_part_split": False,
        "needs_question_review": True,
        "mock_policy": {
            "correction_during_mock": False,
            "part_2_preparation_seconds": 60,
            "part_2_response_seconds": [60, 120],
        },
    }


def _split_speaking_sample_answers(text: str) -> tuple[str, str]:
    markers = (
        r"(?m)^\s*答案[:：]?",
        r"(?im)^\s*sample\s+answers?\b",
        r"(?m)^\s*参考答案[:：]?",
    )
    matches = [
        match
        for pattern in markers
        if (match := re.search(pattern, text))
    ]
    if not matches:
        return text.strip(), ""
    marker = min(matches, key=lambda item: item.start())
    return text[:marker.start()].strip(), text[marker.start():].strip()


def _split_speaking_parts(text: str) -> list[dict[str, Any]]:
    offsets: dict[int, int] = {}
    for match in re.finditer(
        r"(?i)\b(?:TEST\s*\d+\s*[-–—]\s*)?PART\s*([123])\b",
        text,
    ):
        offsets.setdefault(int(match.group(1)), match.start())
    if 1 not in offsets and 2 in offsets:
        prefix = text[:offsets[2]].strip()
        compact_prefix = re.sub(r"\s+", "", prefix).lower()
        if (
            re.search(r"(?i)questions?\s*1\s*[-–—]\s*4", prefix)
            or "pleaseanswerthequestions1-4" in compact_prefix
        ):
            offsets[1] = 0
    if set(offsets) != {1, 2, 3}:
        return []
    ordered = sorted(offsets.items())
    parts: list[dict[str, Any]] = []
    for index, (part_number, start) in enumerate(ordered):
        end = ordered[index + 1][1] if index + 1 < len(ordered) else len(text)
        raw_text = text[start:end].strip()
        questions = _speaking_questions(raw_text)
        cue_card = (
            _speaking_cue_card(raw_text)
            if part_number == 2
            else None
        )
        parts.append({
            "part_number": part_number,
            "raw_text": raw_text,
            "questions": questions,
            "detected_question_count": len(questions),
            "cue_card": cue_card,
            "review_status": "needs_review",
            "correction_during_mock": False,
        })
    return parts


def _speaking_cue_card(text: str) -> dict[str, Any] | None:
    lines = [
        re.sub(r"^[\s·•*-]+", "", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    content_lines = [
        line
        for line in lines
        if not re.fullmatch(
            r"(?i)(?:TEST\s*\d+\s*[-–—]\s*)?PART\s*2",
            line,
        )
        and "pleaseanswerthequestion" not in re.sub(
            r"[^a-z]+",
            "",
            line.lower(),
        )
    ]
    if not content_lines:
        return None

    marker_index = next(
        (
            index
            for index, line in enumerate(content_lines)
            if re.sub(r"[^a-z]+", "", line.lower()) == "youshouldsay"
        ),
        None,
    )
    if marker_index is None:
        topic_lines = content_lines
        prompt_lines: list[str] = []
    else:
        topic_lines = content_lines[:marker_index]
        prompt_lines = content_lines[marker_index + 1:]

    topic = " ".join(topic_lines).strip()
    prompts = [
        re.sub(r"\s+", " ", line).strip()
        for line in prompt_lines
        if line.strip()
    ]
    if not topic:
        return None
    return {
        "topic": re.sub(r"\s+", " ", topic),
        "prompts": prompts,
        "detected_prompt_count": len(prompts),
        "passes_marker_check": bool(topic) and len(prompts) >= 2,
    }


def _speaking_questions(text: str) -> list[str]:
    lines = [
        re.sub(r"^[\s·•*-]+", "", line).strip()
        for line in text.splitlines()
    ]
    questions: list[str] = []
    current = ""
    for line in lines:
        if not line:
            continue
        if current:
            current = f"{current} {line}".strip()
            if "?" in line:
                questions.append(current)
                current = ""
            continue
        if "?" not in line:
            continue
        start = re.sub(r"^\d+[.)]\s*", "", line).strip()
        questions.append(start)
    return questions


def _apply_writing_prompt_override(
    draft: dict[str, Any],
    annotation: dict[str, Any] | None,
) -> dict[str, Any]:
    if not annotation:
        return draft
    if int(annotation.get("task_number") or 0) != int(draft["task_number"]):
        return draft
    draft["reviewed_prompt_text"] = str(annotation["prompt_text"]).strip()
    draft["prompt_review_status"] = (
        "visually_confirmed"
        if annotation.get("review_method") == "visual_pdf_review"
        else "source_text_reviewed"
    )
    draft["needs_prompt_review"] = False
    marker_checks = _writing_prompt_marker_checks(
        draft["reviewed_prompt_text"],
        int(draft["task_number"]),
    )
    draft["reviewed_prompt_marker_checks"] = marker_checks
    draft["reviewed_prompt_passes_marker_check"] = all(marker_checks.values())
    draft["review_evidence_pages"] = list(annotation.get("evidence_pages") or [])
    draft["review_method"] = annotation.get("review_method")
    draft["review_evidence"] = annotation.get("evidence")
    if int(draft["task_number"]) == 1 and annotation.get("media_id"):
        draft["media_id"] = annotation["media_id"]
        draft["needs_visual_review"] = False
        draft["visual_review_status"] = "registered_local_private"
        draft["visual_alt_text"] = annotation.get("visual_alt_text") or (
            "IELTS Academic Writing Task 1 source visual"
        )
    return draft


def _apply_speaking_prompt_override(
    draft: dict[str, Any],
    annotation: dict[str, Any] | None,
) -> dict[str, Any]:
    if not annotation:
        return draft
    prompt_text = str(annotation["prompt_text"]).strip()
    reviewed = _build_speaking_test_draft(prompt_text, {})
    for key in (
        "official_prompt_text",
        "parts",
        "detected_parts",
        "expected_parts",
        "passes_marker_check",
        "needs_part_split",
    ):
        draft[key] = reviewed[key]
    draft["reviewed_prompt_text"] = prompt_text
    draft["prompt_review_status"] = (
        "visually_confirmed"
        if annotation.get("review_method") == "visual_pdf_review"
        else "source_text_reviewed"
    )
    draft["needs_question_review"] = False
    draft["review_evidence_pages"] = list(annotation.get("evidence_pages") or [])
    draft["review_method"] = annotation.get("review_method")
    draft["review_evidence"] = annotation.get("evidence")
    return draft


def _answer_key_numbers(text: str) -> set[int]:
    return {
        int(value)
        for value in re.findall(r"(?<!\d)([1-9]|[1-3]\d|40)(?!\d)", text)
    }


def _build_answer_key_draft(
    text: str,
    common: dict[str, Any],
) -> dict[str, Any]:
    answer_numbers = _answer_key_numbers(text)
    layout_candidates = _layout_answer_candidates(common.get("layout_pages") or [])
    candidate_numbers = {
        int(item["question_number"])
        for item in layout_candidates["answers"]
    }
    return {
        **common,
        "raw_text": text,
        "linked_question_ids": [],
        "needs_answer_mapping": True,
        "detected_answer_numbers": sorted(answer_numbers),
        "missing_answer_numbers": sorted(set(range(1, 41)) - answer_numbers),
        "passes_marker_check": answer_numbers.issuperset(range(1, 41)),
        "layout_answer_candidates": layout_candidates["answers"],
        "layout_duplicate_numbers": layout_candidates["duplicate_numbers"],
        "layout_missing_numbers": sorted(set(range(1, 41)) - candidate_numbers),
    }


def _apply_answer_key_overrides(
    draft: dict[str, Any],
    annotation: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_overrides = (annotation or {}).get("answers") or {}
    overrides = [
        {
            "question_number": int(number),
            **dict(value),
            "confidence": "visually_confirmed",
        }
        for number, value in raw_overrides.items()
    ]
    overrides.sort(key=lambda item: int(item["question_number"]))
    override_numbers = {
        int(item["question_number"])
        for item in overrides
    }
    candidate_numbers = {
        int(item["question_number"])
        for item in draft.get("layout_answer_candidates") or []
    }
    unresolved = sorted(
        set(range(1, 41)) - candidate_numbers - override_numbers
    )
    unresolved_duplicates = sorted(
        set(int(value) for value in draft.get("layout_duplicate_numbers") or [])
        - override_numbers
    )
    draft["reviewed_answer_overrides"] = overrides
    draft["unresolved_answer_numbers"] = unresolved
    draft["unresolved_duplicate_numbers"] = unresolved_duplicates
    draft["candidate_answer_mapping_complete"] = (
        not unresolved and not unresolved_duplicates
    )
    return draft


def _layout_answer_candidates(
    layout_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    answers: list[dict[str, Any]] = []
    counts: dict[int, int] = {}
    for page in layout_pages:
        lines: list[dict[str, Any]] = []
        for item in page.get("lines") or []:
            box = item.get("box") or []
            if len(box) != 4:
                continue
            try:
                x = sum(float(point[0]) for point in box) / 4
                y = sum(float(point[1]) for point in box) / 4
            except (TypeError, ValueError, IndexError):
                continue
            lines.append({
                "text": str(item.get("text") or "").strip(),
                "x": x,
                "y": y,
            })
        lines.sort(key=lambda item: (item["y"], item["x"]))
        for number_line in lines:
            if not re.fullmatch(r"(?:[1-9]|[1-3]\d|40)", number_line["text"]):
                continue
            question_number = int(number_line["text"])
            counts[question_number] = counts.get(question_number, 0) + 1
            candidates = [
                item
                for item in lines
                if item["x"] > number_line["x"] + 18
                and item["x"] < number_line["x"] + 480
                and abs(item["y"] - number_line["y"]) <= 13
                and item["text"]
                and not re.fullmatch(r"\d{1,2}", item["text"])
            ]
            if not candidates:
                continue
            answer = min(candidates, key=lambda item: item["x"])
            if re.search(r"(?i)\b(?:QUESTIONS?|PASSAGE|ORDER|REQUIRED)\b", answer["text"]):
                continue
            answers.append({
                "question_number": question_number,
                "answer_text": answer["text"],
                "page_number": int(page["page_number"]),
                "confidence": "layout_row_candidate",
            })
        for combined_line in lines:
            match = re.fullmatch(
                r"([1-9]|[1-3]\d|40)\s*([A-Za-z(].+)",
                combined_line["text"],
            )
            if not match:
                continue
            question_number = int(match.group(1))
            answer_text = match.group(2).strip()
            if re.search(
                r"(?i)\b(?:QUESTIONS?|PASSAGE|ORDER|REQUIRED)\b",
                answer_text,
            ):
                continue
            counts[question_number] = counts.get(question_number, 0) + 1
            answers.append({
                "question_number": question_number,
                "answer_text": answer_text,
                "page_number": int(page["page_number"]),
                "confidence": "layout_inline_candidate",
            })
        for pair_line in lines:
            dense = re.sub(r"\s+", "", pair_line["text"]).upper()
            match = re.fullmatch(
                r"([1-3]?\d)&([1-3]?\d)(?:INEITHERORDER)?",
                dense,
            )
            if not match:
                continue
            start_number = int(match.group(1))
            end_number = int(match.group(2))
            if not (1 <= start_number < end_number <= 40):
                continue
            pair_answers = [
                item
                for item in lines
                if pair_line["y"] < item["y"] <= pair_line["y"] + 70
                and pair_line["x"] - 190 <= item["x"] <= pair_line["x"] + 190
                and item["text"]
                and not re.fullmatch(r"\d{1,2}", item["text"])
                and not re.search(
                    r"(?i)\b(?:QUESTIONS?|PASSAGE|ORDER|REQUIRED)\b",
                    item["text"],
                )
            ]
            pair_answers.sort(key=lambda item: (item["y"], item["x"]))
            if len(pair_answers) < end_number - start_number + 1:
                continue
            for offset, question_number in enumerate(
                range(start_number, end_number + 1)
            ):
                counts[question_number] = counts.get(question_number, 0) + 1
                answers.append({
                    "question_number": question_number,
                    "answer_text": pair_answers[offset]["text"],
                    "page_number": int(page["page_number"]),
                    "confidence": "layout_pair_order_candidate",
                    "either_order_group": list(
                        range(start_number, end_number + 1)
                    ),
                })
    return {
        "answers": sorted(
            answers,
            key=lambda item: (
                int(item["question_number"]),
                str(item["confidence"]),
            ),
        ),
        "duplicate_numbers": sorted(
            number for number, count in counts.items() if count > 1
        ),
    }


def _apply_reading_group_overrides(
    draft: dict[str, Any],
    annotation: dict[str, Any] | None,
) -> dict[str, Any]:
    overrides = list((annotation or {}).get("groups") or [])
    if not overrides:
        return draft
    for passage in draft.get("passages") or []:
        passage_number = int(passage.get("passage_number") or 0)
        passage_overrides = [
            item
            for item in overrides
            if int(item.get("passage_number") or 0) == passage_number
        ]
        if not passage_overrides:
            continue
        overridden_numbers = {
            number
            for item in passage_overrides
            for number in range(
                int(item["question_start"]),
                int(item["question_end"]) + 1,
            )
        }
        groups = [
            group
            for group in passage.get("question_groups") or []
            if not overridden_numbers.intersection(group.get("question_numbers") or [])
        ]
        for item in passage_overrides:
            start = int(item["question_start"])
            end = int(item["question_end"])
            groups.append({
                "question_start": start,
                "question_end": end,
                "question_numbers": list(range(start, end + 1)),
                "question_type": item["question_type"],
                "word_limit": item.get("word_limit"),
                "raw_text": "",
                "needs_question_split": True,
                "needs_answer_mapping": True,
                "visually_confirmed_structure": True,
                "evidence_pages": item.get("evidence_pages") or [],
                "review_method": item.get("review_method"),
                "evidence": item.get("evidence"),
            })
        groups.sort(
            key=lambda group: (
                int(group["question_start"]),
                int(group["question_end"]),
            )
        )
        numbers = sorted({
            number
            for group in groups
            for number in group.get("question_numbers") or []
        })
        passage["question_groups"] = groups
        passage["detected_question_numbers"] = numbers
        passage["detected_question_types"] = sorted({
            str(group["question_type"])
            for group in groups
            if group.get("question_type") != "unknown"
        })
    detected_numbers = sorted({
        number
        for passage in draft.get("passages") or []
        for number in passage.get("detected_question_numbers") or []
    })
    missing = sorted(set(range(1, 41)) - set(detected_numbers))
    draft["detected_question_numbers"] = detected_numbers
    draft["detected_question_number_count"] = len(detected_numbers)
    draft["missing_question_numbers"] = missing
    draft["passes_marker_check"] = (
        int(draft.get("detected_passage_count") or 0) == 3
        and not missing
    )
    draft["manual_structure_overrides_applied"] = len(overrides)
    return draft


def _build_reading_test_draft(
    text: str,
    common: dict[str, Any],
) -> dict[str, Any]:
    passage_matches: dict[int, re.Match[str]] = {}
    for match in re.finditer(
        r"(?i)\bREADING[\s-]*PASSAGE\s*([123])\b",
        text,
    ):
        passage_number = int(match.group(1))
        passage_matches.setdefault(passage_number, match)

    ordered = sorted(passage_matches.items())
    passages: list[dict[str, Any]] = []
    detected_numbers: set[int] = set()
    for index, (passage_number, match) in enumerate(ordered):
        end = ordered[index + 1][1].start() if index + 1 < len(ordered) else len(text)
        raw_section = text[match.start():end].strip()
        minimum_question_number = (
            1 if passage_number == 1 else 14 if passage_number == 2 else 27
        )
        maximum_question_number = (
            13 if passage_number == 1 else 26 if passage_number == 2 else 40
        )
        section_numbers = _question_numbers_from_instructions(
            raw_section,
            minimum_question_number=minimum_question_number,
            maximum_question_number=maximum_question_number,
        )
        question_groups = _reading_question_groups(
            raw_section,
            minimum_question_number=minimum_question_number,
            maximum_question_number=maximum_question_number,
        )
        covered_numbers = {
            number
            for group in question_groups
            for number in group["question_numbers"]
        }
        question_groups.extend(
            _unheaded_reading_question_groups(
                raw_section,
                covered_numbers,
                minimum_question_number=minimum_question_number,
                maximum_question_number=maximum_question_number,
            )
        )
        question_groups.sort(
            key=lambda group: (
                int(group["question_start"]),
                int(group["question_end"]),
            )
        )
        section_numbers.update(
            number
            for group in question_groups
            for number in group["question_numbers"]
        )
        detected_numbers.update(section_numbers)
        passages.append({
            "passage_number": passage_number,
            "raw_section": raw_section,
            "detected_question_numbers": sorted(section_numbers),
            "question_groups": question_groups,
            "detected_question_types": sorted({
                group["question_type"]
                for group in question_groups
                if group["question_type"] != "unknown"
            }),
            "needs_passage_question_split": True,
        })

    missing = sorted(set(range(1, 41)) - detected_numbers)
    return {
        **common,
        "module": "reading",
        "raw_text": text,
        "passages": passages,
        "detected_passage_count": len(passages),
        "expected_passage_count": 3,
        "detected_question_numbers": sorted(detected_numbers),
        "detected_question_number_count": len(detected_numbers),
        "expected_question_count": 40,
        "missing_question_numbers": missing,
        "passes_marker_check": len(passages) == 3 and not missing,
        "needs_structural_review": True,
        "answer_key_segment_ids": [],
    }


def _question_numbers_from_instructions(
    text: str,
    *,
    minimum_question_number: int = 1,
    maximum_question_number: int = 40,
) -> set[int]:
    numbers: set[int] = set()
    for _, start, end in _reading_question_header_matches(
        text,
        minimum_question_number=minimum_question_number,
        maximum_question_number=maximum_question_number,
    ):
        numbers.update(range(start, end + 1))
    return numbers


def _reading_question_groups(
    text: str,
    *,
    minimum_question_number: int = 1,
    maximum_question_number: int = 40,
) -> list[dict[str, Any]]:
    matches = _reading_question_header_matches(
        text,
        minimum_question_number=minimum_question_number,
        maximum_question_number=maximum_question_number,
    )
    groups: list[dict[str, Any]] = []
    covered_ranges: set[tuple[int, int]] = set()
    effective_matches: list[tuple[re.Match[str], int, int]] = []
    for match, start_number, end_number in matches:
        question_range = (start_number, end_number)
        if question_range in covered_ranges:
            continue
        if any(
            prior_start <= start_number and end_number <= prior_end
            for prior_start, prior_end in covered_ranges
        ):
            continue
        covered_ranges.add(question_range)
        effective_matches.append((match, start_number, end_number))
    for index, (match, start_number, end_number) in enumerate(effective_matches):
        end = (
            effective_matches[index + 1][0].start()
            if index + 1 < len(effective_matches)
            else len(text)
        )
        raw_text = text[match.start():end].strip()
        groups.append({
            "question_start": start_number,
            "question_end": end_number,
            "question_numbers": list(range(start_number, end_number + 1)),
            "question_type": _infer_reading_question_type(raw_text),
            "word_limit": _reading_word_limit(raw_text),
            "raw_text": raw_text,
            "needs_question_split": True,
            "needs_answer_mapping": True,
        })
    return groups


def _reading_question_header_matches(
    text: str,
    *,
    minimum_question_number: int,
    maximum_question_number: int,
) -> list[tuple[re.Match[str], int, int]]:
    """Return explicit or OCR-compacted IELTS Reading question headings.

    English OCR commonly removes the dash from headings such as
    ``Questions 18-22`` and returns ``Questions 1822``.  A compact token is
    split only when it has one unambiguous interpretation inside the current
    passage's legal question range.  The standard whole-passage timing
    instruction is excluded because it is not a question group.
    """

    pattern = re.compile(
        r"(?i)\b(Questions?)\s*(\d{1,4})"
        r"(?:\s*(?:[-–—]|and)\s*(\d{1,2}))?"
    )
    results: list[tuple[re.Match[str], int, int]] = []
    for match in pattern.finditer(text):
        following = re.sub(
            r"\s+",
            "",
            text[match.end():match.end() + 160],
        ).lower()
        if "whicharebasedonreadingpassage" in following:
            continue

        token = match.group(2)
        explicit_end = match.group(3)
        if explicit_end is not None:
            question_range = (int(token), int(explicit_end))
        else:
            value = int(token)
            question_range = (value, value)
            if not (
                minimum_question_number
                <= value
                <= maximum_question_number
            ):
                compact = _split_compact_question_range(
                    token,
                    minimum_question_number=minimum_question_number,
                    maximum_question_number=maximum_question_number,
                )
                if compact is None or match.group(1).lower() == "question":
                    continue
                question_range = compact

        start_number, end_number = question_range
        if not (
            minimum_question_number
            <= start_number
            <= end_number
            <= maximum_question_number
        ):
            continue
        results.append((match, start_number, end_number))
    return results


def _split_compact_question_range(
    token: str,
    *,
    minimum_question_number: int,
    maximum_question_number: int,
) -> tuple[int, int] | None:
    candidates: list[tuple[int, int]] = []
    for split_at in range(1, len(token)):
        start_text = token[:split_at]
        end_text = token[split_at:]
        if (
            start_text.startswith("0")
            or end_text.startswith("0")
        ):
            continue
        start_number = int(start_text)
        end_number = int(end_text)
        if (
            minimum_question_number
            <= start_number
            < end_number
            <= maximum_question_number
            and end_number - start_number <= 12
        ):
            candidates.append((start_number, end_number))
    return candidates[0] if len(candidates) == 1 else None


def _unheaded_reading_question_groups(
    text: str,
    covered_numbers: set[int],
    *,
    minimum_question_number: int = 1,
    maximum_question_number: int = 40,
) -> list[dict[str, Any]]:
    matches = [
        match
        for match in re.finditer(
            r"(?m)^\s*([1-9]|[1-3]\d|40)(?:\s*[.)]|\s+|$)",
            text,
        )
        if minimum_question_number <= int(match.group(1)) <= maximum_question_number
        and int(match.group(1)) not in covered_numbers
    ]
    if not matches:
        return []
    unique: dict[int, re.Match[str]] = {}
    for match in matches:
        unique.setdefault(int(match.group(1)), match)
    ordered_numbers = sorted(unique)
    runs: list[list[int]] = []
    for number in ordered_numbers:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])

    groups: list[dict[str, Any]] = []
    for run in runs:
        if len(run) < 2:
            continue
        start_number, end_number = run[0], run[-1]
        start_pos = unique[start_number].start()
        end_pos = unique[end_number].end()
        local_text = text[max(0, start_pos - 900):min(len(text), end_pos + 900)]
        groups.append({
            "question_start": start_number,
            "question_end": end_number,
            "question_numbers": run,
            "question_type": _nearest_unheaded_question_type(
                text,
                start_pos=start_pos,
                fallback_text=local_text,
            ),
            "word_limit": _reading_word_limit(local_text),
            "raw_text": local_text.strip(),
            "needs_question_split": True,
            "needs_answer_mapping": True,
            "inferred_from_numbered_layout": True,
        })
    return groups


def _nearest_unheaded_question_type(
    text: str,
    *,
    start_pos: int,
    fallback_text: str,
) -> str:
    markers = (
        (r"(?i)complete\s+each\s+sentence\s+with\s+the\s+correct\s+ending", "matching_sentence_endings"),
        (r"(?i)complete\s+the\s+sentences", "sentence_completion"),
        (r"(?i)choose\s+the\s+correct\s+heading", "matching_headings"),
        (r"(?i)list\s+of\s+headings", "matching_headings"),
        (r"(?i)look\s+at\s+the\s+following\s+statements", "matching_features"),
    )
    candidates: list[tuple[int, str]] = []
    for pattern, question_type in markers:
        for match in re.finditer(pattern, text):
            candidates.append((abs(match.start() - start_pos), question_type))
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return _infer_reading_question_type(fallback_text)


def _infer_reading_question_type(text: str) -> str:
    dense = re.sub(r"[^a-z0-9]+", "", text.lower())
    if "true" in dense and "false" in dense and "notgiven" in dense:
        return "true_false_not_given"
    if "yes" in dense and "no" in dense and "notgiven" in dense:
        return "yes_no_not_given"
    if "correctheading" in dense or "listofheadings" in dense:
        return "matching_headings"
    if "completeeachsentencewiththecorrectending" in dense:
        return "matching_sentence_endings"
    if (
        "whichparagraphcontains" in dense
        or "whichsectioncontains" in dense
        or "whichparagraph" in dense and "information" in dense
    ):
        return "matching_information"
    if (
        "matcheachstatement" in dense
        or "matcheach" in dense and "correct" in dense
        or "whichperson" in dense
        or "whichexpert" in dense
        or "lookatthefollowingstatements" in dense
        or "lookatthefollowingpurposes" in dense
    ):
        return "matching_features"
    if "labelthediagram" in dense or "completethediagram" in dense:
        return "diagram_labelling"
    if "completetheflowchart" in dense:
        return "flow_chart_completion"
    if "completethetable" in dense:
        return "table_completion"
    if "completethenotes" in dense:
        return "note_completion"
    if "completethesummary" in dense:
        return "summary_completion"
    if "completethesentences" in dense or "completethesentence" in dense:
        return "sentence_completion"
    if "choosetwoletters" in dense or "choosethreeletters" in dense:
        return "multiple_choice_multiple"
    if "choosethecorrectletter" in dense:
        return "multiple_choice_single"
    if "answerthequestions" in dense:
        return "short_answer"
    return "unknown"


def _reading_word_limit(text: str) -> str | None:
    dense = re.sub(r"[^a-z0-9]+", "", text.lower())
    canonical_limits = (
        ("nomorethanthreewordsandoranumber", "NO MORE THAN THREE WORDS AND/OR A NUMBER"),
        ("nomorethantwowordsandoranumber", "NO MORE THAN TWO WORDS AND/OR A NUMBER"),
        ("nomorethanonewordandoranumber", "NO MORE THAN ONE WORD AND/OR A NUMBER"),
        ("onewordandoranumber", "ONE WORD AND/OR A NUMBER"),
        ("nomorethanthreewords", "NO MORE THAN THREE WORDS"),
        ("nomorethantwowords", "NO MORE THAN TWO WORDS"),
        ("nomorethanoneword", "NO MORE THAN ONE WORD"),
        ("threewordsonly", "THREE WORDS ONLY"),
        ("twowordsonly", "TWO WORDS ONLY"),
        ("onewordonly", "ONE WORD ONLY"),
    )
    for marker, label in canonical_limits:
        if marker in dense:
            return label
    match = re.search(
        r"(?i)\b(?:"
        r"NO\s+MORE\s+THAN\s+(?:ONE|TWO|THREE)?\s*"
        r"(?:WORD(?:S)?|NUMBER(?:S)?)(?:\s+AND/OR\s+A\s+NUMBER)?"
        r"|(?:ONE|TWO|THREE)\s+WORD(?:S)?(?:\s+ONLY)?"
        r"|ONE\s+WORD\s+AND/OR\s+A\s+NUMBER"
        r")\b",
        text,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).upper()


def _split_question_drafts(
    text: str,
    common: dict[str, Any],
) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"(?m)^\s*(\d{1,3})[.)]\s+", text))
    if not matches:
        return [{
            **common,
            "question_id": None,
            "question_number": None,
            "question_type": "unknown",
            "raw_text": text,
            "needs_manual_split": True,
            "needs_answer_mapping": True,
        }]
    drafts: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        drafts.append({
            **common,
            "question_id": None,
            "question_number": int(match.group(1)),
            "question_type": "unknown",
            "raw_text": text[match.start():end].strip(),
            "needs_manual_split": False,
            "needs_answer_mapping": True,
        })
    return drafts


def _write_review_draft(
    home: Path,
    import_id: str,
    payload: dict[str, Any],
) -> None:
    _write_json_atomic(
        _import_sidecar_path(home, import_id, "review-draft.json"),
        payload,
    )


def _invalidate_review_draft(
    summary: dict[str, Any],
    *,
    reason: str,
) -> None:
    if "review_draft" not in summary:
        return
    current = dict(summary.get("review_draft") or {})
    current.update({
        "status": "stale",
        "stale_reason": reason,
        "recovery_action": "rebuild_draft",
    })
    summary["review_draft"] = current


def _import_sidecar_path(home: Path, import_id: str, name: str) -> Path:
    root = (home / "corpus" / "inbox" / import_id).resolve()
    path = (root / name).resolve()
    if path.parent != root or not root.is_dir():
        raise ValueError("Content import inbox is missing")
    return path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_structure_draft(home: Path, import_id: str, summary: dict[str, Any]) -> None:
    target = home / "corpus" / "inbox" / import_id / "structure-draft.json"
    target.write_text(
        json.dumps(
            {
                "draft_version": 1,
                "import_id": import_id,
                "documents": summary.get("documents") or [],
                "page_plan": summary.get("page_plan") or {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


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
