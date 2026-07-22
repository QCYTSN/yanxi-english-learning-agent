from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable

from .storage import (
    connect,
    get_question,
    list_questions,
    question_attempted,
    upsert_passage,
    upsert_question,
)
from .config import load_settings
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
    force: bool = False,
) -> dict[str, int]:
    counts = {"passages": 0, "questions": 0, "duplicates": 0}
    ordered_files = sorted(files, key=lambda item: 0 if item.get("kind") == "passages" else 1)
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
                upsert_passage(home, passage)
                counts["passages"] += 1
        elif kind == "questions":
            for question in _jsonl(path):
                _bind_provenance(question, corpus_id, source_type, authenticity)
                question.setdefault("review_status", "unreviewed")
                question["content_hash"] = content_hash(question)
                question = validate_data(question, "question")
                inserted = upsert_question(home, question, force=force)
                if inserted:
                    counts["questions"] += 1
                else:
                    counts["duplicates"] += 1
        else:
            raise ValueError(f"Unsupported corpus file kind: {kind}")
    return counts


def preflight_question_files(
    home: Path,
    corpus_id: str,
    base_path: Path,
    files: list[dict[str, Any]],
    *,
    source_type: str,
    authenticity: str | None = None,
) -> None:
    """Validate a complete import before mutating its manifest or database."""
    seen_passages: set[str] = set()
    seen_questions: set[str] = set()
    with connect(home) as conn:
        passage_owners = {
            str(row["passage_id"]): row["corpus_id"]
            for row in conn.execute("SELECT passage_id,corpus_id FROM question_passages")
        }
        question_owners = {
            str(row["question_id"]): row["corpus_id"]
            for row in conn.execute("SELECT question_id,corpus_id FROM questions")
        }
    ordered_files = sorted(files, key=lambda item: 0 if item.get("kind") == "passages" else 1)
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
                question.setdefault("review_status", "unreviewed")
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
            f"Item {item.get('question_id') or item.get('passage_id')} declares corpus_id "
            f"{declared_corpus!r}, expected {corpus_id!r}"
        )
    declared_source = item.get("source_type")
    if declared_source is not None and str(declared_source) != source_type:
        raise ValueError(
            f"Item {item.get('question_id') or item.get('passage_id')} declares source_type "
            f"{declared_source!r}, expected {source_type!r}"
        )
    declared_authenticity = item.get("authenticity")
    if authenticity and declared_authenticity is not None and str(declared_authenticity) != authenticity:
        raise ValueError(
            f"Item {item.get('question_id') or item.get('passage_id')} declares authenticity "
            f"{declared_authenticity!r}, expected {authenticity!r}"
        )
    item["corpus_id"] = corpus_id
    item["source_type"] = source_type
    if authenticity is not None:
        item["authenticity"] = authenticity


def search_questions(
    home: Path,
    *,
    query: str | None = None,
    module: str | None = None,
    task: str | None = None,
    question_type: str | None = None,
    topic: str | None = None,
    source_type: str | None = None,
    corpus_id: str | None = None,
    passage_id: str | None = None,
    exclude_completed: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = list_questions(
        home,
        query=query,
        module=module,
        task=task,
        question_type=question_type,
        topic=topic,
        source_type=source_type,
        corpus_id=corpus_id,
        passage_id=passage_id,
        exclude_completed=exclude_completed,
        limit=limit,
    )
    return [dict(row) for row in rows]


def draw_question(home: Path, *, seed: int | None = None, **filters: Any) -> dict[str, Any] | None:
    limit = int(load_settings(home).get("question_draw_limit", 100000))
    candidates = search_questions(home, limit=limit, **filters)
    if not candidates:
        return None
    rng = random.Random(seed)
    selected = rng.choice(candidates)
    return get_question(home, selected["question_id"], include_answer=False)


def show_question(home: Path, question_id: str, include_answer: bool = False) -> dict[str, Any] | None:
    return get_question(home, question_id, include_answer=include_answer)


def show_reading_set(home: Path, passage_id: str, include_answers: bool = False) -> dict[str, Any] | None:
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
    return {"passage": passage, "questions": questions}
