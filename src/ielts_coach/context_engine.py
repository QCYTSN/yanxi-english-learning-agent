from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextBudget:
    recent_message_limit: int
    recent_char_limit: int
    attachment_char_limit: int
    attachment_item_limit: int = 8
    per_attachment_char_limit: int = 80_000


def assemble_tutor_context(
    *,
    thread: dict[str, Any],
    user_message: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    prioritised_attachments: list[dict[str, Any]],
    conversation_summary: dict[str, Any] | None,
    budget: ContextBudget,
    retrieved_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile a bounded, auditable context envelope for the Tutor Runtime.

    This function is deliberately free of storage and provider code. It makes
    context selection deterministic, testable and identical for every model
    provider.
    """

    extracted: list[dict[str, Any]] = []
    attachment_chars_remaining = max(0, budget.attachment_char_limit)
    omitted_attachments = 0
    for attachment in prioritised_attachments[: budget.attachment_item_limit]:
        text = str(attachment.get("extracted_text") or "").strip()
        if not text or attachment_chars_remaining <= 0:
            omitted_attachments += 1
            continue
        excerpt = text[
            : min(budget.per_attachment_char_limit, attachment_chars_remaining)
        ]
        extracted.append(
            {
                "attachment_id": attachment["attachment_id"],
                "name": attachment["original_name"],
                "text": excerpt,
                "extraction_status": attachment["extraction_status"],
            }
        )
        attachment_chars_remaining -= len(excerpt)
    omitted_attachments += max(
        0, len(prioritised_attachments) - budget.attachment_item_limit
    )

    conversation: list[dict[str, Any]] = []
    recent_chars_remaining = max(0, budget.recent_char_limit)
    truncated_messages = 0
    selected_messages = recent_messages[: budget.recent_message_limit]
    for item in reversed(selected_messages):
        if recent_chars_remaining <= 0:
            truncated_messages += 1
            continue
        content = str(item.get("content") or "")
        excerpt = content[:recent_chars_remaining]
        if len(excerpt) < len(content):
            truncated_messages += 1
        if not excerpt:
            continue
        result = (item.get("context") or {}).get("result")
        compact_result = (
            {
                key: result.get(key)
                for key in (
                    "summary",
                    "next_action",
                    "answer_status",
                    "evidence_status",
                )
                if result.get(key) is not None
            }
            if item.get("role") == "assistant" and isinstance(result, dict)
            else None
        )
        conversation.insert(
            0,
            {
                "message_id": item.get("message_id"),
                "role": item["role"],
                "content": excerpt,
                "result": compact_result,
            },
        )
        recent_chars_remaining -= len(excerpt)

    history = [
        {
            "source_type": item.get("source_type"),
            "source_id": item.get("source_id"),
            "title": item.get("title"),
            "content": str(item.get("content") or "")[:1200],
            "created_at": item.get("created_at"),
        }
        for item in (retrieved_history or [])[:8]
    ]
    learning_state = thread.get("learning_state")
    context: dict[str, Any] = {
        "context_version": 3,
        "thread_id": thread["thread_id"],
        "module": thread["module"],
        "mode": "material_dialogue",
        "user_request": user_message["content"],
        "source_context": user_message.get("context") or {},
        "conversation": conversation,
        "conversation_summary": conversation_summary,
        "attachment_text": extracted,
        "retrieved_history": history,
        "material_evidence_sufficient": bool(extracted or prioritised_attachments),
        "learning_state": learning_state,
        "pending_proposals": thread.get("proposals") or [],
        "context_budget": {
            "recent_message_limit": budget.recent_message_limit,
            "recent_char_limit": budget.recent_char_limit,
            "recent_chars_used": sum(
                len(str(item["content"])) for item in conversation
            ),
            "attachment_char_limit": budget.attachment_char_limit,
            "attachment_chars_used": sum(len(item["text"]) for item in extracted),
        },
        "thread_memory": {
            "rolling_summary": conversation_summary,
            "learning_state": learning_state,
        },
        "context_trace": {
            "policy": "bounded-tutor-context@3",
            "selected_message_ids": [
                item.get("message_id") for item in conversation if item.get("message_id")
            ],
            "selected_attachment_ids": [
                item["attachment_id"] for item in extracted
            ],
            "retrieved_history_refs": [
                f"{item.get('source_type')}:{item.get('source_id')}" for item in history
            ],
            "truncated_message_count": truncated_messages,
            "omitted_attachment_count": omitted_attachments,
        },
    }
    fingerprint_source = {
        key: context[key]
        for key in (
            "context_version",
            "thread_id",
            "module",
            "user_request",
            "conversation",
            "conversation_summary",
            "attachment_text",
            "retrieved_history",
            "learning_state",
        )
    }
    context["context_trace"]["context_fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return context
