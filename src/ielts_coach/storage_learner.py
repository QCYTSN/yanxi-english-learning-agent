from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import _now, connect, initialise_database

__all__ = [
    "create_learner_memory",
    "get_learner_memory",
    "list_learner_memories",
    "update_learner_memory",
    "list_learner_memory_revisions",
    "list_learner_memory_conflicts",
    "resolve_learner_memory_conflict",
    "delete_learner_memory",
    "search_learning_history",
]


def create_learner_memory(
    home: Path,
    *,
    memory_type: str,
    statement: str,
    confidence: float,
    evidence_refs: list[str] | None = None,
    scope: str = "teaching_style",
    source_thread_id: str | None = None,
    source_session_id: str | None = None,
    memory_id: str | None = None,
    track_id: str | None = None,
    memory_key: str | None = None,
    expires_at: str | None = None,
    source_kind: str = "learner_confirmed",
    supersedes_memory_id: str | None = None,
    conflicts_with: list[str] | None = None,
) -> dict[str, Any]:
    if not track_id:
        from .domain_packs import DEFAULT_TRACK_ID

        track_id = DEFAULT_TRACK_ID
    initialise_database(home)
    clean = _normalise_memory_statement(statement)
    if not clean:
        raise ValueError("Learner memory statement cannot be empty")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ValueError("Learner memory confidence must be between 0 and 1")
    source_kind = str(source_kind).strip()
    if source_kind not in {
        "learner_confirmed",
        "runtime_observation",
        "imported",
    }:
        raise ValueError("Unsupported learner memory source kind")
    expires_at = _normalise_memory_expiry(expires_at)
    memory_type = str(memory_type).strip()[:80]
    scope = str(scope).strip()[:80]
    if not memory_type or not scope:
        raise ValueError("Learner memory type and scope are required")
    content_hash = _memory_content_hash(clean)
    memory_key = _normalise_memory_key(
        memory_key,
        memory_type=memory_type,
        scope=scope,
        content_hash=content_hash,
    )
    memory_id = memory_id or f"memory_{uuid.uuid4().hex}"
    now = _now()
    result_memory_id = memory_id
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing_by_id = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        if existing_by_id:
            if (
                str(existing_by_id["track_id"]) == track_id
                and str(existing_by_id["memory_key"]) == memory_key
                and str(existing_by_id["content_hash"]) == content_hash
            ):
                return _learner_memory_row(existing_by_id)
            raise ValueError("Learner memory ID already exists with different content")
        if supersedes_memory_id:
            predecessor = conn.execute(
                "SELECT * FROM learner_memories WHERE memory_id=?",
                (supersedes_memory_id,),
            ).fetchone()
            if not predecessor:
                raise ValueError("Superseded learner memory not found")
            if str(predecessor["track_id"]) != track_id:
                raise ValueError("Learner memories from different tracks cannot supersede each other")
        duplicate = conn.execute(
            """
            SELECT * FROM learner_memories
            WHERE track_id=? AND memory_key=? AND content_hash=?
              AND status='active' AND validity_status='current'
              AND (expires_at IS NULL OR expires_at>?)
            ORDER BY updated_at DESC LIMIT 1
            """,
            (track_id, memory_key, content_hash, now),
        ).fetchone()
        if duplicate and not supersedes_memory_id and not conflicts_with:
            result_memory_id = str(duplicate["memory_id"])
            conn.execute(
                """
                UPDATE learner_memories
                SET last_confirmed_at=?,updated_at=?
                WHERE memory_id=?
                """,
                (now, now, result_memory_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO learner_memories(
                  memory_id,track_id,memory_type,memory_key,statement,content_hash,
                  confidence,evidence_refs_json,scope,status,validity_status,revision,
                  source_kind,supersedes_memory_id,conflict_group_id,valid_from,
                  expires_at,last_accessed_at,access_count,source_thread_id,
                  source_session_id,created_at,last_confirmed_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,'active','current',1,?,?,NULL,?,?,NULL,0,?,?,?,?,?)
                """,
                (
                    memory_id,
                    track_id,
                    memory_type,
                    memory_key,
                    clean,
                    content_hash,
                    confidence,
                    json.dumps(evidence_refs or [], ensure_ascii=False),
                    scope,
                    source_kind,
                    supersedes_memory_id,
                    now,
                    expires_at,
                    source_thread_id,
                    source_session_id,
                    now,
                    now,
                    now,
                ),
            )
            if supersedes_memory_id:
                _set_memory_lifecycle_conn(
                    conn,
                    supersedes_memory_id,
                    status=None,
                    validity_status="superseded",
                    conflict_group_id=None,
                    reason="superseded_by_new_memory",
                    changed_at=now,
                )
            _detect_memory_conflicts_conn(
                conn,
                memory_id,
                explicit_memory_ids=conflicts_with or [],
                changed_at=now,
            )
            created = conn.execute(
                "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
            ).fetchone()
            _insert_memory_revision_conn(
                conn,
                created,
                change_reason="created",
                changed_at=now,
            )
    return get_learner_memory(home, result_memory_id) or {}


def get_learner_memory(home: Path, memory_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
    return _learner_memory_row(row) if row else None


def list_learner_memories(
    home: Path,
    *,
    status: str | None = "active",
    memory_type: str | None = None,
    track_id: str | None = None,
    validity_status: str | None = "current",
    include_expired: bool = False,
    touch_access: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not track_id:
        from .domain_packs import DEFAULT_TRACK_ID

        track_id = DEFAULT_TRACK_ID
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        if status not in {"active", "dismissed"}:
            raise ValueError("Unsupported learner memory status")
        clauses.append("status=?")
        params.append(status)
    if track_id:
        clauses.append("track_id=?")
        params.append(track_id)
    if memory_type:
        clauses.append("memory_type=?")
        params.append(memory_type)
    if validity_status:
        if validity_status not in {"current", "conflicted", "superseded", "expired"}:
            raise ValueError("Unsupported learner memory validity status")
        if validity_status == "expired":
            clauses.append(
                "(validity_status='expired' OR "
                "(validity_status='current' AND expires_at IS NOT NULL AND expires_at<=?))"
            )
            params.append(_now())
        else:
            clauses.append("validity_status=?")
            params.append(validity_status)
    if not include_expired and validity_status != "expired":
        clauses.append("(expires_at IS NULL OR expires_at>?)")
        params.append(_now())
    params.append(max(1, min(int(limit), 200)))
    where = " AND ".join(clauses) if clauses else "1=1"
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT * FROM learner_memories WHERE "
            + where
            + " ORDER BY confidence DESC,updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        if touch_access and rows:
            accessed_at = _now()
            ordered_ids = [str(row["memory_id"]) for row in rows]
            conn.executemany(
                """
                UPDATE learner_memories
                SET last_accessed_at=?,access_count=access_count+1
                WHERE memory_id=?
                """,
                [(accessed_at, row["memory_id"]) for row in rows],
            )
            refreshed = conn.execute(
                f"SELECT * FROM learner_memories WHERE memory_id IN "
                f"({','.join('?' for _ in rows)})",
                ordered_ids,
            ).fetchall()
            refreshed_by_id = {str(row["memory_id"]): row for row in refreshed}
            rows = [refreshed_by_id[memory_id] for memory_id in ordered_ids]
    return [_learner_memory_row(row) for row in rows]


def update_learner_memory(
    home: Path,
    memory_id: str,
    *,
    statement: str | None = None,
    confidence: float | None = None,
    status: str | None = None,
    scope: str | None = None,
    memory_key: str | None = None,
    expires_at: str | None = None,
    clear_expiry: bool = False,
    expected_revision: int | None = None,
    change_reason: str = "learner_update",
) -> dict[str, Any]:
    if status is not None and status not in {"active", "dismissed"}:
        raise ValueError("Unsupported learner memory status")
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise ValueError("Learner memory confidence must be between 0 and 1")
    if expires_at is not None:
        expires_at = _normalise_memory_expiry(expires_at)
    now = _now()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
        if not row:
            raise ValueError("Learner memory not found")
        current_revision = int(row["revision"])
        if expected_revision is not None and current_revision != int(expected_revision):
            from .errors import LearningRevisionConflictError

            raise LearningRevisionConflictError(
                f"Stale LearnerMemory revision: expected {expected_revision}, current {current_revision}",
                details={
                    "memory_id": memory_id,
                    "expected_revision": int(expected_revision),
                    "current_revision": current_revision,
                },
            )
        clean_statement = (
            _normalise_memory_statement(statement)
            if statement is not None
            else str(row["statement"])
        )
        if not clean_statement:
            raise ValueError("Learner memory statement cannot be empty")
        clean_scope = str(scope).strip()[:80] if scope is not None else str(row["scope"])
        if not clean_scope:
            raise ValueError("Learner memory scope cannot be empty")
        content_hash = _memory_content_hash(clean_statement)
        clean_key = (
            _normalise_memory_key(
                memory_key,
                memory_type=str(row["memory_type"]),
                scope=clean_scope,
                content_hash=content_hash,
            )
            if memory_key is not None
            else _normalise_memory_key(
                None,
                memory_type=str(row["memory_type"]),
                scope=clean_scope,
                content_hash=content_hash,
            )
            if scope is not None
            and str(row["memory_type"]) in _SINGLETON_MEMORY_TYPES
            else str(row["memory_key"])
        )
        next_status = status if status is not None else str(row["status"])
        next_expires = (
            None
            if clear_expiry
            else expires_at
            if expires_at is not None
            else row["expires_at"]
        )
        semantic_changed = bool(
            clean_statement != str(row["statement"])
            or clean_scope != str(row["scope"])
            or clean_key != str(row["memory_key"])
        )
        lifecycle_changed = bool(
            next_status != str(row["status"])
            or next_expires != row["expires_at"]
        )
        conn.execute(
            """
            UPDATE learner_memories
            SET statement=?,content_hash=?,memory_key=?,confidence=?,status=?,scope=?,
                expires_at=?,revision=revision+1,last_confirmed_at=?,updated_at=?
            WHERE memory_id=?
            """,
            (
                clean_statement,
                content_hash,
                clean_key,
                float(confidence) if confidence is not None else float(row["confidence"]),
                next_status,
                clean_scope,
                next_expires,
                now,
                now,
                memory_id,
            ),
        )
        if next_status == "dismissed":
            _resolve_conflicts_for_dismissed_conn(conn, memory_id, changed_at=now)
        elif semantic_changed or lifecycle_changed:
            _resolve_conflicts_for_changed_memory_conn(
                conn,
                memory_id,
                changed_at=now,
            )
            is_expired = bool(next_expires and str(next_expires) <= now)
            if not is_expired:
                _detect_memory_conflicts_conn(
                    conn,
                    memory_id,
                    explicit_memory_ids=[],
                    changed_at=now,
                )
        elif str(row["validity_status"]) == "current":
            _detect_memory_conflicts_conn(
                conn,
                memory_id,
                explicit_memory_ids=[],
                changed_at=now,
            )
        updated = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
        _insert_memory_revision_conn(
            conn,
            updated,
            change_reason=str(change_reason).strip()[:120] or "learner_update",
            changed_at=now,
        )
    return get_learner_memory(home, memory_id) or {}


def list_learner_memory_revisions(
    home: Path,
    memory_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        if not conn.execute(
            "SELECT 1 FROM learner_memories WHERE memory_id=?", (memory_id,)
        ).fetchone():
            raise ValueError("Learner memory not found")
        rows = conn.execute(
            """
            SELECT * FROM learner_memory_revisions
            WHERE memory_id=? ORDER BY revision DESC LIMIT ?
            """,
            (memory_id, max(1, min(int(limit), 500))),
        ).fetchall()
    return [
        {
            **{
                key: row[key]
                for key in row.keys()
                if key != "evidence_refs_json"
            },
            "confidence": float(row["confidence"]),
            "evidence_refs": json.loads(row["evidence_refs_json"] or "[]"),
        }
        for row in rows
    ]


def list_learner_memory_conflicts(
    home: Path,
    *,
    status: str | None = "open",
    track_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not track_id:
        from .domain_packs import DEFAULT_TRACK_ID

        track_id = DEFAULT_TRACK_ID
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        if status not in {"open", "resolved"}:
            raise ValueError("Unsupported learner memory conflict status")
        clauses.append("conflicts.status=?")
        params.append(status)
    if track_id:
        clauses.append("left_memory.track_id=?")
        params.append(track_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT conflicts.*
            FROM learner_memory_conflicts AS conflicts
            JOIN learner_memories AS left_memory
              ON left_memory.memory_id=conflicts.left_memory_id
            WHERE {where}
            ORDER BY conflicts.created_at DESC LIMIT ?
            """,
            params,
        ).fetchall()
        memories = {
            str(item["memory_id"]): _learner_memory_row(item)
            for item in conn.execute(
                "SELECT * FROM learner_memories WHERE memory_id IN ("
                + ",".join("?" for _ in {str(r['left_memory_id']) for r in rows} | {str(r['right_memory_id']) for r in rows})
                + ")",
                list({str(r['left_memory_id']) for r in rows} | {str(r['right_memory_id']) for r in rows}),
            ).fetchall()
        } if rows else {}
    return [
        {
            **dict(row),
            "left_memory": memories.get(str(row["left_memory_id"])),
            "right_memory": memories.get(str(row["right_memory_id"])),
        }
        for row in rows
    ]


def resolve_learner_memory_conflict(
    home: Path,
    conflict_id: str,
    *,
    resolution: str,
    rationale: str | None = None,
) -> dict[str, Any]:
    if resolution not in {"keep_left", "keep_right", "keep_both", "dismiss_both"}:
        raise ValueError("Unsupported learner memory conflict resolution")
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conflict = conn.execute(
            "SELECT * FROM learner_memory_conflicts WHERE conflict_id=?",
            (conflict_id,),
        ).fetchone()
        if not conflict:
            raise ValueError("Learner memory conflict not found")
        if str(conflict["status"]) == "resolved":
            return {
                **dict(conflict),
                "left_memory": _learner_memory_row(
                    conn.execute(
                        "SELECT * FROM learner_memories WHERE memory_id=?",
                        (conflict["left_memory_id"],),
                    ).fetchone()
                ),
                "right_memory": _learner_memory_row(
                    conn.execute(
                        "SELECT * FROM learner_memories WHERE memory_id=?",
                        (conflict["right_memory_id"],),
                    ).fetchone()
                ),
            }
        left_id = str(conflict["left_memory_id"])
        right_id = str(conflict["right_memory_id"])
        if resolution == "keep_left":
            _set_memory_lifecycle_conn(conn, left_id, status="active", validity_status="current", conflict_group_id=None, reason="conflict_keep_left", changed_at=now)
            _set_memory_lifecycle_conn(conn, right_id, status="dismissed", validity_status="superseded", conflict_group_id=None, reason="conflict_keep_left", changed_at=now)
        elif resolution == "keep_right":
            _set_memory_lifecycle_conn(conn, left_id, status="dismissed", validity_status="superseded", conflict_group_id=None, reason="conflict_keep_right", changed_at=now)
            _set_memory_lifecycle_conn(conn, right_id, status="active", validity_status="current", conflict_group_id=None, reason="conflict_keep_right", changed_at=now)
        elif resolution == "keep_both":
            _set_memory_lifecycle_conn(conn, left_id, status="active", validity_status="current", conflict_group_id=None, reason="conflict_keep_both", changed_at=now)
            _set_memory_lifecycle_conn(conn, right_id, status="active", validity_status="current", conflict_group_id=None, reason="conflict_keep_both", changed_at=now)
        else:
            _set_memory_lifecycle_conn(conn, left_id, status="dismissed", validity_status="current", conflict_group_id=None, reason="conflict_dismiss_both", changed_at=now)
            _set_memory_lifecycle_conn(conn, right_id, status="dismissed", validity_status="current", conflict_group_id=None, reason="conflict_dismiss_both", changed_at=now)
        conn.execute(
            """
            UPDATE learner_memory_conflicts
            SET status='resolved',resolution=?,rationale=?,resolved_at=?
            WHERE conflict_id=?
            """,
            (resolution, (rationale or "")[:1000] or None, now, conflict_id),
        )
        for memory_id in (left_id, right_id):
            _restore_memory_after_conflict_conn(conn, memory_id, changed_at=now)
        updated = conn.execute(
            "SELECT * FROM learner_memory_conflicts WHERE conflict_id=?",
            (conflict_id,),
        ).fetchone()
        left = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?", (left_id,)
        ).fetchone()
        right = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?", (right_id,)
        ).fetchone()
    return {
        **dict(updated),
        "left_memory": _learner_memory_row(left),
        "right_memory": _learner_memory_row(right),
    }


