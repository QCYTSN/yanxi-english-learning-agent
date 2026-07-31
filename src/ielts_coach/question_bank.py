from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable

from .storage import (
    count_questions,
    connect,
    get_question,
    get_question_for_grading,
    initialise_database,
    list_questions,
    question_attempted,
    redact_answer_data,
    upsert_assessment_pack,
    upsert_passage,
    upsert_question,
)
from .config import load_settings
from .conformance import assess_pack, assess_reading_set, enrich_question_conformance
from .content_reviews import refresh_target_status
from .validation import validate_data


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            yield value


def content_hash(question: dict[str, Any]) -> str:
    stable = {
        "module": question.get("module"),
        "task": question.get("task"),
        "question_type": question.get("question_type"),
        "content": question.get("content"),
        "passage_id": question.get("passage_id"),
        "options": question.get("options"),
        "practice_mode": question.get("practice_mode"),
        "answer_constraints": question.get("answer_constraints"),
        "task_data": question.get("task_data"),
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def import_question_files(
    home: Path,
    corpus_id: str,
    base_path: Path,
    files: list[dict[str, Any]],
    *,
    source_type: str,
    authenticity: str | None = None,
    manifest: dict[str, Any] | None = None,
    force: bool = False,
    refresh_reviews: bool = True,
) -> dict[str, int]:
    counts = {"passages": 0, "questions": 0, "assessment_packs": 0, "duplicates": 0}
    order = {"passages": 0, "questions": 1, "assessment_packs": 2}
    ordered_files = sorted(files, key=lambda item: order.get(str(item.get("kind")), 99))
    review_targets: list[tuple[str, str]] = []
    initialise_database(home)
    with connect(home) as conn:
        for file_spec in ordered_files:
            kind = str(file_spec.get("kind", "questions"))
            relative = file_spec.get("path")
            if not relative:
                continue
            path = (base_path / str(relative)).resolve()
            if not path.exists():
                raise FileNotFoundError(f"Corpus data file not found: {path}")
            if kind == "passages":
                for passage in _jsonl(path):
                    _bind_provenance(passage, corpus_id, source_type, authenticity)
                    _discard_source_review_claim(passage)
                    upsert_passage(home, passage, connection=conn)
                    if refresh_reviews:
                        review_targets.append(("passage", str(passage["passage_id"])))
                    counts["passages"] += 1
            elif kind == "questions":
                for question in _jsonl(path):
                    _bind_provenance(question, corpus_id, source_type, authenticity)
                    _discard_source_review_claim(question)
                    question = enrich_question_conformance(question, manifest)
                    question["content_hash"] = content_hash(question)
                    question = validate_data(question, "question")
                    inserted = upsert_question(
                        home,
                        question,
                        force=force,
                        connection=conn,
                    )
                    if inserted:
                        if refresh_reviews:
                            review_targets.append(
                                ("question", str(question["question_id"]))
                            )
                        counts["questions"] += 1
                    else:
                        counts["duplicates"] += 1
            elif kind == "assessment_packs":
                for pack in _jsonl(path):
                    pack = _prepare_assessment_pack(
                        pack,
                        corpus_id=corpus_id,
                        source_type=source_type,
                        authenticity=authenticity,
                        manifest=manifest,
                    )
                    upsert_assessment_pack(home, pack, connection=conn)
                    if refresh_reviews:
                        review_targets.append(
                            ("assessment_pack", str(pack["pack_id"]))
                        )
                    counts["assessment_packs"] += 1
            else:
                raise ValueError(f"Unsupported corpus file kind: {kind}")
    for target_type, target_id in review_targets:
        refresh_target_status(home, target_type, target_id)
    return counts


def preflight_question_files(
    home: Path,
    corpus_id: str,
    base_path: Path,
    files: list[dict[str, Any]],
    *,
    source_type: str,
    authenticity: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> None:
    """Validate a complete import before mutating its manifest or database."""
    seen_passages: set[str] = set()
    seen_questions: set[str] = set()
    seen_question_payloads: dict[str, dict[str, Any]] = {}
    seen_packs: set[str] = set()
    with connect(home) as conn:
        passage_owners = {
            str(row["passage_id"]): row["corpus_id"]
            for row in conn.execute("SELECT passage_id,corpus_id FROM question_passages")
        }
        question_owners = {
            str(row["question_id"]): row["corpus_id"]
            for row in conn.execute("SELECT question_id,corpus_id FROM questions")
        }
        pack_owners = {
            str(row["pack_id"]): row["corpus_id"]
            for row in conn.execute("SELECT pack_id,corpus_id FROM assessment_packs")
        }
    order = {"passages": 0, "questions": 1, "assessment_packs": 2}
    ordered_files = sorted(files, key=lambda item: order.get(str(item.get("kind")), 99))
    for file_spec in ordered_files:
        kind = str(file_spec.get("kind", "questions"))
        relative = file_spec.get("path")
        if not relative:
            continue
        path = (base_path / str(relative)).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Corpus data file not found: {path}")
        if kind == "passages":
            for passage in _jsonl(path):
                _bind_provenance(passage, corpus_id, source_type, authenticity)
                _discard_source_review_claim(passage)
                passage_id = str(passage.get("passage_id", "")).strip()
                if not passage_id or not passage.get("body"):
                    raise ValueError(f"Invalid passage in {path}: passage_id and body are required")
                if passage_id in seen_passages:
                    raise ValueError(f"Duplicate passage_id in import: {passage_id}")
                if passage_id in passage_owners and passage_owners[passage_id] != corpus_id:
                    raise ValueError(
                        f"Passage ID {passage_id!r} already belongs to corpus {passage_owners[passage_id]!r}"
                    )
                seen_passages.add(passage_id)
        elif kind == "questions":
            for question in _jsonl(path):
                _bind_provenance(question, corpus_id, source_type, authenticity)
                _discard_source_review_claim(question)
                question = enrich_question_conformance(question, manifest)
                question["content_hash"] = content_hash(question)
                question = validate_data(question, "question")
                question_id = str(question["question_id"])
                if question_id in seen_questions:
                    raise ValueError(f"Duplicate question_id in import: {question_id}")
                if question_id in question_owners and question_owners[question_id] != corpus_id:
                    raise ValueError(
                        f"Question ID {question_id!r} already belongs to corpus {question_owners[question_id]!r}"
                    )
                passage_id = question.get("passage_id")
                if passage_id and str(passage_id) not in seen_passages:
                    owner = passage_owners.get(str(passage_id))
                    if owner != corpus_id:
                        raise ValueError(
                            f"Question {question_id!r} references unknown passage {passage_id!r}"
                        )
                seen_questions.add(question_id)
                seen_question_payloads[question_id] = question
        elif kind == "assessment_packs":
            for pack in _jsonl(path):
                prepared = _prepare_assessment_pack(
                    pack,
                    corpus_id=corpus_id,
                    source_type=source_type,
                    authenticity=authenticity,
                    manifest=manifest,
                )
                pack_id = str(prepared["pack_id"])
                if pack_id in seen_packs:
                    raise ValueError(f"Duplicate pack_id in import: {pack_id}")
                if pack_id in pack_owners and pack_owners[pack_id] != corpus_id:
                    raise ValueError(
                        f"Assessment pack ID {pack_id!r} already belongs to corpus "
                        f"{pack_owners[pack_id]!r}"
                    )
                missing_questions = [
                    value for value in (prepared.get("question_ids") or [])
                    if str(value) not in seen_questions and not _question_exists(home, str(value))
                ]
                missing_passages = [
                    value for value in (prepared.get("passage_ids") or [])
                    if str(value) not in seen_passages and str(value) not in passage_owners
                ]
                if missing_questions or missing_passages:
                    raise ValueError(
                        f"Assessment pack {prepared['pack_id']!r} references unknown content: "
                        f"questions={missing_questions}, passages={missing_passages}"
                    )
                if prepared.get("review_status") == "reviewed":
                    unverified = []
                    for value in prepared.get("question_ids") or []:
                        question_id = str(value)
                        question = seen_question_payloads.get(question_id) or get_question_for_grading(home, question_id)
                        if not question or question.get("conformance_status") != "verified":
                            unverified.append(question_id)
                    if unverified:
                        raise ValueError(
                            f"Reviewed assessment pack {prepared['pack_id']!r} contains unverified items: "
                            + ", ".join(unverified[:10])
                        )
                seen_packs.add(pack_id)
        else:
            raise ValueError(f"Unsupported corpus file kind: {kind}")


def _bind_provenance(
    item: dict[str, Any],
    corpus_id: str,
    source_type: str,
    authenticity: str | None,
) -> None:
    declared_corpus = item.get("corpus_id")
    if declared_corpus is not None and str(declared_corpus) != corpus_id:
        raise ValueError(
            f"Item {item.get('question_id') or item.get('passage_id') or item.get('pack_id')} declares corpus_id "
            f"{declared_corpus!r}, expected {corpus_id!r}"
        )
    declared_source = item.get("source_type")
    if declared_source is not None and str(declared_source) != source_type:
        raise ValueError(
            f"Item {item.get('question_id') or item.get('passage_id') or item.get('pack_id')} declares source_type "
            f"{declared_source!r}, expected {source_type!r}"
        )
    declared_authenticity = item.get("authenticity")
    if authenticity and declared_authenticity is not None and str(declared_authenticity) != authenticity:
        raise ValueError(
            f"Item {item.get('question_id') or item.get('passage_id') or item.get('pack_id')} declares authenticity "
            f"{declared_authenticity!r}, expected {authenticity!r}"
        )
    item["corpus_id"] = corpus_id
    item["source_type"] = source_type
    if authenticity is not None:
        item["authenticity"] = authenticity


def _discard_source_review_claim(item: dict[str, Any]) -> None:
    """Keep source metadata as evidence, never as a local human approval."""
    declared = item.get("review_status")
    if declared is not None:
        item["source_review_status"] = str(declared)
    declared_conformance = item.pop("conformance_status", None)
    if declared_conformance is not None:
        item["source_conformance_status"] = str(declared_conformance)
    item.pop("conformance_report", None)
    item["review_status"] = "unreviewed"


def search_questions(
    home: Path,
    *,
    query: str | None = None,
    module: str | None = None,
    task: str | None = None,
    part: int | str | None = None,
    question_type: str | None = None,
    topic: str | None = None,
    source_type: str | None = None,
    corpus_id: str | None = None,
    passage_id: str | None = None,
    exclude_completed: bool = False,
    learner_ready: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = list_questions(
        home,
        query=query,
        module=module,
        task=task,
        part=part,
        question_type=question_type,
        topic=topic,
        source_type=source_type,
        corpus_id=corpus_id,
        passage_id=passage_id,
        exclude_completed=exclude_completed,
        learner_ready=learner_ready,
        limit=limit,
        offset=offset,
    )
    return [dict(row) for row in rows]


def draw_question(home: Path, *, seed: int | None = None, **filters: Any) -> dict[str, Any] | None:
    configured_limit = max(
        1, int(load_settings(home).get("question_draw_limit", 100000))
    )
    candidate_count = min(count_questions(home, **filters), configured_limit)
    if candidate_count < 1:
        return None
    rng = random.Random(seed)
    selected = search_questions(
        home,
        limit=1,
        offset=rng.randrange(candidate_count),
        **filters,
    )[0]
    return get_question(home, selected["question_id"], include_answer=False)


def show_question(home: Path, question_id: str, include_answer: bool = False) -> dict[str, Any] | None:
    return get_question(home, question_id, include_answer=include_answer)


def show_reading_set(home: Path, passage_id: str, include_answers: bool = False) -> dict[str, Any] | None:
    if not include_answers:
        with connect(home) as conn:
            passage_row = conn.execute(
                "SELECT payload_json FROM question_passages WHERE passage_id=?",
                (passage_id,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT question_id,payload_json
                FROM questions
                WHERE module='reading' AND passage_id=?
                ORDER BY question_id
                """,
                (passage_id,),
            ).fetchall()
            if not rows:
                return None
            question_ids = [str(row["question_id"]) for row in rows]
            placeholders = ",".join("?" for _ in question_ids)
            option_rows = conn.execute(
                f"""
                SELECT question_id,option_key,option_text
                FROM question_options
                WHERE question_id IN ({placeholders})
                ORDER BY question_id,id
                """,
                question_ids,
            ).fetchall()
        options: dict[str, list[dict[str, str]]] = {}
        for row in option_rows:
            options.setdefault(str(row["question_id"]), []).append(
                {"key": str(row["option_key"]), "text": str(row["option_text"])}
            )
        questions = []
        for row in rows:
            item = redact_answer_data(json.loads(row["payload_json"]))
            if options.get(str(row["question_id"])):
                item["options"] = options[str(row["question_id"])]
            questions.append(item)
        passage = (
            redact_answer_data(json.loads(passage_row["payload_json"]))
            if passage_row
            else None
        )
        if passage and isinstance(passage.get("body"), list):
            passage["body"] = "\n\n".join(
                str(value) for value in passage["body"]
            )
        return {
            "passage": passage,
            "questions": questions,
            "conformance": assess_reading_set(passage or {}, questions),
        }

    rows = search_questions(home, module="reading", passage_id=passage_id, limit=1000)
    if not rows:
        return None
    questions: list[dict[str, Any]] = []
    passage: dict[str, Any] | None = None
    for row in rows:
        item = get_question(home, str(row["question_id"]), include_answer=include_answers)
        if item is None:
            continue
        if passage is None and isinstance(item.get("passage"), dict):
            passage = item.pop("passage")
        else:
            item.pop("passage", None)
        questions.append(item)
    return {
        "passage": passage,
        "questions": questions,
        "conformance": assess_reading_set(passage or {}, questions),
    }


def _question_exists(home: Path, question_id: str) -> bool:
    with connect(home) as conn:
        return conn.execute(
            "SELECT 1 FROM questions WHERE question_id=?", (question_id,)
        ).fetchone() is not None


def _prepare_assessment_pack(
    pack: dict[str, Any],
    *,
    corpus_id: str,
    source_type: str,
    authenticity: str | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    item = dict(pack)
    _bind_provenance(item, corpus_id, source_type, authenticity)
    permissions = (manifest or {}).get("permissions") or {}
    if permissions.get("redistribution_allowed"):
        item.setdefault("rights_status", "redistributable")
    elif permissions.get("local_personal_use_only"):
        item.setdefault("rights_status", "local_private")
    else:
        item.setdefault("rights_status", "external_reference")
    item.setdefault("standard_profile", "ielts-academic")
    item.setdefault("standard_version", "2026-07")
    _discard_source_review_claim(item)
    report = assess_pack(item)
    declared = item.get("conformance_status")
    if declared == "verified" and report["status"] != "verified":
        raise ValueError(
            f"Assessment pack {item.get('pack_id')} claims verified conformance but failed: "
            + "; ".join(report["errors"] or report["warnings"])
        )
    item["conformance_status"] = report["status"]
    item["conformance_report"] = report
    return validate_data(item, "assessment-pack")
