from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .allocation import recommend_allocation
from .config import load_profile
from .score_results import build_score_result
from .storage import connect


MODULES = ("listening", "reading", "writing", "speaking")


def build_progress_dashboard(home: Path, *, days: int = 90) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect(home) as conn:
        sessions = conn.execute(
            """
            SELECT * FROM sessions
            WHERE occurred_at>=? AND status='completed'
            ORDER BY occurred_at
            """,
            (cutoff,),
        ).fetchall()
        criteria = conn.execute(
            """
            SELECT s.module,cs.criterion,
                   COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0) value,
                   cs.confidence,cs.created_at,s.payload_json
            FROM criterion_scores cs JOIN sessions s USING(session_id)
            WHERE s.occurred_at>=? AND s.status='completed'
              AND COALESCE(cs.assessment_role,'local_rubric')='local_rubric'
            ORDER BY cs.created_at
            """,
            (cutoff,),
        ).fetchall()
        reading = conn.execute(
            """
            SELECT ra.question_type,COUNT(*) attempts,
                   SUM(CASE WHEN ra.is_correct=1 THEN 1 ELSE 0 END) correct,
                   AVG(ra.duration_seconds) avg_seconds
            FROM reading_answers ra JOIN sessions s USING(session_id)
            WHERE s.occurred_at>=? AND ra.is_correct IS NOT NULL
            GROUP BY ra.question_type ORDER BY attempts DESC,ra.question_type
            """,
            (cutoff,),
        ).fetchall()
        errors = conn.execute(
            """
            SELECT e.tag,e.status,SUM(e.count) count,COUNT(DISTINCT e.session_id) sessions,
                   MAX(s.occurred_at) last_seen
            FROM errors e JOIN sessions s USING(session_id)
            WHERE s.occurred_at>=?
            GROUP BY e.tag,e.status ORDER BY count DESC,e.tag
            """,
            (cutoff,),
        ).fetchall()

    module_data: dict[str, dict[str, Any]] = {
        module: {
            "completed_sessions": 0,
            "eligible_samples": 0,
            "observation_samples": 0,
            "trend": [],
            "average_band": None,
            "target": None,
            "gap": None,
        }
        for module in MODULES
    }
    profile = load_profile(home)
    eligible_values: dict[str, list[float]] = defaultdict(list)
    listening_scenes: Counter[str] = Counter()
    for row in sessions:
        payload = json.loads(row["payload_json"])
        module = str(row["module"])
        module_data[module]["completed_sessions"] += 1
        score = build_score_result(payload)
        if score["band"] is not None:
            sample = {
                "session_id": row["session_id"],
                "occurred_at": row["occurred_at"],
                "band": float(score["band"]),
                "eligible": bool(score["eligible_for_progress"]),
                "score_kind": score["score_kind"],
                "confidence": score["confidence"],
            }
            module_data[module]["trend"].append(sample)
            if sample["eligible"]:
                eligible_values[module].append(sample["band"])
                module_data[module]["eligible_samples"] += 1
            else:
                module_data[module]["observation_samples"] += 1
        if module == "listening":
            for attempt in payload.get("questions") or []:
                if attempt.get("category"):
                    listening_scenes[str(attempt["category"])] += 1

    for module in MODULES:
        values = eligible_values[module]
        average = round(mean(values), 2) if values else None
        target = (profile.get("target") or {}).get(module)
        module_data[module]["average_band"] = average
        module_data[module]["target"] = target
        module_data[module]["gap"] = (
            round(max(0.0, float(target) - average), 2)
            if target is not None and average is not None
            else None
        )

    criteria_groups: dict[str, dict[str, list[float]]] = {
        "writing": defaultdict(list),
        "speaking": defaultdict(list),
    }
    criterion_eligible: dict[tuple[str, str], int] = Counter()
    for item in criteria:
        if item["module"] in criteria_groups and item["value"] is not None:
            criteria_groups[item["module"]][str(item["criterion"])].append(
                float(item["value"])
            )
            if build_score_result(item)["eligible_for_progress"]:
                criterion_eligible[(item["module"], str(item["criterion"]))] += 1
    criterion_result = {
        module: [
            {
                "criterion": criterion,
                "average": round(mean(values), 2),
                "samples": len(values),
                "first": values[0],
                "latest": values[-1],
                "eligible_samples": criterion_eligible[(module, criterion)],
                "evidence_class": (
                    "progress_eligible"
                    if criterion_eligible[(module, criterion)]
                    else "training_observation"
                ),
            }
            for criterion, values in groups.items()
        ]
        for module, groups in criteria_groups.items()
    }

    listening_errors: Counter[str] = Counter()
    for item in errors:
        tag = str(item["tag"])
        if tag.startswith("listening_"):
            listening_errors[tag.removeprefix("listening_")] += int(item["count"])
    allocation = recommend_allocation(home, persist=False)
    return {
        "dashboard_version": 1,
        "window_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "modules": module_data,
        "criteria": criterion_result,
        "reading_question_types": [
            {
                "question_type": row["question_type"],
                "attempts": int(row["attempts"]),
                "correct": int(row["correct"] or 0),
                "accuracy": round((row["correct"] or 0) / row["attempts"], 3),
                "average_seconds": (
                    round(float(row["avg_seconds"]), 1)
                    if row["avg_seconds"] is not None
                    else None
                ),
            }
            for row in reading
        ],
        "listening": {
            "scenes": [
                {"scene": key, "attempts": value}
                for key, value in listening_scenes.most_common()
            ],
            "error_types": [
                {"type": key, "count": value}
                for key, value in listening_errors.most_common()
            ],
        },
        "errors": {
            "counts": dict(
                Counter(
                    {
                        state: sum(
                            int(row["count"])
                            for row in errors
                            if row["status"] == state
                        )
                        for state in ("active", "monitoring", "resolved")
                    }
                )
            ),
            "items": [dict(row) for row in errors],
        },
        "weekly": {
            "allocation": allocation.allocation,
            "reasons": allocation.reasons,
        },
    }