def delete_learner_memory(home: Path, memory_id: str) -> bool:
    initialise_database(home)
    with connect(home) as conn:
        cursor = conn.execute(
            "DELETE FROM learner_memories WHERE memory_id=?", (memory_id,)
        )
    return cursor.rowcount == 1


def _learner_memory_row(row: sqlite3.Row) -> dict[str, Any]:
    result = {
        **{key: row[key] for key in row.keys() if key != "evidence_refs_json"},
        "confidence": float(row["confidence"]),
        "evidence_refs": json.loads(row["evidence_refs_json"]),
    }
    expired = bool(
        result.get("expires_at")
        and str(result["expires_at"]) <= _now()
        and result.get("validity_status") == "current"
    )
    result["effective_validity_status"] = "expired" if expired else result.get("validity_status")
    result["effective"] = bool(
        result.get("status") == "active"
        and result["effective_validity_status"] == "current"
    )
    return result


_SINGLETON_MEMORY_TYPES = {
    "preferred_name",
    "feedback_language",
    "interface_language",
    "target_band",
    "explanation_order",
    "timezone",
}


def _normalise_memory_statement(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:2000]


def _memory_content_hash(statement: str) -> str:
    return hashlib.sha256(statement.casefold().encode("utf-8")).hexdigest()


def _normalise_memory_key(
    value: str | None,
    *,
    memory_type: str,
    scope: str,
    content_hash: str,
) -> str:
    if value is not None and str(value).strip():
        clean = re.sub(r"[^a-z0-9._:-]+", "-", str(value).casefold()).strip("-")
        if not clean:
            raise ValueError("Learner memory key contains no usable characters")
        return clean[:160]
    if memory_type in _SINGLETON_MEMORY_TYPES:
        return f"{scope}:{memory_type}"[:160]
    seed = f"{scope}|{memory_type}|{content_hash[:20]}"
    return f"memory:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"


