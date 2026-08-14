from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .allocation import recommend_allocation
from .config import load_profile
from .diagnostics import diagnostic_status
from .onboarding import onboarding_status
from .storage import connect, recent_bands


MODULES = ("listening", "reading", "writing", "speaking")
ROUTES = {
    "listening": "ielts-progress",
    "reading": "ielts-reading",
    "writing": "ielts-writing",
    "speaking": "ielts-speaking",
}
PRACTICE_ROUTES = {
    "listening": "/practice?module=listening",
    "reading": "/practice?module=reading",
    "writing": "/practice?module=writing",
    "speaking": "/practice?module=speaking",
}
FALLBACK_TASKS = {
    "listening": ("高频听力场景听写", 20, "skill_drill"),
    "reading": ("雅思阅读题型专项或逐级提示训练", 30, "question_type_drill"),
    "writing": ("完成一道 Academic Writing 单项任务", 45, "section_practice"),
    "speaking": ("领场景口语任务并在练习后贴回转写点评", 20, "section_practice"),
}


def _recent_snapshot(home: Path, module: str | None, days: int) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    where = "WHERE status='completed' AND occurred_at>=?"
    params: list[Any] = [cutoff]
    if module:
        where += " AND module=?"
        params.append(module)
    with connect(home) as conn:
        rows = conn.execute(
            f"SELECT module,COUNT(*) count,MAX(occurred_at) last_at FROM sessions {where} GROUP BY module",
            params,
        ).fetchall()
        error_where = "WHERE e.status<>'resolved' AND s.occurred_at>=?"
        error_params: list[Any] = [cutoff]
        if module:
            error_where += " AND s.module=?"
            error_params.append(module)
        errors = conn.execute(
            f"""
            SELECT e.tag,SUM(e.count) total
            FROM errors e JOIN sessions s USING(session_id)
            {error_where}
            GROUP BY e.tag ORDER BY total DESC,e.tag LIMIT 5
            """,
            error_params,
        ).fetchall()
        ability: list[dict[str, Any]] = []
        if module in {"writing", "speaking"}:
            ability_rows = conn.execute(
                """
                SELECT cs.criterion,
                       ROUND(AVG(COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0)),2) average,
                       COUNT(*) samples
                FROM criterion_scores cs JOIN sessions s USING(session_id)
                WHERE s.module=? AND s.status='completed' AND s.occurred_at>=?
                  AND COALESCE(cs.assessment_role,'local_rubric')='local_rubric'
                  AND COALESCE(cs.confidence,'medium') IN ('medium','high')
                GROUP BY cs.criterion ORDER BY average,cs.criterion LIMIT 4
                """,
                (module, cutoff),
            ).fetchall()
            ability = [
                {"criterion": row["criterion"], "average": row["average"], "samples": row["samples"]}
                for row in ability_rows
            ]
        elif module == "reading":
            ability_rows = conn.execute(
                """
                SELECT ra.question_type,
                       ROUND(AVG(CASE WHEN ra.is_correct=1 THEN 1.0 ELSE 0.0 END),3) accuracy,
                       COUNT(*) samples
                FROM reading_answers ra JOIN sessions s USING(session_id)
                WHERE s.status='completed' AND s.occurred_at>=? AND ra.is_correct IS NOT NULL
                GROUP BY ra.question_type ORDER BY accuracy,ra.question_type LIMIT 3
                """,
                (cutoff,),
            ).fetchall()
            ability = [
                {"question_type": row["question_type"], "accuracy": row["accuracy"], "samples": row["samples"]}
                for row in ability_rows
            ]
    sessions = {
        str(row["module"]): {"count": int(row["count"]), "last_at": row["last_at"]}
        for row in rows
    }
    return {
        "sessions": sessions,
        "active_errors": [
            {"tag": str(row["tag"]), "count": int(row["total"])} for row in errors
        ],
        "ability_signals": ability,
        "scope_days": days,
    }


