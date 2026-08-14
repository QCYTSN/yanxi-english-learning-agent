"""Build the bundled high-frequency vocabulary enrichment presets.

Combines the project's own public-domain/MIT word-form lists with open
dictionary data (ECDICT, MIT-licensed aggregation) so high-frequency word
cards carry phonetic, part of speech, definitions and inflections offline.

Usage:
    python scripts/build_vocab_presets.py --csv path/to/ecdict.csv

The output lands in src/ielts_coach/resources/words/enrichments/ and ships
inside wheels. Attribution updates belong in THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

EXCHANGE_TO_FORM = {
    "p": "past",
    "d": "past",
    "i": "present_participle",
    "3": "third_person",
    "s": "plural",
    "r": "comparative",
    "t": "superlative",
    "0": "base",
    "1": "base",
}

SEED_FILES = (
    "yanxi-starter-100.json",
    "yanxi-frequency-3000.json",
)


def _words(root: Path) -> dict[str, str]:
    """Return {word: yanxi_level} for the bundled high-frequency lists."""
    collected: dict[str, str] = {}
    for name in SEED_FILES:
        payload = json.loads((root / "words" / name).read_text(encoding="utf-8"))
        for item in payload.get("words") or []:
            word = str(item.get("word") or "").strip()
            if word and word not in collected:
                collected[word] = str(item.get("yanxi_level") or "")
    return collected


_POS_PREFIXES = (
    "adj.",
    "adv.",
    "n.",
    "v.",
    "vt.",
    "vi.",
    "prep.",
    "conj.",
    "pron.",
    "int.",
    "num.",
    "art.",
    "aux.",
    "abbr.",
)


def _infer_pos(definition: str) -> str | None:
    found: set[str] = set()
    for line in definition.split("\n"):
        lowered = line.strip().casefold()
        for prefix in _POS_PREFIXES:
            if lowered.startswith(prefix):
                found.add(prefix)
                break
    return "/".join(sorted(found)) if found else None


def _parse_exchange(exchange: str) -> dict[str, str]:
    forms: dict[str, str] = {}
    for part in str(exchange or "").split("/"):
        if ":" not in part:
            continue
        code, _, value = part.partition(":")
        key = EXCHANGE_TO_FORM.get(code.strip())
        value = value.strip()
        if key and value and key not in forms:
            forms[key] = value
    return forms


def build(csv_path: Path, root: Path) -> Path:
    wanted = _words(root)
    output_dir = root / "words" / "enrichments"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "yanxi-presets-high-freq.jsonl"
    written = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle, output.open(
        "w", encoding="utf-8"
    ) as target:
        for row in csv.DictReader(handle):
            word = str(row.get("word") or "").strip()
            level = wanted.get(word)
            if level is None:
                continue
            definition = str(row.get("definition") or "").strip()
            translation = str(row.get("translation") or "").strip()
            entry = {
                "word": word,
                "yanxi_level": level,
                "ipa_uk": str(row.get("phonetic") or "").strip() or None,
                "ipa_us": None,
                "pos": str(row.get("pos") or "").strip()
                or _infer_pos(definition),
                "definitions": [
                    item
                    for item in (
                        {"text": definition, "language": "en"} if definition else None,
                        {"text": translation, "language": "zh"} if translation else None,
                    )
                    if item
                ],
                "examples": [],
                "synonyms": [],
                "antonyms": [],
                "forms": _parse_exchange(str(row.get("exchange") or "")),
                "source": "ecdict-mit",
            }
            target.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1
    print(f"presets written: {written} entries -> {output.relative_to(root)}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    build(args.csv, Path(__file__).resolve().parents[1] / "src" / "ielts_coach" / "resources")


if __name__ == "__main__":
    main()
