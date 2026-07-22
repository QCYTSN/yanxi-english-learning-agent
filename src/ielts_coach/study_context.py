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
        error_where = "WHERE e.status<>'resolved'"
        error_params: list[Any] = []
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
    sessions = {
        str(row["module"]): {"count": int(row["count"]), "last_at": row["last_at"]}
        for row in rows
    }
    return {
        "sessions": sessions,
        "active_errors": [
            {"tag": str(row["tag"]), "count": int(row["total"])} for row in errors
        ],
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
        "context_version": 1,
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
    if setup["status"] == "pending":
        context["next_action"] = "complete_onboarding_once"
    elif setup["baseline_status"] == "missing":
        context["next_action"] = "offer_quick_diagnostic_or_direct_practice"
    else:
        context["next_action"] = "recommend_one_primary_task"
    return context
