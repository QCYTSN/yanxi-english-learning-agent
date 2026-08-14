from __future__ import annotations

import hashlib
import json
import re
import secrets
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .content_imports import create_import
from .context_engine import ContextBudget, assemble_tutor_context
from .data_lifecycle import delete_study_thread_data, purge_unreferenced_media
from .domain_packs import DEFAULT_TRACK_ID, get_domain_pack
from .media import import_image_bytes, resolve_media_file
from .question_bank import show_reading_set
from .storage import (
    connect,
    get_thread_summary,
    initialise_database,
    save_thread_summary,
    search_learning_history,
)
from .storage_quota import assert_local_storage_capacity, invalidate_storage_usage
from .text_anchor import create_text_anchor
from .tutor_state import get_thread_learning_state, list_tutor_proposals
from .uploads import StagedUpload, copy_file_atomic, hash_file, read_zip_member


ALLOWED_ATTACHMENT_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".pdf",
    ".txt",
    ".md",
    ".docx",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_MESSAGE_BYTES = 60 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 8
MAX_EXTRACTED_TEXT = 80_000
MAX_THREAD_CONTEXT_TEXT = 48_000
MAX_THREAD_IMAGES = 8
LIVE_CONTEXT_MESSAGES = 10
MAX_RECENT_CONTEXT_CHARS = 32_000
SUMMARY_ANCHOR_MESSAGES = 4
SUMMARY_RECENT_MESSAGES = 24
SUMMARY_MAX_CHARS = 6_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def create_study_thread(
    home: Path,
    *,
    title: str,
    module: str = "mixed",
    track_id: str = DEFAULT_TRACK_ID,
    model_provider_id: str | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialise_database(home)
    pack = get_domain_pack(track_id)
    if pack.status != "active":
        raise ValueError(f"Learning track is not active: {track_id}")
    supported_modules = {item.dimension_id for item in pack.dimensions} | {"mixed"}
    if module not in supported_modules:
        raise ValueError(
            "Study thread module must belong to the selected learning track or be mixed"
        )
    clean_title = " ".join(title.strip().split())[:120] or "新的 IELTS 学习对话"
    thread_id = _id("thread")
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_threads(
              thread_id,title,module,track_id,status,model_provider_id,
              source_context_json,created_at,updated_at
            ) VALUES(?,?,?,?,'active',?,?,?,?)
            """,
            (
                thread_id,
                clean_title,
                module,
                track_id,
                model_provider_id,
                json.dumps(source_context or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
    return get_study_thread(home, thread_id)


def list_study_threads(home: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT
              threads.*,
              (
                SELECT COUNT(*)
                FROM study_messages AS messages
                WHERE messages.thread_id=threads.thread_id
              ) AS message_count,
              (
                SELECT COUNT(*)
                FROM study_thread_attachments AS attachments
                WHERE attachments.thread_id=threads.thread_id
              ) AS attachment_count,
              (
                SELECT messages.content
                FROM study_messages AS messages
                WHERE messages.thread_id=threads.thread_id
                ORDER BY messages.created_at DESC, messages.message_id DESC
                LIMIT 1
              ) AS last_message_preview
            FROM study_threads AS threads
            WHERE threads.status='active'
            ORDER BY threads.updated_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [_thread_row(row, messages=[], attachments=[]) for row in rows]


def get_study_thread(home: Path, thread_id: str) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM study_threads WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if not row:
            raise ValueError("Study thread not found")
        message_rows = conn.execute(
            """
            SELECT * FROM study_messages
            WHERE thread_id=? ORDER BY created_at,message_id
            """,
            (thread_id,),
        ).fetchall()
        attachment_rows = conn.execute(
            """
            SELECT * FROM study_thread_attachments
            WHERE thread_id=? ORDER BY created_at,attachment_id
            """,
            (thread_id,),
        ).fetchall()
    attachments = [_attachment_row(item) for item in attachment_rows]
    by_message: dict[str, list[dict[str, Any]]] = {}
    for attachment in attachments:
        if attachment.get("message_id"):
            by_message.setdefault(str(attachment["message_id"]), []).append(attachment)
    messages = [
        {
            **_message_row(item),
            "attachments": by_message.get(str(item["message_id"]), []),
        }
        for item in message_rows
    ]
    return {
        **_thread_row(row, messages=messages, attachments=attachments),
        "conversation_summary": get_thread_summary(home, thread_id),
        "learning_state": get_thread_learning_state(home, thread_id),
        "proposals": list_tutor_proposals(
            home, thread_id=thread_id, status="pending", limit=20
        ),
    }


def get_study_thread_overview(home: Path, thread_id: str) -> dict[str, Any]:
    """Return thread chrome/state without materialising its message history."""
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            """
            SELECT
              threads.*,
              (
                SELECT COUNT(*) FROM study_messages AS messages
                WHERE messages.thread_id=threads.thread_id
              ) AS message_count,
              (
                SELECT COUNT(*) FROM study_thread_attachments AS attachments
                WHERE attachments.thread_id=threads.thread_id
              ) AS attachment_count,
              (
                SELECT messages.content FROM study_messages AS messages
                WHERE messages.thread_id=threads.thread_id
                ORDER BY messages.created_at DESC,messages.message_id DESC
                LIMIT 1
              ) AS last_message_preview
            FROM study_threads AS threads
            WHERE threads.thread_id=?
            """,
            (thread_id,),
        ).fetchone()
    if not row:
        raise ValueError("Study thread not found")
    return {
        **_thread_row(row, messages=[], attachments=[]),
        "conversation_summary": get_thread_summary(home, thread_id),
        "learning_state": get_thread_learning_state(home, thread_id),
        "proposals": list_tutor_proposals(
            home, thread_id=thread_id, status="pending", limit=20
        ),
    }


def list_study_messages_page(
    home: Path,
    thread_id: str,
    *,
    limit: int = 30,
    before: str | None = None,
) -> dict[str, Any]:
    """Return a reverse-keyset page, displayed oldest-to-newest by clients."""
    initialise_database(home)
    bounded = max(1, min(int(limit), 100))
    with connect(home) as conn:
        if not conn.execute(
            "SELECT 1 FROM study_threads WHERE thread_id=?", (thread_id,)
        ).fetchone():
            raise ValueError("Study thread not found")
        params: list[Any] = [thread_id]
        cursor_clause = ""
        if before:
            cursor = conn.execute(
                """
                SELECT created_at,message_id FROM study_messages
                WHERE thread_id=? AND message_id=?
                """,
                (thread_id, before),
            ).fetchone()
            if not cursor:
                raise ValueError("Study message cursor not found")
            cursor_clause = (
                " AND (created_at < ? OR (created_at = ? AND message_id < ?))"
            )
            params.extend(
                [cursor["created_at"], cursor["created_at"], cursor["message_id"]]
            )
        rows = conn.execute(
            f"""
            SELECT * FROM study_messages
            WHERE thread_id=?{cursor_clause}
            ORDER BY created_at DESC,message_id DESC
            LIMIT ?
            """,
            (*params, bounded + 1),
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        message_ids = [str(row["message_id"]) for row in rows]
        attachment_rows = []
        if message_ids:
            placeholders = ",".join("?" for _ in message_ids)
            attachment_rows = conn.execute(
                f"""
                SELECT * FROM study_thread_attachments
                WHERE thread_id=? AND message_id IN ({placeholders})
                ORDER BY created_at,attachment_id
                """,
                (thread_id, *message_ids),
            ).fetchall()
    by_message: dict[str, list[dict[str, Any]]] = {}
    for row in attachment_rows:
        attachment = _attachment_row(row, include_extracted_text=False)
        by_message.setdefault(str(attachment["message_id"]), []).append(attachment)
    items = [
        {
            **_message_row(row),
            "attachments": by_message.get(str(row["message_id"]), []),
        }
        for row in reversed(rows)
    ]
    return {
        "items": items,
        "next_cursor": str(rows[-1]["message_id"]) if has_more and rows else None,
        "has_more": has_more,
    }


def rename_study_thread(
    home: Path,
    thread_id: str,
    *,
    title: str,
) -> dict[str, Any]:
    initialise_database(home)
    clean_title = " ".join(title.strip().split())[:120]
    if not clean_title:
        raise ValueError("Study thread title cannot be empty")
    now = _now()
    with connect(home) as conn:
        updated = conn.execute(
            """
            UPDATE study_threads
            SET title=?,updated_at=?
            WHERE thread_id=?
            """,
            (clean_title, now, thread_id),
        )
        if updated.rowcount != 1:
            raise ValueError("Study thread not found")
    return get_study_thread_overview(home, thread_id)


def delete_study_thread(home: Path, thread_id: str) -> dict[str, Any]:
    return delete_study_thread_data(home, thread_id)


def get_study_message(
    home: Path,
    message_id: str,
    *,
    include_attachments: bool = False,
) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM study_messages WHERE message_id=?", (message_id,)
        ).fetchone()
        attachment_rows = (
            conn.execute(
                """
                SELECT * FROM study_thread_attachments
                WHERE message_id=? ORDER BY created_at,attachment_id
                """,
                (message_id,),
            ).fetchall()
            if row and include_attachments
            else []
        )
    if not row:
        return None
    return {
        **_message_row(row),
        **(
            {
                "attachments": [
                    _attachment_row(item, include_extracted_text=False)
                    for item in attachment_rows
                ]
            }
            if include_attachments
            else {}
        ),
    }


def get_study_attachment(
    home: Path,
    thread_id: str,
    attachment_id: str,
) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            """
            SELECT * FROM study_thread_attachments
            WHERE thread_id=? AND attachment_id=?
            """,
            (thread_id, attachment_id),
        ).fetchone()
    return _attachment_row(row) if row else None


def list_study_attachments(
    home: Path,
    thread_id: str,
    *,
    include_extracted_text: bool = True,
) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT
              attachment_id,thread_id,message_id,original_name,stored_name,
              mime_type,file_kind,size_bytes,sha256,media_id,
              {"extracted_text" if include_extracted_text else "'' AS extracted_text"},
              extraction_status,created_at
            FROM study_thread_attachments
            WHERE thread_id=? ORDER BY created_at,attachment_id
            """,
            (thread_id,),
        ).fetchall()
    return [
        _attachment_row(row, include_extracted_text=include_extracted_text)
        for row in rows
    ]


