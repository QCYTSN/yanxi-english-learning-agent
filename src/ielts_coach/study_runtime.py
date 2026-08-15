from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from collections.abc import Callable

from .rubrics import require_rubric
from .session_io import load_session_file
from .session_manager import (
    PREFIXES,
    assert_session_mirror_consistent,
    persist_session_atomic,
)
from .storage import (
    connect,
    get_question,
    get_question_for_grading,
    get_session,
    initialise_database,
    record_session,
    record_runtime_event,
    session_payload_hash,
    set_session_mirror_status,
)
from .validation import validate_data
from .errors import (
    AnswerRevealLockedError,
    SessionMirrorConflictError,
    SessionRevisionConflictError,
)
from .locking import runtime_lock
from .listening_corpus import listening_item, normalise_listening_answer


TERMINAL_STATUSES = {"completed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_path(home: Path, session_id: str, module: str | None = None) -> Path:
    modules = (module,) if module else tuple(PREFIXES)
    for candidate_module in modules:
        candidate = home / "sessions" / str(candidate_module) / f"{session_id}.md"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Session document not found: {session_id}")


def _db_payload(home: Path, session_id: str) -> dict[str, Any] | None:
    row = get_session(home, session_id)
    return json.loads(row["payload_json"]) if row else None


def reconcile_session(
    home: Path,
    session_id: str,
    *,
    prefer: str = "auto",
) -> dict[str, Any]:
    """Explicitly reconcile Session projections without silently choosing a fork."""
    if prefer not in {"auto", "markdown", "sqlite"}:
        raise ValueError("prefer must be auto, markdown or sqlite")
    with runtime_lock(home, f"session:{session_id}"):
        db_data = _db_payload(home, session_id)
        module = str(db_data["module"]) if db_data else None
        path = session_path(home, session_id, module)
        file_data = load_session_file(path)
        if not db_data:
            return persist_session_atomic(
                home,
                path,
                file_data,
                allow_reconcile=True,
            )
        file_revision = int(file_data.get("revision", 0))
        db_revision = int(db_data.get("revision", 0))
        file_hash = session_payload_hash(file_data)
        db_hash = session_payload_hash(db_data)
        if file_revision == db_revision and file_hash == db_hash:
            # Re-recording an explicitly reconciled projection also refreshes
            # payload_hash. Older runtimes could update payload_json without
            # maintaining that guard, leaving two identical projections that
            # still failed the cross-store health audit.
            record_session(home, db_data, mirror_status="synced")
            return file_data
        if file_revision == db_revision and prefer == "auto":
            set_session_mirror_status(home, session_id, "conflict")
            raise SessionMirrorConflictError(
                "Same-revision Session projections contain different content; "
                "choose markdown or sqlite explicitly.",
                details={
                    "session_id": session_id,
                    "revision": file_revision,
                    "markdown_hash": file_hash,
                    "sqlite_hash": db_hash,
                },
            )
        use_markdown = (
            prefer == "markdown"
            or (prefer == "auto" and file_revision > db_revision)
        )
        if use_markdown:
            return persist_session_atomic(
                home,
                path,
                file_data,
                allow_reconcile=True,
            )
        body = str(file_data.get("document_body", ""))
        return persist_session_atomic(
            home,
            path,
            db_data,
            body=body,
            allow_reconcile=True,
        )


def resume_session(home: Path, module: str | None = None) -> dict[str, Any] | None:
    initialise_database(home)
    sql = "SELECT session_id FROM sessions WHERE status NOT IN ('completed','cancelled')"
    params: list[Any] = []
    if module:
        sql += " AND module=?"
        params.append(module)
    sql += " ORDER BY updated_at DESC,occurred_at DESC LIMIT 1"
    with connect(home) as conn:
        row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    session_id = str(row["session_id"])
    path = session_path(home, session_id)
    assert_session_mirror_consistent(home, path)
    return _db_payload(home, session_id)


def mutate_session(
    home: Path,
    session_id: str,
    event_type: str,
    mutator: Callable[[dict[str, Any]], None],
    *,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    path = session_path(home, session_id)
    with runtime_lock(home, f"session:{session_id}"):
        assert_session_mirror_consistent(home, path)
        data = load_session_file(path)
        applied = list(data.get("applied_operations") or [])
        if idempotency_key:
            replay = next(
                (item for item in reversed(applied) if item.get("key") == idempotency_key),
                None,
            )
            if replay:
                data.pop("document_body", None)
                return data
        current = int(data.get("revision", 0))
        if expected_revision is not None and current != expected_revision:
            raise SessionRevisionConflictError(
                f"Stale Session revision: expected {expected_revision}, current {current}",
                details={"expected": expected_revision, "current": current},
            )
        if data.get("status") in TERMINAL_STATUSES:
            raise ValueError(f"Cannot modify a {data.get('status')} Session")
        mutator(data)
        data["revision"] = current + 1
        if idempotency_key:
            applied.append(
                {"key": idempotency_key, "operation": event_type, "revision": data["revision"]}
            )
            data["applied_operations"] = applied[-50:]
        saved = persist_session_atomic(home, path, data)
        record_runtime_event(
            home,
            event_id=f"{session_id}:{saved['revision']}:{event_type}",
            event_type=event_type,
            session_id=session_id,
            module=str(saved["module"]),
            revision=int(saved["revision"]),
            payload={"status": saved.get("status")},
        )
        saved.pop("document_body", None)
        return saved


def submit_writing_version(
    home: Path,
    session_id: str,
    *,
    label: str,
    content: str,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    label = label.lower()
    if label not in {"v1", "v2", "final"}:
        raise ValueError("Writing version label must be v1, v2, or final")
    if not content.strip():
        raise ValueError("Writing content must not be empty")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "writing":
            raise ValueError("This operation requires a Writing Session")
        versions = data.setdefault("versions", [])
        existing = next((item for item in versions if item.get("label") == label), None)
        item = {"label": label, "content": content.strip(), "word_count": len(content.split())}
        if existing:
            existing.update(item)
        else:
            versions.append(item)
        data["status"] = "awaiting_feedback"
        data["submitted_at"] = _now()

    return mutate_session(
        home, session_id, f"writing_version_{label}", apply,
        expected_revision=expected_revision, idempotency_key=idempotency_key,
    )


def submit_listening_attempt(
    home: Path,
    session_id: str,
    *,
    item_id: str,
    user_answer: str,
    error_tags: list[str] | None = None,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    item = listening_item(home, item_id)
    answer = user_answer.strip()
    if not answer:
        raise ValueError("Listening answer must not be empty")
    is_correct = normalise_listening_answer(answer) == normalise_listening_answer(
        str(item["expression"])
    )
    tags = [str(tag).strip() for tag in (error_tags or []) if str(tag).strip()]
    if not is_correct and not tags:
        tags = ["listening_spelling_or_segmentation"]
    attempted_at = _now()

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "listening":
            raise ValueError("This operation requires a Listening Session")
        attempt = {
            "question_id": None,
            "item_id": item_id,
            "question_number": len(data.get("questions") or []) + 1,
            "question_type": "high_frequency_expression",
            "user_answer": answer,
            "correct_answer": item["expression"],
            "is_correct": is_correct,
            "error_tags": tags,
            "attempted_at": attempted_at,
            "category": item["category"],
        }
        data.setdefault("questions", []).append(attempt)
        attempts = data["questions"]
        data["score"] = {
            "correct": sum(1 for row in attempts if row.get("is_correct") is True),
            "total": len(attempts),
        }
        data["raw_score"] = data["score"]["correct"]
        data["last_listening_result"] = attempt
        if not is_correct:
            data.setdefault("errors", []).extend(
                {
                    "tag": tag,
                    "count": 1,
                    "evidence": f"{answer} -> {item['expression']}",
                    "status": "active",
                }
                for tag in tags
            )
        data["status"] = "learner_working"

    return mutate_session(
        home,
        session_id,
        "listening_high_frequency_attempt",
        apply,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )


def apply_writing_review(
    home: Path,
    session_id: str,
    review: dict[str, Any],
    *,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    review = validate_data(review, "writing-review")
    if review["score_kind"] != "ai_training_estimate":
        raise ValueError("Mock fixtures cannot be applied as learner Writing feedback")
    if review["session_id"] != session_id:
        raise ValueError("Writing review session_id does not match the target Session")
    registered_rubric = require_rubric(
        home, "ielts-writing-public-descriptors", "writing"
    )
    review = {
        **review,
        "rubric": {
            "rubric_id": registered_rubric["rubric_id"],
            "publisher": registered_rubric["publisher"],
            "standard": registered_rubric["standard"],
            "version": registered_rubric["version"],
            "source_reference": registered_rubric["source_reference"],
        },
    }

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "writing":
            raise ValueError("This operation requires a Writing Session")
        if data.get("task") and data["task"] != review["task"]:
            raise ValueError("Writing review task does not match the Session task")
        labels = {item.get("label") for item in data.get("versions") or []}
        if review["version_label"] not in labels:
            raise ValueError("Writing review references a version not submitted by the learner")
        data["task"] = review["task"]
        data["scored_version"] = review["version_label"]
        data["score_kind"] = "ai_training_estimate"
        data["score_confidence"] = review["confidence"]
        data["rubric"] = review["rubric"]
        data["estimated_band_range"] = review.get("estimated_band")
        scores: list[dict[str, Any]] = []
        exact = True
        for item in review["criteria"]:
            exact = exact and item["score_low"] == item["score_high"]
            scores.append(
                {
                    "version": review["version_label"],
                    "criterion": item["criterion"],
                    "score_low": item["score_low"],
                    "score_high": item["score_high"],
                    "score": item["score_low"] if item["score_low"] == item["score_high"] else None,
                    "confidence": review["confidence"],
                    "assessment_role": "local_rubric",
                    "evidence_source": "text",
                    "rubric": review["rubric"],
                    "evidence": item["evidence_support"] + item["evidence_limit"],
                }
            )
        previous = [
            item for item in data.get("criterion_scores") or []
            if item.get("version", item.get("version_label")) != review["version_label"]
        ]
        data["criterion_scores"] = previous + scores
        if exact:
            mean = sum(Decimal(str(item["score"])) for item in scores) / Decimal("4")
            data["band"] = float((mean * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
        else:
            data["band"] = None
        data["errors"] = [
            {"tag": item["tag"], "count": 1, "evidence": item["evidence"], "status": "active"}
            for item in review["priority_issues"]
        ]
        data["writing_review"] = review
        data["status"] = "awaiting_revision"

    return mutate_session(
        home, session_id, "writing_review", apply,
        expected_revision=expected_revision, idempotency_key=idempotency_key,
    )


def record_reading_hint(
    home: Path,
    session_id: str,
    *,
    level: int | None = None,
    question_id: str | None = None,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    question = get_question(home, question_id, include_answer=False) if question_id else None
    if question_id and question is None:
        raise ValueError(f"Unknown Reading question: {question_id}")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "reading":
            raise ValueError("This operation requires a Reading Session")
        if data.get("mode") == "timed-practice":
            raise ValueError("Timed Reading practice cannot use hints")
        current = int(data.get("hints_used") or 0)
        next_level = current + 1 if level is None else level
        if next_level not in {1, 2, 3} or next_level < current:
            raise ValueError("Reading hint level must progress monotonically from 1 to 3")
        if question and str(question.get("passage_id") or "") != str(data.get("passage_id") or ""):
            raise ValueError("Reading hint question is not part of this Session passage")
        hint = _reading_hint(question, next_level)
        data["hints_used"] = next_level
        data["latest_hint"] = hint
        data["reading_hints"] = [
            *(data.get("reading_hints") or []),
            hint,
        ][-20:]
        data["status"] = "learner_working"

    return mutate_session(
        home, session_id, "reading_hint", apply,
        expected_revision=expected_revision, idempotency_key=idempotency_key,
    )


def _reading_hint(question: dict[str, Any] | None, level: int) -> dict[str, Any]:
    question_type = str((question or {}).get("question_type") or "unknown")
    strategies = {
        "true_false_not_given": (
            "先判断题干是在陈述事实，还是加入了原文没有比较或限定的信息。",
            "定位题干中的专有名词、数字和限定词，再核对原文表达的是相同、相反，还是没有说明。",
            "最后只检查命题中的范围词与程度词；没有证据不能推成 FALSE，应保留 NOT GIVEN。",
        ),
        "yes_no_not_given": (
            "先确认题干问的是作者观点，而不是文中出现过的客观事实。",
            "定位态度词和评价词，比较作者是否明确赞同、反对，或没有表达立场。",
            "不要用常识补全作者观点；只有明确相反才选 NO，没有立场证据应考虑 NOT GIVEN。",
        ),
        "matching_headings": (
            "先概括每段的中心功能，不要被单个重复词吸引。",
            "比较段落开头、转折句和结尾句，排除只覆盖细节的标题。",
            "用一句话复述整段后再匹配；正确标题必须覆盖主旨而不是例子。",
        ),
        "multiple_choice": (
            "先圈出题干限制条件，再回原文定位同义改写。",
            "逐项找原文证据，区分“原文提到”与“真正回答题干”。",
            "对剩余选项检查范围扩大、因果倒置和偷换主体三类干扰。",
        ),
        "sentence_completion": (
            "先根据空格前后判断所需词性和语法形式。",
            "回原文寻找题干同义改写，并严格遵守词数限制。",
            "代回完整句检查语法、拼写和单复数；不要改写必须取自原文的词。",
        ),
        "summary_completion": (
            "先快速读完整摘要，判断每个空格需要的词性与主题位置。",
            "利用摘要顺序通常跟随原文的特点，从上一个定位点继续向后找。",
            "代回后同时检查逻辑、语法和词数限制，避免把邻近但关系错误的词填入。",
        ),
    }
    generic = (
        "先圈出题干中的定位词与限制词，再寻找原文中的同义改写。",
        "缩小到相关段落，判断题干真正考查的是主旨、细节还是逻辑关系。",
        "提交前核对证据、语法形式和词数限制；不要用原文之外的常识补答案。",
    )
    messages = strategies.get(question_type, generic)
    return {
        "level": level,
        "question_id": (question or {}).get("question_id"),
        "question_type": question_type,
        "message": messages[level - 1],
        "generated_by": "study_runtime",
        "answer_revealed": False,
        "created_at": _now(),
    }


def submit_reading_answers(
    home: Path,
    session_id: str,
    answers: list[dict[str, Any]],
    *,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not answers:
        raise ValueError("At least one Reading answer is required")

    graded_answers: list[dict[str, Any]] = []
    for item in answers:
        question_id = item.get("question_id")
        question = get_question_for_grading(home, str(question_id)) if question_id else None
        graded_answers.append(_grade_reading_item(item, question))

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "reading":
            raise ValueError("This operation requires a Reading Session")
        clean: list[dict[str, Any]] = []
        for item in graded_answers:
            if not item.get("question_type") or item.get("user_answer") in {None, ""}:
                raise ValueError("Each Reading answer needs question_type and user_answer")
            clean.append(
                {
                    "question_id": item.get("question_id"),
                    "question_number": item.get("question_number"),
                    "question_type": item["question_type"],
                    "user_answer": item["user_answer"],
                    "duration_seconds": item.get("duration_seconds"),
                    "correct_answer": item.get("correct_answer"),
                    "is_correct": item.get("is_correct"),
                    "error_tags": [],
                }
            )
        data["questions"] = clean
        scored = [item for item in clean if item.get("is_correct") is not None]
        if scored:
            correct = sum(1 for item in scored if item["is_correct"] is True)
            data["raw_score"] = correct
            data["score"] = {"correct": correct, "total": len(scored)}
            data["score_kind"] = "answer_key_estimate"
            data["answer_key_source"] = "local-corpus-validated-key"
            # A raw score is not an IELTS band unless a verified full-test pack
            # also supplies an explicit conversion table and source.
            if data.get("practice_mode") != "full_mock" or data.get("conformance_status") != "verified":
                data["band"] = None
        data["submitted_at"] = _now()
        data["status"] = "awaiting_feedback"

    return mutate_session(
        home, session_id, "reading_submission", apply,
        expected_revision=expected_revision, idempotency_key=idempotency_key,
    )


def _normalise_objective_answer(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(sorted(_normalise_objective_answer(item) for item in value))
    return " ".join(str(value or "").strip().casefold().split())


def _grade_reading_item(item: dict[str, Any], question: dict[str, Any] | None) -> dict[str, Any]:
    graded = dict(item)
    if not question or "correct_answer" not in question:
        graded["is_correct"] = None
        return graded
    correct_answer = question["correct_answer"]
    accepted = question.get("accepted_answers") or question.get("accepted_variants") or []
    candidates = [correct_answer, *(accepted if isinstance(accepted, list) else [accepted])]
    submitted = _normalise_objective_answer(item.get("user_answer"))
    graded["correct_answer"] = correct_answer
    graded["is_correct"] = any(
        submitted == _normalise_objective_answer(candidate) for candidate in candidates
    )
    return graded


def apply_reading_review(
    home: Path,
    session_id: str,
    review: dict[str, Any],
    *,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    review = validate_data(review, "reading-review")
    if review["session_id"] != session_id:
        raise ValueError("Reading review session_id does not match the target Session")

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "reading":
            raise ValueError("This operation requires a Reading Session")
        if review["mode"] == "guided_hint":
            if data.get("mode") == "timed-practice":
                raise ValueError("Timed Reading practice cannot receive guided hints")
            data["hints_used"] = max(int(data.get("hints_used") or 0), int(review["hint_level"]))
            data["reading_review"] = review
            data["status"] = "learner_working"
            return
        if review["answer_revealed"] and not data.get("submitted_at"):
            raise AnswerRevealLockedError(
                "Reading answers cannot be revealed before learner submission"
            )
        submitted = {str(item.get("question_id") or item.get("question_number")): item for item in data.get("questions") or []}
        merged_by_key = {key: dict(value) for key, value in submitted.items()}
        errors: list[dict[str, Any]] = []
        for item in review["items"]:
            key = str(item.get("question_id") or item.get("question_number"))
            base = dict(merged_by_key.get(key, {}))
            base.update(item)
            if "correct_answer" in item:
                base["is_correct"] = str(base.get("user_answer")).casefold() == str(item["correct_answer"]).casefold()
            merged_by_key[key] = base
            for tag in item.get("error_tags") or []:
                errors.append({"tag": tag, "count": 1, "evidence": item.get("reasoning"), "status": "active"})
        data["questions"] = list(merged_by_key.values()) or data.get("questions", [])
        data["errors"] = errors
        data["reading_review"] = review
        data["answer_revealed_at"] = _now() if review["answer_revealed"] else data.get("answer_revealed_at")
        correct = sum(1 for item in data["questions"] if item.get("is_correct") is True)
        scored = sum(1 for item in data["questions"] if item.get("is_correct") is not None)
        data["score"] = {"correct": correct, "total": scored} if scored else data.get("score")
        data["status"] = "awaiting_revision"

    return mutate_session(
        home, session_id, "reading_review", apply,
        expected_revision=expected_revision, idempotency_key=idempotency_key,
    )
