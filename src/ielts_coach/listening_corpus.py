from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from .storage import (
    get_listening_item,
    list_listening_items,
    listening_attempt_rows,
    upsert_listening_items,
)


REVIEW_INTERVAL_DAYS = (0, 1, 3, 7, 14, 30)


def install_starter_listening(home: Path) -> int:
    resource = resources.files("ielts_coach.resources").joinpath(
        "starter-corpus/listening-high-frequency.jsonl"
    )
    items: list[dict[str, Any]] = []
    for line_number, line in enumerate(resource.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"Invalid Listening starter item at line {line_number}")
        items.append(item)
    upsert_listening_items(home, items)
    return len(items)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def listening_progress(home: Path) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in listening_attempt_rows(home):
        if row.get("item_id"):
            grouped[str(row["item_id"])].append(row)
    now = datetime.now(timezone.utc)
    result: dict[str, dict[str, Any]] = {}
    for item_id, attempts in grouped.items():
        correct = sum(1 for item in attempts if item["is_correct"] is True)
        incorrect = sum(1 for item in attempts if item["is_correct"] is False)
        streak = 0
        for item in reversed(attempts):
            if item["is_correct"] is True:
                streak += 1
            else:
                break
        mastery = min(5, streak + (1 if correct >= 3 and correct > incorrect * 2 else 0))
        latest = max(
            (_parse_time(item["payload"].get("attempted_at")) for item in attempts),
            default=None,
            key=lambda value: value or datetime.min.replace(tzinfo=timezone.utc),
        )
        next_review = latest + timedelta(days=REVIEW_INTERVAL_DAYS[mastery]) if latest else now
        result[item_id] = {
            "attempts": len(attempts),
            "correct": correct,
            "incorrect": incorrect,
            "streak": streak,
            "mastery": mastery,
            "last_practised_at": latest.isoformat() if latest else None,
            "next_review_at": next_review.isoformat(),
            "due": next_review <= now,
        }
    return result


def browse_listening_items(
    home: Path,
    *,
    category: str | None = None,
    query: str | None = None,
    due_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    progress = listening_progress(home)
    items = []
    for item in list_listening_items(home, category=category, query=query, limit=1000):
        enriched = dict(item)
        enriched["progress"] = progress.get(
            str(item["item_id"]),
            {
                "attempts": 0,
                "correct": 0,
                "incorrect": 0,
                "streak": 0,
                "mastery": 0,
                "last_practised_at": None,
                "next_review_at": None,
                "due": True,
            },
        )
        if not due_only or enriched["progress"]["due"]:
            items.append(enriched)
    items.sort(
        key=lambda item: (
            not bool(item["progress"]["due"]),
            int(item["progress"]["mastery"]),
            int(item["progress"]["attempts"]),
            int(item.get("priority", 1)),
            str(item["item_id"]),
        )
    )
    return items[: max(1, min(int(limit), 1000))]


def listening_categories(home: Path) -> list[dict[str, Any]]:
    items = browse_listening_items(home, limit=1000)
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        category = str(item["category"])
        entry = grouped.setdefault(
            category,
            {
                "category": category,
                "label": item.get("category_label", category),
                "total": 0,
                "due": 0,
                "mastered": 0,
            },
        )
        entry["total"] += 1
        entry["due"] += int(bool(item["progress"]["due"]))
        entry["mastered"] += int(int(item["progress"]["mastery"]) >= 4)
    return list(grouped.values())


def listening_item(home: Path, item_id: str) -> dict[str, Any]:
    item = get_listening_item(home, item_id)
    if not item:
        raise ValueError(f"Unknown Listening item: {item_id}")
    return item


def normalise_listening_answer(value: str) -> str:
    return " ".join(
        "".join(character for character in value.casefold().strip() if character.isalnum() or character.isspace()).split()
    )