def _first_user_message_id(home: Path, thread_id: str) -> str | None:
    with connect(home) as conn:
        row = conn.execute(
            """
            SELECT message_id FROM study_messages
            WHERE thread_id=? AND role='user'
            ORDER BY created_at,message_id LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
    return str(row["message_id"]) if row else None


def add_user_message(
    home: Path,
    thread_id: str,
    *,
    content: str,
    files: list[tuple[str, bytes, str | None] | StagedUpload],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread = get_study_thread_overview(home, thread_id)
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Describe what you want the IELTS teacher to explain")
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValueError("A message can contain at most 8 attachments")
    attachment_bytes = sum(_attachment_input_size(item) for item in files)
    if attachment_bytes > MAX_MESSAGE_BYTES:
        raise ValueError("Message attachments exceed the 60 MB limit")
    assert_local_storage_capacity(home, attachment_bytes)
    context = _validated_source_context(home, context or {})
    message_id = _id("message")
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_messages(
              message_id,thread_id,role,content,status,context_json,created_at
            ) VALUES(?,?,'user',?,'complete',?,?)
            """,
            (
                message_id,
                thread_id,
                clean_content,
                json.dumps(context, ensure_ascii=False),
                now,
            ),
        )
        conn.execute(
            "UPDATE study_threads SET updated_at=? WHERE thread_id=?",
            (now, thread_id),
        )
    stored_records: list[dict[str, Any]] = []
    try:
        for item in files:
            if isinstance(item, StagedUpload):
                original_name = item.original_name
                data: bytes | Path = item.path
                mime_type = item.mime_type
                size_bytes = item.size_bytes
                sha256 = item.sha256
            else:
                original_name, data, mime_type = item
                size_bytes = len(data)
                sha256 = hashlib.sha256(data).hexdigest()
            stored_records.append(_store_attachment(
                home,
                thread_id=thread_id,
                message_id=message_id,
                original_name=original_name,
                data=data,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=sha256,
            ))
    except Exception:
        media_ids = [
            str(item["media_id"]) for item in stored_records if item.get("media_id")
        ]
        with connect(home) as conn:
            for media_id in media_ids:
                conn.execute(
                    "DELETE FROM media_bindings WHERE media_id=?", (media_id,)
                )
            conn.execute(
                "DELETE FROM study_messages WHERE message_id=?", (message_id,)
            )
        attachment_root = (home / "study-threads" / thread_id / "attachments").resolve()
        for item in stored_records:
            if item.get("stored_name"):
                path = (attachment_root / str(item["stored_name"])).resolve()
                if path.parent == attachment_root:
                    path.unlink(missing_ok=True)
        purge_unreferenced_media(home, media_ids=media_ids)
        invalidate_storage_usage(home)
        raise
    refresh_study_thread_summary(home, thread_id)
    return get_study_message(
        home, message_id, include_attachments=True
    ) or {"message_id": message_id, "thread_id": str(thread["thread_id"])}


