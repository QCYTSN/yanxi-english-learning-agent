from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .storage import connect
from .validation import validate_data


def import_calibration_case(
    home: Path,
    data: dict[str, Any],
    *,
    base_path: Path | None = None,
) -> dict[str, Any]:
    data = validate_data(data, "calibration-case")
    module = str(data["module"])
    criterion = str(data["criterion"])
    task = data.get("task")
    if module == "writing":
        if task not in {"task1", "task2"}:
            raise ValueError("Writing calibration cases require task1 or task2")
        allowed = (
            {"TA", "CC", "LR", "GRA", "overall"}
            if task == "task1"
            else {"TR", "CC", "LR", "GRA", "overall"}
        )
        if criterion not in allowed:
            raise ValueError(f"Invalid {task} calibration criterion: {criterion}")
    elif criterion not in {"FC", "LR", "GRA", "PRON", "overall"}:
        raise ValueError(f"Invalid Speaking calibration criterion: {criterion}")

    raw_path = Path(str(data["input_path"]))
    path = raw_path if raw_path.is_absolute() else (base_path or Path.cwd()) / raw_path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Calibration input not found: {path}")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    stored = {**data, "input_path": str(path), "content_hash": content_hash}
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO calibration_cases(
              case_id,module,task,criterion,official_score,source_reference,input_path,
              content_hash,permissions_json,payload_json,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET
              module=excluded.module,task=excluded.task,criterion=excluded.criterion,
              official_score=excluded.official_score,source_reference=excluded.source_reference,
              input_path=excluded.input_path,content_hash=excluded.content_hash,
              permissions_json=excluded.permissions_json,payload_json=excluded.payload_json,
              imported_at=excluded.imported_at
            """,
            (
                stored["case_id"],
                stored["module"],
                stored.get("task"),
                stored["criterion"],
                stored["official_score"],
                stored["source_reference"],
                str(path),
                content_hash,
                json.dumps(stored["permissions"], ensure_ascii=False),
                json.dumps(stored, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return stored


def list_calibration_cases(home: Path) -> list[dict[str, Any]]:
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT case_id,module,task,criterion,input_path,content_hash,imported_at "
            "FROM calibration_cases ORDER BY case_id"
        ).fetchall()
    return [dict(row) for row in rows]


def prepare_calibration_run(home: Path, model: str, output: Path) -> dict[str, Any]:
    if not model.strip():
        raise ValueError("Calibration model name is required")
    cases = list_calibration_cases(home)
    if not cases:
        raise ValueError("No calibration cases are registered")
    run = {
        "run_version": 1,
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "blind": True,
        "instructions": (
            "Score each input without looking up its official result. Fill exactly one "
            "of predicted_score or predicted_low/predicted_high."
        ),
        "predictions": [
            {
                "case_id": item["case_id"],
                "module": item["module"],
                "task": item["task"],
                "criterion": item["criterion"],
                "input_path": item["input_path"],
                "content_hash": item["content_hash"],
                "predicted_score": None,
                "predicted_low": None,
                "predicted_high": None,
                "notes": None,
            }
            for item in cases
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(run, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return run


def import_calibration_run(
    home: Path,
    data: dict[str, Any],
    *,
    tolerance: float = 0.5,
) -> int:
    model = str(data.get("model", "")).strip()
    predictions = data.get("predictions")
    if not model or not isinstance(predictions, list):
        raise ValueError("Calibration run requires model and predictions")
    with connect(home) as conn:
        cases = {
            row["case_id"]: row
            for row in conn.execute(
                "SELECT case_id,module,criterion,official_score,content_hash "
                "FROM calibration_cases"
            ).fetchall()
        }
    count = 0
    for prediction in predictions:
        if not isinstance(prediction, dict):
            raise ValueError("Each calibration prediction must be an object")
        case_id = str(prediction.get("case_id", ""))
        case = cases.get(case_id)
        if case is None:
            raise ValueError(f"Unknown calibration case: {case_id}")
        if prediction.get("content_hash") != case["content_hash"]:
            raise ValueError(f"Calibration input changed after case import: {case_id}")
        record_calibration(
            home,
            {
                "case_id": case_id,
                "module": case["module"],
                "criterion": case["criterion"],
                "model": model,
                "official_score": case["official_score"],
                "predicted_score": prediction.get("predicted_score"),
                "predicted_low": prediction.get("predicted_low"),
                "predicted_high": prediction.get("predicted_high"),
                "tolerance": tolerance,
                "notes": prediction.get("notes"),
            },
        )
        count += 1
    return count


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
                data["case_id"],
                data["module"],
                data.get("criterion", "overall"),
                data["model"],
                official,
                low,
                high,
                predicted,
                error,
                passed,
                tolerance,
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
        lines.append(
            "暂无校准结果。请导入用户合法获得的已评分样例，并记录模型盲评结果。"
        )
    else:
        lines.append(
            "| Model | Module | Criterion | Samples | MAE | Tolerance | Pass rate |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|")
        for row in rows:
            lines.append(
                f"| {row['model']} | {row['module']} | {row['criterion']} | "
                f"{row['samples']} | {row['mae']:.2f} | ±{row['tolerance']:.2f} | "
                f"{row['pass_rate']:.0f}% |"
            )
    return "\n".join(lines) + "\n"
