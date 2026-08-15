from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import get_content_import_job, update_content_import_job


AUDIO_REVIEW_VERSION = 1


def read_audio_review(
    home: Path,
    import_id: str,
    stored_name: str,
) -> dict[str, Any]:
    job, file_record = _audio_file(home, import_id, stored_name)
    path = _review_path(home, import_id, stored_name)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("audio_review_version") != AUDIO_REVIEW_VERSION:
            raise ValueError("Unsupported audio review version")
        return payload
    return {
        "audio_review_version": AUDIO_REVIEW_VERSION,
        "revision": 0,
        "import_id": import_id,
        "stored_name": stored_name,
        "original_name": file_record.get("original_name"),
        "source_file_sha256": file_record["sha256"],
        "source_type": job["source_type"],
        "authenticity": job["authenticity"],
        "rights_status": job["rights_status"],
        "duration_seconds": None,
        "transcript": "",
        "cues": [],
        "review_status": "needs_review",
        "eligible_for_import": False,
        "updated_at": None,
    }


def update_audio_review(
    home: Path,
    import_id: str,
    *,
    stored_name: str,
    transcript: str,
    cues: list[dict[str, Any]],
    duration_seconds: float | None,
    review_status: str,
    expected_revision: int,
) -> dict[str, Any]:
    if review_status not in {"needs_review", "reviewed"}:
        raise ValueError("Unsupported audio review status")
    current = read_audio_review(home, import_id, stored_name)
    if int(current.get("revision") or 0) != expected_revision:
        raise ValueError("Audio review revision conflict; reload the latest review")
    normalised_cues = _normalise_cues(cues, duration_seconds)
    clean_transcript = transcript.strip()
    if review_status == "reviewed" and (not clean_transcript or not normalised_cues):
        raise ValueError(
            "A reviewed audio record requires a transcript and timestamp cues"
        )
    current.update({
        "revision": expected_revision + 1,
        "duration_seconds": duration_seconds,
        "transcript": clean_transcript,
        "transcript_hash": hashlib.sha256(
            clean_transcript.encode("utf-8")
        ).hexdigest(),
        "cues": normalised_cues,
        "review_status": review_status,
        "eligible_for_import": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json_atomic(_review_path(home, import_id, stored_name), current)

    job = get_content_import_job(home, import_id) or {}
    summary = dict(job.get("summary") or {})
    for document in summary.get("documents") or []:
        if document.get("stored_name") != stored_name:
            continue
        document.update({
            "status": "audio_review_ready",
            "duration_seconds": duration_seconds,
            "transcript_chars": len(clean_transcript),
            "timestamp_cue_count": len(normalised_cues),
            "audio_review_status": review_status,
            "audio_review_revision": current["revision"],
        })
    update_content_import_job(
        home,
        import_id,
        status=(
            job.get("status")
            if job.get("status") not in {"failed", "needs_structuring"}
            else "ready_for_review"
        ),
        error_message=None,
        summary=summary,
    )
    return current


def _normalise_cues(
    cues: list[dict[str, Any]],
    duration_seconds: float | None,
) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for index, cue in enumerate(cues, start=1):
        start = round(float(cue.get("start_seconds") or 0), 3)
        end = round(float(cue.get("end_seconds") or start), 3)
        text = str(cue.get("text") or "").strip()
        if start < 0 or end < start:
            raise ValueError(f"Invalid timestamp cue {index}")
        if duration_seconds is not None and end > duration_seconds + 0.5:
            raise ValueError(f"Timestamp cue {index} exceeds the audio duration")
        if not text:
            raise ValueError(f"Timestamp cue {index} has no transcript text")
        normalised.append({
            "cue_id": str(cue.get("cue_id") or f"cue-{index:04d}"),
            "start_seconds": start,
            "end_seconds": end,
            "text": text,
        })
    normalised.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))
    for previous, current in zip(normalised, normalised[1:], strict=False):
        if current["start_seconds"] < previous["end_seconds"] - 0.05:
            raise ValueError("Timestamp cues cannot overlap")
    return normalised


def _audio_file(
    home: Path,
    import_id: str,
    stored_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    job = get_content_import_job(home, import_id)
    if not job:
        raise ValueError(f"Unknown content import: {import_id}")
    file_record = next(
        (
            item
            for item in job.get("files") or []
            if item.get("stored_name") == stored_name
        ),
        None,
    )
    if not file_record or file_record.get("file_kind") != "audio":
        raise ValueError("Audio review can only target an imported audio file")
    return job, file_record


def _review_path(home: Path, import_id: str, stored_name: str) -> Path:
    root = (home / "corpus" / "inbox" / import_id).resolve()
    if not root.is_dir():
        raise ValueError("Content import inbox is missing")
    digest = hashlib.sha256(stored_name.encode("utf-8")).hexdigest()[:16]
    return root / f"audio-review-{digest}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)
