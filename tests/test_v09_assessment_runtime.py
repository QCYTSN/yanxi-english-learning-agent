from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from ielts_coach.assessment_builder import assemble_assessment_pack
from ielts_coach.assessment_runtime import (
    bind_speaking_result,
    create_speaking_handoff,
    get_assessment_run,
    pause_assessment_run,
    record_writing_score,
    save_response,
    start_assessment_run,
    start_audio_playback,
    submit_assessment_run,
    update_audio_playback,
)
from ielts_coach.conformance import enrich_question_conformance
from ielts_coach.content_reviews import get_target_review, record_content_review
from ielts_coach.init_home import initialise_home
from ielts_coach.media import import_audio_bytes
from ielts_coach.question_bank import content_hash
from ielts_coach.session_io import load_session_file
from ielts_coach.storage import (
    connect,
    get_assessment_pack,
    get_question_for_grading,
    upsert_assessment_pack,
    upsert_passage,
    upsert_question,
)


def _approve(home: Path, target_type: str, target_id: str) -> None:
    target = get_target_review(home, target_type, target_id, include_material=False)
    record_content_review(
        home,
        target_type=target_type,
        target_id=target_id,
        reviewer="V0.9 acceptance reviewer",
        decision="approved",
        checklist={key: True for key in target["required_checklist"]},
    )


def _question(**values: object) -> dict[str, object]:
    item: dict[str, object] = {
        "corpus_id": "ielts-ai-coach-starter",
        "module": "reading",
        "question_type": "short_answer",
        "content": "Write the synthetic answer.",
        "source_type": "project_original",
        "authenticity": "practice_only",
        "rights_status": "redistributable",
        "practice_mode": "full_mock",
        "review_status": "unreviewed",
        "correct_answer": "alpha",
        "accepted_variants": ["Alpha"],
        "answer_constraints": {"word_limit": 1},
        "evidence_location": "Synthetic paragraph A",
    }
    item.update(values)
    enriched = enrich_question_conformance(item)
    enriched["content_hash"] = content_hash(enriched)
    return enriched


def _reading_pack(home: Path) -> dict[str, object]:
    question_ids: list[str] = []
    counts = [13, 13, 14]
    for passage_index, count in enumerate(counts, start=1):
        passage_id = f"V09-R-P{passage_index}"
        upsert_passage(
            home,
            {
                "passage_id": passage_id,
                "corpus_id": "ielts-ai-coach-starter",
                "title": f"Synthetic passage {passage_index}",
                "body": " ".join(
                    f"synthetic{passage_index}_{word}" for word in range(800)
                ),
                "source_type": "project_original",
                "rights_status": "redistributable",
            },
        )
        _approve(home, "passage", passage_id)
        for local_number in range(1, count + 1):
            number = len(question_ids) + 1
            question_id = f"V09-R-Q{number:02d}"
            item = _question(
                question_id=question_id,
                passage_id=passage_id,
                question_number=number,
                content=f"Question {number}: write the synthetic answer.",
            )
            assert upsert_question(home, item) is True
            _approve(home, "question", question_id)
            question_ids.append(question_id)
    pack = assemble_assessment_pack(
        home,
        module="reading",
        title="V0.9 synthetic reading full mock",
        question_ids=question_ids,
    )
    pack["band_conversion"] = {
        str(raw): (0.0 if raw == 0 else min(9.0, max(0.5, round(raw / 2) / 2)))
        for raw in range(41)
    }
    pack["band_conversion_source"] = "Synthetic V0.9 test table"
    upsert_assessment_pack(home, pack)
    _approve(home, "assessment_pack", str(pack["pack_id"]))
    return get_assessment_pack(home, str(pack["pack_id"])) or {}


def _wav_bytes(seconds: float = 1.0, rate: int = 8000) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(b"\x00\x00" * int(seconds * rate))
    return stream.getvalue()