def _normalise_memory_expiry(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Learner memory expiry must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _insert_memory_revision_conn(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    change_reason: str,
    changed_at: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO learner_memory_revisions(
          memory_id,revision,statement,content_hash,confidence,evidence_refs_json,
          memory_key,scope,status,validity_status,source_kind,expires_at,
          change_reason,changed_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            row["memory_id"],
            int(row["revision"]),
            row["statement"],
            row["content_hash"],
            float(row["confidence"]),
            row["evidence_refs_json"],
            row["memory_key"],
            row["scope"],
            row["status"],
            row["validity_status"],
            row["source_kind"],
            row["expires_at"],
            change_reason[:120],
            changed_at,
        ),
    )


def _set_memory_lifecycle_conn(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    status: str | None,
    validity_status: str,
    conflict_group_id: str | None,
    reason: str,
    changed_at: str,
) -> None:
    row = conn.execute(
        "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
    ).fetchone()
    if not row:
        raise ValueError("Learner memory not found")
    next_status = status if status is not None else str(row["status"])
    if (
        next_status == str(row["status"])
        and validity_status == str(row["validity_status"])
        and conflict_group_id == row["conflict_group_id"]
    ):
        return
    conn.execute(
        """
        UPDATE learner_memories
        SET status=?,validity_status=?,conflict_group_id=?,revision=revision+1,
            updated_at=? WHERE memory_id=?
        """,
        (next_status, validity_status, conflict_group_id, changed_at, memory_id),
    )
    updated = conn.execute(
        "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
    ).fetchone()
    _insert_memory_revision_conn(
        conn, updated, change_reason=reason, changed_at=changed_at
    )


def _detect_memory_conflicts_conn(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    explicit_memory_ids: list[str],
    changed_at: str,
) -> None:
    row = conn.execute(
        "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
    ).fetchone()
    if (
        not row
        or str(row["status"]) != "active"
        or (
            row["expires_at"] is not None
            and str(row["expires_at"]) <= changed_at
        )
    ):
        return
    candidates = conn.execute(
        """
        SELECT * FROM learner_memories
        WHERE memory_id<>? AND track_id=? AND memory_key=? AND status='active'
          AND validity_status IN ('current','conflicted')
          AND (expires_at IS NULL OR expires_at>?)
        """,
        (memory_id, row["track_id"], row["memory_key"], changed_at),
    ).fetchall()
    explicit = {str(item) for item in explicit_memory_ids if str(item).strip()}
    if explicit:
        placeholders = ",".join("?" for _ in explicit)
        candidates.extend(
            conn.execute(
                f"SELECT * FROM learner_memories WHERE memory_id IN ({placeholders})",
                sorted(explicit),
            ).fetchall()
        )
    mismatched = [
        str(item["memory_id"])
        for item in candidates
        if str(item["track_id"]) != str(row["track_id"])
    ]
    if mismatched:
        raise ValueError("Learner memory conflicts cannot cross learning tracks")
    unique = {
        str(item["memory_id"]): item
        for item in candidates
        if str(item["memory_id"]) != memory_id
        and (
            str(item["content_hash"]) != str(row["content_hash"])
            or str(item["memory_id"]) in explicit
        )
    }
    if not unique:
        return
    group_seed = f"{row['track_id']}|{row['memory_key']}"
    group_id = f"memory_conflict_{hashlib.sha256(group_seed.encode('utf-8')).hexdigest()[:20]}"
    conn.execute(
        """
        UPDATE learner_memories
        SET validity_status='conflicted',conflict_group_id=?,updated_at=?
        WHERE memory_id=?
        """,
        (group_id, changed_at, memory_id),
    )
    for candidate_id in sorted(unique):
        candidate = unique[candidate_id]
        if str(candidate["validity_status"]) != "conflicted" or candidate["conflict_group_id"] != group_id:
            _set_memory_lifecycle_conn(
                conn,
                candidate_id,
                status=None,
                validity_status="conflicted",
                conflict_group_id=group_id,
                reason="conflict_detected",
                changed_at=changed_at,
            )
        left_id, right_id = sorted((memory_id, candidate_id))
        conflict_id = f"memory_conflict_{hashlib.sha256(f'{left_id}|{right_id}'.encode()).hexdigest()[:24]}"
        conn.execute(
            """
            INSERT INTO learner_memory_conflicts(
              conflict_id,conflict_group_id,left_memory_id,right_memory_id,
              status,created_at
            ) VALUES(?,?,?,?,'open',?)
            ON CONFLICT(conflict_id) DO UPDATE SET
              conflict_group_id=excluded.conflict_group_id,
              status='open',resolution=NULL,rationale=NULL,
              created_at=excluded.created_at,resolved_at=NULL
            """,
            (conflict_id, group_id, left_id, right_id, changed_at),
        )


def _resolve_conflicts_for_dismissed_conn(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    changed_at: str,
) -> None:
    rows = conn.execute(
        """
        SELECT * FROM learner_memory_conflicts
        WHERE status='open' AND (left_memory_id=? OR right_memory_id=?)
        """,
        (memory_id, memory_id),
    ).fetchall()
    for conflict in rows:
        other_id = (
            str(conflict["right_memory_id"])
            if str(conflict["left_memory_id"]) == memory_id
            else str(conflict["left_memory_id"])
        )
        resolution = (
            "keep_right"
            if str(conflict["left_memory_id"]) == memory_id
            else "keep_left"
        )
        conn.execute(
            """
            UPDATE learner_memory_conflicts
            SET status='resolved',resolution=?,rationale='memory_dismissed',resolved_at=?
            WHERE conflict_id=?
            """,
            (resolution, changed_at, conflict["conflict_id"]),
        )
        _restore_memory_after_conflict_conn(conn, other_id, changed_at=changed_at)


def _resolve_conflicts_for_changed_memory_conn(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    changed_at: str,
) -> None:
    rows = conn.execute(
        """
        SELECT * FROM learner_memory_conflicts
        WHERE status='open' AND (left_memory_id=? OR right_memory_id=?)
        """,
        (memory_id, memory_id),
    ).fetchall()
    peers: set[str] = set()
    for conflict in rows:
        peers.add(
            str(conflict["right_memory_id"])
            if str(conflict["left_memory_id"]) == memory_id
            else str(conflict["left_memory_id"])
        )
        conn.execute(
            """
            UPDATE learner_memory_conflicts
            SET status='resolved',resolution='keep_both',
                rationale='memory_changed',resolved_at=?
            WHERE conflict_id=?
            """,
            (changed_at, conflict["conflict_id"]),
        )
    for candidate_id in sorted(peers | {memory_id}):
        _restore_memory_after_conflict_conn(
            conn,
            candidate_id,
            changed_at=changed_at,
        )


def _restore_memory_after_conflict_conn(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    changed_at: str,
) -> None:
    row = conn.execute(
        "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
    ).fetchone()
    if (
        not row
        or str(row["status"]) != "active"
        or str(row["validity_status"]) in {"superseded", "expired"}
    ):
        return
    open_conflict = conn.execute(
        """
        SELECT conflict_group_id FROM learner_memory_conflicts
        WHERE status='open' AND (left_memory_id=? OR right_memory_id=?)
        ORDER BY created_at DESC LIMIT 1
        """,
        (memory_id, memory_id),
    ).fetchone()
    desired = "conflicted" if open_conflict else "current"
    desired_group = str(open_conflict["conflict_group_id"]) if open_conflict else None
    if str(row["validity_status"]) != desired or row["conflict_group_id"] != desired_group:
        _set_memory_lifecycle_conn(
            conn,
            memory_id,
            status=None,
            validity_status=desired,
            conflict_group_id=desired_group,
            reason="conflicts_remaining" if desired == "conflicted" else "conflicts_resolved",
            changed_at=changed_at,
        )


def search_learning_history(
    home: Path,
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Search local conversations, writing versions and error evidence.

    Structured answers and scores remain outside this fuzzy retrieval path.
    """
    initialise_database(home)
    clean = " ".join(query.strip().split())[:240]
    if not clean:
        return []
    escaped = clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    bounded = max(1, min(int(limit), 50))
    with connect(home) as conn:
        tokenizer_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='learning_history_tokenizer'"
        ).fetchone()
        tokenizer = str(tokenizer_row["value"]) if tokenizer_row else "unavailable"
        if tokenizer != "unavailable" and (tokenizer != "trigram" or len(clean) >= 3):
            phrase = _learning_history_match_expression(clean, tokenizer)
            try:
                indexed_rows = conn.execute(
                    """
                    SELECT source_type,source_id,title,content,created_at
                    FROM learning_history_fts
                    WHERE learning_history_fts MATCH ?
                    ORDER BY rank,created_at DESC LIMIT ?
                    """,
                    (phrase, bounded),
                ).fetchall()
            except sqlite3.OperationalError:
                indexed_rows = []
            if indexed_rows:
                return [
                    {
                        **dict(row),
                        "content": str(row["content"] or "")[:1200],
                    }
                    for row in indexed_rows
                ]
        message_rows = conn.execute(
            """
            SELECT 'study_message' source_type,m.message_id source_id,
                   t.title title,m.content content,m.created_at created_at
            FROM study_messages m JOIN study_threads t USING(thread_id)
            WHERE m.content LIKE ? ESCAPE '\\'
            ORDER BY m.created_at DESC LIMIT ?
            """,
            (pattern, bounded),
        ).fetchall()
        writing_rows = conn.execute(
            """
            SELECT 'writing_version' source_type,
                   w.session_id || ':' || w.version_label source_id,
                   'Writing ' || w.version_label title,w.content content,
                   w.created_at created_at
            FROM writing_versions w
            WHERE w.content LIKE ? ESCAPE '\\'
            ORDER BY w.created_at DESC LIMIT ?
            """,
            (pattern, bounded),
        ).fetchall()
        error_rows = conn.execute(
            """
            SELECT 'error_record' source_type,
                   CAST(e.id AS TEXT) source_id,e.tag title,
                   COALESCE(e.evidence,'') content,s.occurred_at created_at
            FROM errors e JOIN sessions s USING(session_id)
            WHERE e.tag LIKE ? ESCAPE '\\' OR COALESCE(e.evidence,'') LIKE ? ESCAPE '\\'
            ORDER BY s.occurred_at DESC LIMIT ?
            """,
            (pattern, pattern, bounded),
        ).fetchall()
    combined = [dict(row) for row in (*message_rows, *writing_rows, *error_rows)]
    combined.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return [
        {
            **item,
            "content": str(item.get("content") or "")[:1200],
        }
        for item in combined[:bounded]
    ]


def _learning_history_match_expression(clean: str, tokenizer: str) -> str:
    terms: list[str] = []
    for word in re.findall(r"[A-Za-z0-9_']{3,}", clean):
        lowered = word.casefold()
        if lowered not in terms:
            terms.append(lowered)
    if tokenizer == "trigram":
        for sequence in re.findall(r"[\u3400-\u9fff]{3,}", clean):
            for index in range(0, len(sequence) - 2, max(1, len(sequence) // 6)):
                trigram = sequence[index : index + 3]
                if trigram not in terms:
                    terms.append(trigram)
                if len(terms) >= 10:
                    break
    if not terms:
        terms = [clean]
    return " OR ".join(
        '"' + term.replace('"', '""') + '"' for term in terms[:10]
    )