def add_assistant_message(
    home: Path,
    *,
    thread_id: str,
    result: dict[str, Any],
    agent_run_id: str,
) -> dict[str, Any]:
    with connect(home) as conn:
        existing = conn.execute(
            """
            SELECT message_id
            FROM study_messages
            WHERE agent_run_id=? AND role='assistant'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (agent_run_id,),
        ).fetchone()
    if existing:
        return get_study_message(home, str(existing["message_id"])) or {}

    message_id = f"message:agent:{agent_run_id}"
    now = _now()
    content = str(result.get("summary") or result.get("next_action") or "讲解已完成")
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_messages(
              message_id,thread_id,role,content,status,context_json,
              agent_run_id,created_at
            ) VALUES(?,?,'assistant',?,'complete',?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET
              content=excluded.content,
              status='complete',
              context_json=excluded.context_json,
              agent_run_id=excluded.agent_run_id
            """,
            (
                message_id,
                thread_id,
                content,
                json.dumps({"result": result}, ensure_ascii=False),
                agent_run_id,
                now,
            ),
        )
        conn.execute(
            "UPDATE study_threads SET updated_at=? WHERE thread_id=?",
            (now, thread_id),
        )
    refresh_study_thread_summary(home, thread_id)
    return get_study_message(home, message_id) or {}


