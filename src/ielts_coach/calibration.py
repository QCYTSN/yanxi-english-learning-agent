from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import connect
from .validation import validate_data


def record_calibration(home: Path, data: dict[str, Any]) -> None:
    data = validate_data(data, "calibration-record")
    official = float(data["official_score"])
    predicted = data.get("predicted_score")
    low = data.get("predicted_low")
    high = data.get("predicted_high")
    if predicted is not None:
        error = abs(float(predicted) - official)
    elif low is not None and high is not None:
        midpoint = (float(low) + float(high)) / 2
        error = abs(midpoint - official)
    else:
        raise ValueError("Provide predicted_score or predicted_low/predicted_high")
    tolerance = float(data.get("tolerance", 0.5))
    passed = int(error <= tolerance)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO calibration_results(
              case_id,module,criterion,model,official_score,predicted_low,
              predicted_high,predicted_score,absolute_error,passed,tolerance,notes,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(case_id,model,criterion) DO UPDATE SET
              official_score=excluded.official_score,
              predicted_low=excluded.predicted_low,
              predicted_high=excluded.predicted_high,
              predicted_score=excluded.predicted_score,
              absolute_error=excluded.absolute_error,
              passed=excluded.passed,
              tolerance=excluded.tolerance,
              notes=excluded.notes,
              created_at=excluded.created_at
            """,
            (
                data["case_id"], data["module"], data.get("criterion", "overall"),
                data["model"], official, low, high, predicted, error, passed, tolerance,
                data.get("notes"),
            ),
        )


def calibration_report(home: Path) -> str:
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT model,module,criterion,tolerance,COUNT(*) samples,AVG(absolute_error) mae,
                   AVG(passed)*100 pass_rate
            FROM calibration_results
            GROUP BY model,module,criterion,tolerance
            ORDER BY model,module,criterion,tolerance
            """
        ).fetchall()
    lines = ["# 评分校准报告", ""]
    if not rows:
        lines.append("暂无校准结果。请导入用户合法获得的已评分样例，并记录模型预测。")
    else:
        lines.append("| Model | Module | Criterion | Samples | MAE | Tolerance | Pass rate |")
        lines.append("|---|---|---|---:|---:|---:|---:|")
        for row in rows:
            lines.append(
                f"| {row['model']} | {row['module']} | {row['criterion']} | {row['samples']} | {row['mae']:.2f} | ±{row['tolerance']:.2f} | {row['pass_rate']:.0f}% |"
            )
    return "\n".join(lines) + "\n"
