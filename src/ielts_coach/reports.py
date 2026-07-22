from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from .allocation import recommend_allocation
from .config import load_settings
from .profiles import build_learning_profile
from .storage import connect, error_counts_since, sessions_since


def build_summary(home: Path, days: int = 14) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = sessions_since(home, cutoff)
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["module"]] += 1
        score_kind = row["score_kind"] if "score_kind" in row.keys() else None
        confidence = row["score_confidence"] if "score_confidence" in row.keys() else None
        usable_score = (
            score_kind != "partial_profile"
            and (score_kind != "ai_training_estimate" or confidence in (None, "medium", "high"))
        )
        if row["band"] is not None and usable_score:
            grouped[row["module"]].append(float(row["band"]))

    lines = [f"# 最近 {days} 天学习摘要", ""]
    for module in ("listening", "reading", "writing", "speaking"):
        values = grouped[module]
        avg = f"{mean(values):.2f}" if values else "无可用分数"
        lines.append(f"- {module.title()}: {counts[module]} 次，平均 {avg}")

    errors = error_counts_since(home, cutoff)
    lines.extend(["", "## 高频错误"])
    if not errors:
        lines.append("暂无错误标签。")
    else:
        for row in errors[:10]:
            lines.append(f"- {row['tag']}: {row['total']}")

    with connect(home) as conn:
        reading = conn.execute(
            """
            SELECT question_type,
                   SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END) total,
                   SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) correct
            FROM reading_answers ra JOIN sessions s ON s.session_id=ra.session_id
            WHERE s.occurred_at>=?
            GROUP BY question_type
            HAVING SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END) > 0
            ORDER BY total DESC
            """,
            (cutoff,),
        ).fetchall()
    if reading:
        lines.extend(["", "## 阅读题型表现"])
        for row in reading:
            accuracy = (row["correct"] or 0) / row["total"] * 100
            lines.append(f"- {row['question_type']}: {accuracy:.0f}%（{row['total']}题）")
    return "\n".join(lines) + "\n"


def build_weekly_report(home: Path) -> str:
    days = int(load_settings(home).get("weekly_report_days", 7))
    summary = build_summary(home, days)
    result = recommend_allocation(home, persist=True)
    lines = [summary.rstrip(), "", "## 下一周期建议分配"]
    for module, value in result.allocation.items():
        lines.append(f"- {module.title()}: {value * 100:.0f}%")
    lines.extend(["", "## 调整依据"])
    lines.extend(f"- {reason}" for reason in result.reasons)
    return "\n".join(lines) + "\n"


def build_trend_report(home: Path, limit: int = 10) -> str:
    lines = ["# IELTS 趋势报告", "", "## 科目趋势"]
    with connect(home) as conn:
        for module in ("listening", "reading", "writing", "speaking"):
            rows = conn.execute(
                """
                SELECT band,occurred_at FROM sessions
                WHERE module=? AND status='completed' AND band IS NOT NULL
                  AND COALESCE(score_kind,'unspecified') <> 'partial_profile'
                  AND (
                        COALESCE(score_kind,'unspecified') <> 'ai_training_estimate'
                        OR COALESCE(score_confidence,'medium') IN ('medium','high')
                      )
                ORDER BY occurred_at DESC LIMIT ?
                """,
                (module, limit),
            ).fetchall()
            values = [float(row["band"]) for row in reversed(rows)]
            if len(values) >= 2:
                split = max(1, len(values) // 2)
                early, recent = mean(values[:split]), mean(values[split:])
                lines.append(f"- {module.title()}: {early:.2f} → {recent:.2f}（Δ {recent-early:+.2f}，{len(values)}个样本）")
            elif values:
                lines.append(f"- {module.title()}: {values[0]:.2f}（样本不足以判断趋势）")
            else:
                lines.append(f"- {module.title()}: 暂无分数")

        criteria = conn.execute(
            """
            SELECT s.module,cs.criterion,cs.version_label,
                   COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0) value,cs.created_at
            FROM criterion_scores cs JOIN sessions s ON s.session_id=cs.session_id
            WHERE COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0) IS NOT NULL
              AND s.status='completed'
              AND COALESCE(cs.assessment_role,'local_rubric')='local_rubric'
              AND COALESCE(cs.confidence,'medium') IN ('medium','high')
            ORDER BY cs.created_at
            """
        ).fetchall()
        reading = conn.execute(
            """
            SELECT question_type,
                   SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END) total,
                   SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) correct
            FROM reading_answers
            GROUP BY question_type
            HAVING SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END) > 0
            ORDER BY total DESC
            """
        ).fetchall()

    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in criteria:
        grouped[(row["module"], row["criterion"])].append(float(row["value"]))
    lines.extend(["", "## 写作/口语分项"])
    if not grouped:
        lines.append("暂无结构化分项评分。")
    else:
        for (module, criterion), values in grouped.items():
            label = f"{module.title()} {criterion}"
            if len(values) >= 2:
                lines.append(f"- {label}: {values[0]:.2f} → {values[-1]:.2f}（{len(values)}个样本）")
            else:
                lines.append(f"- {label}: {values[0]:.2f}（1个样本）")

    lines.extend(["", "## 阅读题型累计正确率"])
    if not reading:
        lines.append("暂无结构化阅读答题数据。")
    else:
        for row in reading:
            accuracy = (row["correct"] or 0) / row["total"] * 100
            lines.append(f"- {row['question_type']}: {accuracy:.0f}%（{row['total']}题）")
    return "\n".join(lines) + "\n"
