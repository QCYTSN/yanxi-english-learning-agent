from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .conformance import assess_pack, assess_question
from .storage import (
    connect,
    get_question,
    initialise_database,
)


TARGET_TYPES = {"question", "passage", "assessment_pack"}
DECISIONS = {"approved", "changes_requested", "rejected"}
_DERIVED_FIELDS = {
    "review_status",
    "conformance_status",
    "conformance_report",
    "local_review_status",
}


def review_content_hash(home: Path, target_type: str, target_id: str) -> str:
    _, material = _load_target(home, target_type, target_id)
    return _content_digest(material)


def _content_digest(material: dict[str, Any]) -> str:
    canonical = _strip_derived(material)
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def required_checklist(
    target_type: str,
    material: dict[str, Any],
) -> dict[str, str]:
    _validate_target_type(target_type)
    if target_type == "passage":
        return {
            "text_complete": "Passage text is complete and readable",
            "paragraph_labels_checked": "Paragraph labels and references were checked",
            "rights_checked": "Source and local-use rights were checked",
        }
    if target_type == "assessment_pack":
        return {
            "structure_checked": "IELTS module structure and timing were checked",
            "items_checked": "Every referenced item has a current local approval",
            "rights_checked": "Pack provenance and rights were checked",
        }
    checklist = {
        "prompt_complete": "Prompt and instructions are complete",
        "instructions_checked": "IELTS question-type instructions were checked",
        "rights_checked": "Source and local-use rights were checked",
    }
    module = str(material.get("module") or "")
    if module in {"reading", "listening"}:
        checklist.update(
            {
                "answer_key_checked": "Answer key and accepted variants were checked",
                "evidence_checked": "Evidence location or answer rationale was checked",
            }
        )
    else:
        checklist["ielts_format_checked"] = "Task or speaking part format was checked"
    return checklist


def get_target_review(
    home: Path,
    target_type: str,
    target_id: str,
    *,
    include_material: bool = True,
) -> dict[str, Any]:
    material, _ = _load_target(home, target_type, target_id)
    if target_type == "question" and include_material:
        # Preserve Reading answer integrity when a timed Session is active.
        visible = get_question(home, target_id, include_answer=True)
        if visible is None:
            raise ValueError(f"Unknown question: {target_id}")
        material = visible
    state = _review_state(home, target_type, target_id)
    result = {
        "target_type": target_type,
        "target_id": target_id,
        "content_hash": state["content_hash"],
        "local_review_status": state["local_review_status"],
        "current_review": state["current_review"],
        "stale_review_count": state["stale_review_count"],
        "required_checklist": required_checklist(target_type, material),
    }
    if include_material:
        result["material"] = material
    if target_type == "assessment_pack":
        result["dependency_status"] = _pack_dependency_status(home, material)
    return result


def get_target_review_statuses(
    home: Path,
    target_type: str,
    target_ids: list[str],
) -> dict[str, str]:
    """Resolve current local review states in bounded queries for list views."""
    _validate_target_type(target_type)
    ids = list(dict.fromkeys(str(value) for value in target_ids if value))
    if not ids:
        return {}
    initialise_database(home)
    table, key = {
        "question": ("questions", "question_id"),
        "passage": ("question_passages", "passage_id"),
        "assessment_pack": ("assessment_packs", "pack_id"),
    }[target_type]
    placeholders = ",".join("?" for _ in ids)
    with connect(home) as conn:
        rows = conn.execute(
            f"SELECT {key} target_id,payload_json FROM {table} WHERE {key} IN ({placeholders})",
            ids,
        ).fetchall()
        passage_payloads: dict[str, dict[str, Any]] = {}
        if target_type == "question":
            materials = [json.loads(row["payload_json"]) for row in rows]
            passage_ids = list(
                dict.fromkeys(
                    str(item["passage_id"])
                    for item in materials
                    if item.get("passage_id")
                )
            )
            if passage_ids:
                passage_placeholders = ",".join("?" for _ in passage_ids)
                passage_payloads = {
                    str(row["passage_id"]): json.loads(row["payload_json"])
                    for row in conn.execute(
                        f"""
                        SELECT passage_id,payload_json FROM question_passages
                        WHERE passage_id IN ({passage_placeholders})
                        """,
                        passage_ids,
                    ).fetchall()
                }
        review_rows = conn.execute(
            f"""
            SELECT target_id,content_hash,decision,superseded_at
            FROM content_reviews
            WHERE target_type=? AND target_id IN ({placeholders})
            """,
            [target_type, *ids],
        ).fetchall()

    current_hashes: dict[str, str] = {}
    for row in rows:
        material = json.loads(row["payload_json"])
        hash_material = dict(material)
        if target_type == "question" and material.get("passage_id"):
            passage = passage_payloads.get(str(material["passage_id"]))
            if passage:
                hash_material["_linked_passage"] = passage
        current_hashes[str(row["target_id"])] = _content_digest(hash_material)

    reviews: dict[str, list[Any]] = {}
    for row in review_rows:
        reviews.setdefault(str(row["target_id"]), []).append(row)
    result: dict[str, str] = {}
    for target_id in ids:
        current_hash = current_hashes.get(target_id)
        target_reviews = reviews.get(target_id, [])
        current = next(
            (
                row
                for row in target_reviews
                if current_hash
                and row["content_hash"] == current_hash
                and row["superseded_at"] is None
            ),
            None,
        )
        result[target_id] = (
            str(current["decision"])
            if current
            else (
                "stale"
                if any(row["content_hash"] != current_hash for row in target_reviews)
                else "unreviewed"
            )
        )
    return result


