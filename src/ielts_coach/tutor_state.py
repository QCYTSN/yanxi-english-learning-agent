from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import (
    connect,
    create_learner_memory,
    initialise_database,
)


STATE_VERSION = 1
_MODULES = {"listening", "reading", "writing", "speaking", "mixed"}
_PROPOSAL_TYPES = {
    "practice_session",
    "review_item",
    "learner_memory",
    "material_promotion",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_state() -> dict[str, Any]:
    return {
        "state_version": STATE_VERSION,
        "module": "mixed",
        "current_material_ids": [],
        "current_question": None,
        "learner_answer": None,
        "learner_reasoning": None,
        "teaching_goal": None,
        "hint_level": 0,
        "answer_stage": "not_applicable",
        "evidence_refs": [],
        "unresolved_issue": None,
        "correction_status": "not_applicable",
    }


def get_thread_learning_state(home: Path, thread_id: str) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        thread = conn.execute(
            "SELECT module FROM study_threads WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if not thread:
            raise ValueError("Study thread not found")
        row = conn.execute(
            "SELECT * FROM tutor_thread_states WHERE thread_id=?", (thread_id,)
        ).fetchone()
    if not row:
        state = _empty_state()
        state["module"] = str(thread["module"])
        return {
            "thread_id": thread_id,
            "revision": 0,
            "state": state,
            "last_message_id": None,
            "last_agent_run_id": None,
            "updated_at": None,
        }
    state = _normalise_state(json.loads(row["state_json"] or "{}"))
    return {
        "thread_id": thread_id,
        "revision": int(row["revision"]),
        "state": state,
        "last_message_id": row["last_message_id"],
        "last_agent_run_id": row["last_agent_run_id"],
        "updated_at": row["updated_at"],
    }


def list_tutor_proposals(
    home: Path,
    *,
    thread_id: str | None = None,
    status: str | None = "pending",
    limit: int = 50,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if thread_id:
        clauses.append("thread_id=?")
        params.append(thread_id)
    if status:
        if status not in {"pending", "confirmed", "dismissed", "executed", "failed"}:
            raise ValueError("Unknown tutor proposal status")
        clauses.append("status=?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 200)))
    with connect(home) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM tutor_proposals
            {where}
            ORDER BY created_at DESC,proposal_id DESC LIMIT ?
            """,
            params,
        ).fetchall()
    return [_proposal_row(row) for row in rows]


def persist_tutor_turn_effects(
    home: Path,
    *,
    run: dict[str, Any],
    result: dict[str, Any],
    orchestration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Commit soft teaching state and confirmation-gated proposals once per run."""
    initialise_database(home)
    request = run.get("request") or {}
    thread_id = str(request.get("study_thread_id") or "")
    message_id = str(request.get("user_message_id") or "")
    run_id = str(run.get("run_id") or "")
    if not thread_id or not message_id or not run_id:
        raise ValueError("Tutor turn persistence requires thread, message and run IDs")
    orchestration = dict(orchestration or run.get("orchestration") or {})
    now = _now()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        committed = conn.execute(
            "SELECT state_revision FROM tutor_turn_commits WHERE run_id=?", (run_id,)
        ).fetchone()
        if committed:
            state_revision = int(committed["state_revision"])
        else:
            existing = conn.execute(
                "SELECT * FROM tutor_thread_states WHERE thread_id=?", (thread_id,)
            ).fetchone()
            previous = (
                _normalise_state(json.loads(existing["state_json"] or "{}"))
                if existing
                else _empty_state()
            )
            state = _derive_next_state(previous, request, result, orchestration)
            state_revision = int(existing["revision"] if existing else 0) + 1
            created_at = str(existing["created_at"] if existing else now)
            conn.execute(
                """
                INSERT INTO tutor_thread_states(
                  thread_id,revision,state_json,last_message_id,last_agent_run_id,
                  created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(thread_id) DO UPDATE SET
                  revision=excluded.revision,state_json=excluded.state_json,
                  last_message_id=excluded.last_message_id,
                  last_agent_run_id=excluded.last_agent_run_id,
                  updated_at=excluded.updated_at
                """,
                (
                    thread_id,
                    state_revision,
                    json.dumps(state, ensure_ascii=False),
                    message_id,
                    run_id,
                    created_at,
                    now,
                ),
            )
            for index, proposal in enumerate(orchestration.get("proposals") or []):
                clean = _normalise_proposal(proposal, result=result)
                if not clean:
                    continue
                proposal_id = f"proposal:{run_id}:{index + 1}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tutor_proposals(
                      proposal_id,thread_id,source_message_id,agent_run_id,
                      proposal_type,title,rationale,status,payload_json,result_json,
                      created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,'pending',?,'{}',?,?)
                    """,
                    (
                        proposal_id,
                        thread_id,
                        message_id,
                        run_id,
                        clean["proposal_type"],
                        clean["title"],
                        clean["rationale"],
                        json.dumps(clean["payload"], ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO tutor_turn_commits(run_id,thread_id,state_revision,created_at)
                VALUES(?,?,?,?)
                """,
                (run_id, thread_id, state_revision, now),
            )
    return {
        "learning_state": get_thread_learning_state(home, thread_id),
        "proposals": list_tutor_proposals(home, thread_id=thread_id, status="pending"),
    }


def resolve_tutor_proposal(
    home: Path,
    proposal_id: str,
    *,
    decision: str,
) -> dict[str, Any]:
    if decision not in {"confirm", "dismiss"}:
        raise ValueError("Tutor proposal decision must be confirm or dismiss")
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM tutor_proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
    if not row:
        raise ValueError("Tutor proposal not found")
    proposal = _proposal_row(row)
    if proposal["status"] in {"dismissed", "executed"}:
        return proposal
    now = _now()
    if decision == "dismiss":
        with connect(home) as conn:
            conn.execute(
                """
                UPDATE tutor_proposals
                SET status='dismissed',updated_at=?,resolved_at=?
                WHERE proposal_id=? AND status IN ('pending','confirmed')
                """,
                (now, now, proposal_id),
            )
        return _get_proposal(home, proposal_id)

    try:
        result = _execute_confirmed_proposal(home, proposal)
        status = "executed"
    except Exception as exc:
        result = {"error": str(exc)[-1000:]}
        status = "failed"
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE tutor_proposals
            SET status=?,result_json=?,updated_at=?,resolved_at=?
            WHERE proposal_id=? AND status IN ('pending','confirmed','failed')
            """,
            (status, json.dumps(result, ensure_ascii=False), now, now, proposal_id),
        )
    return _get_proposal(home, proposal_id)


def _execute_confirmed_proposal(
    home: Path,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    payload = proposal["payload"]
    proposal_type = proposal["proposal_type"]
    if proposal_type == "practice_session":
        module = _clean_module(payload.get("module"))
        return {
            "route": payload.get("route") or (
                f"/practice?module={module}" if module != "mixed" else "/practice"
            ),
            "requires_user_launch": True,
        }
    if proposal_type == "material_promotion":
        return {"route": "/content-studio", "requires_user_launch": True}
    if proposal_type == "learner_memory":
        statement = str(payload.get("statement") or "").strip()
        if not statement:
            raise ValueError("Learner memory proposal has no statement")
        memory = create_learner_memory(
            home,
            memory_type=str(payload.get("memory_type") or "learning_preference")[:80],
            statement=statement[:1000],
            confidence=float(payload.get("confidence") or 0.8),
            evidence_refs=[f"tutor-proposal:{proposal['proposal_id']}"],
            scope=str(payload.get("scope") or "teaching_style")[:80],
            source_thread_id=str(proposal["thread_id"]),
        )
        return {"memory_id": memory["memory_id"], "route": "/settings/memory"}
    if proposal_type == "review_item":
        module = _clean_module(payload.get("module"))
        review_id = f"RT-tutor-{hashlib.sha256(proposal['proposal_id'].encode()).hexdigest()[:16]}"
        stable_key = f"tutor-proposal:{proposal['proposal_id']}"
        route = str(payload.get("route") or (
            f"/practice?module={module}" if module != "mixed" else "/practice"
        ))
        now = _now()
        with connect(home) as conn:
            conn.execute(
                """
                INSERT INTO review_tasks(
                  review_task_id,stable_key,module,review_kind,status,priority,due_at,
                  source_type,source_id,session_id,title,action,route,payload_json,
                  created_at,updated_at
                ) VALUES(?,?,?,?,'pending',70,?,'tutor_proposal',?,?,?,?,?,?,?,?)
                ON CONFLICT(stable_key) DO NOTHING
                """,
                (
                    review_id,
                    stable_key,
                    module,
                    _safe_review_kind(payload.get("review_kind")),
                    now,
                    proposal["proposal_id"],
                    payload.get("session_id"),
                    str(payload.get("title") or proposal["title"])[:200],
                    str(payload.get("action") or proposal["rationale"])[:1000],
                    route,
                    json.dumps({"thread_id": proposal["thread_id"]}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return {"review_task_id": review_id, "route": route}
    raise ValueError("Unsupported tutor proposal type")


def _derive_next_state(
    previous: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
    orchestration: dict[str, Any],
) -> dict[str, Any]:
    state = _normalise_state(previous)
    canonical = request.get("canonical_session") or {}
    source = canonical.get("source_context") or {}
    module = _clean_module(result.get("module") or canonical.get("module"))
    if module != "mixed" or state["module"] == "mixed":
        state["module"] = module
    material_ids = [
        str(item.get("attachment_id"))
        for item in canonical.get("attachment_text") or []
        if item.get("attachment_id")
    ]
    material_ids.extend(
        str(item.get("media_id"))
        for item in canonical.get("registered_media") or []
        if item.get("media_id")
    )
    if material_ids:
        state["current_material_ids"] = list(dict.fromkeys(material_ids))[:16]
    question_id = source.get("question_id")
    passage_id = source.get("passage_id")
    if question_id or passage_id:
        state["current_question"] = {
            "question_id": question_id,
            "passage_id": passage_id,
            "title": source.get("passage_title"),
        }
    if source.get("learner_answer") is not None:
        state["learner_answer"] = str(source["learner_answer"])[:4000]
    if source.get("learner_reasoning") is not None:
        state["learner_reasoning"] = str(source["learner_reasoning"])[:6000]
    goal = str(orchestration.get("teaching_goal") or "").strip()
    if goal:
        state["teaching_goal"] = goal[:500]
    answer_status = str(result.get("answer_status") or "not_applicable")
    if answer_status == "withheld":
        state["hint_level"] = min(3, max(1, int(state.get("hint_level") or 0) + 1))
        state["answer_stage"] = "solving"
    elif answer_status == "verified":
        state["answer_stage"] = "reviewed"
    elif answer_status == "unverified":
        state["answer_stage"] = "attempted"
    elif result.get("request_kind") == "teacher_dialogue":
        state["answer_stage"] = "not_applicable"
    refs = []
    for item in result.get("evidence") or []:
        quote = str(item.get("quote") or "")
        refs.append(
            {
                "source": str(item.get("source") or "")[:500],
                "claim": str(item.get("claim") or "")[:1000],
                "quote": quote[:2000] or None,
                "text_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest() if quote else None,
            }
        )
    if refs:
        state["evidence_refs"] = refs[:12]
    limitations = result.get("limitations") or []
    unresolved = str(result.get("next_action") or "").strip()
    state["unresolved_issue"] = unresolved[:1000] if limitations or answer_status in {"withheld", "unverified"} else None
    state["correction_status"] = (
        "in_progress"
        if answer_status in {"withheld", "unverified"}
        else "resolved"
        if answer_status == "verified"
        else "not_applicable"
    )
    return state


def _normalise_state(value: dict[str, Any]) -> dict[str, Any]:
    result = _empty_state()
    result.update({key: value[key] for key in result if key in value})
    result["state_version"] = STATE_VERSION
    result["module"] = _clean_module(result.get("module"))
    result["hint_level"] = max(0, min(int(result.get("hint_level") or 0), 3))
    if result["answer_stage"] not in {"not_applicable", "not_attempted", "solving", "attempted", "reviewed"}:
        result["answer_stage"] = "not_applicable"
    if result["correction_status"] not in {"not_applicable", "in_progress", "resolved"}:
        result["correction_status"] = "not_applicable"
    result["current_material_ids"] = [str(item) for item in result.get("current_material_ids") or []][:16]
    result["evidence_refs"] = list(result.get("evidence_refs") or [])[:12]
    return result


def _normalise_proposal(
    value: Any,
    *,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    proposal_type = str(value.get("proposal_type") or value.get("command") or "")
    proposal_type = {
        "create_practice_session": "practice_session",
        "create_review_item": "review_item",
        "save_learner_memory": "learner_memory",
        "promote_material": "material_promotion",
    }.get(proposal_type, proposal_type)
    if proposal_type not in _PROPOSAL_TYPES:
        return None
    payload = dict(value.get("payload") or {})
    for key in ("module", "route", "title", "action", "statement", "review_kind", "memory_type", "scope", "session_id"):
        if value.get(key) is not None and key not in payload:
            payload[key] = value[key]
    title = str(value.get("title") or {
        "practice_session": "开始一项正式练习",
        "review_item": "加入复习队列",
        "learner_memory": "记住这项学习偏好",
        "material_promotion": "把材料整理成练习",
    }[proposal_type])[:200]
    rationale = str(value.get("rationale") or result.get("next_action") or title)[:1000]
    return {
        "proposal_type": proposal_type,
        "title": title,
        "rationale": rationale,
        "payload": payload,
    }


def _clean_module(value: Any) -> str:
    module = str(value or "mixed").casefold()
    return module if module in _MODULES else "mixed"


def _safe_review_kind(value: Any) -> str:
    review_kind = str(value or "error_review")
    allowed = {
        "error_review",
        "listening_expression",
        "writing_revision",
        "reading_wrong_answer",
    }
    return review_kind if review_kind in allowed else "error_review"


def _proposal_row(row: Any) -> dict[str, Any]:
    return {
        "proposal_id": row["proposal_id"],
        "thread_id": row["thread_id"],
        "source_message_id": row["source_message_id"],
        "agent_run_id": row["agent_run_id"],
        "proposal_type": row["proposal_type"],
        "title": row["title"],
        "rationale": row["rationale"],
        "status": row["status"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "result": json.loads(row["result_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
    }


def _get_proposal(home: Path, proposal_id: str) -> dict[str, Any]:
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM tutor_proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
    if not row:
        raise ValueError("Tutor proposal not found")
    return _proposal_row(row)
