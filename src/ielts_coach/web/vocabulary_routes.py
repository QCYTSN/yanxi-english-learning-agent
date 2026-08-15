from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query

from ..model_providers import (
    ModelProviderError,
    active_model_route,
)
from ..vocabulary import (
    add_vocabulary_item,
    apply_adaptive_vocabulary_review,
    deterministic_word_forms,
    due_vocabulary_reviews,
    ensure_deterministic_enrichment,
    get_vocabulary_item,
    list_recent_ingests,
    list_vocabulary_items,
    record_typing_mistake,
    run_vocabulary_enrichment,
    schedule_vocabulary_review,
    set_vocabulary_status,
    undo_vocabulary_ingest,
)
from .auth import require_session


def register_vocabulary_routes(
    app: FastAPI,
    *,
    target: Path,
    local_jobs: Any,
) -> None:
    @app.get("/api/v1/vocabulary", dependencies=[Depends(require_session)])
    def vocabulary_list(
        track_id: str = Query("general-english"),
        status: str | None = Query(None),
        limit: int = Query(200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_vocabulary_items(
            target,
            track_id=track_id,
            status=status,
            limit=limit,
        )

    @app.get("/api/v1/vocabulary/seed", dependencies=[Depends(require_session)])
    def vocabulary_seed(
        level: str | None = Query(None),
        limit: int = Query(100, ge=1, le=20000),
    ) -> dict[str, Any]:
        """Bundled public-domain starter words for typing practice and cold start."""
        from ..seed_words import load_seed_words, seed_metadata

        words = load_seed_words()
        if level:
            words = [item for item in words if item.get("yanxi_level") == level]
        return {
            "meta": seed_metadata(),
            "words": words[:limit],
        }

    @app.get("/api/v1/vocabulary/due", dependencies=[Depends(require_session)])
    def vocabulary_due(
        track_id: str = Query("general-english"),
        limit: int = Query(50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return due_vocabulary_reviews(target, track_id=track_id, limit=limit)

    @app.post("/api/v1/vocabulary", dependencies=[Depends(require_session)])
    def vocabulary_add(payload: dict[str, Any]) -> dict[str, Any]:
        supported = {
            "word", "meaning", "usage", "example", "collocations",
            "review_kind", "source_type", "source_id", "track_id",
        }
        unknown = set(payload) - supported
        if unknown:
            raise ValueError(
                f"Unsupported vocabulary fields: {', '.join(sorted(unknown))}"
            )
        return add_vocabulary_item(target, **payload)

    @app.patch("/api/v1/vocabulary/{item_id}/review", dependencies=[Depends(require_session)])
    def vocabulary_review_schedule(
        item_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        outcome = str(payload.get("outcome") or "").strip()
        if outcome:
            return apply_adaptive_vocabulary_review(
                target, item_id, outcome=outcome
            )
        days = int(payload.get("days") or 3)
        return schedule_vocabulary_review(target, item_id, days=days)

    @app.get(
        "/api/v1/vocabulary/{item_id}/enrichment",
        dependencies=[Depends(require_session)],
    )
    def vocabulary_enrichment_get(item_id: str) -> dict[str, Any]:
        item = get_vocabulary_item(target, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Vocabulary item not found")
        enrichment = ensure_deterministic_enrichment(target, item_id)
        if enrichment is None:
            return {
                "item_id": item_id,
                "word": item["word"],
                "status": "pending",
                "forms": deterministic_word_forms(str(item["word"])),
                "definitions": [],
                "examples": [],
                "synonyms": [],
                "antonyms": [],
                "ipa_uk": None,
                "ipa_us": None,
                "pos": None,
                "source": None,
            }
        return {"status": "available", "word": item["word"], **enrichment}

    @app.post(
        "/api/v1/vocabulary/{item_id}/enrich",
        dependencies=[Depends(require_session)],
    )
    def vocabulary_enrich_trigger(
        item_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        item = get_vocabulary_item(target, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Vocabulary item not found")
        enrichment = ensure_deterministic_enrichment(target, item_id)
        try:
            active_model_route(target)
        except ModelProviderError:
            return {
                "item_id": item_id,
                "word": item["word"],
                "status": "deterministic_only",
                "enrichment": enrichment,
            }
        if local_jobs is not None:
            job = local_jobs.submit(
                "vocab_enrich",
                {"item_id": item_id},
                priority=40,
                dedupe_key=f"vocab-enrich:{item_id}",
            )
            status = job["status"]
        else:
            background_tasks.add_task(
                run_vocabulary_enrichment, target, item_id
            )
            status = "queued"
        return {
            "item_id": item_id,
            "word": item["word"],
            "status": status,
            "enrichment": enrichment,
        }

    @app.patch("/api/v1/vocabulary/{item_id}/status", dependencies=[Depends(require_session)])
    def vocabulary_status_update(
        item_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(payload.get("status") or "learning")
        return set_vocabulary_status(target, item_id, status=status)

    @app.get("/api/v1/vocabulary/ingested", dependencies=[Depends(require_session)])
    def vocabulary_ingested(
        track_id: str = Query("general-english"),
        limit: int = Query(20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        """Recent dialogue-ingested candidates awaiting learner confirmation."""
        return list_recent_ingests(target, track_id=track_id, limit=limit)

    @app.post("/api/v1/vocabulary/ingested/{item_id}/undo", dependencies=[Depends(require_session)])
    def vocabulary_ingest_undo(item_id: str) -> dict[str, Any]:
        """Remove one still-unconfirmed word the tutor auto-ingested."""
        return undo_vocabulary_ingest(target, item_id)

    @app.post("/api/v1/vocabulary/typing-mistake", dependencies=[Depends(require_session)])
    def vocabulary_typing_mistake(payload: dict[str, Any]) -> dict[str, Any]:
        """Feed a typing miss into learner memory so dialogue can reuse it."""
        word = str(payload.get("word") or "")
        track_id = str(payload.get("track_id") or "general-english")
        if not word:
            raise ValueError("A typing mistake needs a word")
        return record_typing_mistake(target, word, track_id=track_id)

