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

from .content_imports import create_import
from .media import import_image_bytes, resolve_media_file
from .question_bank import show_reading_set
from .storage import connect, initialise_database
from .text_anchor import create_text_anchor


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
MAX_THREAD_CONTEXT_TEXT = 120_000
MAX_THREAD_IMAGES = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def create_study_thread(
    home: Path,
    *,
    title: str,
    module: str = "mixed",
    model_provider_id: str | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialise_database(home)
    if module not in {"reading", "writing", "mixed"}:
        raise ValueError("Study thread module must be reading, writing or mixed")
    clean_title = " ".join(title.strip().split())[:120] or "新的 IELTS 学习对话"
    thread_id = _id("thread")
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_threads(
              thread_id,title,module,status,model_provider_id,
              source_context_json,created_at,updated_at
            ) VALUES(?,?,?,'active',?,?,?,?)
            """,
            (
                thread_id,
                clean_title,
                module,
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
    return _thread_row(row, messages=messages, attachments=attachments)


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
    return get_study_thread(home, thread_id)


def delete_study_thread(home: Path, thread_id: str) -> dict[str, Any]:
    initialise_database(home)
    storage_root = (home / "study-threads").resolve()
    thread_storage = (storage_root / thread_id).resolve()
    if thread_storage.parent != storage_root:
        raise ValueError("Unsafe study thread path")
    with connect(home) as conn:
        row = conn.execute(
            "SELECT thread_id FROM study_threads WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        if not row:
            raise ValueError("Study thread not found")
        conn.execute("DELETE FROM study_threads WHERE thread_id=?", (thread_id,))
    if thread_storage.is_dir():
        shutil.rmtree(thread_storage)
    return {"thread_id": thread_id, "deleted": True}


def get_study_message(home: Path, message_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM study_messages WHERE message_id=?", (message_id,)
        ).fetchone()
    return _message_row(row) if row else None


def add_user_message(
    home: Path,
    thread_id: str,
    *,
    content: str,
    files: list[tuple[str, bytes, str | None]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread = get_study_thread(home, thread_id)
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Describe what you want the IELTS teacher to explain")
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValueError("A message can contain at most 8 attachments")
    if sum(len(data) for _, data, _ in files) > MAX_MESSAGE_BYTES:
        raise ValueError("Message attachments exceed the 60 MB limit")
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
    try:
        for original_name, data, mime_type in files:
            _store_attachment(
                home,
                thread_id=thread_id,
                message_id=message_id,
                original_name=original_name,
                data=data,
                mime_type=mime_type,
            )
    except Exception:
        with connect(home) as conn:
            conn.execute(
                "DELETE FROM study_messages WHERE message_id=?", (message_id,)
            )
        raise
    updated = get_study_thread(home, str(thread["thread_id"]))
    return next(
        item for item in updated["messages"] if item["message_id"] == message_id
    )


def add_assistant_message(
    home: Path,
    *,
    thread_id: str,
    result: dict[str, Any],
    agent_run_id: str,
) -> dict[str, Any]:
    message_id = _id("message")
    now = _now()
    content = str(result.get("summary") or result.get("next_action") or "讲解已完成")
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_messages(
              message_id,thread_id,role,content,status,context_json,
              agent_run_id,created_at
            ) VALUES(?,?,'assistant',?,'complete',?,?,?)
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
    return get_study_message(home, message_id) or {}


def study_thread_agent_context(
    home: Path,
    *,
    thread_id: str,
    message_id: str,
) -> dict[str, Any]:
    thread = get_study_thread(home, thread_id)
    message = next(
        (item for item in thread["messages"] if item["message_id"] == message_id),
        None,
    )
    if not message or message["role"] != "user":
        raise ValueError("Study thread user message not found")
    recent = thread["messages"][-12:]
    extracted: list[dict[str, Any]] = []
    remaining_chars = MAX_THREAD_CONTEXT_TEXT
    for attachment in _prioritised_attachments(thread, message_id):
        text = str(attachment.get("extracted_text") or "").strip()
        if text and remaining_chars > 0:
            excerpt = text[: min(MAX_EXTRACTED_TEXT, remaining_chars)]
            extracted.append(
                {
                    "attachment_id": attachment["attachment_id"],
                    "name": attachment["original_name"],
                    "text": excerpt,
                    "extraction_status": attachment["extraction_status"],
                }
            )
            remaining_chars -= len(excerpt)
    return {
        "thread_id": thread_id,
        "module": thread["module"],
        "mode": "material_dialogue",
        "user_request": message["content"],
        "source_context": message.get("context") or {},
        "conversation": [
            {
                "role": item["role"],
                "content": item["content"],
                "result": (
                    item.get("context", {}).get("result")
                    if item["role"] == "assistant"
                    else None
                ),
            }
            for item in recent
        ],
        "attachment_text": extracted,
        "material_evidence_sufficient": bool(extracted or thread["attachments"]),
    }


def thread_media_ids(
    home: Path,
    thread_id: str,
    *,
    message_id: str | None = None,
) -> list[str]:
    thread = get_study_thread(home, thread_id)
    attachments = (
        _prioritised_attachments(thread, message_id)
        if message_id
        else list(reversed(thread["attachments"]))
    )
    return [
        str(item["media_id"])
        for item in attachments
        if item.get("media_id")
    ][:MAX_THREAD_IMAGES]


def _prioritised_attachments(
    thread: dict[str, Any],
    message_id: str | None,
) -> list[dict[str, Any]]:
    attachments = list(thread.get("attachments") or [])
    first_user_message = next(
        (
            item
            for item in thread.get("messages") or []
            if item.get("role") == "user"
        ),
        None,
    )
    priority_message_ids = [
        value
        for value in (
            message_id,
            first_user_message.get("message_id") if first_user_message else None,
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
    thread = get_study_thread(home, thread_id)
    if not thread["attachments"]:
        raise ValueError("Add at least one source file before creating a practice draft")
    payloads: list[tuple[str, bytes, str | None]] = []
    for attachment in thread["attachments"]:
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
    data: bytes,
    mime_type: str | None,
) -> dict[str, Any]:
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"Attachment exceeds the 25 MB limit: {original_name}")
    clean_name = _safe_name(original_name)
    suffix = Path(clean_name).suffix.casefold()
    if suffix not in ALLOWED_ATTACHMENT_SUFFIXES:
        raise ValueError(
            "Supported attachments: PNG, JPG, WEBP, PDF, TXT, Markdown and DOCX"
        )
    attachment_id = _id("attachment")
    sha256 = hashlib.sha256(data).hexdigest()
    media_id: str | None = None
    stored_name: str | None = None
    extracted_text = ""
    extraction_status = "not_applicable"
    if suffix in IMAGE_SUFFIXES:
        asset = import_image_bytes(
            home,
            data,
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
        path.write_bytes(data)
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
                len(data),
                sha256,
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
        "size_bytes": len(data),
        "sha256": sha256,
        "media_id": media_id,
        "extracted_text": extracted_text,
        "extraction_status": extraction_status,
        "created_at": now,
    }


def _extract_text(path: Path, suffix: str) -> tuple[str, str]:
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="replace")[
                :MAX_EXTRACTED_TEXT
            ], "text_available"
        if suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
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


def _attachment_row(row: Any) -> dict[str, Any]:
    return {
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
        "extracted_text": row["extracted_text"],
        "extraction_status": row["extraction_status"],
        "created_at": row["created_at"],
    }
