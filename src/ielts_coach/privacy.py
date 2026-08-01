from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_profile
from .storage import connect, initialise_database, json_payload_hash


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
    authorization_kind = (
        "blocked"
        if not allowed
        else "local_processing"
        if not remote_processing
        else "one_time_consent"
        if reason == "explicit_one_time_consent"
        else "profile_policy"
    )
    return {
        "allowed": allowed,
        "reason": reason,
        "authorization_kind": authorization_kind,
        "source_type": resolved,
        "private_source": private,
        "remote_processing": remote_processing,
        "consent_persisted": False,
        "consent_reusable": False,
        "policy_snapshot": {
            "allow_cloud_upload": bool(privacy.get("allow_cloud_upload", False)),
            "allow_private_corpus": bool(privacy.get("allow_private_corpus", True)),
        },
    }


def build_privacy_receipt(
    *,
    run_id: str,
    decision: dict[str, Any],
    provider_ids: list[str],
    scope: dict[str, Any],
) -> dict[str, Any]:
    """Build a consumed, non-reusable audit receipt without retaining content."""
    if not decision.get("allowed"):
        raise PermissionError("A blocked privacy decision cannot create a receipt")
    now = datetime.now(timezone.utc).isoformat()
    clean_provider_ids = [str(item) for item in provider_ids if str(item).strip()]
    audit_scope = {
        **scope,
        "run_id": run_id,
        "source_type": decision.get("source_type"),
        "remote_processing": bool(decision.get("remote_processing")),
        "private_source": bool(decision.get("private_source")),
        "provider_ids": clean_provider_ids,
    }
    return {
        "receipt_id": f"privacy:{run_id}",
        "run_id": run_id,
        "authorization_kind": str(decision["authorization_kind"]),
        "reason": str(decision["reason"]),
        "remote_processing": bool(decision.get("remote_processing")),
        "private_source": bool(decision.get("private_source")),
        "source_type": decision.get("source_type"),
        "provider_ids": clean_provider_ids,
        "scope_hash": json_payload_hash(audit_scope),
        "policy": {
            "decision_reason": decision.get("reason"),
            "authorization_kind": decision.get("authorization_kind"),
            "profile": decision.get("policy_snapshot") or {},
            "consent_reusable": False,
        },
        "reusable": False,
        "created_at": now,
        "consumed_at": now,
    }


def assert_processing_permission(home: Path, **kwargs: Any) -> dict[str, Any]:
    result = check_processing_permission(home, **kwargs)
    if not result["allowed"]:
        raise PermissionError(
            "Remote processing is blocked for this private source. Use only material you may "
            "send to the chosen provider and provide explicit one-time consent, or process locally."
        )
    return result
