from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .diagnostics import diagnostic_status, start_diagnostic
from .listening_corpus import browse_listening_items
from .storage import connect, initialise_database
from .study_context import build_study_context


MANAGED_REVIEW_SOURCES = {
    "session_error",
    "listening_item",
    "writing_session",
    "reading_answer",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _route_with_unit(route: str, unit_id: str) -> str:
    parts = urlsplit(route)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["practice_unit_id"] = unit_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _session_route(module: str, session_id: str, *, feedback: bool = False) -> str:
    if feedback and module in {"writing", "reading"}:
        return f"/feedback/{session_id}"
    if module == "speaking":
        return f"/practice/speaking?session={session_id}"
    if module == "listening":
        return f"/practice/listening/{session_id}"
    return f"/practice/{module}/{session_id}"


def _candidate_review_tasks(home: Path) -> list[dict[str, Any]]:
    now = _now()
    candidates: list[dict[str, Any]] = []
    with connect(home) as conn:
        error_rows = conn.execute(
            """
            SELECT e.id,e.session_id,e.tag,e.count,e.evidence,s.module
            FROM errors e JOIN sessions s USING(session_id)
            WHERE e.status<>'resolved'
            ORDER BY e.count DESC,e.id
            """
        ).fetchall()
        reading_rows = conn.execute(
            """
            SELECT ra.id,ra.session_id,ra.question_id,ra.question_number,
                   ra.question_type,ra.user_answer,ra.evidence_location
            FROM reading_answers ra
            WHERE ra.is_correct=0
            ORDER BY ra.id
            """
        ).fetchall()
        writing_rows = conn.execute(
            """
            SELECT s.session_id,s.occurred_at
            FROM sessions s
            WHERE s.module='writing' AND s.status='awaiting_revision'
              AND EXISTS (
                SELECT 1 FROM writing_versions v
                WHERE v.session_id=s.session_id AND lower(v.version_label)='v1'
              )
              AND NOT EXISTS (
                SELECT 1 FROM writing_versions v
                WHERE v.session_id=s.session_id AND lower(v.version_label) IN ('v2','final')
              )
            ORDER BY s.occurred_at
            """
        ).fetchall()
    for row in error_rows:
        module = str(row["module"])
        candidates.append(
            {
                "stable_key": f"error:{row['id']}",
                "module": module,
                "review_kind": "error_review",
                "priority": min(100, 55 + int(row["count"]) * 5),
                "due_at": now,
                "source_type": "session_error",
                "source_id": str(row["id"]),
                "session_id": str(row["session_id"]),
                "title": f"复盘错误：{row['tag']}",
                "action": "回到原 Session，确认错误原因并完成一次针对性改正。",
                "route": _session_route(module, str(row["session_id"]), feedback=True),
                "payload": {
                    "tag": row["tag"],
                    "count": int(row["count"]),
                    "evidence": row["evidence"],
                },
            }
        )
    for row in reading_rows:
        question_label = row["question_number"] or row["question_id"] or row["id"]
        candidates.append(
            {
                "stable_key": f"reading-answer:{row['id']}",
                "module": "reading",
                "review_kind": "reading_wrong_answer",
                "priority": 80,
                "due_at": now,
                "source_type": "reading_answer",
                "source_id": str(row["id"]),
                "session_id": str(row["session_id"]),
                "title": f"复盘 Reading 第 {question_label} 题",
                "action": "先重新定位原文证据，再检查题型方法与错误选项。",
                "route": _session_route("reading", str(row["session_id"]), feedback=True),
                "payload": {
                    "question_id": row["question_id"],
                    "question_number": row["question_number"],
                    "question_type": row["question_type"],
                    "user_answer": row["user_answer"],
                    "evidence_location": row["evidence_location"],
                },
            }
        )
    for row in writing_rows:
        candidates.append(
            {
                "stable_key": f"writing-v2:{row['session_id']}",
                "module": "writing",
                "review_kind": "writing_revision",
                "priority": 90,
                "due_at": str(row["occurred_at"] or now),
                "source_type": "writing_session",
                "source_id": str(row["session_id"]),
                "session_id": str(row["session_id"]),
                "title": "根据证据完成 Writing V2",
                "action": "先处理三个最高优先级问题，再提交自己的 V2；不要先看模型范文。",
                "route": _session_route("writing", str(row["session_id"]), feedback=True),
                "payload": {},
            }
        )
    for item in browse_listening_items(home, due_only=True, limit=1000):
        progress = item.get("progress") or {}
        if int(progress.get("attempts") or 0) < 1:
            continue
        due_at = str(progress.get("next_review_at") or now)
        candidates.append(
            {
                "stable_key": f"listening:{item['item_id']}:{due_at}",
                "module": "listening",
                "review_kind": "listening_expression",
                "priority": 70 + min(20, int(item.get("priority") or 1) * 2),
                "due_at": due_at,
                "source_type": "listening_item",
                "source_id": str(item["item_id"]),
                "session_id": None,
                "title": f"到期听写：{item.get('category_label') or item['category']}",
                "action": "先听后写，再核对拼写、连读和场景含义。",
                "route": f"/practice/listening?item={item['item_id']}",
                "payload": {
                    "item_id": item["item_id"],
                    "category": item["category"],
                    "mastery": progress.get("mastery"),
                },
            }
        )
    return candidates


def sync_review_tasks(home: Path) -> dict[str, int]:
    initialise_database(home)
    candidates = _candidate_review_tasks(home)
    active_keys = {item["stable_key"] for item in candidates}
    now = _now()
    with connect(home) as conn:
        for item in candidates:
            conn.execute(
                """
                INSERT INTO review_tasks(
                  review_task_id,stable_key,module,review_kind,status,priority,due_at,
                  source_type,source_id,session_id,title,action,route,payload_json,
                  created_at,updated_at
                ) VALUES(?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(stable_key) DO UPDATE SET
                  priority=excluded.priority,due_at=excluded.due_at,title=excluded.title,
                  action=excluded.action,route=excluded.route,payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                WHERE review_tasks.status IN ('pending','in_progress')
                """,
                (
                    _id("RT"),
                    item["stable_key"],
                    item["module"],
                    item["review_kind"],
                    item["priority"],
                    item["due_at"],
                    item["source_type"],
                    item["source_id"],
                    item["session_id"],
                    item["title"],
                    item["action"],
                    item["route"],
                    json.dumps(item["payload"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        open_rows = conn.execute(
            """
            SELECT review_task_id,stable_key FROM review_tasks
            WHERE status IN ('pending','in_progress')
              AND source_type IN ('session_error','listening_item','writing_session','reading_answer')
            """
        ).fetchall()
        stale_ids = [
            str(row["review_task_id"])
            for row in open_rows
            if str(row["stable_key"]) not in active_keys
        ]
        if stale_ids:
            placeholders = ",".join("?" for _ in stale_ids)
            conn.execute(
                f"""
                UPDATE review_tasks SET status='completed',completed_at=?,updated_at=?
                WHERE review_task_id IN ({placeholders})
                """,
                (now, now, *stale_ids),
            )
        counts = conn.execute(
            "SELECT status,COUNT(*) count FROM review_tasks GROUP BY status"
        ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in counts}


def _review_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json") or "{}")
    return result


def list_review_tasks(
    home: Path,
    *,
    status: str = "pending",
    module: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sync_review_tasks(home)
    clauses = ["status=?"]
    params: list[Any] = [status]
    if module:
        clauses.append("module=?")
        params.append(module)
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM review_tasks WHERE {' AND '.join(clauses)}
            ORDER BY due_at,priority DESC,created_at LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    return [_review_row(row) for row in rows]


def get_practice_unit(home: Path, unit_id: str) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM practice_units WHERE unit_id=?", (unit_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown PracticeUnit: {unit_id}")
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json") or "{}")
    result["launch_url"] = _route_with_unit(str(result["route"]), unit_id)
    return result


def list_practice_units(
    home: Path, *, scheduled_for: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    initialise_database(home)
    where = ""
    params: list[Any] = []
    if scheduled_for:
        where = "WHERE scheduled_for=?"
        params.append(scheduled_for)
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(
            f"SELECT unit_id FROM practice_units {where} "
            "ORDER BY scheduled_for DESC,created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [get_practice_unit(home, str(row["unit_id"])) for row in rows]


def _create_unit(
    home: Path,
    *,
    unit_kind: str,
    module: str | None,
    title: str,
    status: str,
    scheduled_for: str,
    source_type: str,
    source_key: str,
    route: str,
    estimated_minutes: int | None,
    payload: dict[str, Any],
    diagnostic_id: str | None = None,
    session_id: str | None = None,
    assessment_run_id: str | None = None,
) -> dict[str, Any]:
    now = _now()
    unit_id = _id("PU")
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO practice_units(
              unit_id,unit_kind,module,title,status,scheduled_for,source_type,
              source_key,route,estimated_minutes,diagnostic_id,session_id,
              assessment_run_id,payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_key) DO NOTHING
            """,
            (
                unit_id,
                unit_kind,
                module,
                title,
                status,
                scheduled_for,
                source_type,
                source_key,
                route,
                estimated_minutes,
                diagnostic_id,
                session_id,
                assessment_run_id,
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT unit_id FROM practice_units WHERE source_key=?", (source_key,)
        ).fetchone()
    return get_practice_unit(home, str(row["unit_id"]))


def materialise_today_unit(home: Path, slot: str) -> dict[str, Any]:
    if slot not in {"primary", "consolidation", "diagnostic"}:
        raise ValueError("Today slot must be primary, consolidation or diagnostic")
    initialise_database(home)
    day = date.today().isoformat()
    source_key = f"today:{day}:{slot}"
    with connect(home) as conn:
        existing = conn.execute(
            "SELECT unit_id FROM practice_units WHERE source_key=?", (source_key,)
        ).fetchone()
    if existing:
        return get_practice_unit(home, str(existing["unit_id"]))
    if slot == "diagnostic":
        diagnostic = diagnostic_status(home)
        if diagnostic.get("status") != "active":
            diagnostic = start_diagnostic(home, "quick")
        unit = _create_unit(
            home,
            unit_kind="diagnostic",
            module=None,
            title="完成四科 Quick Diagnostic",
            status="in_progress",
            scheduled_for=day,
            source_type="today_plan",
            source_key=source_key,
            route="/diagnostic",
            estimated_minutes=90,
            diagnostic_id=str(diagnostic["diagnostic_id"]),
            payload={"slot": slot, "diagnostic_mode": "quick"},
        )
        return bind_practice_unit(
            home, str(unit["unit_id"]), diagnostic_id=str(diagnostic["diagnostic_id"])
        )
    if slot == "consolidation":
        review_tasks = list_review_tasks(home, limit=1)
        if review_tasks:
            task = review_tasks[0]
            unit = _create_unit(
                home,
                unit_kind="review",
                module=str(task["module"]),
                title=str(task["title"]),
                status="in_progress",
                scheduled_for=day,
                source_type="today_plan",
                source_key=source_key,
                route=str(task["route"]),
                estimated_minutes=20,
                session_id=task.get("session_id"),
                payload={"slot": slot, "review_task_id": task["review_task_id"]},
            )
            with connect(home) as conn:
                conn.execute(
                    """
                    UPDATE review_tasks SET status='in_progress',practice_unit_id=?,updated_at=?
                    WHERE review_task_id=? AND status='pending'
                    """,
                    (unit["unit_id"], _now(), task["review_task_id"]),
                )
            return get_practice_unit(home, str(unit["unit_id"]))
    context = build_study_context(home)
    task = context["today_plan"][slot]
    return _create_unit(
        home,
        unit_kind="practice",
        module=str(task["module"]),
        title=str(task["title"]),
        status="planned",
        scheduled_for=day,
        source_type="today_plan",
        source_key=source_key,
        route=str(task["route"]),
        estimated_minutes=int(task["estimated_minutes"]),
        payload={"slot": slot, "recommendation": task},
    )


def start_review_task(home: Path, review_task_id: str) -> dict[str, Any]:
    sync_review_tasks(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM review_tasks WHERE review_task_id=?", (review_task_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown ReviewTask: {review_task_id}")
    task = _review_row(row)
    if task["status"] in {"completed", "dismissed"}:
        raise ValueError("Completed or dismissed ReviewTask cannot be started")
    unit = _create_unit(
        home,
        unit_kind="review",
        module=str(task["module"]),
        title=str(task["title"]),
        status="in_progress",
        scheduled_for=date.today().isoformat(),
        source_type="review_queue",
        source_key=f"review:{review_task_id}",
        route=str(task["route"]),
        estimated_minutes=20,
        session_id=task.get("session_id"),
        payload={"review_task_id": review_task_id},
    )
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE review_tasks SET status='in_progress',practice_unit_id=?,updated_at=?
            WHERE review_task_id=?
            """,
            (unit["unit_id"], _now(), review_task_id),
        )
    return get_practice_unit(home, str(unit["unit_id"]))


def bind_practice_unit(
    home: Path,
    unit_id: str,
    *,
    session_id: str | None = None,
    assessment_run_id: str | None = None,
    diagnostic_id: str | None = None,
) -> dict[str, Any]:
    unit = get_practice_unit(home, unit_id)
    if unit["status"] in {"completed", "cancelled"}:
        raise ValueError("A completed or cancelled PracticeUnit cannot be rebound")
    now = _now()
    with connect(home) as conn:
        if session_id:
            row = conn.execute(
                "SELECT module FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown Session: {session_id}")
            if unit.get("module") and row["module"] != unit["module"]:
                raise ValueError("PracticeUnit and Session modules do not match")
            conn.execute(
                "UPDATE sessions SET practice_unit_id=? WHERE session_id=?",
                (unit_id, session_id),
            )
        if assessment_run_id:
            row = conn.execute(
                "SELECT session_id,module FROM assessment_runs WHERE run_id=?",
                (assessment_run_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown AssessmentRun: {assessment_run_id}")
            conn.execute(
                "UPDATE assessment_runs SET practice_unit_id=? WHERE run_id=?",
                (unit_id, assessment_run_id),
            )
            session_id = session_id or str(row["session_id"])
            conn.execute(
                "UPDATE sessions SET practice_unit_id=? WHERE session_id=?",
                (unit_id, session_id),
            )
        if diagnostic_id:
            row = conn.execute(
                "SELECT diagnostic_id FROM diagnostic_runs WHERE diagnostic_id=?",
                (diagnostic_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown Diagnostic: {diagnostic_id}")
            conn.execute(
                "UPDATE diagnostic_runs SET practice_unit_id=? WHERE diagnostic_id=?",
                (unit_id, diagnostic_id),
            )
        conn.execute(
            """
            UPDATE practice_units
            SET status='in_progress',session_id=COALESCE(?,session_id),
                assessment_run_id=COALESCE(?,assessment_run_id),
                diagnostic_id=COALESCE(?,diagnostic_id),revision=revision+1,updated_at=?
            WHERE unit_id=?
            """,
            (session_id, assessment_run_id, diagnostic_id, now, unit_id),
        )
    return get_practice_unit(home, unit_id)


def complete_review_task(home: Path, review_task_id: str) -> dict[str, Any]:
    now = _now()
    with connect(home) as conn:
        row = conn.execute(
            "SELECT practice_unit_id FROM review_tasks WHERE review_task_id=?",
            (review_task_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown ReviewTask: {review_task_id}")
        conn.execute(
            """
            UPDATE review_tasks SET status='completed',completed_at=?,updated_at=?
            WHERE review_task_id=?
            """,
            (now, now, review_task_id),
        )
        if row["practice_unit_id"]:
            conn.execute(
                """
                UPDATE practice_units SET status='completed',completed_at=?,
                    updated_at=?,revision=revision+1 WHERE unit_id=?
                """,
                (now, now, row["practice_unit_id"]),
            )
        updated = conn.execute(
            "SELECT * FROM review_tasks WHERE review_task_id=?", (review_task_id,)
        ).fetchone()
    return _review_row(updated)


def complete_practice_unit(
    home: Path,
    *,
    unit_id: str | None = None,
    session_id: str | None = None,
    assessment_run_id: str | None = None,
    diagnostic_id: str | None = None,
) -> dict[str, Any] | None:
    selectors = [
        ("unit_id", unit_id),
        ("session_id", session_id),
        ("assessment_run_id", assessment_run_id),
        ("diagnostic_id", diagnostic_id),
    ]
    column, value = next(((name, item) for name, item in selectors if item), (None, None))
    if not column or not value:
        raise ValueError("A PracticeUnit identifier or bound domain identifier is required")
    now = _now()
    with connect(home) as conn:
        row = conn.execute(
            f"SELECT unit_id FROM practice_units WHERE {column}=?", (value,)
        ).fetchone()
        if not row:
            return None
        resolved_unit_id = str(row["unit_id"])
        conn.execute(
            """
            UPDATE practice_units SET status='completed',completed_at=?,
                updated_at=?,revision=revision+1 WHERE unit_id=?
            """,
            (now, now, resolved_unit_id),
        )
        conn.execute(
            """
            UPDATE review_tasks SET status='completed',completed_at=?,updated_at=?
            WHERE practice_unit_id=? AND status IN ('pending','in_progress')
            """,
            (now, now, resolved_unit_id),
        )
    return get_practice_unit(home, resolved_unit_id)