def study_thread_agent_context(
    home: Path,
    *,
    thread_id: str,
    message_id: str,
) -> dict[str, Any]:
    thread = get_study_thread_overview(home, thread_id)
    message = get_study_message(home, message_id)
    if not message or message["role"] != "user":
        raise ValueError("Study thread user message not found")
    if message["thread_id"] != thread_id:
        raise ValueError("Study thread user message not found")
    summary = refresh_study_thread_summary(home, thread_id)
    recent_page = list_study_messages_page(
        home, thread_id, limit=LIVE_CONTEXT_MESSAGES
    )
    recent = recent_page["items"]
    attachments = list_study_attachments(home, thread_id)
    first_user_message_id = _first_user_message_id(home, thread_id)
    prioritised_attachments = _prioritised_attachments(
        attachments,
        message_id=message_id,
        first_user_message_id=first_user_message_id,
    )
    summary_payload = (
        {
            "summary": summary["summary"],
            "message_count": summary["message_count"],
            "through_message_id": summary.get("through_message_id"),
        }
        if summary
        else None
    )
    retrieved_history = [
        item
        for item in search_learning_history(home, str(message["content"]), limit=5)
        if str(item.get("source_id")) != message_id
    ][:4]
    return assemble_tutor_context(
        thread=thread,
        user_message=message,
        recent_messages=recent,
        prioritised_attachments=prioritised_attachments,
        conversation_summary=summary_payload,
        retrieved_history=retrieved_history,
        budget=ContextBudget(
            recent_message_limit=LIVE_CONTEXT_MESSAGES,
            recent_char_limit=MAX_RECENT_CONTEXT_CHARS,
            attachment_char_limit=MAX_THREAD_CONTEXT_TEXT,
            attachment_item_limit=MAX_THREAD_IMAGES,
            per_attachment_char_limit=MAX_EXTRACTED_TEXT,
        ),
    )


