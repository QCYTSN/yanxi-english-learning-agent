"""Bundled starter word lists for typing practice and cold start.

Two sources, both copyright-safe for public builds:

- ``yanxi-starter-100.json`` — public-domain General Service List (West
  1953), top-100 band, self-assessed A1.
- ``yanxi-frequency-3000.json`` — FrequencyWords ``en_50k`` (hermitdave,
  MIT), top-3000 by corpus frequency, heuristic A1/A1-A2/B1 bands.

Word forms and a 言蹊 self-assessed level band only — no definitions,
examples or commercial dictionary content. Definitions are generated live
by the BYO-API model when a learner asks.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

_SEED_PATHS = (
    "words/yanxi-starter-100.json",
    "words/yanxi-frequency-3000.json",
)


def _read_bundle(name: str) -> dict[str, Any]:
    try:
        with resources.files("ielts_coach.resources").joinpath(name).open(
            "r", encoding="utf-8"
        ) as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        # Fall back to the source checkout when running from a repo checkout.
        root = Path(__file__).resolve().parents[1] / "ielts_coach" / "resources"
        with (root / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)


def load_seed_words() -> list[dict[str, Any]]:
    """Return the bundled starter words, GSL starter first, deduplicated."""
    words: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in _SEED_PATHS:
        for item in list(_read_bundle(name).get("words") or []):
            word = str(item.get("word") or "").casefold()
            if not word or word in seen:
                continue
            seen.add(word)
            words.append(item)
    return words


def seed_metadata() -> dict[str, Any]:
    """Return the seed's combined title, source and band note for the UI."""
    bundles = [_read_bundle(name) for name in _SEED_PATHS]
    return {
        "seed_id": bundles[0].get("seed_id"),
        "title": "言蹊起步词表 · 高频 3000",
        "level_note": bundles[0].get("level_note"),
        "bands": bundles[0].get("bands"),
        "source": [
            {
                "origin": bundle.get("source", {}).get("origin"),
                "rights": bundle.get("source", {}).get("rights"),
            }
            for bundle in bundles
        ],
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
