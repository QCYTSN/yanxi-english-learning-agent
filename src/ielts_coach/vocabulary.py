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
    if status not in {"candidate", "learning", "mastered", "known", "dismissed"}:
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


def ingest_taught_words(
    home: Path,
    words: list[dict[str, Any]],
    *,
    agent_run_id: str,
    track_id: str = "general-english",
) -> list[dict[str, Any]]:
    """Auto-ingest words the tutor explained in conversation as candidates.

    Conversation-taught words enter the list with status ``candidate`` so the
    learner can confirm, undo or mark them as already known. Idempotent per
    (track, word): an existing row is never demoted — a mastered, known or
    dismissed word stays as it is, and a candidate is refreshed with any
    richer explanation from the newer turn.
    """
    ingested: list[dict[str, Any]] = []
    for item in words:
        word = str(item.get("word") or "").strip()
        if not word:
            continue
        meaning = item.get("meaning") or None
        usage = item.get("usage") or None
        example = item.get("example") or None
        collocations = [str(value) for value in (item.get("collocations") or [])]
        initialise_database(home)
        now = _now()
        item_id = f"vocab:{word.casefold()[:120]}"
        with connect(home) as conn:
            existing = conn.execute(
                "SELECT * FROM vocabulary_items WHERE track_id=? AND word=?",
                (track_id, word),
            ).fetchone()
            if existing:
                status = str(existing["status"])
                if status in {"mastered", "known", "dismissed"}:
                    continue
                conn.execute(
                    """
                    UPDATE vocabulary_items
                    SET meaning=COALESCE(?,meaning), usage=COALESCE(?,usage),
                        example=COALESCE(?,example),
                        collocations_json=?,
                        source_type='agent_dialogue',
                        source_id=?, status='candidate', updated_at=?
                    WHERE item_id=?
                    """,
                    (
                        meaning,
                        usage,
                        example,
                        json.dumps(collocations, ensure_ascii=False),
                        agent_run_id,
                        now,
                        existing["item_id"],
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM vocabulary_items WHERE item_id=?",
                    (existing["item_id"],),
                ).fetchone()
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
                        word,
                        meaning,
                        usage,
                        example,
                        json.dumps(collocations, ensure_ascii=False),
                        "agent_dialogue",
                        agent_run_id,
                        "candidate",
                        "sentence_recall",
                        None,
                        0,
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
                ).fetchone()
        ingested.append(_row(row))
    return ingested


def list_recent_ingests(
    home: Path,
    *,
    track_id: str = "general-english",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Recent conversation-ingested candidates, newest first, for undo UI."""
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM vocabulary_items
            WHERE track_id=? AND status='candidate' AND source_type='agent_dialogue'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (track_id, limit),
        ).fetchall()
    return [_row(row) for row in rows]


def undo_vocabulary_ingest(
    home: Path,
    item_id: str,
    *,
    track_id: str = "general-english",
) -> dict[str, Any]:
    """Remove a still-unconfirmed candidate that came from conversation."""
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=? AND track_id=?",
            (item_id, track_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown vocabulary item: {item_id}")
        if str(row["status"]) != "candidate":
            raise ValueError("Only unconfirmed candidate words can be undone")
        conn.execute(
            "DELETE FROM vocabulary_items WHERE item_id=? AND status='candidate'",
            (item_id,),
        )
    return {"item_id": item_id, "removed": True}


def record_typing_mistake(
    home: Path,
    word: str,
    *,
    track_id: str = "general-english",
) -> dict[str, Any]:
    """Feed a typing miss into the learner's memory so dialogue can reuse it.

    The mistake is stored as a ``spelling_weakness`` learner memory with a
    stable memory key per word: re-ingestion refreshes the same memory instead
    of duplicating it. The tutor context already surfaces active learner
    memories, so the next conversation can explain the word proactively.

    It also closes the practice loop: the word gets a short review due in one
    day, and a word marked mastered/known that is misspelled drops back to
    ``learning`` so the due-review query will pick it up again.
    """
    from .storage import create_learner_memory

    word = str(word or "").strip().casefold()
    if not word:
        raise ValueError("A typing mistake needs a word")
    initialise_database(home)
    memory = create_learner_memory(
        home,
        memory_type="spelling_weakness",
        memory_key=f"typing:{word}",
        statement=f"Learner often misspells \"{word}\" while typing practice.",
        confidence=0.7,
        scope="learning_history",
        source_kind="runtime_observation",
        track_id=track_id,
    )
    now = _now()
    review_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE vocabulary_items
            SET review_count=review_count+1,
                next_review_at=?,
                status=CASE
                    WHEN status IN ('mastered','known') THEN 'learning'
                    ELSE status
                END,
                updated_at=?
            WHERE track_id=? AND word=?
            """,
            (review_at, now, track_id, word),
        )
    return {
        "memory_id": memory["memory_id"],
        "word": word,
        "recorded": True,
    }