def refresh_study_thread_summary(
    home: Path,
    thread_id: str,
) -> dict[str, Any] | None:
    """Keep stable opening anchors plus a bounded recent-history digest."""
    with connect(home) as conn:
        total = int(
            conn.execute(
                "SELECT COUNT(*) FROM study_messages WHERE thread_id=?",
                (thread_id,),
            ).fetchone()[0]
        )
        if total <= LIVE_CONTEXT_MESSAGES:
            return get_thread_summary(home, thread_id)
        archived_count = total - LIVE_CONTEXT_MESSAGES
        existing = get_thread_summary(home, thread_id)
        if existing and int(existing["message_count"]) == archived_count:
            return existing
        anchors = conn.execute(
            """
            SELECT message_id,role,content,created_at
            FROM study_messages
            WHERE thread_id=?
            ORDER BY created_at,message_id
            LIMIT ?
            """,
            (thread_id, min(SUMMARY_ANCHOR_MESSAGES, archived_count)),
        ).fetchall()
        recent_archived_desc = conn.execute(
            """
            SELECT message_id,role,content,created_at
            FROM study_messages
            WHERE thread_id=?
            ORDER BY created_at DESC,message_id DESC
            LIMIT ? OFFSET ?
            """,
            (thread_id, SUMMARY_RECENT_MESSAGES, LIVE_CONTEXT_MESSAGES),
        ).fetchall()
    recent_archived = list(reversed(recent_archived_desc))
    seen: set[str] = set()
    selected = []
    for row in [*anchors, *recent_archived]:
        row_id = str(row["message_id"])
        if row_id not in seen:
            selected.append(row)
            seen.add(row_id)
    parts = ["【对话起点与长期目标】"]
    remaining = SUMMARY_MAX_CHARS
    anchor_ids = {str(row["message_id"]) for row in anchors}
    recent_heading_added = False
    for row in selected:
        if str(row["message_id"]) not in anchor_ids and not recent_heading_added:
            parts.append("【最近的阶段性进展】")
            recent_heading_added = True
        role = "学习者" if row["role"] == "user" else "英语教师"
        content = " ".join(str(row["content"]).split())
        excerpt = content[: min(320, remaining)]
        if not excerpt:
            continue
        parts.append(f"{role}：{excerpt}")
        remaining -= len(excerpt)
        if remaining <= 0:
            break
    if not parts:
        return existing
    return save_thread_summary(
        home,
        thread_id=thread_id,
        summary="\n".join(parts),
        message_count=archived_count,
        through_message_id=(
            str(recent_archived[-1]["message_id"]) if recent_archived else None
        ),
    )


def thread_media_ids(
    home: Path,
    thread_id: str,
    *,
    message_id: str | None = None,
) -> list[str]:
    attachments = list_study_attachments(
        home, thread_id, include_extracted_text=False
    )
    attachments = (
        _prioritised_attachments(
            attachments,
            message_id=message_id,
            first_user_message_id=_first_user_message_id(home, thread_id),
        )
        if message_id
        else list(reversed(attachments))
    )
    return [
        str(item["media_id"])
        for item in attachments
        if item.get("media_id")
    ][:MAX_THREAD_IMAGES]


def _prioritised_attachments(
    attachments: list[dict[str, Any]],
    *,
    message_id: str | None,
    first_user_message_id: str | None,
) -> list[dict[str, Any]]:
    priority_message_ids = [
        value
        for value in (
            message_id,
            first_user_message_id,
        )
        if value
    ]
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for priority_id in priority_message_ids:
        for attachment in attachments:
            if attachment.get("message_id") == priority_id:
                attachment_id = str(attachment["attachment_id"])
                if attachment_id not in seen:
                    ordered.append(attachment)
                    seen.add(attachment_id)
    for attachment in reversed(attachments):
        attachment_id = str(attachment["attachment_id"])
        if attachment_id not in seen:
            ordered.append(attachment)
            seen.add(attachment_id)
    return ordered


