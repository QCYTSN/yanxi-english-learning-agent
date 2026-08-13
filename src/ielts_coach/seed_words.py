"""Bundled starter word lists for typing practice and cold start.

Six sources, all copyright-safe for public builds:

- ``yanxi-starter-100.json`` — public-domain General Service List (West
  1953), top-100 band, self-assessed A1.
- ``yanxi-frequency-3000.json`` — FrequencyWords ``en_50k`` (hermitdave,
  MIT), top-3000 by corpus frequency, heuristic A1/A1-A2/B1 bands.
- ``yanxi-cet4.json`` / ``yanxi-cet6.json`` / ``yanxi-toefl.json`` — exam
  word forms (CET-4 / CET-6 / TOEFL) extracted from the KyleBing
  english-vocabulary list; word forms only, no definitions or examples.
- ``yanxi-ielts-academic.json`` — Academic Word List (Coxhead) 570-family
  headwords (TheoSeo93/Academic_Words_list, OSL-1.1), the recognised
  IELTS-academic core.

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
    "words/yanxi-cet4.json",
    "words/yanxi-cet6.json",
    "words/yanxi-toefl.json",
    "words/yanxi-ielts-academic.json",
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
    """Return the bundled starter words, GSL starter first, deduplicated.

    A word seen in several lists keeps its first-seen level band but unions
    the exam tags, so the 雅思/四六级/托福 labels survive deduplication.
    """
    words: list[dict[str, Any]] = []
    by_word: dict[str, dict[str, Any]] = {}
    for name in _SEED_PATHS:
        for item in list(_read_bundle(name).get("words") or []):
            word = str(item.get("word") or "").casefold()
            if not word:
                continue
            existing = by_word.get(word)
            if existing is None:
                entry = dict(item)
                entry["word"] = word
                by_word[word] = entry
                words.append(entry)
                continue
            tags = set(existing.get("tags") or [])
            tags.update(item.get("tags") or [])
            if tags:
                existing["tags"] = sorted(tags)
    return words


def seed_metadata() -> dict[str, Any]:
    """Return the seed's combined title, source and band note for the UI."""
    bundles = [_read_bundle(name) for name in _SEED_PATHS]
    return {
        "seed_id": bundles[0].get("seed_id"),
        "title": "言蹊词汇池 · 通用 + 考试词表",
        "level_note": bundles[0].get("level_note"),
        "bands": {str(len(bundle.get("words") or [])): bundle.get("bands") for bundle in bundles},
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
