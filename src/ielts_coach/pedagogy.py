from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain_packs import DEFAULT_TRACK_ID, get_domain_pack
from .errors import InvalidTeachingTransitionError, LearningRevisionConflictError
from .learning_model import ensure_learning_model
from .storage import connect, initialise_database


TEACHING_PHASES = (
    "diagnose",
    "teach",
    "guided_practice",
    "independent_practice",
    "assess",
    "review",
    "consolidate",
)
TEACHING_CYCLE_STATUSES = {"active", "paused", "completed", "cancelled"}

# The graph is intentionally explicit. A model may recommend one of these
# transitions, but only Runtime or a learner-confirmed API operation can apply it.
ALLOWED_TEACHING_TRANSITIONS: dict[str, frozenset[str]] = {
    "diagnose": frozenset({"teach", "guided_practice", "independent_practice", "assess"}),
    "teach": frozenset({"diagnose", "guided_practice"}),
    "guided_practice": frozenset({"teach", "independent_practice", "assess"}),
    "independent_practice": frozenset({"guided_practice", "assess"}),
    "assess": frozenset({"teach", "guided_practice", "review", "consolidate"}),
    "review": frozenset({"teach", "guided_practice", "assess", "consolidate"}),
    "consolidate": frozenset({"diagnose", "review"}),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def is_teaching_transition_allowed(from_phase: str, to_phase: str) -> bool:
    return to_phase in ALLOWED_TEACHING_TRANSITIONS.get(from_phase, frozenset())


def start_teaching_cycle(
    home: Path,
    *,
    title: str,
    track_id: str = DEFAULT_TRACK_ID,
    phase: str = "diagnose",
    dimension_id: str | None = None,
    skill_id: str | None = None,
    objective_id: str | None = None,
    activity_id: str | None = None,
    thread_id: str | None = None,
    session_id: str | None = None,
    context: dict[str, Any] | None = None,
    source_type: str = "learner",
    source_id: str | None = None,
) -> dict[str, Any]:
    if phase not in TEACHING_PHASES:
        raise ValueError(f"Unsupported teaching phase: {phase}")
    clean_title = " ".join(str(title).strip().split())[:200]
    if not clean_title:
        raise ValueError("Teaching cycle title is required")
    if not any((thread_id, objective_id, activity_id, session_id, skill_id)):
        raise ValueError("Teaching cycle must be linked to a learning target or activity")
    pack = get_domain_pack(track_id)
    if dimension_id:
        pack.dimension(dimension_id)
    if skill_id:
        skill = pack.skill(skill_id)
        if dimension_id and skill.dimension_id != dimension_id:
            raise ValueError("Teaching cycle skill and dimension do not match")
        dimension_id = dimension_id or skill.dimension_id
    ensure_learning_model(home, track_id)
    initialise_database(home)
    now = _now()
    cycle_id = _id("cycle")
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        (
            dimension_id,
            skill_id,
            objective_id,
            activity_id,
            thread_id,
            session_id,
        ) = _validate_cycle_links_conn(
            conn,
            track_id=track_id,
            dimension_id=dimension_id,
            skill_id=skill_id,
            objective_id=objective_id,
            activity_id=activity_id,
            thread_id=thread_id,
            session_id=session_id,
        )
        if thread_id:
            existing = conn.execute(
                """
                SELECT cycle_id FROM teaching_cycles
                WHERE thread_id=? AND status IN ('active','paused')
                """,
                (thread_id,),
            ).fetchone()
            if existing:
                raise ValueError(
                    f"Study thread already has an unfinished teaching cycle: {existing['cycle_id']}"
                )
        conn.execute(
            """
            INSERT INTO teaching_cycles(
              cycle_id,track_id,dimension_id,skill_id,objective_id,activity_id,
              thread_id,session_id,title,phase,status,revision,context_json,
              source_type,source_id,started_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,'active',0,?,?,?,?,?)
            """,
            (
                cycle_id,
                track_id,
                dimension_id,
                skill_id,
                objective_id,
                activity_id,
                thread_id,
                session_id,
                clean_title,
                phase,
                json.dumps(context or {}, ensure_ascii=False, sort_keys=True, default=str),
                str(source_type).strip()[:80] or "learner",
                source_id,
                now,
                now,
            ),
        )
        _append_event_conn(
            conn,
            cycle_id=cycle_id,
            event_type="cycle_started",
            from_phase=phase,
            to_phase=phase,
            actor="learner" if source_type == "learner" else "runtime",
            reason_code="cycle_started",
            source_type=source_type,
            source_id=source_id,
            evidence_refs=[],
            metadata={"initial_phase": phase},
            created_at=now,
        )
    return get_teaching_cycle(home, cycle_id)


def get_teaching_cycle(
    home: Path,
    cycle_id: str,
    *,
    include_events: bool = True,
) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM teaching_cycles WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        if not row:
            raise ValueError("Teaching cycle not found")
        events = (
            conn.execute(
                """
                SELECT * FROM teaching_cycle_events
                WHERE cycle_id=? ORDER BY sequence
                """,
                (cycle_id,),
            ).fetchall()
            if include_events
            else []
        )
    result = _cycle_row(row)
    if include_events:
        result["events"] = [_event_row(item) for item in events]
    result["recommendation"] = recommend_teaching_transition(home, cycle_id)
    return result


def get_active_teaching_cycle(home: Path, thread_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            """
            SELECT cycle_id FROM teaching_cycles
            WHERE thread_id=? AND status IN ('active','paused')
            ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,updated_at DESC LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
    return get_teaching_cycle(home, str(row["cycle_id"]), include_events=False) if row else None


def list_teaching_cycles(
    home: Path,
    *,
    track_id: str = DEFAULT_TRACK_ID,
    status: str | None = None,
    thread_id: str | None = None,
    objective_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses = ["track_id=?"]
    params: list[Any] = [track_id]
    if status:
        if status not in TEACHING_CYCLE_STATUSES:
            raise ValueError("Unsupported teaching cycle status")
        clauses.append("status=?")
        params.append(status)
    if thread_id:
        clauses.append("thread_id=?")
        params.append(thread_id)
    if objective_id:
        clauses.append("objective_id=?")
        params.append(objective_id)
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM teaching_cycles
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                     updated_at DESC LIMIT ?
            """,
            params,
        ).fetchall()
        recommendations = [
            _recommend_cycle_row(row, _select_cycle_mastery_conn(conn, row))
            for row in rows
        ]
    return [
        {**_cycle_row(row), "recommendation": recommendation}
        for row, recommendation in zip(rows, recommendations, strict=True)
    ]


def transition_teaching_cycle(
    home: Path,
    cycle_id: str,
    *,
    to_phase: str,
    expected_revision: int,
    actor: str = "learner",
    reason_code: str = "learner_transition",
    source_type: str | None = None,
    source_id: str | None = None,
    evidence_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if to_phase not in TEACHING_PHASES:
        raise ValueError(f"Unsupported teaching phase: {to_phase}")
    if actor not in {"runtime", "learner"}:
        raise ValueError("Only Runtime or the learner can transition a teaching cycle")
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM teaching_cycles WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        if not row:
            raise ValueError("Teaching cycle not found")
        _check_cycle_revision(row, expected_revision)
        if str(row["status"]) != "active":
            raise InvalidTeachingTransitionError(
                "Only an active teaching cycle can change phase",
                details={"cycle_id": cycle_id, "status": row["status"]},
            )
        from_phase = str(row["phase"])
        if from_phase == to_phase or not is_teaching_transition_allowed(from_phase, to_phase):
            raise InvalidTeachingTransitionError(
                f"Teaching phase cannot move from {from_phase} to {to_phase}",
                details={
                    "cycle_id": cycle_id,
                    "from_phase": from_phase,
                    "to_phase": to_phase,
                    "allowed": sorted(ALLOWED_TEACHING_TRANSITIONS[from_phase]),
                },
            )
        conn.execute(
            """
            UPDATE teaching_cycles
            SET phase=?,revision=revision+1,updated_at=? WHERE cycle_id=?
            """,
            (to_phase, now, cycle_id),
        )
        _append_event_conn(
            conn,
            cycle_id=cycle_id,
            event_type="phase_transition",
            from_phase=from_phase,
            to_phase=to_phase,
            actor=actor,
            reason_code=reason_code,
            source_type=source_type,
            source_id=source_id,
            evidence_refs=evidence_refs or [],
            metadata=metadata or {},
            created_at=now,
        )
    return get_teaching_cycle(home, cycle_id)


def update_teaching_cycle_status(
    home: Path,
    cycle_id: str,
    *,
    status: str,
    expected_revision: int,
    actor: str = "learner",
    reason_code: str | None = None,
) -> dict[str, Any]:
    if status not in TEACHING_CYCLE_STATUSES:
        raise ValueError("Unsupported teaching cycle status")
    if actor not in {"runtime", "learner"}:
        raise ValueError("Only Runtime or the learner can update a teaching cycle")
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM teaching_cycles WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        if not row:
            raise ValueError("Teaching cycle not found")
        _check_cycle_revision(row, expected_revision)
        previous = str(row["status"])
        allowed = {
            "active": {"paused", "completed", "cancelled"},
            "paused": {"active", "cancelled"},
            "completed": set(),
            "cancelled": set(),
        }
        if status == previous or status not in allowed[previous]:
            raise InvalidTeachingTransitionError(
                f"Teaching cycle status cannot move from {previous} to {status}",
                details={"cycle_id": cycle_id, "from_status": previous, "to_status": status},
            )
        conn.execute(
            """
            UPDATE teaching_cycles SET status=?,revision=revision+1,updated_at=?,
              completed_at=CASE WHEN ? IN ('completed','cancelled') THEN ? ELSE NULL END
            WHERE cycle_id=?
            """,
            (status, now, status, now, cycle_id),
        )
        phase = str(row["phase"])
        _append_event_conn(
            conn,
            cycle_id=cycle_id,
            event_type="status_transition",
            from_phase=phase,
            to_phase=phase,
            actor=actor,
            reason_code=reason_code or f"status_{status}",
            source_type=None,
            source_id=None,
            evidence_refs=[],
            metadata={"from_status": previous, "to_status": status},
            created_at=now,
        )
    return get_teaching_cycle(home, cycle_id)


def recommend_teaching_transition(home: Path, cycle_id: str) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        cycle = conn.execute(
            "SELECT * FROM teaching_cycles WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        if not cycle:
            raise ValueError("Teaching cycle not found")
        mastery = _select_cycle_mastery_conn(conn, cycle)
    return _recommend_cycle_row(cycle, mastery)


def _recommend_cycle_row(
    cycle: sqlite3.Row,
    mastery: sqlite3.Row | None,
) -> dict[str, Any]:
    status = str(cycle["status"])
    phase = str(cycle["phase"])
    if status == "paused":
        return _recommendation("resume", None, "cycle_paused", mastery)
    if status in {"completed", "cancelled"}:
        return _recommendation("none", None, f"cycle_{status}", mastery)
    estimate = float(mastery["estimate"]) if mastery else None
    if phase == "diagnose":
        target, reason = (
            ("teach", "diagnostic_support_needed")
            if estimate is None or estimate < 0.45
            else ("guided_practice", "diagnostic_guided_practice")
            if estimate < 0.72
            else ("assess", "diagnostic_ready_to_assess")
        )
    elif phase == "teach":
        target, reason = "guided_practice", "instruction_needs_guided_application"
    elif phase == "guided_practice":
        target, reason = (
            ("teach", "guided_practice_support_needed")
            if estimate is not None and estimate < 0.45
            else ("independent_practice", "guided_practice_ready_for_independence")
        )
    elif phase == "independent_practice":
        target, reason = (
            ("guided_practice", "independent_practice_support_needed")
            if estimate is not None and estimate < 0.55
            else ("assess", "independent_practice_ready_to_assess")
        )
    elif phase == "assess":
        target, reason = (
            ("review", "assessment_needs_review")
            if estimate is None or estimate < 0.8
            else ("consolidate", "assessment_secure")
        )
    elif phase == "review":
        target, reason = (
            ("guided_practice", "review_needs_more_practice")
            if estimate is None or estimate < 0.72
            else ("assess", "review_ready_to_reassess")
        )
    else:
        return _recommendation("complete", None, "consolidation_complete", mastery)
    return _recommendation("transition", target, reason, mastery)


def observe_tutor_turn(
    home: Path,
    *,
    thread_id: str,
    result: dict[str, Any],
    run_id: str,
    message_id: str,
) -> dict[str, Any] | None:
    """Project a validated Tutor result into a bounded teaching cycle.

    Only the structured request kind and answer state are retained. Tutor prose
    and hidden reasoning never enter cycle state.
    """
    request_kind = str(result.get("request_kind") or "teacher_dialogue")
    module = str(result.get("module") or "mixed")
    if request_kind == "teacher_dialogue" and module == "mixed":
        return None
    target_phase = {
        "material_orientation": "diagnose",
        "context_analysis": "diagnose",
        "close_reading": "teach",
        "question_explanation": "teach",
        "guided_hint": "guided_practice",
        "writing_feedback": "review",
    }.get(request_kind, "diagnose")
    if result.get("answer_status") == "verified":
        target_phase = "review"
    cycle = get_active_teaching_cycle(home, thread_id)
    if cycle is None:
        return start_teaching_cycle(
            home,
            title=f"{module.title()} learning cycle" if module != "mixed" else "Learning cycle",
            track_id=DEFAULT_TRACK_ID,
            dimension_id=module if module in {"listening", "reading", "writing", "speaking"} else None,
            phase=target_phase,
            thread_id=thread_id,
            source_type="runtime",
            source_id=run_id,
            context={"origin": "validated_tutor_turn"},
        )
    if cycle["status"] == "paused":
        return cycle
    if target_phase != cycle["phase"] and is_teaching_transition_allowed(str(cycle["phase"]), target_phase):
        try:
            return transition_teaching_cycle(
                home,
                str(cycle["cycle_id"]),
                to_phase=target_phase,
                expected_revision=int(cycle["revision"]),
                actor="runtime",
                reason_code="validated_tutor_turn",
                source_type="agent_run",
                source_id=run_id,
                evidence_refs=[f"message:{message_id}"],
                metadata={"request_kind": request_kind, "answer_status": result.get("answer_status")},
            )
        except LearningRevisionConflictError:
            return get_active_teaching_cycle(home, thread_id)
    try:
        _record_observation(
            home,
            str(cycle["cycle_id"]),
            expected_revision=int(cycle["revision"]),
            reason_code="validated_tutor_turn_observed",
            source_type="agent_run",
            source_id=run_id,
            evidence_refs=[f"message:{message_id}"],
            metadata={"request_kind": request_kind, "answer_status": result.get("answer_status")},
        )
    except LearningRevisionConflictError:
        pass
    return get_active_teaching_cycle(home, thread_id)


def ingest_session_teaching_cycle(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """Project a formal Session milestone into its linked teaching cycle."""
    activity_id = data.get("learning_activity_id")
    if not activity_id:
        return
    activity = conn.execute(
        "SELECT thread_id FROM learning_activities WHERE activity_id=?",
        (activity_id,),
    ).fetchone()
    if not activity or not activity["thread_id"]:
        return
    cycle = conn.execute(
        """
        SELECT * FROM teaching_cycles
        WHERE thread_id=? AND status='active' ORDER BY updated_at DESC LIMIT 1
        """,
        (activity["thread_id"],),
    ).fetchone()
    if not cycle:
        return
    session_id = str(data.get("session_id") or "")
    status = str(data.get("status") or "completed")
    event_type = "formal_session_completed" if status == "completed" else "formal_session_started"
    if conn.execute(
        """
        SELECT 1 FROM teaching_cycle_events
        WHERE cycle_id=? AND event_type=? AND source_type='session' AND source_id=?
        """,
        (cycle["cycle_id"], event_type, session_id),
    ).fetchone():
        return
    target_phase = "assess" if status == "completed" else "independent_practice"
    from_phase = str(cycle["phase"])
    to_phase = target_phase if (
        target_phase == from_phase or is_teaching_transition_allowed(from_phase, target_phase)
    ) else from_phase
    now = _now()
    conn.execute(
        """
        UPDATE teaching_cycles
        SET phase=?,session_id=?,revision=revision+1,updated_at=? WHERE cycle_id=?
        """,
        (to_phase, session_id, now, cycle["cycle_id"]),
    )
    _append_event_conn(
        conn,
        cycle_id=str(cycle["cycle_id"]),
        event_type=event_type,
        from_phase=from_phase,
        to_phase=to_phase,
        actor="runtime",
        reason_code=event_type,
        source_type="session",
        source_id=session_id,
        evidence_refs=[f"session:{session_id}"],
        metadata={"session_status": status, "module": data.get("module")},
        created_at=now,
    )


def _record_observation(
    home: Path,
    cycle_id: str,
    *,
    expected_revision: int,
    reason_code: str,
    source_type: str,
    source_id: str,
    evidence_refs: list[str],
    metadata: dict[str, Any],
) -> None:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM teaching_cycles WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        if not row:
            raise ValueError("Teaching cycle not found")
        _check_cycle_revision(row, expected_revision)
        if conn.execute(
            """
            SELECT 1 FROM teaching_cycle_events
            WHERE cycle_id=? AND event_type='tutor_observation'
              AND source_type=? AND source_id=?
            """,
            (cycle_id, source_type, source_id),
        ).fetchone():
            return
        phase = str(row["phase"])
        conn.execute(
            "UPDATE teaching_cycles SET revision=revision+1,updated_at=? WHERE cycle_id=?",
            (now, cycle_id),
        )
        _append_event_conn(
            conn,
            cycle_id=cycle_id,
            event_type="tutor_observation",
            from_phase=phase,
            to_phase=phase,
            actor="runtime",
            reason_code=reason_code,
            source_type=source_type,
            source_id=source_id,
            evidence_refs=evidence_refs,
            metadata=metadata,
            created_at=now,
        )


def _validate_cycle_links_conn(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    dimension_id: str | None,
    skill_id: str | None,
    objective_id: str | None,
    activity_id: str | None,
    thread_id: str | None,
    session_id: str | None,
) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    if activity_id:
        activity = conn.execute(
            "SELECT track_id,dimension_id,objective_id,thread_id,session_id FROM learning_activities WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError("Teaching cycle activity not found")
        if str(activity["track_id"]) != track_id:
            raise ValueError("Teaching cycle and activity tracks do not match")
        if objective_id and activity["objective_id"] and str(activity["objective_id"]) != objective_id:
            raise ValueError("Teaching cycle activity and objective do not match")
        dimension_id = dimension_id or activity["dimension_id"]
        objective_id = objective_id or activity["objective_id"]
        thread_id = thread_id or activity["thread_id"]
        session_id = session_id or activity["session_id"]
    if objective_id:
        objective = conn.execute(
            "SELECT track_id,dimension_id,skill_id FROM learning_objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if not objective:
            raise ValueError("Teaching cycle objective not found")
        if str(objective["track_id"]) != track_id:
            raise ValueError("Teaching cycle and objective tracks do not match")
        if dimension_id and str(objective["dimension_id"]) != str(dimension_id):
            raise ValueError("Teaching cycle and objective dimensions do not match")
        if skill_id and objective["skill_id"] and str(objective["skill_id"]) != str(skill_id):
            raise ValueError("Teaching cycle and objective skills do not match")
        dimension_id = dimension_id or str(objective["dimension_id"])
        skill_id = skill_id or objective["skill_id"]
    for table, identifier, label in (
        ("study_threads", thread_id, "thread"),
        ("sessions", session_id, "Session"),
    ):
        if identifier:
            linked = conn.execute(
                f"SELECT track_id FROM {table} WHERE "
                + ("thread_id=?" if table == "study_threads" else "session_id=?"),
                (identifier,),
            ).fetchone()
            if not linked:
                raise ValueError(f"Teaching cycle {label} not found")
            if str(linked["track_id"]) != track_id:
                raise ValueError(f"Teaching cycle and {label} tracks do not match")
    if skill_id and not conn.execute(
        "SELECT 1 FROM learning_skill_nodes WHERE track_id=? AND skill_id=?",
        (track_id, skill_id),
    ).fetchone():
        raise ValueError("Teaching cycle skill not found")
    return (
        str(dimension_id) if dimension_id else None,
        str(skill_id) if skill_id else None,
        str(objective_id) if objective_id else None,
        str(activity_id) if activity_id else None,
        str(thread_id) if thread_id else None,
        str(session_id) if session_id else None,
    )


def _check_cycle_revision(row: sqlite3.Row, expected_revision: int) -> None:
    current = int(row["revision"])
    if current != int(expected_revision):
        raise LearningRevisionConflictError(
            f"Stale TeachingCycle revision: expected {expected_revision}, current {current}",
            details={
                "cycle_id": row["cycle_id"],
                "expected_revision": int(expected_revision),
                "current_revision": current,
            },
        )


def _append_event_conn(
    conn: sqlite3.Connection,
    *,
    cycle_id: str,
    event_type: str,
    from_phase: str,
    to_phase: str,
    actor: str,
    reason_code: str,
    source_type: str | None,
    source_id: str | None,
    evidence_refs: list[str],
    metadata: dict[str, Any],
    created_at: str,
) -> None:
    sequence = int(
        conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM teaching_cycle_events WHERE cycle_id=?",
            (cycle_id,),
        ).fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO teaching_cycle_events(
          event_id,cycle_id,sequence,event_type,from_phase,to_phase,actor,
          reason_code,source_type,source_id,evidence_refs_json,metadata_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _id("cycle_event"),
            cycle_id,
            sequence,
            event_type[:80],
            from_phase,
            to_phase,
            actor,
            reason_code[:120],
            source_type[:80] if source_type else None,
            source_id[:240] if source_id else None,
            json.dumps(evidence_refs[:50], ensure_ascii=False),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
            created_at,
        ),
    )


def _select_cycle_mastery_conn(
    conn: sqlite3.Connection,
    cycle: sqlite3.Row,
) -> sqlite3.Row | None:
    if cycle["skill_id"]:
        return conn.execute(
            "SELECT * FROM skill_mastery WHERE track_id=? AND skill_id=?",
            (cycle["track_id"], cycle["skill_id"]),
        ).fetchone()
    if cycle["dimension_id"]:
        return conn.execute(
            """
            SELECT mastery.* FROM skill_mastery AS mastery
            JOIN learning_skill_nodes AS nodes
              ON nodes.track_id=mastery.track_id AND nodes.skill_id=mastery.skill_id
            WHERE mastery.track_id=? AND nodes.dimension_id=?
            ORDER BY mastery.estimate ASC,mastery.confidence DESC LIMIT 1
            """,
            (cycle["track_id"], cycle["dimension_id"]),
        ).fetchone()
    return None


def _recommendation(
    action: str,
    target_phase: str | None,
    reason_code: str,
    mastery: sqlite3.Row | None,
) -> dict[str, Any]:
    return {
        "action": action,
        "target_phase": target_phase,
        "reason_code": reason_code,
        "deterministic": True,
        "applied": False,
        "mastery": (
            {
                "skill_id": mastery["skill_id"],
                "estimate": float(mastery["estimate"]),
                "confidence": float(mastery["confidence"]),
                "evidence_count": int(mastery["evidence_count"]),
                "status": mastery["status"],
            }
            if mastery
            else None
        ),
    }


def _cycle_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        **{key: row[key] for key in row.keys() if key != "context_json"},
        "revision": int(row["revision"]),
        "context": json.loads(row["context_json"] or "{}"),
    }


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        **{
            key: row[key]
            for key in row.keys()
            if key not in {"evidence_refs_json", "metadata_json"}
        },
        "sequence": int(row["sequence"]),
        "evidence_refs": json.loads(row["evidence_refs_json"] or "[]"),
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }
