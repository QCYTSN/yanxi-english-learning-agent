from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ielts_coach.init_home import initialise_home
from ielts_coach.vocabulary import (
    VOCAB_REVIEW_LADDER,
    add_vocabulary_item,
    apply_adaptive_vocabulary_review,
    deterministic_word_forms,
    ensure_deterministic_enrichment,
    upsert_vocabulary_enrichment,
)
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="enrich-test-token-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    response = client.post(
        "/api/auth/exchange",
        json={"token": "enrich-test-token-long-enough"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    client.headers.update({CSRF_HEADER_NAME: csrf})
    return client


def _word(home: Path, word: str = "study") -> dict:
    return add_vocabulary_item(home, word=word)


def test_adaptive_review_ladder_advances_and_resets(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    item = _word(home)

    # Recall streak climbs the ladder one rung at a time.
    for index, expected_days in enumerate(VOCAB_REVIEW_LADDER, start=1):
        reviewed = apply_adaptive_vocabulary_review(
            home, item["item_id"], outcome="recalled"
        )
        assert reviewed["review_interval_days"] == expected_days
        assert reviewed["success_streak"] == index
        assert reviewed["review_count"] == index

    # The ladder caps at its longest interval.
    capped = apply_adaptive_vocabulary_review(
        home, item["item_id"], outcome="recalled"
    )
    assert capped["review_interval_days"] == VOCAB_REVIEW_LADDER[-1]
    assert capped["success_streak"] == len(VOCAB_REVIEW_LADDER) + 1

    # A miss resets the streak and the interval.
    missed = apply_adaptive_vocabulary_review(
        home, item["item_id"], outcome="missed"
    )
    assert missed["success_streak"] == 0
    assert missed["review_interval_days"] == VOCAB_REVIEW_LADDER[0]


def test_adaptive_review_rejects_unknown_outcome(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    item = _word(home)
    try:
        apply_adaptive_vocabulary_review(
            home, item["item_id"], outcome="maybe"
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "maybe" in str(exc)


def test_deterministic_word_forms_cover_common_inflections() -> None:
    forms = deterministic_word_forms("study")
    assert forms.get("third_person") == "studies"
    assert forms.get("past") == "studied"
    assert forms.get("present_participle") == "studying"
    assert deterministic_word_forms("zzzzunknownword") == {}


def test_enrichment_upsert_fills_only_supplied_fields(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    item = _word(home)

    first = upsert_vocabulary_enrichment(
        home,
        item["item_id"],
        ipa_us="/stʌdi/",
        pos="verb",
        source="bundled",
    )
    assert first["ipa_us"] == "/stʌdi/"
    assert first["pos"] == "verb"
    assert first["definitions"] == []

    second = upsert_vocabulary_enrichment(
        home,
        item["item_id"],
        definitions=[{"text": "to learn about a subject", "language": "en"}],
        forms={"past": "studied"},
        source="model",
    )
    # Supplied fields are merged without erasing earlier ones.
    assert second["ipa_us"] == "/stʌdi/"
    assert second["pos"] == "verb"
    assert second["definitions"][0]["text"] == "to learn about a subject"
    assert second["forms"]["past"] == "studied"


def test_bundled_preset_provides_offline_word_card_fields(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    item = _word(home, "study")
    enrichment = ensure_deterministic_enrichment(home, item["item_id"])
    assert enrichment is not None
    assert enrichment["source"] == "bundled"
    # ECDICT-derived part of speech and definitions, offline.
    assert enrichment["pos"]
    assert enrichment["definitions"]
    # Local lemminflect inflections are merged in.
    assert enrichment["forms"].get("third_person") == "studies"


def test_enrichment_api_returns_deterministic_forms_without_a_model(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    client = _client(home)
    item = _word(home)

    fetched = client.get(f"/api/v1/vocabulary/{item['item_id']}/enrichment")
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["word"] == "study"
    assert payload["status"] in {"available", "pending"}
    assert payload["forms"].get("third_person") == "studies"

    triggered = client.post(f"/api/v1/vocabulary/{item['item_id']}/enrich")
    assert triggered.status_code == 200
    # No enabled provider in tests: the deterministic-only path is taken.
    assert triggered.json()["status"] == "deterministic_only"

    missing = client.get("/api/v1/vocabulary/vocab:nope/enrichment")
    assert missing.status_code == 404
