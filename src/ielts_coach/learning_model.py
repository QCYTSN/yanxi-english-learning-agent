from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .domain_packs import DEFAULT_TRACK_ID, DomainPackSpec, get_domain_pack
from .errors import LearningRevisionConflictError
from .storage import connect, initialise_database


EVIDENCE_KIND_WEIGHTS = {
    "attempt": 1.0,
    "assessment": 1.25,
    "review": 1.1,
    "tutor_observation": 0.7,
    "self_report": 0.35,
}
OBJECTIVE_STATUSES = {"planned", "active", "achieved", "paused", "archived"}
ACTIVITY_STATUSES = {"planned", "in_progress", "completed", "cancelled"}
REVIEW_STATUSES = {"pending", "in_progress", "completed", "dismissed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _stable_id(prefix: str, *parts: object) -> str:
    source = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_value(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _bounded_score(value: float, label: str) -> float:
    score = float(value)
    if score < 0 or score > 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return score


def _iso_datetime(value: str | None, *, label: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 datetime") from exc
    return text


def _ensure_skill_nodes_conn(conn: sqlite3.Connection, pack: DomainPackSpec) -> None:
    fingerprint = hashlib.sha256(
        _json([item.descriptor() for item in pack.skills]).encode("utf-8")
    ).hexdigest()
    marker_key = f"domain_pack:{pack.track_id}:skills"
    marker = conn.execute(
        "SELECT value FROM schema_meta WHERE key=?",
        (marker_key,),
    ).fetchone()
    if marker and str(marker["value"]) == fingerprint:
        count = conn.execute(
            "SELECT COUNT(*) FROM learning_skill_nodes WHERE track_id=?",
            (pack.track_id,),
        ).fetchone()[0]
        if int(count) == len(pack.skills):
            return
    now = _now()
    for item in sorted(pack.skills, key=lambda skill: (skill.order, skill.skill_id)):
        conn.execute(
            """
            INSERT INTO learning_skill_nodes(
              track_id,skill_id,dimension_id,parent_skill_id,title,description,
              sort_order,metadata_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,'{}',?,?)
            ON CONFLICT(track_id,skill_id) DO UPDATE SET
              dimension_id=excluded.dimension_id,
              parent_skill_id=excluded.parent_skill_id,
              title=excluded.title,
              description=excluded.description,
              sort_order=excluded.sort_order,
              updated_at=excluded.updated_at
            """,
            (
                pack.track_id,
                item.skill_id,
                item.dimension_id,
                item.parent_skill_id,
                item.title,
                item.description,
                item.order,
                now,
                now,
            ),
        )
    conn.execute(
        """
        INSERT INTO schema_meta(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (marker_key, fingerprint),
    )


def ensure_learning_model(
    home: Path,
    track_id: str = DEFAULT_TRACK_ID,
) -> dict[str, Any]:
    initialise_database(home)
    pack = get_domain_pack(track_id)
    with connect(home) as conn:
        _ensure_skill_nodes_conn(conn, pack)
        count = conn.execute(
            "SELECT COUNT(*) FROM learning_skill_nodes WHERE track_id=?",
            (track_id,),
        ).fetchone()[0]
    return {"track_id": track_id, "skill_count": int(count)}


def list_skill_nodes(home: Path, *, track_id: str = DEFAULT_TRACK_ID) -> list[dict[str, Any]]:
    pack = get_domain_pack(track_id)
    ensure_learning_model(home, track_id)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT nodes.*,mastery.estimate,mastery.confidence AS mastery_confidence,
                   mastery.evidence_count,mastery.status AS mastery_status,
                   mastery.last_evidence_at,mastery.next_review_at,
                   mastery.calculation_json
            FROM learning_skill_nodes AS nodes
            LEFT JOIN skill_mastery AS mastery
              ON mastery.track_id=nodes.track_id AND mastery.skill_id=nodes.skill_id
            WHERE nodes.track_id=?
            ORDER BY nodes.sort_order,nodes.skill_id
            """,
            (track_id,),
        ).fetchall()
    result = [_skill_row(row) for row in rows]
    dimension_order = {item.dimension_id: item.order for item in pack.dimensions}
    result.sort(
        key=lambda item: (
            dimension_order.get(str(item["dimension_id"]), 10_000),
            int(item["order"]),
            str(item["skill_id"]),
        )
    )
    return result


def create_learning_objective(
    home: Path,
    *,
    title: str,
    track_id: str = DEFAULT_TRACK_ID,
    dimension_id: str,
    skill_id: str | None = None,
    description: str | None = None,
    status: str = "active",
    priority: int = 50,
    target_value: float | None = None,
    target_label: str | None = None,
    due_at: str | None = None,
    source_type: str = "learner",
    source_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_title = " ".join(str(title).strip().split())[:200]
    if not clean_title:
        raise ValueError("Learning objective title is required")
    if status not in OBJECTIVE_STATUSES:
        raise ValueError(f"Unsupported learning objective status: {status}")
    if int(priority) < 0 or int(priority) > 100:
        raise ValueError("Learning objective priority must be between 0 and 100")
    pack = get_domain_pack(track_id)
    pack.dimension(dimension_id)
    if skill_id:
        skill = pack.skill(skill_id)
        if skill.dimension_id != dimension_id:
            raise ValueError("Learning objective skill and dimension do not match")
    target = None if target_value is None else _bounded_score(target_value, "target_value")
    due = _iso_datetime(due_at, label="due_at")
    ensure_learning_model(home, track_id)
    objective_id = _id("objective")
    now = _now()
    achieved_at = now if status == "achieved" else None
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO learning_objectives(
              objective_id,track_id,dimension_id,skill_id,title,description,status,
              priority,target_value,target_label,due_at,source_type,source_id,
              metadata_json,revision,created_at,updated_at,achieved_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)
            """,
            (
                objective_id,
                track_id,
                dimension_id,
                skill_id,
                clean_title,
                description,
                status,
                int(priority),
                target,
                target_label,
                due,
                str(source_type).strip()[:80] or "learner",
                source_id,
                _json(metadata or {}),
                now,
                now,
                achieved_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM learning_objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
    return _objective_row(row)


def update_learning_objective(
    home: Path,
    objective_id: str,
    *,
    updates: dict[str, Any],
    expected_revision: int | None = None,
) -> dict[str, Any]:
    allowed = {
        "title",
        "description",
        "status",
        "priority",
        "target_value",
        "target_label",
        "due_at",
        "metadata",
    }
    unsupported = set(updates) - allowed
    if unsupported:
        raise ValueError(
            f"Unsupported learning objective fields: {', '.join(sorted(unsupported))}"
        )
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM learning_objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown learning objective: {objective_id}")
        current_revision = int(row["revision"])
        if expected_revision is not None and current_revision != int(expected_revision):
            raise LearningRevisionConflictError(
                f"Stale LearningObjective revision: expected {expected_revision}, "
                f"current {current_revision}",
                details={
                    "objective_id": objective_id,
                    "expected_revision": int(expected_revision),
                    "current_revision": current_revision,
                },
            )
        values: dict[str, Any] = {
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": int(row["priority"]),
            "target_value": row["target_value"],
            "target_label": row["target_label"],
            "due_at": row["due_at"],
            "metadata_json": row["metadata_json"],
        }
        if "title" in updates:
            values["title"] = " ".join(str(updates["title"]).strip().split())[:200]
            if not values["title"]:
                raise ValueError("Learning objective title is required")
        if "description" in updates:
            values["description"] = updates["description"]
        if "status" in updates:
            if updates["status"] not in OBJECTIVE_STATUSES:
                raise ValueError(
                    f"Unsupported learning objective status: {updates['status']}"
                )
            values["status"] = updates["status"]
        if "priority" in updates:
            priority = int(updates["priority"])
            if priority < 0 or priority > 100:
                raise ValueError("Learning objective priority must be between 0 and 100")
            values["priority"] = priority
        if "target_value" in updates:
            values["target_value"] = (
                None
                if updates["target_value"] is None
                else _bounded_score(updates["target_value"], "target_value")
            )
        if "target_label" in updates:
            values["target_label"] = updates["target_label"]
        if "due_at" in updates:
            values["due_at"] = _iso_datetime(updates["due_at"], label="due_at")
        if "metadata" in updates:
            values["metadata_json"] = _json(updates["metadata"] or {})
        now = _now()
        achieved_at = row["achieved_at"]
        if values["status"] == "achieved" and not achieved_at:
            achieved_at = now
        elif values["status"] != "achieved":
            achieved_at = None
        conn.execute(
            """
            UPDATE learning_objectives SET
              title=?,description=?,status=?,priority=?,target_value=?,target_label=?,
              due_at=?,metadata_json=?,revision=revision+1,updated_at=?,achieved_at=?
            WHERE objective_id=?
            """,
            (
                values["title"],
                values["description"],
                values["status"],
                values["priority"],
                values["target_value"],
                values["target_label"],
                values["due_at"],
                values["metadata_json"],
                now,
                achieved_at,
                objective_id,
            ),
        )
        updated = conn.execute(
            "SELECT * FROM learning_objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
    return _objective_row(updated)


def list_learning_objectives(
    home: Path,
    *,
    track_id: str = DEFAULT_TRACK_ID,
    dimension_id: str | None = None,
    status: str | None = None,
    skill_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_learning_model(home, track_id)
    clauses = ["track_id=?"]
    params: list[Any] = [track_id]
    if dimension_id:
        get_domain_pack(track_id).dimension(dimension_id)
        clauses.append("dimension_id=?")
        params.append(dimension_id)
    if status:
        if status not in OBJECTIVE_STATUSES:
            raise ValueError(f"Unsupported learning objective status: {status}")
        clauses.append("status=?")
        params.append(status)
    if skill_id:
        get_domain_pack(track_id).skill(skill_id)
        clauses.append("skill_id=?")
        params.append(skill_id)
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM learning_objectives
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
                     priority DESC,COALESCE(due_at,'9999'),created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_objective_row(row) for row in rows]


def create_learning_activity(
    home: Path,
    *,
    activity_type: str,
    title: str,
    track_id: str = DEFAULT_TRACK_ID,
    dimension_id: str | None = None,
    objective_id: str | None = None,
    source_type: str = "runtime",
    source_id: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    payload: dict[str, Any] | None = None,
    status: str = "planned",
) -> dict[str, Any]:
    pack = get_domain_pack(track_id)
    if dimension_id:
        pack.dimension(dimension_id)
    if status not in ACTIVITY_STATUSES:
        raise ValueError(f"Unsupported learning activity status: {status}")
    clean_title = " ".join(str(title).strip().split())[:200]
    if not clean_title:
        raise ValueError("Learning activity title is required")
    clean_activity_type = str(activity_type).strip()[:100]
    if not clean_activity_type:
        raise ValueError("Learning activity type is required")
    clean_source_type = str(source_type).strip()[:80]
    if not clean_source_type:
        raise ValueError("Learning activity source type is required")
    ensure_learning_model(home, track_id)
    now = _now()
    activity_id = _id("activity")
    with connect(home) as conn:
        if objective_id:
            objective = conn.execute(
                "SELECT track_id,dimension_id FROM learning_objectives WHERE objective_id=?",
                (objective_id,),
            ).fetchone()
            if not objective:
                raise ValueError(f"Unknown learning objective: {objective_id}")
            if objective["track_id"] != track_id:
                raise ValueError("Learning activity and objective tracks do not match")
            if dimension_id and objective["dimension_id"] != dimension_id:
                raise ValueError("Learning activity and objective dimensions do not match")
            if not dimension_id:
                dimension_id = str(objective["dimension_id"])
        if session_id:
            session = conn.execute(
                "SELECT track_id FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not session:
                raise ValueError(f"Unknown learning activity Session: {session_id}")
            if str(session["track_id"]) != track_id:
                raise ValueError("Learning activity and Session tracks do not match")
        if thread_id:
            thread = conn.execute(
                "SELECT track_id FROM study_threads WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
            if not thread:
                raise ValueError(f"Unknown learning activity thread: {thread_id}")
            if str(thread["track_id"]) != track_id:
                raise ValueError("Learning activity and thread tracks do not match")
        conn.execute(
            """
            INSERT INTO learning_activities(
              activity_id,track_id,dimension_id,activity_type,title,status,
              objective_id,source_type,source_id,session_id,thread_id,payload_json,
              revision,started_at,completed_at,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?, ?,0,?,?,?,?)
            """,
            (
                activity_id,
                track_id,
                dimension_id,
                clean_activity_type,
                clean_title,
                status,
                objective_id,
                clean_source_type,
                source_id,
                session_id,
                thread_id,
                _json(payload or {}),
                now if status == "in_progress" else None,
                now if status == "completed" else None,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM learning_activities WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
    return _activity_row(row)


def update_learning_activity(
    home: Path,
    activity_id: str,
    *,
    updates: dict[str, Any],
    expected_revision: int | None = None,
) -> dict[str, Any]:
    allowed = {"title", "status", "payload"}
    unsupported = set(updates) - allowed
    if unsupported:
        raise ValueError(
            f"Unsupported learning activity fields: {', '.join(sorted(unsupported))}"
        )
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM learning_activities WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown learning activity: {activity_id}")
        current_revision = int(row["revision"])
        if expected_revision is not None and current_revision != int(expected_revision):
            raise LearningRevisionConflictError(
                f"Stale LearningActivity revision: expected {expected_revision}, "
                f"current {current_revision}",
                details={
                    "activity_id": activity_id,
                    "expected_revision": int(expected_revision),
                    "current_revision": current_revision,
                },
            )
        title = str(row["title"])
        status = str(row["status"])
        payload_json = str(row["payload_json"])
        if "title" in updates:
            title = " ".join(str(updates["title"]).strip().split())[:200]
            if not title:
                raise ValueError("Learning activity title is required")
        if "status" in updates:
            status = str(updates["status"])
            if status not in ACTIVITY_STATUSES:
                raise ValueError(f"Unsupported learning activity status: {status}")
        if "payload" in updates:
            payload_json = _json(updates["payload"] or {})
        now = _now()
        started_at = row["started_at"]
        completed_at = row["completed_at"]
        if status in {"in_progress", "completed"} and not started_at:
            started_at = now
        if status == "completed" and not completed_at:
            completed_at = now
        elif status != "completed":
            completed_at = None
        conn.execute(
            """
            UPDATE learning_activities SET
              title=?,status=?,payload_json=?,revision=revision+1,
              started_at=?,completed_at=?,updated_at=?
            WHERE activity_id=?
            """,
            (
                title,
                status,
                payload_json,
                started_at,
                completed_at,
                now,
                activity_id,
            ),
        )
        updated = conn.execute(
            "SELECT * FROM learning_activities WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
    return _activity_row(updated)


def list_learning_activities(
    home: Path,
    *,
    track_id: str = DEFAULT_TRACK_ID,
    dimension_id: str | None = None,
    status: str | None = None,
    objective_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_learning_model(home, track_id)
    clauses = ["track_id=?"]
    params: list[Any] = [track_id]
    if dimension_id:
        get_domain_pack(track_id).dimension(dimension_id)
        clauses.append("dimension_id=?")
        params.append(dimension_id)
    if status:
        if status not in ACTIVITY_STATUSES:
            raise ValueError(f"Unsupported learning activity status: {status}")
        clauses.append("status=?")
        params.append(status)
    if objective_id:
        clauses.append("objective_id=?")
        params.append(objective_id)
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM learning_activities
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC LIMIT ?
            """,
            params,
        ).fetchall()
    return [_activity_row(row) for row in rows]


def record_mastery_evidence(
    home: Path,
    *,
    skill_id: str,
    score: float,
    confidence: float,
    evidence_kind: str,
    source_type: str,
    source_id: str,
    track_id: str = DEFAULT_TRACK_ID,
    objective_id: str | None = None,
    activity_id: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    rationale: str | None = None,
    payload: dict[str, Any] | None = None,
    observed_at: str | None = None,
    schedule_review: bool = True,
) -> dict[str, Any]:
    ensure_learning_model(home, track_id)
    with connect(home) as conn:
        evidence = _record_mastery_evidence_conn(
            conn,
            track_id=track_id,
            skill_id=skill_id,
            score=score,
            confidence=confidence,
            evidence_kind=evidence_kind,
            source_type=source_type,
            source_id=source_id,
            objective_id=objective_id,
            activity_id=activity_id,
            session_id=session_id,
            thread_id=thread_id,
            rationale=rationale,
            payload=payload,
            observed_at=observed_at,
            schedule_review=schedule_review,
        )
        mastery = _mastery_for_skill_conn(conn, track_id, skill_id)
        review = conn.execute(
            """
            SELECT * FROM learning_review_schedules
            WHERE stable_key=?
            """,
            (_review_stable_key(track_id, skill_id, objective_id),),
        ).fetchone()
    return {
        "evidence": _evidence_row(evidence),
        "mastery": _mastery_row(mastery) if mastery else None,
        "review": _review_row(review) if review else None,
    }


def _record_mastery_evidence_conn(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    skill_id: str,
    score: float,
    confidence: float,
    evidence_kind: str,
    source_type: str,
    source_id: str,
    objective_id: str | None = None,
    activity_id: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    rationale: str | None = None,
    payload: dict[str, Any] | None = None,
    observed_at: str | None = None,
    schedule_review: bool = True,
) -> sqlite3.Row:
    pack = get_domain_pack(track_id)
    pack.skill(skill_id)
    _ensure_skill_nodes_conn(conn, pack)
    if evidence_kind not in EVIDENCE_KIND_WEIGHTS:
        raise ValueError(f"Unsupported mastery evidence kind: {evidence_kind}")
    bounded_score = _bounded_score(score, "score")
    bounded_confidence = _bounded_score(confidence, "confidence")
    clean_source_type = str(source_type).strip()[:80]
    clean_source_id = str(source_id).strip()[:240]
    if not clean_source_type or not clean_source_id:
        raise ValueError("Mastery evidence source_type and source_id are required")
    existing = conn.execute(
        """
        SELECT * FROM mastery_evidence
        WHERE track_id=? AND skill_id=? AND source_type=? AND source_id=?
        """,
        (track_id, skill_id, clean_source_type, clean_source_id),
    ).fetchone()
    observed = _iso_datetime(observed_at, label="observed_at")
    if observed is None:
        observed = str(existing["observed_at"]) if existing else _now()
    if objective_id:
        objective = conn.execute(
            "SELECT track_id,skill_id FROM learning_objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if not objective:
            raise ValueError(f"Unknown learning objective: {objective_id}")
        if objective["track_id"] != track_id:
            raise ValueError("Mastery evidence and objective tracks do not match")
        if objective["skill_id"] and objective["skill_id"] != skill_id:
            raise ValueError("Mastery evidence and objective skills do not match")
    if activity_id:
        activity = conn.execute(
            "SELECT track_id,objective_id FROM learning_activities WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError(f"Unknown learning activity: {activity_id}")
        if activity["track_id"] != track_id:
            raise ValueError("Mastery evidence and activity tracks do not match")
    evidence_id = _stable_id(
        "evidence", track_id, skill_id, clean_source_type, clean_source_id
    )
    created_at = _now()
    payload_json = _json(payload or {})
    changed = existing is None or (
        str(existing["evidence_kind"]) != evidence_kind
        or float(existing["score"]) != bounded_score
        or float(existing["confidence"]) != bounded_confidence
        or existing["objective_id"] != objective_id
        or existing["activity_id"] != activity_id
        or existing["session_id"] != session_id
        or existing["thread_id"] != thread_id
        or existing["rationale"] != rationale
        or str(existing["payload_json"]) != payload_json
        or str(existing["observed_at"]) != observed
    )
    conn.execute(
        """
        INSERT INTO mastery_evidence(
          evidence_id,track_id,skill_id,objective_id,activity_id,evidence_kind,
          score,confidence,source_type,source_id,session_id,thread_id,rationale,
          payload_json,observed_at,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(track_id,skill_id,source_type,source_id) DO UPDATE SET
          objective_id=excluded.objective_id,
          activity_id=excluded.activity_id,
          evidence_kind=excluded.evidence_kind,
          score=excluded.score,
          confidence=excluded.confidence,
          session_id=excluded.session_id,
          thread_id=excluded.thread_id,
          rationale=excluded.rationale,
          payload_json=excluded.payload_json,
          observed_at=excluded.observed_at
        """,
        (
            evidence_id,
            track_id,
            skill_id,
            objective_id,
            activity_id,
            evidence_kind,
            bounded_score,
            bounded_confidence,
            clean_source_type,
            clean_source_id,
            session_id,
            thread_id,
            rationale,
            payload_json,
            observed,
            created_at,
        ),
    )
    evidence = conn.execute(
        """
        SELECT * FROM mastery_evidence
        WHERE track_id=? AND skill_id=? AND source_type=? AND source_id=?
        """,
        (track_id, skill_id, clean_source_type, clean_source_id),
    ).fetchone()
    mastery = _recalculate_skill_mastery_conn(conn, track_id, skill_id)
    if schedule_review and changed:
        _schedule_review_conn(
            conn,
            track_id=track_id,
            skill_id=skill_id,
            objective_id=objective_id,
            evidence_id=str(evidence["evidence_id"]),
            score=float(mastery["estimate"]),
        )
    return evidence


def _recalculate_skill_mastery_conn(
    conn: sqlite3.Connection,
    track_id: str,
    skill_id: str,
) -> sqlite3.Row:
    rows = conn.execute(
        """
        SELECT evidence_kind,score,confidence,observed_at
        FROM mastery_evidence
        WHERE track_id=? AND skill_id=?
        ORDER BY observed_at DESC,evidence_id DESC LIMIT 20
        """,
        (track_id, skill_id),
    ).fetchall()
    weighted_total = 0.0
    weight_total = 0.0
    calculation_items: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        kind = str(row["evidence_kind"])
        recency_weight = 0.92**index
        weight = (
            EVIDENCE_KIND_WEIGHTS.get(kind, 0.5)
            * float(row["confidence"])
            * recency_weight
        )
        weighted_total += float(row["score"]) * weight
        weight_total += weight
        calculation_items.append(
            {
                "kind": kind,
                "score": float(row["score"]),
                "confidence": float(row["confidence"]),
                "recency_weight": round(recency_weight, 6),
            }
        )
    estimate = weighted_total / weight_total if weight_total else 0.0
    confidence = min(1.0, weight_total / 4.0)
    if not rows:
        status = "unknown"
    elif estimate < 0.4:
        status = "needs_support"
    elif estimate < 0.7:
        status = "developing"
    elif estimate < 0.85:
        status = "secure"
    else:
        status = "strong"
    now = _now()
    last_evidence_at = str(rows[0]["observed_at"]) if rows else None
    existing_review = conn.execute(
        """
        SELECT MIN(due_at) FROM learning_review_schedules
        WHERE track_id=? AND skill_id=? AND status IN ('pending','in_progress')
        """,
        (track_id, skill_id),
    ).fetchone()[0]
    calculation = {
        "algorithm": "transparent-weighted-recency@1",
        "window": 20,
        "weight_total": round(weight_total, 6),
        "items": calculation_items,
    }
    conn.execute(
        """
        INSERT INTO skill_mastery(
          track_id,skill_id,estimate,confidence,evidence_count,status,
          last_evidence_at,next_review_at,calculation_json,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(track_id,skill_id) DO UPDATE SET
          estimate=excluded.estimate,
          confidence=excluded.confidence,
          evidence_count=excluded.evidence_count,
          status=excluded.status,
          last_evidence_at=excluded.last_evidence_at,
          next_review_at=excluded.next_review_at,
          calculation_json=excluded.calculation_json,
          updated_at=excluded.updated_at
        """,
        (
            track_id,
            skill_id,
            round(estimate, 6),
            round(confidence, 6),
            len(rows),
            status,
            last_evidence_at,
            existing_review,
            _json(calculation),
            now,
        ),
    )
    return _mastery_for_skill_conn(conn, track_id, skill_id)


def _interval_days(score: float, repetition_count: int = 0) -> int:
    if score >= 0.85:
        base = 14
    elif score >= 0.7:
        base = 7
    elif score >= 0.5:
        base = 3
    else:
        base = 1
    if repetition_count > 0 and score >= 0.7:
        base *= min(4, 2**min(repetition_count, 2))
    return base


def _review_stable_key(
    track_id: str,
    skill_id: str,
    objective_id: str | None,
) -> str:
    return f"{track_id}:{skill_id}:{objective_id or '-'}"


def _refresh_skill_next_review_conn(
    conn: sqlite3.Connection,
    track_id: str,
    skill_id: str,
) -> str | None:
    next_review_at = conn.execute(
        """
        SELECT MIN(due_at) FROM learning_review_schedules
        WHERE track_id=? AND skill_id=? AND status IN ('pending','in_progress')
        """,
        (track_id, skill_id),
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE skill_mastery SET next_review_at=?,updated_at=?
        WHERE track_id=? AND skill_id=?
        """,
        (next_review_at, _now(), track_id, skill_id),
    )
    return str(next_review_at) if next_review_at is not None else None


def _schedule_review_conn(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    skill_id: str,
    objective_id: str | None,
    evidence_id: str,
    score: float,
) -> sqlite3.Row:
    stable_key = _review_stable_key(track_id, skill_id, objective_id)
    current = conn.execute(
        "SELECT * FROM learning_review_schedules WHERE stable_key=?",
        (stable_key,),
    ).fetchone()
    repetition_count = int(current["repetition_count"]) if current else 0
    interval_days = _interval_days(score, repetition_count)
    due_at = (datetime.now(timezone.utc) + timedelta(days=interval_days)).isoformat()
    priority = max(10, min(100, int(round((1.0 - score) * 100))))
    now = _now()
    review_id = str(current["review_id"]) if current else _id("review")
    conn.execute(
        """
        INSERT INTO learning_review_schedules(
          review_id,stable_key,track_id,skill_id,objective_id,status,due_at,
          interval_days,repetition_count,priority,source_evidence_id,
          last_reviewed_at,payload_json,created_at,updated_at
        ) VALUES(?,?,?,?,?,'pending',?,?,?,?,?,NULL,'{}',?,?)
        ON CONFLICT(stable_key) DO UPDATE SET
          objective_id=excluded.objective_id,
          status='pending',
          due_at=excluded.due_at,
          interval_days=excluded.interval_days,
          priority=excluded.priority,
          source_evidence_id=excluded.source_evidence_id,
          updated_at=excluded.updated_at
        """,
        (
            review_id,
            stable_key,
            track_id,
            skill_id,
            objective_id,
            due_at,
            interval_days,
            repetition_count,
            priority,
            evidence_id,
            now,
            now,
        ),
    )
    _refresh_skill_next_review_conn(conn, track_id, skill_id)
    return conn.execute(
        "SELECT * FROM learning_review_schedules WHERE stable_key=?",
        (stable_key,),
    ).fetchone()


def list_mastery_evidence(
    home: Path,
    *,
    track_id: str = DEFAULT_TRACK_ID,
    skill_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_learning_model(home, track_id)
    clauses = ["track_id=?"]
    params: list[Any] = [track_id]
    if skill_id:
        get_domain_pack(track_id).skill(skill_id)
        clauses.append("skill_id=?")
        params.append(skill_id)
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM mastery_evidence WHERE {' AND '.join(clauses)}
            ORDER BY observed_at DESC,evidence_id DESC LIMIT ?
            """,
            params,
        ).fetchall()
    return [_evidence_row(row) for row in rows]


def list_learning_reviews(
    home: Path,
    *,
    track_id: str = DEFAULT_TRACK_ID,
    dimension_id: str | None = None,
    status: str | None = "pending",
    due_only: bool = False,
    skill_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_learning_model(home, track_id)
    clauses = ["reviews.track_id=?"]
    params: list[Any] = [track_id]
    if dimension_id:
        get_domain_pack(track_id).dimension(dimension_id)
        clauses.append("nodes.dimension_id=?")
        params.append(dimension_id)
    if status:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Unsupported learning review status: {status}")
        clauses.append("reviews.status=?")
        params.append(status)
    if due_only:
        clauses.append("reviews.due_at<=?")
        params.append(_now())
    if skill_id:
        get_domain_pack(track_id).skill(skill_id)
        clauses.append("reviews.skill_id=?")
        params.append(skill_id)
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT reviews.*,nodes.title AS skill_title,nodes.dimension_id
            FROM learning_review_schedules AS reviews
            JOIN learning_skill_nodes AS nodes
              ON nodes.track_id=reviews.track_id AND nodes.skill_id=reviews.skill_id
            WHERE {' AND '.join(clauses)}
            ORDER BY reviews.due_at,reviews.priority DESC,reviews.created_at
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_review_row(row) for row in rows]


def complete_learning_review(
    home: Path,
    review_id: str,
    *,
    score: float,
    confidence: float = 1.0,
    rationale: str | None = None,
    continue_review: bool = True,
) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        review = conn.execute(
            "SELECT * FROM learning_review_schedules WHERE review_id=?",
            (review_id,),
        ).fetchone()
        if not review:
            raise ValueError(f"Unknown learning review: {review_id}")
        if review["status"] == "dismissed":
            raise ValueError("Dismissed learning review cannot be completed")
        next_repetition = int(review["repetition_count"]) + 1
        evidence = _record_mastery_evidence_conn(
            conn,
            track_id=str(review["track_id"]),
            skill_id=str(review["skill_id"]),
            score=score,
            confidence=confidence,
            evidence_kind="review",
            source_type="learning_review",
            source_id=f"{review_id}:{next_repetition}",
            objective_id=review["objective_id"],
            rationale=rationale,
            payload={"review_id": review_id, "repetition": next_repetition},
            schedule_review=False,
        )
        mastery = _mastery_for_skill_conn(
            conn, str(review["track_id"]), str(review["skill_id"])
        )
        now = _now()
        if continue_review:
            interval_days = _interval_days(float(mastery["estimate"]), next_repetition)
            due_at = (
                datetime.now(timezone.utc) + timedelta(days=interval_days)
            ).isoformat()
            status = "pending"
        else:
            interval_days = int(review["interval_days"])
            due_at = str(review["due_at"])
            status = "completed"
        conn.execute(
            """
            UPDATE learning_review_schedules SET
              status=?,due_at=?,interval_days=?,repetition_count=?,
              source_evidence_id=?,last_reviewed_at=?,updated_at=?
            WHERE review_id=?
            """,
            (
                status,
                due_at,
                interval_days,
                next_repetition,
                evidence["evidence_id"],
                now,
                now,
                review_id,
            ),
        )
        _refresh_skill_next_review_conn(
            conn, str(review["track_id"]), str(review["skill_id"])
        )
        updated = conn.execute(
            "SELECT * FROM learning_review_schedules WHERE review_id=?",
            (review_id,),
        ).fetchone()
        mastery = _mastery_for_skill_conn(
            conn, str(review["track_id"]), str(review["skill_id"])
        )
    return {
        "review": _review_row(updated),
        "evidence": _evidence_row(evidence),
        "mastery": _mastery_row(mastery),
    }


def update_learning_review_status(
    home: Path,
    review_id: str,
    status: str,
) -> dict[str, Any]:
    if status not in {"pending", "in_progress", "dismissed"}:
        raise ValueError("Review status must be pending, in_progress or dismissed")
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM learning_review_schedules WHERE review_id=?",
            (review_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown learning review: {review_id}")
        conn.execute(
            "UPDATE learning_review_schedules SET status=?,updated_at=? WHERE review_id=?",
            (status, _now(), review_id),
        )
        _refresh_skill_next_review_conn(
            conn, str(row["track_id"]), str(row["skill_id"])
        )
        updated = conn.execute(
            "SELECT * FROM learning_review_schedules WHERE review_id=?",
            (review_id,),
        ).fetchone()
    return _review_row(updated)


def get_learning_model_snapshot(
    home: Path,
    *,
    track_id: str = DEFAULT_TRACK_ID,
    dimension_id: str | None = None,
) -> dict[str, Any]:
    pack = get_domain_pack(track_id)
    if dimension_id:
        pack.dimension(dimension_id)
    skills = list_skill_nodes(home, track_id=track_id)
    if dimension_id:
        skills = [item for item in skills if item["dimension_id"] == dimension_id]
    objectives = list_learning_objectives(
        home,
        track_id=track_id,
        dimension_id=dimension_id,
        limit=100,
    )
    due_reviews = list_learning_reviews(
        home,
        track_id=track_id,
        dimension_id=dimension_id,
        status="pending",
        due_only=True,
        limit=20,
    )
    observed = [
        item
        for item in skills
        if item["mastery"] is not None
        and int(item["mastery"]["evidence_count"]) > 0
    ]
    return {
        "model_version": 1,
        "track": pack.descriptor(include_capabilities=False, include_skills=False),
        "dimension_id": dimension_id,
        "objectives": objectives,
        "skills": skills,
        "due_reviews": due_reviews,
        "summary": {
            "skill_count": len(skills),
            "observed_skill_count": len(observed),
            "active_objective_count": sum(
                item["status"] in {"planned", "active"} for item in objectives
            ),
            "due_review_count": len(due_reviews),
        },
    }


def ingest_session_mastery_evidence(
    conn: sqlite3.Connection,
    data: dict[str, Any],
) -> None:
    """Project one authoritative IELTS Session into the generic learner model.

    The projection is deterministic and idempotent. It never invents a skill
    score: it uses per-question correctness, validated criterion scores, or a
    session score already accepted by the Teaching Runtime.
    """

    track_id = str(data.get("track_id") or DEFAULT_TRACK_ID)
    if track_id != DEFAULT_TRACK_ID:
        return
    pack = get_domain_pack(track_id)
    _ensure_skill_nodes_conn(conn, pack)
    session_id = str(data.get("session_id") or "").strip()
    module = str(data.get("module") or "").strip().casefold()
    if not session_id or module not in {item.dimension_id for item in pack.dimensions}:
        return
    existing_rows = conn.execute(
        """
        SELECT * FROM mastery_evidence
        WHERE session_id=? AND source_type='ielts_session'
        """,
        (session_id,),
    ).fetchall()
    old_skills = {str(row["skill_id"]) for row in existing_rows}
    observed_at = str(data.get("occurred_at") or _now())
    pending: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("questions") or []):
        if not isinstance(item, dict) or item.get("is_correct") is None:
            continue
        label = str(item.get("question_type") or "")
        skill_id = pack.resolve_evidence_skill(
            dimension_id=module,
            evidence_kind="question_type",
            label=label,
        )
        item_key = (
            item.get("question_id")
            or item.get("question_number")
            or f"index-{index + 1}"
        )
        pending.append(
            {
                "skill_id": skill_id,
                "score": 1.0 if bool(item["is_correct"]) else 0.0,
                "confidence": 1.0,
                "evidence_kind": "attempt",
                "source_id": f"{session_id}:question:{item_key}",
                "rationale": f"Question result: {label or 'unspecified type'}",
                "payload": item,
            }
        )
    for index, item in enumerate(data.get("criterion_scores") or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("assessment_role") or "local_rubric")
        if role != "local_rubric":
            continue
        value = item.get("score")
        if value is None and item.get("score_low") is not None and item.get("score_high") is not None:
            value = (float(item["score_low"]) + float(item["score_high"])) / 2.0
        if value is None:
            continue
        criterion = str(item.get("criterion") or f"criterion-{index + 1}")
        skill_id = pack.resolve_evidence_skill(
            dimension_id=module,
            evidence_kind="criterion",
            label=criterion,
        )
        confidence_label = str(item.get("confidence") or data.get("score_confidence") or "medium")
        pending.append(
            {
                "skill_id": skill_id,
                "score": pack.assessment_scale.normalise(float(value)),
                "confidence": _confidence_value(confidence_label),
                "evidence_kind": "assessment",
                "source_id": f"{session_id}:criterion:{criterion.casefold()}",
                "rationale": f"Validated IELTS criterion score: {criterion}",
                "payload": item,
            }
        )
    if not pending:
        band = data.get("band", data.get("estimated_overall"))
        if band is not None:
            score_kind = str(data.get("score_kind") or "unspecified")
            confidence_label = str(data.get("score_confidence") or "low")
            if score_kind in {
                "official_result",
                "answer_key_estimate",
                "ai_training_estimate",
            }:
                skill_id = pack.dimension(module).default_skill_id
                pending.append(
                    {
                        "skill_id": skill_id,
                        "score": pack.assessment_scale.normalise(float(band)),
                        "confidence": _confidence_value(confidence_label),
                        "evidence_kind": "assessment",
                        "source_id": f"{session_id}:overall",
                        "rationale": f"Accepted session score ({score_kind})",
                        "payload": {
                            "band": band,
                            "score_kind": score_kind,
                            "score_confidence": confidence_label,
                        },
                    }
                )
    expected_signatures = {
        (str(item["skill_id"]), str(item["source_id"])): (
            str(item["evidence_kind"]),
            float(item["score"]),
            float(item["confidence"]),
            str(item["rationale"]),
            _json(item["payload"]),
            observed_at,
        )
        for item in pending
    }
    existing_signatures = {
        (str(row["skill_id"]), str(row["source_id"])): (
            str(row["evidence_kind"]),
            float(row["score"]),
            float(row["confidence"]),
            str(row["rationale"]),
            str(row["payload_json"]),
            str(row["observed_at"]),
        )
        for row in existing_rows
    }
    projection_changed = existing_signatures != expected_signatures
    for row in existing_rows:
        key = (str(row["skill_id"]), str(row["source_id"]))
        if key not in expected_signatures:
            conn.execute(
                "DELETE FROM mastery_evidence WHERE evidence_id=?",
                (row["evidence_id"],),
            )

    affected = set(old_skills)
    for item in pending:
        _record_mastery_evidence_conn(
            conn,
            track_id=track_id,
            skill_id=str(item["skill_id"]),
            score=float(item["score"]),
            confidence=float(item["confidence"]),
            evidence_kind=str(item["evidence_kind"]),
            source_type="ielts_session",
            source_id=str(item["source_id"]),
            session_id=session_id,
            rationale=str(item["rationale"]),
            payload=dict(item["payload"]),
            observed_at=observed_at,
            schedule_review=False,
        )
        affected.add(str(item["skill_id"]))
    for skill_id in affected:
        mastery = _recalculate_skill_mastery_conn(conn, track_id, skill_id)
        if not projection_changed:
            continue
        newest = conn.execute(
            """
            SELECT evidence_id FROM mastery_evidence
            WHERE track_id=? AND skill_id=?
            ORDER BY observed_at DESC,evidence_id DESC LIMIT 1
            """,
            (track_id, skill_id),
        ).fetchone()
        if newest:
            _schedule_review_conn(
                conn,
                track_id=track_id,
                skill_id=skill_id,
                objective_id=None,
                evidence_id=str(newest["evidence_id"]),
                score=float(mastery["estimate"]),
            )
        else:
            conn.execute(
                "DELETE FROM learning_review_schedules WHERE stable_key=?",
                (_review_stable_key(track_id, skill_id, None),),
            )
            _refresh_skill_next_review_conn(conn, track_id, skill_id)


def _confidence_value(label: str) -> float:
    return {"high": 0.9, "medium": 0.7, "low": 0.45}.get(
        str(label).casefold(), 0.5
    )


def _mastery_for_skill_conn(
    conn: sqlite3.Connection,
    track_id: str,
    skill_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM skill_mastery WHERE track_id=? AND skill_id=?",
        (track_id, skill_id),
    ).fetchone()


def _skill_row(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    mastery = None
    if "estimate" in keys and row["estimate"] is not None:
        mastery = {
            "estimate": float(row["estimate"]),
            "confidence": float(row["mastery_confidence"]),
            "evidence_count": int(row["evidence_count"]),
            "status": row["mastery_status"],
            "last_evidence_at": row["last_evidence_at"],
            "next_review_at": row["next_review_at"],
            "calculation": _json_value(row["calculation_json"], {}),
        }
    return {
        "track_id": row["track_id"],
        "skill_id": row["skill_id"],
        "dimension_id": row["dimension_id"],
        "parent_skill_id": row["parent_skill_id"],
        "title": row["title"],
        "description": row["description"],
        "order": int(row["sort_order"]),
        "metadata": _json_value(row["metadata_json"], {}),
        "mastery": mastery,
    }


def _objective_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "objective_id": row["objective_id"],
        "track_id": row["track_id"],
        "dimension_id": row["dimension_id"],
        "skill_id": row["skill_id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": int(row["priority"]),
        "target_value": (
            None if row["target_value"] is None else float(row["target_value"])
        ),
        "target_label": row["target_label"],
        "due_at": row["due_at"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "metadata": _json_value(row["metadata_json"], {}),
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "achieved_at": row["achieved_at"],
    }


def _activity_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "activity_id": row["activity_id"],
        "track_id": row["track_id"],
        "dimension_id": row["dimension_id"],
        "activity_type": row["activity_type"],
        "title": row["title"],
        "status": row["status"],
        "objective_id": row["objective_id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "session_id": row["session_id"],
        "thread_id": row["thread_id"],
        "payload": _json_value(row["payload_json"], {}),
        "revision": int(row["revision"]),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _evidence_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "evidence_id": row["evidence_id"],
        "track_id": row["track_id"],
        "skill_id": row["skill_id"],
        "objective_id": row["objective_id"],
        "activity_id": row["activity_id"],
        "evidence_kind": row["evidence_kind"],
        "score": float(row["score"]),
        "confidence": float(row["confidence"]),
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "session_id": row["session_id"],
        "thread_id": row["thread_id"],
        "rationale": row["rationale"],
        "payload": _json_value(row["payload_json"], {}),
        "observed_at": row["observed_at"],
        "created_at": row["created_at"],
    }


def _mastery_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "track_id": row["track_id"],
        "skill_id": row["skill_id"],
        "estimate": float(row["estimate"]),
        "confidence": float(row["confidence"]),
        "evidence_count": int(row["evidence_count"]),
        "status": row["status"],
        "last_evidence_at": row["last_evidence_at"],
        "next_review_at": row["next_review_at"],
        "calculation": _json_value(row["calculation_json"], {}),
        "updated_at": row["updated_at"],
    }


def _review_row(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "review_id": row["review_id"],
        "stable_key": row["stable_key"],
        "track_id": row["track_id"],
        "skill_id": row["skill_id"],
        "skill_title": row["skill_title"] if "skill_title" in keys else None,
        "dimension_id": row["dimension_id"] if "dimension_id" in keys else None,
        "objective_id": row["objective_id"],
        "status": row["status"],
        "due_at": row["due_at"],
        "interval_days": int(row["interval_days"]),
        "repetition_count": int(row["repetition_count"]),
        "priority": int(row["priority"]),
        "source_evidence_id": row["source_evidence_id"],
        "last_reviewed_at": row["last_reviewed_at"],
        "payload": _json_value(row["payload_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
