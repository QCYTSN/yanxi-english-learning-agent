"""P0 dialogue word auto-ingestion: candidate + undo + already-known dedup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ielts_coach.agent_contracts import persist_agent_contract
from ielts_coach.storage import create_agent_run, initialise_database
from ielts_coach.vocabulary import (
    add_vocabulary_item,
    ingest_taught_words,
    list_recent_ingests,
    list_vocabulary_items,
    set_vocabulary_status,
    undo_vocabulary_ingest,
)


def test_migration_34_rebuilds_table_with_candidate_statuses(tmp_path: Path) -> None:
    import sqlite3

    from ielts_coach.migrations import _v34_vocabulary_candidate_states

    db = tmp_path / "v34.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE vocabulary_items (
            item_id TEXT PRIMARY KEY,
            track_id TEXT NOT NULL DEFAULT 'general-english',
            word TEXT NOT NULL,
            meaning TEXT, usage TEXT, example TEXT,
            collocations_json TEXT NOT NULL DEFAULT '[]',
            source_type TEXT NOT NULL, source_id TEXT,
            status TEXT NOT NULL DEFAULT 'learning'
              CHECK(status IN ('learning','mastered','dismissed')),
            review_kind TEXT NOT NULL DEFAULT 'sentence_recall',
            next_review_at TEXT, review_count INTEGER NOT NULL DEFAULT 0,
            last_reviewed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(track_id, word)
        );
        INSERT INTO vocabulary_items VALUES(
          'vocab:old','general-english','old','旧词',NULL,NULL,'[]',
          'learner_input',NULL,'learning','sentence_recall',NULL,0,NULL,
          '2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    _v34_vocabulary_candidate_states(conn)
    conn.commit()

    constraint = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='vocabulary_items'"
    ).fetchone()[0]
    assert "candidate" in constraint and "known" in constraint
    old = conn.execute(
        "SELECT word,status FROM vocabulary_items WHERE item_id='vocab:old'"
    ).fetchone()
    assert old == ("old", "learning")
    conn.close()


def test_ingest_creates_candidate_and_rejects_duplicate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    ingested = ingest_taught_words(
        home,
        [{"word": "accommodation", "meaning": "住宿"}],
        agent_run_id="run_1",
    )
    assert ingested[0]["status"] == "candidate"
    assert ingested[0]["source_type"] == "agent_dialogue"
    assert ingested[0]["source_id"] == "run_1"

    # Re-ingesting a mastered word must not demote it.
    set_vocabulary_status(home, ingested[0]["item_id"], status="mastered")
    again = ingest_taught_words(
        home,
        [{"word": "accommodation", "meaning": "住宿安排"}],
        agent_run_id="run_2",
    )
    assert again == []
    items = list_vocabulary_items(home, status="mastered")
    assert [item["word"] for item in items] == ["accommodation"]


def test_known_word_is_never_reoffered(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = ingest_taught_words(
        home, [{"word": "schedule"}], agent_run_id="run_1"
    )[0]
    set_vocabulary_status(home, first["item_id"], status="known")
    assert ingest_taught_words(home, [{"word": "schedule"}], agent_run_id="run_2") == []
    candidates = list_recent_ingests(home)
    assert candidates == []


def test_candidate_refresh_updates_meaning(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = ingest_taught_words(
        home, [{"word": "elaborate", "meaning": "详细说明"}], agent_run_id="run_1"
    )[0]
    second = ingest_taught_words(
        home,
        [{"word": "elaborate", "meaning": "详尽阐述", "example": "Please elaborate."}],
        agent_run_id="run_2",
    )[0]
    assert second["item_id"] == first["item_id"]
    assert second["meaning"] == "详尽阐述"
    assert second["example"] == "Please elaborate."
    assert second["status"] == "candidate"


def test_undo_removes_only_unconfirmed_candidates(tmp_path: Path) -> None:
    home = tmp_path / "home"
    item = ingest_taught_words(home, [{"word": "transient"}], agent_run_id="run_1")[0]
    removed = undo_vocabulary_ingest(home, item["item_id"])
    assert removed["removed"] is True
    assert list_vocabulary_items(home) == []

    # Undo after confirmation is refused.
    item = add_vocabulary_item(home, word="persistent")
    with pytest.raises(ValueError, match="Only unconfirmed candidate"):
        undo_vocabulary_ingest(home, item["item_id"])


def test_contract_persist_ingests_words_taught(tmp_path: Path) -> None:
    home = tmp_path / "home"
    thread = _create_thread(home)
    run = _create_run(home, "run_x", "study-help@1", thread)
    result = {
        "contract_version": 1,
        "module": "mixed",
        "request_kind": "teacher_dialogue",
        "evidence_status": "not_required",
        "answer_status": "not_applicable",
        "summary": "讲解了一个词。",
        "sections": [{"title": "词", "content": "meaningful 的意思。"}],
        "evidence": [],
        "words_taught": [
            {"word": "meaningful", "meaning": "有意义的", "usage": "a meaningful task"}
        ],
        "limitations": [],
        "next_action": None,
    }
    persist_agent_contract(home, run, result)
    candidates = list_recent_ingests(home)
    assert [item["word"] for item in candidates] == ["meaningful"]
    assert candidates[0]["source_id"] == "run_x"


def test_contract_vocabulary_lesson_ingests_single_word(tmp_path: Path) -> None:
    home = tmp_path / "home"
    thread = _create_thread(home)
    run = _create_run(home, "run_y", "general-vocabulary@1", thread)
    result = {
        "contract_version": 1,
        "word": "pipeline",
        "meaning": "管线",
        "usage": "pipeline test",
        "example": "This is a pipeline test.",
        "collocations": [],
        "review_suggestion": {"suggested": False, "kind": "none"},
        "limitations": [],
    }
    persist_agent_contract(home, run, result)
    candidates = list_recent_ingests(home)
    assert [item["word"] for item in candidates] == ["pipeline"]
    assert candidates[0]["meaning"] == "管线"


def test_study_help_without_words_taught_ingests_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    thread = _create_thread(home)
    run = _create_run(home, "run_z", "study-help@1", thread)
    result = {
        "contract_version": 1,
        "module": "mixed",
        "request_kind": "teacher_dialogue",
        "evidence_status": "not_required",
        "answer_status": "not_applicable",
        "summary": "闲聊。",
        "sections": [],
        "evidence": [],
        "limitations": [],
        "next_action": None,
    }
    persist_agent_contract(home, run, result)
    assert list_recent_ingests(home) == []
    assert list_vocabulary_items(home) == []


def _create_thread(home: Path) -> str:
    from ielts_coach.study_threads import create_study_thread

    thread = create_study_thread(
        home,
        title="词汇对话",
        module="mixed",
        track_id="general-english",
    )
    return str(thread["thread_id"])


def _create_run(home: Path, run_id: str, contract: str, thread_id: str) -> dict:
    run = {
        "run_id": run_id,
        "adapter_id": "mock",
        "action": "teacher_dialogue",
        "output_contract": contract,
        "study_session_id": None,
        "study_thread_id": thread_id,
        "request": {"study_thread_id": thread_id},
        "status": "queued",
    }
    return create_agent_run(home, run)



def test_seed_words_bundle_is_starter_plus_frequency_3000() -> None:
    from ielts_coach.seed_words import load_seed_words, seed_metadata, seed_words_pool

    words = load_seed_words()
    # GSL starter-100 (deduplicated) + FrequencyWords top-3000 pool.
    assert 2900 <= len(words) <= 3100
    assert all(item["word"] for item in words)
    assert all(item.get("yanxi_level") in {"A1", "A1-A2", "B1"} for item in words)
    assert all(str(item["word"]).islower() for item in words)
    meta = seed_metadata()
    assert meta["seed_id"] == "yanxi-starter-100"
    assert meta["source"][0]["rights"] == "public_domain"
    assert meta["source"][1]["rights"] == "MIT"
    pool = seed_words_pool(limit=5)
    assert pool == ["the", "of", "and", "to", "a"]
    assert seed_words_pool(limit=3, exclude={"the", "of", "and"}) == ["to", "a", "in"]
    assert len(seed_words_pool()) == len(words)
    assert seed_words_pool(level="B1")


def test_typing_mistake_writes_learner_memory(tmp_path: Path) -> None:
    from ielts_coach.storage import list_learner_memories
    from ielts_coach.vocabulary import record_typing_mistake

    home = tmp_path / "home"
    result = record_typing_mistake(home, "accommodation")
    assert result["recorded"] is True
    memories = list_learner_memories(
        home,
        memory_type="spelling_weakness",
        track_id="general-english",
    )
    assert len(memories) == 1
    assert memories[0]["memory_key"] == "typing:accommodation"
    assert "accommodation" in memories[0]["statement"]

    # Re-recording the same word refreshes the same memory, not a duplicate.
    record_typing_mistake(home, "accommodation")
    memories = list_learner_memories(
        home,
        memory_type="spelling_weakness",
        track_id="general-english",
    )
    assert len(memories) == 1

    # The memory is visible to the tutor context pipeline.
    from ielts_coach.tutor_orchestrator import TutorOrchestrator

    orchestrator = TutorOrchestrator(home)
    context = orchestrator.initial_context(
        "hello",
        thread_id=_create_thread(home),
    )
    assert any(
        item["memory_type"] == "spelling_weakness"
        for item in context["learner_memories"]
    )


def test_typing_mistake_schedules_review_and_downgrades_mastered(tmp_path: Path) -> None:
    from ielts_coach.storage import connect
    from ielts_coach.vocabulary import (
        add_vocabulary_item,
        due_vocabulary_reviews,
        record_typing_mistake,
        set_vocabulary_status,
    )

    home = tmp_path / "home"
    item = add_vocabulary_item(home, word="accommodation", meaning="住宿")
    set_vocabulary_status(home, item["item_id"], status="mastered")

    # A miss on a mastered word drops it back to learning and schedules
    # a short review, so the due-review surface picks it up again.
    record_typing_mistake(home, "accommodation")
    with connect(home) as conn:
        row = conn.execute(
            "SELECT status, next_review_at, review_count FROM vocabulary_items WHERE word=?",
            ("accommodation",),
        ).fetchone()
    assert row["status"] == "learning"
    assert row["next_review_at"] is not None
    assert row["review_count"] == 1

    # Not due yet: the mistake schedules review for tomorrow.
    assert due_vocabulary_reviews(home, track_id="general-english") == []
    tomorrow = (
        datetime.now(timezone.utc) + timedelta(days=1, hours=1)
    ).isoformat()
    due = due_vocabulary_reviews(home, track_id="general-english", now=tomorrow)
    assert any(item["word"] == "accommodation" for item in due)