def record_content_review(
    home: Path,
    *,
    target_type: str,
    target_id: str,
    reviewer: str,
    decision: str,
    checklist: dict[str, bool] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    _validate_target_type(target_type)
    if decision not in DECISIONS:
        raise ValueError("Unsupported review decision")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer name is required")
    if len(reviewer) > 100:
        raise ValueError("Reviewer name is too long")
    if notes and len(notes) > 5000:
        raise ValueError("Review notes are too long")

    material, _ = _load_target(home, target_type, target_id)
    checklist = {str(key): bool(value) for key, value in (checklist or {}).items()}
    if decision == "approved":
        _validate_approval(home, target_type, target_id, material, checklist)

    current_hash = review_content_hash(home, target_type, target_id)
    now = _now()
    review_id = f"REV-{secrets.token_hex(8).upper()}"
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE content_reviews SET superseded_at=?
            WHERE target_type=? AND target_id=? AND content_hash=? AND superseded_at IS NULL
            """,
            (now, target_type, target_id, current_hash),
        )
        conn.execute(
            """
            INSERT INTO content_reviews(
              review_id,target_type,target_id,content_hash,reviewer,decision,
              checklist_json,notes,created_at,superseded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                review_id,
                target_type,
                target_id,
                current_hash,
                reviewer,
                decision,
                json.dumps(checklist, ensure_ascii=False, sort_keys=True),
                notes,
                now,
            ),
        )
    refresh_target_status(home, target_type, target_id)
    return get_target_review(home, target_type, target_id, include_material=False)


