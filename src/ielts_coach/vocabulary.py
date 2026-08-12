from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import connect, initialise_database


REVIEW_KINDS = ("sentence_recall", "fill_context", "spaced_review")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_vocabulary_item(
    home: Path,
    *,
    word: str,
    meaning: str | None = None,
    usage: str | None = None,
    example: str | None = None,
    collocations: list[str] | None = None,
    review_kind: str = "sentence_recall",
    source_type: str = "learner_input",
    source_id: str | None = None,
    track_id: str = "general-english",
) -> dict[str, Any]:
    """Add one learner-owned word to the personal vocabulary list.

    Idempotent per (track, word): adding the same word again updates the
    existing row instead of duplicating it.
    """
    if not word or not word.strip():
        raise ValueError("A vocabulary item needs a word")
    if review_kind not in REVIEW_KINDS:
        raise ValueError(f"Unsupported review kind: {review_kind}")
    initialise_database(home)
    now = _now()
    item_id = f"vocab:{word.strip().casefold()[:120]}"
    with connect(home) as conn:
        existing = conn.execute(
            "SELECT item_id FROM vocabulary_items WHERE track_id=? AND word=?",
            (track_id, word.strip()),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE vocabulary_items
                SET meaning=COALESCE(?,meaning), usage=COALESCE(?,usage),
                    example=COALESCE(?,example),
                    collocations_json=?,
                    source_type=COALESCE(?,source_type),
                    source_id=COALESCE(?,source_id),
                    updated_at=?
                WHERE item_id=?
                """,
                (
                    meaning,
                    usage,
                    example,
                    json.dumps(collocations or [], ensure_ascii=False),
                    source_type,
                    source_id,
                    now,
                    existing["item_id"],
                ),
            )
            item_id = existing["item_id"]
        else:
            conn.execute(
                """
                INSERT INTO vocabulary_items(
                  item_id,track_id,word,meaning,usage,example,
                  collocations_json,source_type,source_id,status,review_kind,
                  next_review_at,review_count,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    item_id,
                    track_id,
                    word.strip(),
                    meaning,
                    usage,
                    example,
                    json.dumps(collocations or [], ensure_ascii=False),
                    source_type,
                    source_id,
                    "learning",
                    review_kind,
                    None,
                    0,
                    now,
                    now,
                ),
            )
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
        ).fetchone()
    return _row(row)


def list_vocabulary_items(
    home: Path,
    *,
    track_id: str = "general-english",
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses = ["track_id=?"]
    params: list[Any] = [track_id]
    if status:
        clauses.append("status=?")
        params.append(status)
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM vocabulary_items
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [_row(row) for row in rows]


def due_vocabulary_reviews(
    home: Path,
    *,
    track_id: str = "general-english",
    now: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Words whose spaced review is due, for the Today reminder surface."""
    initialise_database(home)
    now = now or _now()
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM vocabulary_items
            WHERE track_id=? AND status='learning'
              AND (next_review_at IS NULL OR next_review_at <= ?)
            ORDER BY next_review_at IS NULL DESC, next_review_at ASC
            LIMIT ?
            """,
            (track_id, now, limit),
        ).fetchall()
    return [_row(row) for row in rows]


def schedule_vocabulary_review(
    home: Path,
    item_id: str,
    *,
    days: int,
) -> dict[str, Any]:
    """Push a word's next review out by `days` (spaced-repetition step)."""
    initialise_database(home)
    next_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE vocabulary_items
            SET next_review_at=?, review_count=review_count+1,
                last_reviewed_at=?, updated_at=?
            WHERE item_id=?
            """,
            (next_at, _now(), _now(), item_id),
        )
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown vocabulary item: {item_id}")
    return _row(row)


def set_vocabulary_status(
    home: Path,
    item_id: str,
    *,
    status: str,
) -> dict[str, Any]:
    if status not in {"learning", "mastered", "dismissed"}:
        raise ValueError(f"Unsupported vocabulary status: {status}")
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            "UPDATE vocabulary_items SET status=?, updated_at=? WHERE item_id=?",
            (status, _now(), item_id),
        )
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown vocabulary item: {item_id}")
    return _row(row)


def _row(row: Any) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "track_id": row["track_id"],
        "word": row["word"],
        "meaning": row["meaning"],
        "usage": row["usage"],
        "example": row["example"],
        "collocations": json.loads(row["collocations_json"] or "[]"),
        "status": row["status"],
        "review_kind": row["review_kind"],
        "next_review_at": row["next_review_at"],
        "review_count": row["review_count"],
        "last_reviewed_at": row["last_reviewed_at"],
        "created_at": row["created_at"],
    }
