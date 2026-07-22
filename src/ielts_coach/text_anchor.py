from __future__ import annotations

import hashlib
from typing import Any


def document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_text_anchor(
    text: str,
    quote: str,
    *,
    document_kind: str,
    document_id: str,
    occurrence: int = 1,
) -> dict[str, Any]:
    if not quote:
        raise ValueError("TextAnchor quote must not be empty")
    positions: list[int] = []
    cursor = 0
    while True:
        index = text.find(quote, cursor)
        if index < 0:
            break
        positions.append(index)
        cursor = index + max(1, len(quote))
    if occurrence < 1 or occurrence > len(positions):
        raise ValueError("TextAnchor quote occurrence does not exist in the document")
    start = positions[occurrence - 1]
    return {
        "anchor_version": 1,
        "document_kind": document_kind,
        "document_id": document_id,
        "quote": quote,
        "start": start,
        "end": start + len(quote),
        "offset_encoding": "unicode_code_points",
        "occurrence": occurrence,
        "document_hash": document_hash(text),
        "status": "resolved",
    }


def validate_text_anchor(anchor: dict[str, Any], text: str) -> dict[str, Any]:
    if anchor.get("offset_encoding") != "unicode_code_points":
        raise ValueError("TextAnchor offset_encoding must be unicode_code_points")
    if anchor.get("document_hash") != document_hash(text):
        raise ValueError("TextAnchor document_hash does not match the canonical document")
    start, end = int(anchor.get("start", -1)), int(anchor.get("end", -1))
    quote = str(anchor.get("quote", ""))
    if start < 0 or end < start or text[start:end] != quote:
        raise ValueError("TextAnchor offsets do not match quote")
    return anchor