def approve_content_batch(
    home: Path,
    *,
    targets: list[tuple[str, str]],
    reviewer: str,
    notes: str,
) -> dict[str, int]:
    """Approve an already-audited target set without repeated dependency scans."""

    reviewer = reviewer.strip()
    if not reviewer or len(reviewer) > 100:
        raise ValueError("A reviewer name of at most 100 characters is required")
    if len(notes) > 5000:
        raise ValueError("Review notes are too long")
    unique = list(dict.fromkeys(targets))
    for target_type, _ in unique:
        _validate_target_type(target_type)

    non_packs: list[tuple[str, str, dict[str, Any], dict[str, bool], str]] = []
    packs: list[tuple[str, str, dict[str, Any], dict[str, bool], str]] = []
    for target_type, target_id in unique:
        material, _ = _load_target(home, target_type, target_id)
        checklist = {
            key: True for key in required_checklist(target_type, material)
        }
        item = (
            target_type,
            target_id,
            material,
            checklist,
            review_content_hash(home, target_type, target_id),
        )
        if target_type == "assessment_pack":
            packs.append(item)
            continue
        _validate_approval(home, target_type, target_id, material, checklist)
        non_packs.append(item)

    now = _now()
    initialise_database(home)
    with connect(home) as conn:
        for target_type, target_id, material, checklist, content_hash in non_packs:
            _insert_batch_approval(
                conn,
                target_type=target_type,
                target_id=target_id,
                content_hash=content_hash,
                reviewer=reviewer,
                checklist=checklist,
                notes=notes,
                now=now,
            )
            if target_type == "question":
                candidate = dict(material)
                candidate["review_status"] = "reviewed"
                report = assess_question(candidate)
                candidate["conformance_status"] = report["status"]
                candidate["conformance_report"] = report
                conn.execute(
                    """
                    UPDATE questions
                    SET review_status='reviewed',conformance_status=?,
                        payload_json=?,updated_at=?
                    WHERE question_id=?
                    """,
                    (
                        candidate["conformance_status"],
                        json.dumps(candidate, ensure_ascii=False, default=str),
                        now,
                        target_id,
                    ),
                )

    # Pack validation intentionally runs after question/passage approvals exist.
    prepared_packs: list[
        tuple[str, str, dict[str, Any], dict[str, bool], str]
    ] = []
    for item in packs:
        target_type, target_id, material, checklist, content_hash = item
        _validate_approval(home, target_type, target_id, material, checklist)
        prepared_packs.append(item)
    with connect(home) as conn:
        for target_type, target_id, material, checklist, content_hash in prepared_packs:
            _insert_batch_approval(
                conn,
                target_type=target_type,
                target_id=target_id,
                content_hash=content_hash,
                reviewer=reviewer,
                checklist=checklist,
                notes=notes,
                now=now,
            )
            candidate = dict(material)
            candidate["review_status"] = "reviewed"
            report = assess_pack(candidate)
            candidate["conformance_status"] = report["status"]
            candidate["conformance_report"] = report
            conn.execute(
                """
                UPDATE assessment_packs
                SET review_status='reviewed',conformance_status=?,
                    payload_json=?,updated_at=?
                WHERE pack_id=?
                """,
                (
                    candidate["conformance_status"],
                    json.dumps(candidate, ensure_ascii=False, default=str),
                    now,
                    target_id,
                ),
            )
    return {
        "questions": sum(item[0] == "question" for item in non_packs),
        "passages": sum(item[0] == "passage" for item in non_packs),
        "assessment_packs": len(prepared_packs),
    }


def _insert_batch_approval(
    conn: Any,
    *,
    target_type: str,
    target_id: str,
    content_hash: str,
    reviewer: str,
    checklist: dict[str, bool],
    notes: str,
    now: str,
) -> None:
    conn.execute(
        """
        UPDATE content_reviews SET superseded_at=?
        WHERE target_type=? AND target_id=? AND content_hash=?
          AND superseded_at IS NULL
        """,
        (now, target_type, target_id, content_hash),
    )
    conn.execute(
        """
        INSERT INTO content_reviews(
          review_id,target_type,target_id,content_hash,reviewer,decision,
          checklist_json,notes,created_at,superseded_at
        ) VALUES(?,?,?,?,?,'approved',?,?,?,NULL)
        """,
        (
            f"REV-{secrets.token_hex(8).upper()}",
            target_type,
            target_id,
            content_hash,
            reviewer,
            json.dumps(checklist, ensure_ascii=False, sort_keys=True),
            notes,
            now,
        ),
    )


def refresh_target_status(home: Path, target_type: str, target_id: str) -> None:
    material, _ = _load_target(home, target_type, target_id)
    state = _review_state(home, target_type, target_id)
    approved = state["local_review_status"] == "approved"
    if target_type == "passage":
        with connect(home) as conn:
            question_ids = [
                str(row["question_id"])
                for row in conn.execute(
                    "SELECT question_id FROM questions WHERE passage_id=?",
                    (target_id,),
                ).fetchall()
            ]
        for question_id in question_ids:
            refresh_target_status(home, "question", question_id)
        _refresh_dependent_packs(home, "passage", target_id)
        return
    if target_type == "question":
        candidate = dict(material)
        candidate["review_status"] = "reviewed" if approved else "unreviewed"
        report = assess_question(candidate)
        candidate["conformance_status"] = report["status"]
        candidate["conformance_report"] = report
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE questions
                SET review_status=?,conformance_status=?,payload_json=?,updated_at=?
                WHERE question_id=?
                """,
                (
                    candidate["review_status"],
                    candidate["conformance_status"],
                    json.dumps(candidate, ensure_ascii=False, default=str),
                    _now(),
                    target_id,
                ),
            )
        _refresh_dependent_packs(home, "question", target_id)
        return

    dependency_status = _pack_dependency_status(home, material)
    effectively_approved = approved and dependency_status["ready"]
    candidate = dict(material)
    candidate["review_status"] = "reviewed" if effectively_approved else "in_review"
    report = assess_pack(candidate)
    candidate["conformance_status"] = report["status"]
    candidate["conformance_report"] = report
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE assessment_packs
            SET review_status=?,conformance_status=?,payload_json=?,updated_at=?
            WHERE pack_id=?
            """,
            (
                candidate["review_status"],
                candidate["conformance_status"],
                json.dumps(candidate, ensure_ascii=False, default=str),
                _now(),
                target_id,
            ),
        )


