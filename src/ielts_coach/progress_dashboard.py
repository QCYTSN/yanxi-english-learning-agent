from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .allocation import recommend_allocation
from .config import load_profile
from .diagnostics import diagnostic_status
from .score_results import build_score_result
from .storage import connect, initialise_database


MODULES = ("listening", "reading", "writing", "speaking")
MODULE_LABELS = {
    "listening": "听力",
    "reading": "阅读",
    "writing": "写作",
    "speaking": "口语",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_payload(row: Any) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    payload.update(
        {
            "session_id": row["session_id"],
            "module": row["module"],
            "status": row["status"],
            "occurred_at": row["occurred_at"],
            "band": row["band"],
            "score_kind": row["score_kind"],
            "score_confidence": row["score_confidence"],
            "practice_mode": row["practice_mode"],
            "conformance_status": row["conformance_status"],
            "answer_key_source": row["answer_key_source"],
            "band_conversion_source": row["band_conversion_source"],
        }
    )
    return payload


def _trend_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [float(item["band"]) for item in samples if item["eligible"]]
    if len(eligible) < 2:
        return {
            "direction": "insufficient",
            "delta": None,
            "early_average": eligible[0] if eligible else None,
            "recent_average": None,
            "sample_count": len(eligible),
        }
    split = max(1, len(eligible) // 2)
    early = mean(eligible[:split])
    recent = mean(eligible[split:])
    delta = recent - early
    direction = "improving" if delta >= 0.15 else "declining" if delta <= -0.15 else "stable"
    return {
        "direction": direction,
        "delta": round(delta, 2),
        "early_average": round(early, 2),
        "recent_average": round(recent, 2),
        "sample_count": len(eligible),
    }


def _trend_buckets(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for sample in samples:
        occurred = datetime.fromisoformat(str(sample["occurred_at"]).replace("Z", "+00:00"))
        iso_year, iso_week, _ = occurred.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        bucket = grouped.setdefault(
            key,
            {
                "period": key,
                "period_start": (
                    occurred - timedelta(days=occurred.weekday())
                ).date().isoformat(),
                "eligible_values": [],
                "observation_samples": 0,
            },
        )
        if sample["eligible"]:
            bucket["eligible_values"].append(float(sample["band"]))
        else:
            bucket["observation_samples"] += 1
    result: list[dict[str, Any]] = []
    for bucket in grouped.values():
        values = bucket.pop("eligible_values")
        result.append(
            {
                **bucket,
                "average_band": round(mean(values), 2) if values else None,
                "eligible_samples": len(values),
            }
        )
    return result


def _session_rows(
    home: Path,
    *,
    start: datetime,
    end: datetime | None = None,
) -> list[Any]:
    clauses = ["occurred_at>=?", "status='completed'"]
    params: list[Any] = [start.isoformat()]
    if end is not None:
        clauses.append("occurred_at<?")
        params.append(end.isoformat())
    with connect(home) as conn:
        return conn.execute(
            f"SELECT * FROM sessions WHERE {' AND '.join(clauses)} ORDER BY occurred_at",
            params,
        ).fetchall()


def _eligible_averages(rows: Iterable[Any]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        score = build_score_result(_parse_payload(row))
        if score["eligible_for_progress"] and score["band"] is not None:
            grouped[str(row["module"])].append(float(score["band"]))
    return {module: round(mean(values), 2) for module, values in grouped.items()}


def build_progress_dashboard(home: Path, *, days: int = 90) -> dict[str, Any]:
    initialise_database(home)
    cutoff = _now() - timedelta(days=days)
    sessions = _session_rows(home, start=cutoff)
    with connect(home) as conn:
        criteria = conn.execute(
            """
            SELECT s.module,s.session_id,s.status,s.occurred_at,s.band,s.score_kind,
                   s.score_confidence,s.practice_mode,s.conformance_status,
                   s.answer_key_source,s.band_conversion_source,s.payload_json,
                   cs.criterion,
                   COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0) value,
                   cs.confidence,cs.created_at
            FROM criterion_scores cs JOIN sessions s USING(session_id)
            WHERE s.occurred_at>=? AND s.status='completed'
              AND COALESCE(cs.assessment_role,'local_rubric')='local_rubric'
            ORDER BY cs.created_at
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        reading = conn.execute(
            """
            SELECT ra.question_type,COUNT(*) attempts,
                   SUM(CASE WHEN ra.is_correct=1 THEN 1 ELSE 0 END) correct,
                   AVG(ra.duration_seconds) avg_seconds
            FROM reading_answers ra JOIN sessions s USING(session_id)
            WHERE s.occurred_at>=? AND s.status='completed' AND ra.is_correct IS NOT NULL
            GROUP BY ra.question_type ORDER BY attempts DESC,ra.question_type
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        errors = conn.execute(
            """
            SELECT s.module,e.tag,e.status,SUM(e.count) count,
                   COUNT(DISTINCT e.session_id) sessions,MAX(s.occurred_at) last_seen
            FROM errors e JOIN sessions s USING(session_id)
            WHERE s.occurred_at>=?
            GROUP BY s.module,e.tag,e.status
            ORDER BY CASE e.status WHEN 'active' THEN 0 WHEN 'monitoring' THEN 1 ELSE 2 END,
                     count DESC,e.tag
            """,
            (cutoff.isoformat(),),
        ).fetchall()

    module_data: dict[str, dict[str, Any]] = {
        module: {
            "completed_sessions": 0,
            "eligible_samples": 0,
            "observation_samples": 0,
            "trend": [],
            "trend_buckets": [],
            "trend_summary": {},
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
        payload = _parse_payload(row)
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
        module_data[module]["trend_summary"] = _trend_summary(module_data[module]["trend"])
        module_data[module]["trend_buckets"] = _trend_buckets(module_data[module]["trend"])

    criteria_groups: dict[str, dict[str, list[float]]] = {
        "writing": defaultdict(list),
        "speaking": defaultdict(list),
    }
    criterion_eligible: dict[tuple[str, str], int] = Counter()
    for item in criteria:
        module = str(item["module"])
        criterion = str(item["criterion"])
        if module in criteria_groups and item["value"] is not None:
            criteria_groups[module][criterion].append(float(item["value"]))
            if build_score_result(_parse_payload(item))["eligible_for_progress"]:
                criterion_eligible[(module, criterion)] += 1
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
    dashboard = {
        "dashboard_version": 2,
        "window_days": days,
        "generated_at": _now().isoformat(),
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
            "counts": {
                state: sum(
                    int(row["count"]) for row in errors if row["status"] == state
                )
                for state in ("active", "monitoring", "resolved")
            },
            "items": [dict(row) for row in errors],
        },
        "weekly": {
            "allocation": allocation.allocation,
            "reasons": allocation.reasons,
        },
    }
    dashboard["next_actions"] = build_next_actions(home, dashboard=dashboard)
    return dashboard


def build_next_actions(
    home: Path, *, dashboard: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    if dashboard is None:
        dashboard = build_progress_dashboard(home)
    from .learning_orchestration import list_review_tasks

    actions: list[dict[str, Any]] = []
    for task in list_review_tasks(home, limit=2):
        actions.append(
            {
                "action_id": f"review:{task['review_task_id']}",
                "action_kind": "review",
                "module": task["module"],
                "title": task["title"],
                "reason": task["action"],
                "priority": 100 if task["priority"] >= 80 else 90,
                "estimated_minutes": 20,
                "route": task["route"],
                "review_task_id": task["review_task_id"],
            }
        )
    diagnostic = diagnostic_status(home)
    if diagnostic.get("status") in {"not_started", "cancelled"}:
        actions.append(
            {
                "action_id": "diagnostic:quick",
                "action_kind": "diagnostic",
                "module": None,
                "title": "完成一次 Quick Diagnostic",
                "reason": "当前四科基线尚未建立；先补真实证据，再判断趋势。",
                "priority": 95,
                "estimated_minutes": 90,
                "route": "/diagnostic",
            }
        )
    allocation = dashboard["weekly"]["allocation"]
    ranked = sorted(
        MODULES,
        key=lambda module: (
            dashboard["modules"][module]["gap"] or 0,
            allocation.get(module, 0),
        ),
        reverse=True,
    )
    for module in ranked:
        item = dashboard["modules"][module]
        evidence_needed = item["eligible_samples"] < 2
        title = (
            f"为{MODULE_LABELS[module]}补一份可信样本"
            if evidence_needed
            else f"推进{MODULE_LABELS[module]}当前最大差距"
        )
        reason = (
            "可信样本不足，训练观察不会直接进入正式趋势。"
            if evidence_needed
            else f"当前距目标仍有 {item['gap']:.2f} Band。"
            if item["gap"] is not None
            else dashboard["weekly"]["reasons"][0]
            if dashboard["weekly"]["reasons"]
            else "根据当前 70/30 训练分配选择。"
        )
        actions.append(
            {
                "action_id": f"practice:{module}",
                "action_kind": "practice",
                "module": module,
                "title": title,
                "reason": reason,
                "priority": 85 if evidence_needed else 75,
                "estimated_minutes": 60 if module in {"reading", "writing"} else 30,
                "route": f"/practice?module={module}",
                "practice_mode": "section_practice",
            }
        )
        break
    actions.sort(key=lambda item: (-int(item["priority"]), str(item["action_id"])))
    return actions[:4]


def build_structured_weekly_report(
    home: Path,
    *,
    ending_at: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    initialise_database(home)
    end = (ending_at or _now()).astimezone(timezone.utc)
    start = end - timedelta(days=7)
    previous_start = start - timedelta(days=7)
    current_rows = _session_rows(home, start=start, end=end)
    previous_rows = _session_rows(home, start=previous_start, end=start)
    current_average = _eligible_averages(current_rows)
    previous_average = _eligible_averages(previous_rows)
    dashboard = build_progress_dashboard(home, days=7)
    with connect(home) as conn:
        completed_units = conn.execute(
            """
            SELECT COUNT(*) count,COALESCE(SUM(estimated_minutes),0) minutes
            FROM practice_units WHERE completed_at>=? AND completed_at<?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        completed_reviews = conn.execute(
            """
            SELECT COUNT(*) count FROM review_tasks
            WHERE completed_at>=? AND completed_at<?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        review_backlog = conn.execute(
            "SELECT COUNT(*) count FROM review_tasks WHERE status IN ('pending','in_progress')"
        ).fetchone()
    module_summaries: dict[str, dict[str, Any]] = {}
    for module in MODULES:
        item = dashboard["modules"][module]
        change = (
            round(current_average[module] - previous_average[module], 2)
            if module in current_average and module in previous_average
            else None
        )
        module_summaries[module] = {
            "completed_sessions": item["completed_sessions"],
            "eligible_samples": item["eligible_samples"],
            "observation_samples": item["observation_samples"],
            "average_band": current_average.get(module),
            "previous_average_band": previous_average.get(module),
            "change": change,
            "target": item["target"],
            "gap": item["gap"],
        }
    wins: list[str] = []
    for module, item in module_summaries.items():
        if item["change"] is not None and item["change"] >= 0.15:
            wins.append(
                f"{MODULE_LABELS[module]}可信样本较上一周期提升 {item['change']:+.2f} Band。"
            )
    if int(completed_reviews["count"]):
        wins.append(f"完成 {int(completed_reviews['count'])} 项到期复习。")
    if int(completed_units["count"]):
        wins.append(f"完成 {int(completed_units['count'])} 个正式学习单元。")
    risks: list[str] = []
    for module, item in module_summaries.items():
        if item["completed_sessions"] and not item["eligible_samples"]:
            risks.append(
                f"{MODULE_LABELS[module]}本周只有训练观察，尚无可进入正式趋势的样本。"
            )
        if item["change"] is not None and item["change"] <= -0.15:
            risks.append(
                f"{MODULE_LABELS[module]}可信样本较上一周期下降 {item['change']:.2f} Band。"
            )
    if int(review_backlog["count"]):
        risks.append(f"仍有 {int(review_backlog['count'])} 项待复习任务。")
    iso_year, iso_week, _ = end.isocalendar()
    report: dict[str, Any] = {
        "report_version": 1,
        "report_id": f"WR-{iso_year}-W{iso_week:02d}",
        "period_key": f"{iso_year}-W{iso_week:02d}",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "generated_at": _now().isoformat(),
        "source_counts": {
            "completed_sessions": len(current_rows),
            "completed_practice_units": int(completed_units["count"]),
            "estimated_minutes": int(completed_units["minutes"]),
            "completed_reviews": int(completed_reviews["count"]),
            "review_backlog": int(review_backlog["count"]),
        },
        "modules": module_summaries,
        "wins": wins,
        "risks": risks,
        "allocation": dashboard["weekly"],
        "next_actions": dashboard["next_actions"],
    }
    report["markdown"] = _weekly_markdown(report)
    source_value = {key: value for key, value in report.items() if key not in {"generated_at", "markdown"}}
    report["source_hash"] = hashlib.sha256(
        json.dumps(source_value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if persist:
        with connect(home) as conn:
            conn.execute(
                """
                INSERT INTO weekly_reports(
                  report_id,period_key,period_start,period_end,source_hash,payload_json,
                  markdown,generated_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(period_key) DO UPDATE SET
                  period_start=excluded.period_start,period_end=excluded.period_end,
                  source_hash=excluded.source_hash,payload_json=excluded.payload_json,
                  markdown=excluded.markdown,generated_at=excluded.generated_at,
                  updated_at=excluded.updated_at
                """,
                (
                    report["report_id"],
                    report["period_key"],
                    report["period_start"],
                    report["period_end"],
                    report["source_hash"],
                    json.dumps(report, ensure_ascii=False),
                    report["markdown"],
                    report["generated_at"],
                    report["generated_at"],
                ),
            )
    return report


def _weekly_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# IELTS 周报 {report['period_key']}",
        "",
        f"- 完成 Session：{report['source_counts']['completed_sessions']}",
        f"- 完成学习单元：{report['source_counts']['completed_practice_units']}",
        f"- 完成复习：{report['source_counts']['completed_reviews']}",
        "",
        "## 四科证据",
    ]
    for module, item in report["modules"].items():
        average = (
            f"{item['average_band']:.2f}"
            if item["average_band"] is not None
            else "无可信分数"
        )
        lines.append(
            f"- {MODULE_LABELS[module]}：{item['completed_sessions']} 次，"
            f"可信样本 {item['eligible_samples']}，平均 {average}"
        )
    lines.extend(["", "## 本周进展"])
    lines.extend(f"- {item}" for item in report["wins"]) if report["wins"] else lines.append("- 暂无足够证据判断提升。")
    lines.extend(["", "## 风险与缺口"])
    lines.extend(f"- {item}" for item in report["risks"]) if report["risks"] else lines.append("- 暂无新增风险。")
    lines.extend(["", "## 下一步"])
    lines.extend(f"- {item['title']}：{item['reason']}" for item in report["next_actions"])
    return "\n".join(lines) + "\n"


def list_weekly_reports(home: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM weekly_reports
            ORDER BY period_start DESC LIMIT ?
            """,
            (max(1, min(int(limit), 104)),),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