def test_reading_run_freezes_pack_hides_answers_and_grades_only_after_submit(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    pack = _reading_pack(home)

    first = start_assessment_run(
        home, str(pack["pack_id"]), idempotency_key="reading-start"
    )
    replay = start_assessment_run(
        home, str(pack["pack_id"]), idempotency_key="reading-start"
    )
    assert replay["run_id"] == first["run_id"]
    assert first["timer"]["time_limit_seconds"] == 3600
    assert len(first["sections"]) == 3
    assert len(first["pack_snapshot"]["questions"]) == 40
    assert "correct_answer" not in first["pack_snapshot"]["questions"][0]
    with pytest.raises(ValueError, match="cannot be paused"):
        pause_assessment_run(home, first["run_id"])

    response = save_response(
        home,
        first["run_id"],
        "V09-R-Q01",
        {"answer": " ALPHA "},
        section_key="V09-R-P1",
        expected_revision=0,
        idempotency_key="reading-answer-1",
    )
    assert response["revision"] == 1
    assert save_response(
        home,
        first["run_id"],
        "V09-R-Q01",
        {"answer": "ignored duplicate"},
        section_key="V09-R-P1",
        expected_revision=1,
        idempotency_key="reading-answer-1",
    )["response"] == {"answer": " ALPHA "}
    with pytest.raises(ValueError, match="Stale response revision"):
        save_response(
            home,
            first["run_id"],
            "V09-R-Q01",
            {"answer": "alpha"},
            section_key="V09-R-P1",
            expected_revision=0,
        )

    changed = dict(get_question_for_grading(home, "V09-R-Q01") or {})
    changed["correct_answer"] = "changed after run start"
    changed["content_hash"] = content_hash(changed)
    assert upsert_question(home, changed, force=True) is True
    with connect(home) as connection:
        connection.execute(
            "UPDATE assessment_runs SET resumed_at=? WHERE run_id=?",
            ("2020-01-01T00:00:00+00:00", first["run_id"]),
        )
    assert get_assessment_run(home, first["run_id"])["timer"]["expired"] is True
    with pytest.raises(ValueError, match="time limit has expired"):
        save_response(
            home,
            first["run_id"],
            "V09-R-Q02",
            {"answer": "alpha"},
            section_key="V09-R-P1",
        )

    completed = submit_assessment_run(
        home, first["run_id"], idempotency_key="reading-submit"
    )
    assert completed["status"] == "completed"
    assert completed["score_result"]["raw_score"] == 1
    assert completed["score_result"]["total"] == 40
    assert completed["score_result"]["band"] == 0.5
    assert completed["score_result"]["question_results"][0]["correct_answer"] == "alpha"
    assert completed["submission"]["unanswered_question_ids"] == [
        f"V09-R-Q{number:02d}" for number in range(2, 41)
    ]
    session = load_session_file(
        home / "sessions" / "reading" / f"{first['session_id']}.md"
    )
    assert session["status"] == "completed"
    assert session["answer_revealed_at"]
    with pytest.raises(ValueError, match="not writable"):
        save_response(
            home,
            first["run_id"],
            "V09-R-Q02",
            {"answer": "alpha"},
            section_key="V09-R-P1",
        )


def test_writing_run_uses_one_session_and_runtime_owns_task_weighting(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    pack = assemble_assessment_pack(
        home,
        module="writing",
        title="V0.9 writing full mock",
        question_ids=["START-WT1-001", "START-WT2-001"],
    )
    _approve(home, "assessment_pack", pack["pack_id"])
    run = start_assessment_run(home, pack["pack_id"])
    assert run["timer"]["time_limit_seconds"] == 3600
    assert [section["section_key"] for section in run["sections"]] == [
        "task1",
        "task2",
    ]
    save_response(
        home,
        run["run_id"],
        "START-WT1-001",
        {"text": "Task one learner response."},
        section_key="task1",
    )
    save_response(
        home,
        run["run_id"],
        "START-WT2-001",
        {"text": "Task two learner response."},
        section_key="task2",
    )
    reviewing = submit_assessment_run(home, run["run_id"])
    assert reviewing["status"] == "reviewing"
    result = record_writing_score(
        home,
        run["run_id"],
        task1={
            "criteria": {"TA": 5.5, "CC": 6.0, "LR": 6.0, "GRA": 6.5},
            "evidence": ["Task 1 evidence"],
            "confidence": "medium",
        },
        task2={
            "criteria": {"TR": 7.0, "CC": 7.0, "LR": 7.0, "GRA": 7.0},
            "evidence": ["Task 2 evidence"],
            "confidence": "high",
        },
    )
    assert result["status"] == "completed"
    assert result["score_result"]["task1"]["band"] == 6.0
    assert result["score_result"]["task2"]["band"] == 7.0
    assert result["score_result"]["band"] == 6.5
    assert result["score_result"]["aggregation"] == "(Task 1 + 2 × Task 2) / 3"
    session = load_session_file(
        home / "sessions" / "writing" / f"{run['session_id']}.md"
    )
    assert session["status"] == "completed"
    assert session["assessment_run_id"] == run["run_id"]


def test_listening_audio_is_registered_frozen_and_can_only_start_once(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    media_ids: list[str] = []
    for part in range(1, 5):
        media = import_audio_bytes(
            home,
            _wav_bytes(seconds=1 + part / 10),
            filename=f"part-{part}.wav",
            mime_type="audio/wav",
            transcript=f"Synthetic transcript for part {part}.",
            timestamps=[{"start_seconds": 0, "end_seconds": 1, "text": "alpha"}],
        )
        media_ids.append(media["media_id"])

    question_ids: list[str] = []
    for part in range(1, 5):
        for local_number in range(1, 11):
            number = (part - 1) * 10 + local_number
            question_id = f"V09-L-Q{number:02d}"
            item = _question(
                question_id=question_id,
                module="listening",
                part=part,
                passage_id=None,
                question_number=number,
                content=f"Listening question {number}: write the synthetic answer.",
                audio_media_id=media_ids[part - 1],
                evidence_location=f"Part {part}, synthetic timestamp",
                transcript_timestamp={"start_seconds": 0, "end_seconds": 1},
            )
            assert upsert_question(home, item) is True
            _approve(home, "question", question_id)
            question_ids.append(question_id)
    pack = assemble_assessment_pack(
        home,
        module="listening",
        title="V0.9 synthetic listening full mock",
        question_ids=question_ids,
    )
    _approve(home, "assessment_pack", pack["pack_id"])
    run = start_assessment_run(home, pack["pack_id"])
    assert "transcript_timestamp" not in run["pack_snapshot"]["questions"][0]
    started = start_audio_playback(home, run["run_id"], media_ids[0])
    assert started["media_state"][media_ids[0]]["play_count"] == 1
    progressed = update_audio_playback(
        home,
        run["run_id"],
        media_ids[0],
        position_seconds=0.8,
        completed=False,
    )
    assert progressed["media_state"][media_ids[0]]["position_seconds"] == 0.8
    with pytest.raises(ValueError, match="only be started once"):
        start_audio_playback(home, run["run_id"], media_ids[0])
    with pytest.raises(ValueError, match="cannot move backwards"):
        update_audio_playback(
            home,
            run["run_id"],
            media_ids[0],
            position_seconds=0,
        )


def test_speaking_handoff_and_result_stay_bound_to_authoritative_session(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    pack = assemble_assessment_pack(
        home,
        module="speaking",
        title="V0.9 speaking full mock",
        question_ids=[
            "START-SP1-001",
            "START-SP1-006",
            "START-SP2-001",
            "START-SP3-001",
            "START-SP3-002",
        ],
    )
    _approve(home, "assessment_pack", pack["pack_id"])
    run = start_assessment_run(home, pack["pack_id"])
    package = create_speaking_handoff(home, run["run_id"])
    assert package["assessment_run_id"] == run["run_id"]
    assert package["session_id"] == run["session_id"]
    assert "Do not correct" in package["prompt"]
    assert "11-14 minutes" in package["prompt"]
    reviewing = submit_assessment_run(home, run["run_id"])
    assert reviewing["status"] == "reviewing"
    with pytest.raises(ValueError, match="audio-based pronunciation evidence"):
        bind_speaking_result(
            home,
            run["run_id"],
            {
                "session_id": run["session_id"],
                "band": 7.0,
                "speaking_report": {"evidence_types": ["transcript"]},
            },
        )
    completed = bind_speaking_result(
        home,
        run["run_id"],
        {
            "session_id": run["session_id"],
            "band": 7.0,
            "score_kind": "ai_training_estimate",
            "score_confidence": "medium",
            "speaking_report": {
                "evidence_types": ["transcript", "voice_model_observation"]
            },
        },
    )
    assert completed["status"] == "completed"
    assert completed["score_result"]["pronunciation_evidence_sufficient"] is True
    assert get_assessment_run(home, run["run_id"])["session_id"] == run["session_id"]
