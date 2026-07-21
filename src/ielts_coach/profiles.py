from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .storage import connect


def build_learning_profile(home: Path) -> str:
    with connect(home) as conn:
        sessions = conn.execute(
            "SELECT module,occurred_at,band,duration_minutes FROM sessions WHERE status='completed' ORDER BY occurred_at"
        ).fetchall()
        errors = conn.execute(
            """
            SELECT tag,SUM(count) total,MAX(s.occurred_at) last_seen
            FROM errors e JOIN sessions s USING(session_id)
            WHERE e.status<>'resolved' GROUP BY tag ORDER BY total DESC
            """
        ).fetchall()
        criteria = conn.execute(
            """
            SELECT s.module,cs.criterion,
                   AVG(COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0)) avg_score,
                   COUNT(*) samples
            FROM criterion_scores cs JOIN sessions s ON s.session_id=cs.session_id
            GROUP BY s.module,cs.criterion ORDER BY s.module,cs.criterion
            """
        ).fetchall()
        reading = conn.execute(
            "SELECT question_type,COUNT(*) total,SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) correct,AVG(duration_seconds) avg_seconds FROM reading_answers GROUP BY question_type ORDER BY total DESC"
        ).fetchall()

    lines = ["# IELTS 学习画像", "", "## 1. 错误画像"]
    if errors:
        for row in errors[:12]:
            lines.append(f"- {row['tag']}: {row['total']} 次；最近出现 {row['last_seen']}")
    else:
        lines.append("暂无稳定错误数据。")

    lines.extend(["", "## 2. 能力画像"])
    by_module: dict[str, list[float]] = defaultdict(list)
    for row in sessions:
        if row["band"] is not None:
            by_module[row["module"]].append(float(row["band"]))
    for module in ("listening", "reading", "writing", "speaking"):
        values = by_module[module]
        lines.append(
            f"- {module.title()}: {mean(values):.2f}（{len(values)} 个有分数样本）"
            if values
            else f"- {module.title()}: 暂无可用分数"
        )
    if criteria:
        lines.append("- 分项评分：")
        for row in criteria:
            lines.append(f"  - {row['module'].title()} {row['criterion']}: {row['avg_score']:.2f}（{row['samples']}）")
    if reading:
        lines.append("- 阅读题型正确率：")
        for row in reading:
            accuracy = (row["correct"] or 0) / row["total"] * 100
            time_text = "n/a" if row["avg_seconds"] is None else f"{row['avg_seconds']:.0f}s"
            lines.append(f"  - {row['question_type']}: {accuracy:.0f}%（{row['total']}题，平均 {time_text}）")

    lines.extend(["", "## 3. 行为画像"])
    if not sessions:
        lines.append("暂无训练行为数据。")
        return "\n".join(lines) + "\n"
    active_days = len({str(row["occurred_at"])[:10] for row in sessions})
    durations = [float(row["duration_minutes"]) for row in sessions if row["duration_minutes"] is not None]
    last_time = max(str(row["occurred_at"]) for row in sessions)
    lines.append(f"- 完成训练：{len(sessions)} 次")
    lines.append(f"- 活跃日期：{active_days} 天")
    lines.append(f"- 平均训练时长：{mean(durations):.1f} 分钟" if durations else "- 平均训练时长：暂无数据")
    lines.append(f"- 最近训练：{last_time}")
    module_counts: dict[str, int] = defaultdict(int)
    for row in sessions:
        module_counts[row["module"]] += 1
    lines.append("- 科目分布：" + "，".join(f"{m} {module_counts[m]}" for m in module_counts))
    return "\n".join(lines) + "\n"
