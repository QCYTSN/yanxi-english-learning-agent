from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_profile
from .storage import connect, initialise_database


PRIVATE_SOURCE_TYPES = {"licensed_private", "seasonal_reported", "personal"}


def resolve_source_type(
    home: Path,
    *,
    source_type: str | None = None,
    question_id: str | None = None,
    corpus_id: str | None = None,
) -> str | None:
    if source_type:
        return source_type
    initialise_database(home)
    with connect(home) as conn:
        if question_id:
            row = conn.execute("SELECT source_type FROM questions WHERE question_id=?", (question_id,)).fetchone()
            if row:
                return str(row["source_type"])
        if corpus_id:
            row = conn.execute("SELECT source_type FROM corpora WHERE corpus_id=?", (corpus_id,)).fetchone()
            if row:
                return str(row["source_type"])
    return None


def check_processing_permission(
    home: Path,
    *,
    remote_processing: bool,
    explicit_consent: bool = False,
    source_type: str | None = None,
    question_id: str | None = None,
    corpus_id: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_source_type(
        home, source_type=source_type, question_id=question_id, corpus_id=corpus_id
    )
    profile = load_profile(home)
    privacy = profile.get("privacy") or {}
    private = resolved in PRIVATE_SOURCE_TYPES
    allowed = True
    reason = "local_processing"
    if remote_processing and resolved is None and (question_id or corpus_id):
        allowed = False
        reason = "unknown_indexed_source"
    elif remote_processing and private and not privacy.get("allow_private_corpus", True):
        allowed = False
        reason = "private_corpus_disabled"
    elif remote_processing and private and not privacy.get("allow_cloud_upload", False):
        allowed = bool(explicit_consent)
        reason = "explicit_one_time_consent" if allowed else "cloud_upload_disabled"
    elif remote_processing:
        reason = "profile_allows_or_source_is_public"
    return {
        "allowed": allowed,
        "reason": reason,
        "source_type": resolved,
        "private_source": private,
        "remote_processing": remote_processing,
        "consent_persisted": False,
    }


def assert_processing_permission(home: Path, **kwargs: Any) -> dict[str, Any]:
    result = check_processing_permission(home, **kwargs)
    if not result["allowed"]:
        raise PermissionError(
            "Remote processing is blocked for this private source. Use only material you may "
            "send to the chosen provider and provide explicit one-time consent, or process locally."
        )
    return result