def promote_study_thread(home: Path, thread_id: str) -> dict[str, Any]:
    thread = get_study_thread_overview(home, thread_id)
    attachments = list_study_attachments(home, thread_id)
    if not attachments:
        raise ValueError("Add at least one source file before creating a practice draft")
    payloads: list[tuple[str, bytes, str | None]] = []
    for attachment in attachments:
        path = resolve_study_attachment(home, attachment)
        payloads.append(
            (
                str(attachment["original_name"]),
                path.read_bytes(),
                attachment.get("mime_type"),
            )
        )
    return create_import(
        home,
        title=f"{thread['title']} · 练习草稿",
        source_type="personal",
        authenticity="unreviewed",
        rights_status="local_private",
        files=payloads,
    )


def resolve_study_attachment(home: Path, attachment: dict[str, Any]) -> Path:
    if attachment.get("media_id"):
        _, path = resolve_media_file(home, str(attachment["media_id"]))
        return path
    stored_name = str(attachment.get("stored_name") or "")
    thread_id = str(attachment["thread_id"])
    root = (home / "study-threads" / thread_id / "attachments").resolve()
    path = (root / stored_name).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Study attachment is missing or outside the data home")
    return path


def _store_attachment(
    home: Path,
    *,
    thread_id: str,
    message_id: str,
    original_name: str,
    data: bytes | Path,
    mime_type: str | None,
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    measured_size = int(
        size_bytes
        if size_bytes is not None
        else data.stat().st_size
        if isinstance(data, Path)
        else len(data)
    )
    if measured_size > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"Attachment exceeds the 25 MB limit: {original_name}")
    clean_name = _safe_name(original_name)
    suffix = Path(clean_name).suffix.casefold()
    if suffix not in ALLOWED_ATTACHMENT_SUFFIXES:
        raise ValueError(
            "Supported attachments: PNG, JPG, WEBP, PDF, TXT, Markdown and DOCX"
        )
    attachment_id = _id("attachment")
    digest = sha256 or (
        hash_file(data) if isinstance(data, Path) else hashlib.sha256(data).hexdigest()
    )
    media_id: str | None = None
    stored_name: str | None = None
    extracted_text = ""
    extraction_status = "not_applicable"
    if suffix in IMAGE_SUFFIXES:
        asset = import_image_bytes(
            home,
            data.read_bytes() if isinstance(data, Path) else data,
            alt_text=f"Study material: {clean_name}",
            owner_type="study_thread",
            owner_id=thread_id,
        )
        media_id = str(asset["media_id"])
        file_kind = "image"
        extraction_status = "visual_only"
    else:
        file_kind = {
            ".pdf": "pdf",
            ".docx": "document",
            ".txt": "text",
            ".md": "text",
        }[suffix]
        stored_name = f"{attachment_id}{suffix}"
        target = home / "study-threads" / thread_id / "attachments"
        target.mkdir(parents=True, exist_ok=True)
        path = (target / stored_name).resolve()
        if path.parent != target.resolve():
            raise ValueError("Unsafe attachment path")
        if isinstance(data, Path):
            copy_file_atomic(data, path)
        else:
            path.write_bytes(data)
        invalidate_storage_usage(home)
        extracted_text, extraction_status = _extract_text(path, suffix)
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_thread_attachments(
              attachment_id,thread_id,message_id,original_name,stored_name,
              mime_type,file_kind,size_bytes,sha256,media_id,extracted_text,
              extraction_status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                attachment_id,
                thread_id,
                message_id,
                clean_name,
                stored_name,
                mime_type,
                file_kind,
                measured_size,
                digest,
                media_id,
                extracted_text,
                extraction_status,
                now,
            ),
        )
    return {
        "attachment_id": attachment_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "original_name": clean_name,
        "stored_name": stored_name,
        "mime_type": mime_type,
        "file_kind": file_kind,
        "size_bytes": measured_size,
        "sha256": digest,
        "media_id": media_id,
        "extracted_text": extracted_text,
        "extraction_status": extraction_status,
        "created_at": now,
    }


def _attachment_input_size(
    item: tuple[str, bytes, str | None] | StagedUpload,
) -> int:
    return item.size_bytes if isinstance(item, StagedUpload) else len(item[1])


