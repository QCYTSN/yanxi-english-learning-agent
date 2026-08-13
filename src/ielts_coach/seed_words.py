"""Bundled starter word list for typing practice and cold start.

The seed is a public-domain frequency list (General Service List, West 1953,
top-100 band). It carries word forms and a 言蹊 self-assessed level band only —
no definitions, examples or commercial dictionary content. Definitions are
generated live by the BYO-API model when a learner asks, so the bundle stays
copyright-safe for public builds.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

_SEED_PATH = "words/yanxi-starter-100.json"


def load_seed_words() -> list[dict[str, Any]]:
    """Return the bundled starter words with their 言蹊 level band."""
    try:
        with resources.files("ielts_coach.resources").joinpath(_SEED_PATH).open(
            "r", encoding="utf-8"
        ) as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        # Fall back to the source checkout when running from a repo checkout.
        root = Path(__file__).resolve().parents[1] / "ielts_coach" / "resources"
        with (root / _SEED_PATH).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    return list(data.get("words") or [])


def seed_metadata() -> dict[str, Any]:
    """Return the seed's title, source and band note for the UI."""
    try:
        with resources.files("ielts_coach.resources").joinpath(_SEED_PATH).open(
            "r", encoding="utf-8"
        ) as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        root = Path(__file__).resolve().parents[1] / "ielts_coach" / "resources"
        with (root / _SEED_PATH).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    return {
        "seed_id": data.get("seed_id"),
        "title": data.get("title"),
        "level_note": data.get("level_note"),
        "bands": data.get("bands"),
        "source": data.get("source"),
    }


def seed_words_pool(
    *,
    limit: int | None = None,
    level: str | None = None,
    exclude: set[str] | None = None,
) -> list[str]:
    """Words for typing practice, filtered by optional level and excludes."""
    words = load_seed_words()
    selected = [
        str(item["word"])
        for item in words
        if (level is None or str(item.get("yanxi_level", "A1")) == level)
        and (exclude is None or str(item["word"]) not in exclude)
    ]
    if limit is not None:
        selected = selected[: max(1, int(limit))]
    return selected