def build_study_context(
    home: Path,
    *,
    module: str | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """Return the minimum deterministic context needed to begin a study turn.

    Module-specific calls deliberately omit global reports and allocation. The
    generic call includes a compact four-skill snapshot for planning.
    """
    if module is not None:
        module = module.lower()
        if module not in MODULES:
            raise ValueError(f"Unsupported module: {module}")
    profile = load_profile(home)
    setup = onboarding_status(home)
    history = _recent_snapshot(home, module, days)
    context: dict[str, Any] = {
        "context_version": 2,
        "route": ROUTES.get(module, "ielts"),
        "module": module,
        "onboarding": setup,
        "history_window_days": days,
        "history": history,
    }

    if module:
        context["profile"] = {
            "target": profile["target"].get(module),
            "minimum_required": profile.get("minimum_required", {}).get(module),
            "current": profile.get("current", {}).get(module),
            "feedback_language": profile.get("preferences", {}).get("feedback_language"),
            "model_answers_visible_by_default": profile.get("preferences", {}).get(
                "model_answers_visible_by_default", False
            ),
        }
        bands = recent_bands(home, module, 3)
        context["history"]["recent_bands"] = bands
        context["next_action"] = (
            "complete_onboarding_once" if setup["status"] == "pending" else "start_requested_practice"
        )
        return context

    allocation = recommend_allocation(home, persist=False)
    context["profile"] = {
        "exam_type": profile["exam"]["type"],
        "test_date": profile["exam"].get("test_date"),
        "target": profile["target"],
        "minimum_required": profile.get("minimum_required", {}),
        "current": profile.get("current", {}),
    }
    context["diagnostic"] = diagnostic_status(home)
    context["allocation"] = allocation.allocation
    context["allocation_reasons"] = allocation.reasons[:3]
    with connect(home) as conn:
        pack_rows = conn.execute(
            """
            SELECT module,COUNT(*) count FROM assessment_packs
            WHERE practice_mode='full_mock' AND conformance_status='verified'
            GROUP BY module
            """
        ).fetchall()
    verified_packs = {str(row["module"]): int(row["count"]) for row in pack_rows}
    ranked = sorted(
        MODULES,
        key=lambda name: (
            float(allocation.evidence.get("target_gaps", {}).get(name) or 0),
            float(allocation.allocation.get(name, 0)),
        ),
        reverse=True,
    )
    primary = ranked[0]
    consolidation = next(
        (
            name
            for name in sorted(
                MODULES,
                key=lambda item: float(allocation.allocation.get(item, 0)),
                reverse=True,
            )
            if name != primary
        ),
        ranked[1],
    )
    context["today_plan"] = {
        "strategy": "70_30",
        "primary": _recommended_task(
            primary,
            share=0.70,
            allocation=allocation,
            target=profile["target"],
            verified_pack_count=verified_packs.get(primary, 0),
        ),
        "consolidation": _recommended_task(
            consolidation,
            share=0.30,
            allocation=allocation,
            target=profile["target"],
            verified_pack_count=verified_packs.get(consolidation, 0),
        ),
        "verified_full_mock_count": sum(verified_packs.values()),
    }
    if setup["status"] == "pending":
        context["next_action"] = "complete_onboarding_once"
    elif setup["baseline_status"] == "missing":
        context["next_action"] = "offer_quick_diagnostic_or_direct_practice"
    else:
        context["next_action"] = "recommend_one_primary_task"
    return context


def _recommended_task(
    module: str,
    *,
    share: float,
    allocation: Any,
    target: dict[str, Any],
    verified_pack_count: int,
) -> dict[str, Any]:
    full_mock_available = verified_pack_count > 0
    current = allocation.recent_average.get(module)
    gap = allocation.evidence.get("target_gaps", {}).get(module)
    if full_mock_available:
        title = f"完成一套 {module.title()} verified full mock"
        minutes = 60 if module in {"reading", "writing"} else 35
        mode = "full_mock"
    else:
        title, minutes, mode = FALLBACK_TASKS[module]
    reason = next(
        (
            item
            for item in allocation.reasons
            if module.lower() in item.lower()
            or {
                "listening": "听力",
                "reading": "阅读",
                "writing": "写作",
                "speaking": "口语",
            }[module]
            in item
        ),
        f"当前训练分配为 {allocation.allocation[module] * 100:.0f}%。",
    )
    return {
        "module": module,
        "share": share,
        "title": title,
        "reason": reason,
        "estimated_minutes": minutes,
        "target_band": target.get(module),
        "recent_band": current,
        "target_gap": round(float(gap), 2) if gap is not None else None,
        "content_available": full_mock_available,
        "practice_mode": mode,
        "fallback": not full_mock_available,
        "route": PRACTICE_ROUTES[module],
    }