def _extract_text(path: Path, suffix: str) -> tuple[str, str]:
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="replace")[
                :MAX_EXTRACTED_TEXT
            ], "text_available"
        if suffix == ".docx":
            xml = read_zip_member(path, "word/document.xml")
            root = ElementTree.fromstring(xml)
            text = "\n".join(
                item.text or ""
                for item in root.iter()
                if item.tag.endswith("}t")
            )
            return text[:MAX_EXTRACTED_TEXT], (
                "text_available" if text.strip() else "text_unavailable"
            )
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted and reader.decrypt("") == 0:
                return "", "password_required"
            chunks: list[str] = []
            for page in reader.pages[:40]:
                chunks.append(page.extract_text() or "")
                if sum(len(item) for item in chunks) >= MAX_EXTRACTED_TEXT:
                    break
            text = "\n\n".join(chunks)[:MAX_EXTRACTED_TEXT]
            return text, "text_available" if text.strip() else "ocr_required"
    except Exception:
        return "", "extraction_failed"
    return "", "not_applicable"


def _validated_source_context(
    home: Path, context: dict[str, Any]
) -> dict[str, Any]:
    clean = dict(context)
    passage_id = clean.get("passage_id")
    quote = str(clean.get("quote") or "").strip()
    if passage_id and quote:
        reading_set = show_reading_set(home, str(passage_id), include_answers=False)
        if not reading_set:
            raise ValueError("Reading passage not found")
        passage = reading_set["passage"]
        body = str(passage.get("body") or "")
        anchor = create_text_anchor(
            body,
            quote,
            document_kind="reading_passage",
            document_id=str(passage_id),
            occurrence=int(clean.get("occurrence") or 1),
        )
        radius = 500
        clean.update(
            {
                "anchor": anchor,
                "passage_title": passage.get("title"),
                "passage_excerpt": body[
                    max(0, anchor["start"] - radius) : min(
                        len(body), anchor["end"] + radius
                    )
                ],
            }
        )
    return clean


def _safe_name(value: str) -> str:
    name = Path(value or "attachment").name
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name).strip(" .")
    return name[:160] or "attachment"


def _thread_row(
    row: Any,
    *,
    messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    latest_message = messages[-1]["content"] if messages else ""
    preview = (
        row["last_message_preview"]
        if "last_message_preview" in keys
        else latest_message
    )
    return {
        "thread_id": row["thread_id"],
        "title": row["title"],
        "module": row["module"],
        "track_id": row["track_id"] if "track_id" in keys else DEFAULT_TRACK_ID,
        "status": row["status"],
        "model_provider_id": row["model_provider_id"],
        "source_context": json.loads(row["source_context_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "messages": messages,
        "attachments": attachments,
        "message_count": (
            int(row["message_count"])
            if "message_count" in keys
            else len(messages)
        ),
        "attachment_count": (
            int(row["attachment_count"])
            if "attachment_count" in keys
            else len(attachments)
        ),
        "last_message_preview": " ".join(str(preview or "").split())[:180],
    }


def _message_row(row: Any) -> dict[str, Any]:
    return {
        "message_id": row["message_id"],
        "thread_id": row["thread_id"],
        "role": row["role"],
        "content": row["content"],
        "status": row["status"],
        "context": json.loads(row["context_json"] or "{}"),
        "agent_run_id": row["agent_run_id"],
        "created_at": row["created_at"],
    }


def _attachment_row(
    row: Any,
    *,
    include_extracted_text: bool = True,
) -> dict[str, Any]:
    attachment = {
        "attachment_id": row["attachment_id"],
        "thread_id": row["thread_id"],
        "message_id": row["message_id"],
        "original_name": row["original_name"],
        "stored_name": row["stored_name"],
        "mime_type": row["mime_type"],
        "file_kind": row["file_kind"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "media_id": row["media_id"],
        "extraction_status": row["extraction_status"],
        "created_at": row["created_at"],
    }
    if include_extracted_text:
        attachment["extracted_text"] = row["extracted_text"]
    return attachment