VOCAB_REVIEW_LADDER = (1, 2, 4, 7, 14, 30, 60)
VALID_REVIEW_OUTCOMES = ("recalled", "missed")

_INFLECTION_TAGS = {
    "NNS": "plural",
    "VBD": "past",
    "VBG": "present_participle",
    "VBN": "past_participle",
    "VBZ": "third_person",
    "JJR": "comparative",
    "JJS": "superlative",
}


def get_vocabulary_item(home: Path, item_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
        ).fetchone()
    return _row(row) if row else None


def apply_adaptive_vocabulary_review(
    home: Path,
    item_id: str,
    *,
    outcome: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Apply one outcome-based review step with an adaptive interval ladder.

    A recalled word advances one ladder step (1, 2, 4, 7, 14, 30, 60 days); a
    missed word resets the ladder and returns the next day. The streak is
    persisted so future reviews continue from the correct rung.
    """
    if outcome not in VALID_REVIEW_OUTCOMES:
        raise ValueError(
            f"Unsupported review outcome: {outcome!r}; "
            f"choose one of {VALID_REVIEW_OUTCOMES}"
        )
    initialise_database(home)
    now = now or _now()
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown vocabulary item: {item_id}")
        streak = int(row["success_streak"] or 0)
        if outcome == "recalled":
            streak += 1
            rung = min(streak - 1, len(VOCAB_REVIEW_LADDER) - 1)
        else:
            streak = 0
            rung = 0
        days = VOCAB_REVIEW_LADDER[rung]
        next_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        conn.execute(
            """
            UPDATE vocabulary_items
            SET next_review_at=?, review_count=review_count+1,
                last_reviewed_at=?, success_streak=?, updated_at=?
            WHERE item_id=?
            """,
            (next_at, now, streak, now, item_id),
        )
        row = conn.execute(
            "SELECT * FROM vocabulary_items WHERE item_id=?", (item_id,)
        ).fetchone()
    result = _row(row)
    result["review_interval_days"] = days
    return result


def deterministic_word_forms(word: str) -> dict[str, str]:
    """Derive inflected forms locally without a model."""
    try:
        import lemminflect
    except ImportError:
        return {}
    try:
        inflections = lemminflect.getAllInflections(word)
    except Exception:
        return {}
    forms: dict[str, str] = {}
    for tag, candidates in inflections.items():
        key = _INFLECTION_TAGS.get(tag)
        if key is None or key in forms:
            continue
        candidates = (
            candidates if isinstance(candidates, (tuple, list)) else (candidates,)
        )
        for candidate in candidates:
            if candidate and candidate.casefold() != word.casefold():
                forms[key] = str(candidate)
                break
    return forms


def get_vocabulary_enrichment(
    home: Path,
    item_id: str,
) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM vocabulary_enrichments WHERE item_id=?", (item_id,)
        ).fetchone()
    if not row:
        return None
    return _enrichment_row(row)


def upsert_vocabulary_enrichment(
    home: Path,
    item_id: str,
    *,
    ipa_uk: str | None = None,
    ipa_us: str | None = None,
    pos: str | None = None,
    definitions: list[dict[str, Any]] | None = None,
    examples: list[dict[str, Any]] | None = None,
    synonyms: list[str] | None = None,
    antonyms: list[str] | None = None,
    forms: dict[str, str] | None = None,
    source: str = "runtime",
) -> dict[str, Any]:
    """Store word-card enrichment fields, filling only the supplied parts."""
    initialise_database(home)
    now = _now()
    def_json = (
        json.dumps(definitions, ensure_ascii=False)
        if definitions is not None
        else None
    )
    ex_json = (
        json.dumps(examples, ensure_ascii=False) if examples is not None else None
    )
    syn_json = (
        json.dumps(synonyms, ensure_ascii=False) if synonyms is not None else None
    )
    ant_json = (
        json.dumps(antonyms, ensure_ascii=False) if antonyms is not None else None
    )
    forms_json = (
        json.dumps(forms, ensure_ascii=False) if forms is not None else None
    )
    with connect(home) as conn:
        existing = conn.execute(
            "SELECT item_id FROM vocabulary_enrichments WHERE item_id=?",
            (item_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE vocabulary_enrichments
                SET ipa_uk=COALESCE(?,ipa_uk), ipa_us=COALESCE(?,ipa_us),
                    pos=COALESCE(?,pos),
                    definitions_json=CASE WHEN ? IS NOT NULL THEN ? ELSE definitions_json END,
                    examples_json=CASE WHEN ? IS NOT NULL THEN ? ELSE examples_json END,
                    synonyms_json=CASE WHEN ? IS NOT NULL THEN ? ELSE synonyms_json END,
                    antonyms_json=CASE WHEN ? IS NOT NULL THEN ? ELSE antonyms_json END,
                    forms_json=CASE WHEN ? IS NOT NULL THEN ? ELSE forms_json END,
                    source=?, generated_at=?, updated_at=?
                WHERE item_id=?
                """,
                (
                    ipa_uk,
                    ipa_us,
                    pos,
                    def_json,
                    def_json,
                    ex_json,
                    ex_json,
                    syn_json,
                    syn_json,
                    ant_json,
                    ant_json,
                    forms_json,
                    forms_json,
                    source,
                    now,
                    now,
                    item_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO vocabulary_enrichments(
                  item_id,ipa_uk,ipa_us,pos,definitions_json,examples_json,
                  synonyms_json,antonyms_json,forms_json,source,generated_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    item_id,
                    ipa_uk,
                    ipa_us,
                    pos,
                    json.dumps(definitions or [], ensure_ascii=False),
                    json.dumps(examples or [], ensure_ascii=False),
                    json.dumps(synonyms or [], ensure_ascii=False),
                    json.dumps(antonyms or [], ensure_ascii=False),
                    json.dumps(forms or {}, ensure_ascii=False),
                    source,
                    now,
                    now,
                ),
            )
        row = conn.execute(
            "SELECT * FROM vocabulary_enrichments WHERE item_id=?", (item_id,)
        ).fetchone()
    return _enrichment_row(row)


_BUNDLED_PRESET_PATH = (
    Path(__file__).resolve().parent
    / "resources"
    / "words"
    / "enrichments"
    / "yanxi-presets-high-freq.jsonl"
)
_bundled_presets: dict[str, dict[str, Any]] | None = None


def load_bundled_enrichment(word: str) -> dict[str, Any] | None:
    """Look up a bundled high-frequency word card preset (offline)."""
    global _bundled_presets
    if _bundled_presets is None:
        index: dict[str, dict[str, Any]] = {}
        if _BUNDLED_PRESET_PATH.is_file():
            try:
                for line in _BUNDLED_PRESET_PATH.read_text(
                    encoding="utf-8"
                ).splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    index[str(entry.get("word") or "").casefold()] = entry
            except (OSError, json.JSONDecodeError):
                index = {}
        _bundled_presets = index
    return _bundled_presets.get(word.casefold())


VOCAB_ENRICHMENT_INSTRUCTIONS = (
    "Generate a compact structured lexicon entry for the single English "
    "word provided in this request. Return only confident facts: one or two "
    "learner-friendly English definitions, one or two natural example "
    "sentences, up to five synonyms and up to five antonyms, the most common "
    "part of speech, and UK/US IPA when you are confident. Never invent "
    "inflected forms; leave forms empty when unsure. Return JSON matching "
    "the supplied schema exactly."
)


def run_vocabulary_enrichment(home: Path, item_id: str) -> dict[str, Any]:
    """Generate rich word-card fields through the configured model route.

    Runs inside the isolated background worker. The result passes the
    vocab-enrichment@1 schema and is stored with source='model' provenance.
    Locally derivable word forms are merged in afterwards.
    """
    item = get_vocabulary_item(home, item_id)
    if not item:
        raise ValueError(f"Unknown vocabulary item: {item_id}")
    word = str(item["word"])
    from .inference import InferenceBroker
    from .validation import load_schema

    prepared = InferenceBroker(home).prepare()
    request = {
        "request_id": f"vocab-enrich:{item_id}",
        "output_contract": "vocab-enrichment@1",
        "capability_id": "vocabulary_lesson",
        "skill_envelope": {
            "skill": "vocabulary-enrichment",
            "instructions": VOCAB_ENRICHMENT_INSTRUCTIONS,
            "references": [],
            "context_policy": {"response_mode": "single_json_object"},
            "output_schema": load_schema("vocab-enrichment"),
        },
        "word": word,
        "track_id": str(item["track_id"]),
        "media_refs": [],
        "runtime_hints": {"reasoning_effort": "low"},
    }
    result = prepared.adapter.start(home, request)
    forms = deterministic_word_forms(word)
    merged_forms = {**forms, **(result.get("forms") or {})}
    return upsert_vocabulary_enrichment(
        home,
        item_id,
        ipa_uk=result.get("ipa_uk"),
        ipa_us=result.get("ipa_us"),
        pos=result.get("pos"),
        definitions=result.get("definitions") or [],
        examples=result.get("examples") or [],
        synonyms=result.get("synonyms") or [],
        antonyms=result.get("antonyms") or [],
        forms=merged_forms,
        source="model",
    )


def ensure_deterministic_enrichment(
    home: Path,
    item_id: str,
) -> dict[str, Any] | None:
    """Fill locally derivable word-card fields when nothing is stored yet.

    Bundled high-frequency presets (IPA, part of speech, definitions) and
    locally computed inflections are merged without touching model-generated
    fields that already exist.
    """
    item = get_vocabulary_item(home, item_id)
    if not item:
        return None
    word = str(item["word"])
    existing = get_vocabulary_enrichment(home, item_id)
    forms = deterministic_word_forms(word)
    preset = load_bundled_enrichment(word)
    preset_forms = dict(preset.get("forms") or {}) if preset else {}
    merged_forms = {**preset_forms, **forms}
    if existing is None:
        if not forms and not preset:
            return None
        return upsert_vocabulary_enrichment(
            home,
            item_id,
            ipa_uk=preset.get("ipa_uk") if preset else None,
            ipa_us=preset.get("ipa_us") if preset else None,
            pos=preset.get("pos") if preset else None,
            definitions=preset.get("definitions") if preset else None,
            examples=preset.get("examples") if preset else None,
            synonyms=preset.get("synonyms") if preset else None,
            antonyms=preset.get("antonyms") if preset else None,
            forms=merged_forms or None,
            source="bundled" if preset else "runtime",
        )
    updates: dict[str, Any] = {}
    if preset:
        if not existing.get("ipa_uk") and not existing.get("ipa_us"):
            updates["ipa_uk"] = preset.get("ipa_uk")
            updates["ipa_us"] = preset.get("ipa_us")
        if not existing.get("pos"):
            updates["pos"] = preset.get("pos")
        if not existing.get("definitions"):
            updates["definitions"] = preset.get("definitions")
        if not existing.get("examples"):
            updates["examples"] = preset.get("examples")
        if not existing.get("synonyms"):
            updates["synonyms"] = preset.get("synonyms")
        if not existing.get("antonyms"):
            updates["antonyms"] = preset.get("antonyms")
    missing_forms = {
        key: value
        for key, value in merged_forms.items()
        if key not in (existing.get("forms") or {})
    }
    if missing_forms:
        updates["forms"] = {**(existing.get("forms") or {}), **missing_forms}
    if updates:
        return upsert_vocabulary_enrichment(
            home,
            item_id,
            source=existing.get("source") or "bundled",
            **updates,
        )
    return existing


def _enrichment_row(row: Any) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "ipa_uk": row["ipa_uk"],
        "ipa_us": row["ipa_us"],
        "pos": row["pos"],
        "definitions": json.loads(row["definitions_json"] or "[]"),
        "examples": json.loads(row["examples_json"] or "[]"),
        "synonyms": json.loads(row["synonyms_json"] or "[]"),
        "antonyms": json.loads(row["antonyms_json"] or "[]"),
        "forms": json.loads(row["forms_json"] or "{}"),
        "source": row["source"],
        "generated_at": row["generated_at"],
    }


def _row(row: Any) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "track_id": row["track_id"],
        "word": row["word"],
        "meaning": row["meaning"],
        "usage": row["usage"],
        "example": row["example"],
        "collocations": json.loads(row["collocations_json"] or "[]"),
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "status": row["status"],
        "review_kind": row["review_kind"],
        "next_review_at": row["next_review_at"],
        "review_count": row["review_count"],
        "last_reviewed_at": row["last_reviewed_at"],
        "success_streak": row["success_streak"] if "success_streak" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