def _refresh_dependent_packs(home: Path, target_type: str, target_id: str) -> None:
    key = "question_ids" if target_type == "question" else "passage_ids"
    with connect(home) as conn:
        rows = conn.execute("SELECT pack_id,payload_json FROM assessment_packs").fetchall()
    pack_ids = [
        str(row["pack_id"])
        for row in rows
        if target_id in {str(value) for value in (json.loads(row["payload_json"]).get(key) or [])}
    ]
    for pack_id in pack_ids:
        refresh_target_status(home, "assessment_pack", pack_id)


def list_content_reviews(
    home: Path,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if target_type:
        _validate_target_type(target_type)
        clauses.append("target_type=?")
        params.append(target_type)
    if target_id:
        clauses.append("target_id=?")
        params.append(target_id)
    sql = "SELECT * FROM content_reviews"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_review_row(row) for row in rows]


def list_review_queue(
    home: Path,
    *,
    target_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if target_type:
        _validate_target_type(target_type)
    initialise_database(home)
    selected: list[tuple[str, str, str]] = []
    with connect(home) as conn:
        if target_type in {None, "question"}:
            selected.extend(
                ("question", str(row["question_id"]), str(row["title"] or row["content"])[:160])
                for row in conn.execute(
                    "SELECT question_id,title,content FROM questions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            )
        if target_type in {None, "passage"}:
            selected.extend(
                ("passage", str(row["passage_id"]), str(row["title"] or row["passage_id"]))
                for row in conn.execute(
                    "SELECT passage_id,title FROM question_passages ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            )
        if target_type in {None, "assessment_pack"}:
            selected.extend(
                ("assessment_pack", str(row["pack_id"]), str(row["title"]))
                for row in conn.execute(
                    "SELECT pack_id,title FROM assessment_packs ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            )
    result: list[dict[str, Any]] = []
    for item_type, item_id, title in selected:
        state = _review_state(home, item_type, item_id)
        if state["local_review_status"] == "approved":
            continue
        result.append(
            {
                "target_type": item_type,
                "target_id": item_id,
                "title": title,
                "local_review_status": state["local_review_status"],
                "stale_review_count": state["stale_review_count"],
            }
        )
        if len(result) >= limit:
            break
    return result


def ensure_bundled_content_reviews(
    home: Path,
    *,
    corpus_id: str,
    reviewer: str = "IELTS AI Coach bundled-content review",
) -> None:
    """Register project-controlled reviews; user manifests cannot invoke this path."""
    initialise_database(home)
    now = _now()
    pack_ids: list[str] = []
    with connect(home) as conn:
        passage_rows = conn.execute(
            "SELECT passage_id,payload_json FROM question_passages WHERE corpus_id=?",
            (corpus_id,),
        ).fetchall()
        passage_material = {
            str(row["passage_id"]): json.loads(row["payload_json"])
            for row in passage_rows
        }
        question_rows = conn.execute(
            "SELECT question_id,payload_json FROM questions WHERE corpus_id=?",
            (corpus_id,),
        ).fetchall()
        for target_type, target_id, material, hash_material in [
            *[
                ("passage", passage_id, payload, payload)
                for passage_id, payload in passage_material.items()
            ],
            *[
                (
                    "question",
                    str(row["question_id"]),
                    json.loads(row["payload_json"]),
                    {
                        **json.loads(row["payload_json"]),
                        **(
                            {"_linked_passage": passage_material[str(json.loads(row["payload_json"])["passage_id"])]}
                            if json.loads(row["payload_json"]).get("passage_id")
                            and str(json.loads(row["payload_json"])["passage_id"]) in passage_material
                            else {}
                        ),
                    },
                )
                for row in question_rows
            ],
        ]:
            content_hash = _content_digest(hash_material)
            approved = conn.execute(
                """
                SELECT 1 FROM content_reviews
                WHERE target_type=? AND target_id=? AND content_hash=?
                  AND decision='approved' AND superseded_at IS NULL
                LIMIT 1
                """,
                (target_type, target_id, content_hash),
            ).fetchone()
            if not approved:
                checklist = {
                    key: True for key in required_checklist(target_type, material)
                }
                conn.execute(
                    """
                    INSERT INTO content_reviews(
                      review_id,target_type,target_id,content_hash,reviewer,decision,
                      checklist_json,notes,created_at,superseded_at
                    ) VALUES(?,?,?,?,?,'approved',?,?,?,NULL)
                    """,
                    (
                        f"REV-{secrets.token_hex(8).upper()}",
                        target_type,
                        target_id,
                        content_hash,
                        reviewer,
                        json.dumps(checklist, ensure_ascii=False, sort_keys=True),
                        "Project-owned bundled content reviewed before release.",
                        now,
                    ),
                )
            if target_type == "question":
                candidate = dict(material)
                candidate["review_status"] = "reviewed"
                report = assess_question(candidate)
                candidate["conformance_status"] = report["status"]
                candidate["conformance_report"] = report
                conn.execute(
                    """
                    UPDATE questions
                    SET review_status='reviewed',conformance_status=?,payload_json=?,updated_at=?
                    WHERE question_id=?
                    """,
                    (
                        candidate["conformance_status"],
                        json.dumps(candidate, ensure_ascii=False, default=str),
                        now,
                        target_id,
                    ),
                )
        pack_ids = [
            str(row["pack_id"])
            for row in conn.execute(
                "SELECT pack_id FROM assessment_packs WHERE corpus_id=?",
                (corpus_id,),
            ).fetchall()
        ]
    for pack_id in pack_ids:
        state = _review_state(home, "assessment_pack", pack_id)
        if state["local_review_status"] == "approved":
            refresh_target_status(home, "assessment_pack", pack_id)
            continue
        material, _ = _load_target(home, "assessment_pack", pack_id)
        record_content_review(
            home,
            target_type="assessment_pack",
            target_id=pack_id,
            reviewer=reviewer,
            decision="approved",
            checklist={key: True for key in required_checklist("assessment_pack", material)},
            notes="Project-owned bundled content reviewed before release.",
        )


def _review_state(home: Path, target_type: str, target_id: str) -> dict[str, Any]:
    current_hash = review_content_hash(home, target_type, target_id)
    initialise_database(home)
    with connect(home) as conn:
        current = conn.execute(
            """
            SELECT * FROM content_reviews
            WHERE target_type=? AND target_id=? AND content_hash=? AND superseded_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (target_type, target_id, current_hash),
        ).fetchone()
        stale_count = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM content_reviews
                WHERE target_type=? AND target_id=? AND content_hash<>?
                """,
                (target_type, target_id, current_hash),
            ).fetchone()[0]
        )
    decision = str(current["decision"]) if current else None
    return {
        "content_hash": current_hash,
        "local_review_status": decision or ("stale" if stale_count else "unreviewed"),
        "current_review": _review_row(current) if current else None,
        "stale_review_count": stale_count,
    }


def _validate_approval(
    home: Path,
    target_type: str,
    target_id: str,
    material: dict[str, Any],
    checklist: dict[str, bool],
) -> None:
    required = required_checklist(target_type, material)
    missing = [key for key in required if checklist.get(key) is not True]
    if missing:
        raise ValueError("Approval requires every checklist item: " + ", ".join(missing))
    if target_type == "question":
        candidate = dict(material)
        candidate["review_status"] = "reviewed"
        report = assess_question(candidate)
        if report["errors"]:
            raise ValueError("Question failed IELTS conformance: " + "; ".join(report["errors"]))
        if candidate.get("module") == "reading" and not candidate.get("evidence_location"):
            raise ValueError("Reading approval requires an evidence_location")
    elif target_type == "assessment_pack":
        dependencies = _pack_dependency_status(home, material)
        if not dependencies["ready"]:
            missing_ids = dependencies["missing_question_reviews"] + dependencies["missing_passage_reviews"]
            raise ValueError(
                "Pack approval requires current local approval for every dependency: "
                + ", ".join(missing_ids[:12])
            )
        candidate = dict(material)
        candidate["review_status"] = "reviewed"
        report = assess_pack(candidate)
        if report["status"] != "verified":
            raise ValueError(
                "Pack structure is not complete: "
                + "; ".join(report["errors"] or report["warnings"])
            )


def _pack_dependency_status(home: Path, pack: dict[str, Any]) -> dict[str, Any]:
    question_ids = [str(value) for value in (pack.get("question_ids") or [])]
    passage_ids = [str(value) for value in (pack.get("passage_ids") or [])]
    initialise_database(home)
    with connect(home) as conn:
        question_material = _payloads_by_id(
            conn,
            table="questions",
            key="question_id",
            ids=question_ids,
        )
        linked_passage_ids = {
            str(material["passage_id"])
            for material in question_material.values()
            if material.get("passage_id")
        }
        all_passage_ids = list(dict.fromkeys([*passage_ids, *sorted(linked_passage_ids)]))
        passage_material = _payloads_by_id(
            conn,
            table="question_passages",
            key="passage_id",
            ids=all_passage_ids,
        )
        review_rows = conn.execute(
            """
            SELECT target_type,target_id,content_hash
            FROM content_reviews
            WHERE decision='approved' AND superseded_at IS NULL
              AND target_type IN ('question','passage')
            """
        ).fetchall()
    approved = {
        (str(row["target_type"]), str(row["target_id"]), str(row["content_hash"]))
        for row in review_rows
    }

    missing_questions: list[str] = []
    for question_id in question_ids:
        material = question_material.get(question_id)
        if material is None:
            missing_questions.append(question_id)
            continue
        hash_material = dict(material)
        passage_id = material.get("passage_id")
        if passage_id and str(passage_id) in passage_material:
            hash_material["_linked_passage"] = passage_material[str(passage_id)]
        content_hash = _content_digest(hash_material)
        if ("question", question_id, content_hash) not in approved:
            missing_questions.append(question_id)

    missing_passages = [
        passage_id
        for passage_id in passage_ids
        if passage_id not in passage_material
        or (
            "passage",
            passage_id,
            _content_digest(passage_material[passage_id]),
        )
        not in approved
    ]
    return {
        "ready": not missing_questions and not missing_passages,
        "missing_question_reviews": missing_questions,
        "missing_passage_reviews": missing_passages,
    }


def _payloads_by_id(
    conn: Any,
    *,
    table: str,
    key: str,
    ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT {key},payload_json FROM {table} WHERE {key} IN ({placeholders})",
        ids,
    ).fetchall()
    return {
        str(row[key]): json.loads(row["payload_json"])
        for row in rows
    }


def _load_target(
    home: Path,
    target_type: str,
    target_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_target_type(target_type)
    initialise_database(home)
    table, key = {
        "question": ("questions", "question_id"),
        "passage": ("question_passages", "passage_id"),
        "assessment_pack": ("assessment_packs", "pack_id"),
    }[target_type]
    with connect(home) as conn:
        row = conn.execute(
            f"SELECT payload_json FROM {table} WHERE {key}=?",
            (target_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown {target_type}: {target_id}")
        material = json.loads(row["payload_json"])
        hash_material: dict[str, Any] = dict(material)
        if target_type == "question" and material.get("passage_id"):
            passage = conn.execute(
                "SELECT payload_json FROM question_passages WHERE passage_id=?",
                (str(material["passage_id"]),),
            ).fetchone()
            if passage:
                hash_material["_linked_passage"] = json.loads(passage["payload_json"])
    return material, hash_material


def _strip_derived(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_derived(item)
            for key, item in value.items()
            if str(key) not in _DERIVED_FIELDS
        }
    if isinstance(value, list):
        return [_strip_derived(item) for item in value]
    return value


def _review_row(row: Any) -> dict[str, Any]:
    return {
        "review_id": str(row["review_id"]),
        "target_type": str(row["target_type"]),
        "target_id": str(row["target_id"]),
        "content_hash": str(row["content_hash"]),
        "reviewer": str(row["reviewer"]),
        "decision": str(row["decision"]),
        "checklist": json.loads(row["checklist_json"] or "{}"),
        "notes": row["notes"],
        "created_at": str(row["created_at"]),
        "superseded_at": row["superseded_at"],
    }


def _validate_target_type(target_type: str) -> None:
    if target_type not in TARGET_TYPES:
        raise ValueError("target_type must be question, passage, or assessment_pack")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
