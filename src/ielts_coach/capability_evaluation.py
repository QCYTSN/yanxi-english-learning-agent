from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agent_contracts import (
    CONTRACT_SCHEMAS,
    AgentContractValidationError,
    validate_agent_contract,
)
from .storage import connect, initialise_database


SUCCESSFUL_RUN_STATUSES = {"persisted", "test_passed"}


def run_contract_evaluation(
    home: Path,
    case_directory: Path,
    *,
    suite_name: str = "agent-contract-regression",
) -> dict[str, Any]:
    """Run local positive/negative contract cases without retaining their content."""
    case_directory = case_directory.resolve()
    if not case_directory.is_dir():
        raise ValueError(f"Evaluation case directory does not exist: {case_directory}")

    cases: list[dict[str, Any]] = []
    for contract in sorted(CONTRACT_SCHEMAS):
        stem = contract.partition("@")[0]
        for expected_valid in (True, False):
            suffix = "valid" if expected_valid else "invalid"
            path = case_directory / f"{stem}.{suffix}.json"
            if not path.is_file():
                raise ValueError(f"Missing evaluation case: {path.name}")
            raw = path.read_bytes()
            case_hash = hashlib.sha256(raw).hexdigest()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Unreadable evaluation case: {path.name}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Evaluation case must contain a JSON object: {path.name}")

            actual_valid = True
            failure_stage: str | None = None
            error_code: str | None = None
            try:
                validate_agent_contract(contract, payload)
            except AgentContractValidationError as exc:
                actual_valid = False
                failure_stage = exc.stage
                error_code = exc.code
            except Exception:
                actual_valid = False
                failure_stage = "domain"
                error_code = "AGENT_OUTPUT_DOMAIN_INVALID"
            cases.append(
                {
                    "contract": contract,
                    "case_kind": suffix,
                    "case_hash": case_hash,
                    "expected_valid": expected_valid,
                    "actual_valid": actual_valid,
                    "passed": actual_valid is expected_valid,
                    "failure_stage": failure_stage,
                    "error_code": error_code,
                }
            )

    completed_at = _now()
    passed_count = sum(1 for item in cases if item["passed"])
    report_body = {
        "suite_name": suite_name,
        "source_label": case_directory.name,
        "case_count": len(cases),
        "passed_count": passed_count,
        "failed_count": len(cases) - passed_count,
        "status": "passed" if passed_count == len(cases) else "failed",
        "contracts": sorted(CONTRACT_SCHEMAS),
        "cases": cases,
    }
    report_hash = _json_hash(report_body)
    result = {
        "evaluation_id": f"evaluation-{uuid.uuid4().hex}",
        **report_body,
        "report_hash": report_hash,
        "created_at": completed_at,
        "completed_at": completed_at,
        "content_retention": "hashes_and_outcomes_only",
    }
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO capability_evaluation_runs(
              evaluation_id,suite_name,source_label,case_count,passed_count,
              failed_count,status,report_hash,report_json,created_at,completed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                result["evaluation_id"],
                suite_name,
                result["source_label"],
                result["case_count"],
                result["passed_count"],
                result["failed_count"],
                result["status"],
                report_hash,
                json.dumps(report_body, ensure_ascii=False, separators=(",", ":")),
                completed_at,
                completed_at,
            ),
        )
    return result


def list_capability_evaluations(home: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    initialise_database(home)
    bounded = max(1, min(int(limit), 100))
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT * FROM capability_evaluation_runs "
            "ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        ).fetchall()
    return [
        {
            "evaluation_id": row["evaluation_id"],
            "suite_name": row["suite_name"],
            "source_label": row["source_label"],
            "case_count": int(row["case_count"]),
            "passed_count": int(row["passed_count"]),
            "failed_count": int(row["failed_count"]),
            "status": row["status"],
            "report_hash": row["report_hash"],
            "report": json.loads(row["report_json"]),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "content_retention": "hashes_and_outcomes_only",
        }
        for row in rows
    ]


def provider_reliability_report(home: Path, *, days: int = 30) -> dict[str, Any]:
    """Summarise metadata-only inference reliability for release decisions."""
    initialise_database(home)
    window_days = max(1, min(int(days), 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    with connect(home) as conn:
        runs = conn.execute(
            """
            SELECT run_id,output_contract,status,error_code,created_at,started_at,completed_at
            FROM agent_runs ORDER BY created_at DESC LIMIT 10000
            """
        ).fetchall()
        attempts = conn.execute(
            """
            SELECT provider_id,provider_kind,model_id,fallback_index,status,
                   failure_stage,error_code,started_at,completed_at
            FROM provider_attempts ORDER BY started_at DESC LIMIT 20000
            """
        ).fetchall()

    current_runs = [row for row in runs if _in_window(row["created_at"], cutoff)]
    current_attempts = [row for row in attempts if _in_window(row["started_at"], cutoff)]
    successful_runs = sum(1 for row in current_runs if row["status"] in SUCCESSFUL_RUN_STATUSES)
    terminal_runs = [
        row for row in current_runs
        if row["completed_at"] is not None or row["status"] in SUCCESSFUL_RUN_STATUSES | {"failed", "cancelled"}
    ]
    latencies = [
        latency
        for row in terminal_runs
        if (latency := _duration_ms(row["started_at"], row["completed_at"])) is not None
    ]

    provider_groups: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for row in current_attempts:
        provider_groups[
            (
                str(row["provider_id"]),
                str(row["provider_kind"] or "unknown"),
                str(row["model_id"] or "unknown"),
            )
        ].append(row)
    providers = []
    for (provider_id, provider_kind, model_id), rows in sorted(provider_groups.items()):
        attempt_latencies = [
            latency
            for row in rows
            if (latency := _duration_ms(row["started_at"], row["completed_at"])) is not None
        ]
        validated = sum(1 for row in rows if row["status"] == "validated")
        providers.append(
            {
                "provider_id": provider_id,
                "provider_kind": provider_kind,
                "model_id": model_id,
                "attempts": len(rows),
                "validated": validated,
                "validation_rate": _ratio(validated, len(rows)),
                "fallback_attempts": sum(1 for row in rows if int(row["fallback_index"] or 0) > 0),
                "failure_stages": _counts(row["failure_stage"] for row in rows),
                "error_codes": _counts(row["error_code"] for row in rows),
                "average_latency_ms": _average(attempt_latencies),
                "p95_latency_ms": _percentile(attempt_latencies, 0.95),
            }
        )

    evaluations = list_capability_evaluations(home, limit=1)
    latest_evaluation = evaluations[0] if evaluations else None
    runtime_sample_status = "sufficient" if len(terminal_runs) >= 20 else "insufficient"
    if latest_evaluation is None:
        release_status = "evaluation_required"
    elif latest_evaluation["status"] != "passed":
        release_status = "blocked"
    elif runtime_sample_status == "insufficient":
        release_status = "contract_ready_runtime_observation_needed"
    elif _ratio(successful_runs, len(terminal_runs)) >= 0.9:
        release_status = "ready"
    else:
        release_status = "runtime_reliability_below_gate"
    return {
        "window_days": window_days,
        "generated_at": _now(),
        "runtime": {
            "runs": len(current_runs),
            "terminal_runs": len(terminal_runs),
            "successful_runs": successful_runs,
            "success_rate": _ratio(successful_runs, len(terminal_runs)),
            "sample_status": runtime_sample_status,
            "average_latency_ms": _average(latencies),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "error_codes": _counts(row["error_code"] for row in terminal_runs),
        },
        "providers": providers,
        "latest_contract_evaluation": (
            {
                "evaluation_id": latest_evaluation["evaluation_id"],
                "status": latest_evaluation["status"],
                "passed_count": latest_evaluation["passed_count"],
                "case_count": latest_evaluation["case_count"],
                "report_hash": latest_evaluation["report_hash"],
                "completed_at": latest_evaluation["completed_at"],
            }
            if latest_evaluation
            else None
        ),
        "release_gate": {
            "status": release_status,
            "contract_suite_required": True,
            "minimum_terminal_runtime_samples": 20,
            "minimum_runtime_success_rate": 0.9,
        },
        "privacy": "metadata_only_no_prompts_or_responses",
    }


def _json_hash(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _in_window(value: Any, cutoff: datetime) -> bool:
    parsed = _parse_time(value)
    return bool(parsed and parsed >= cutoff)


def _duration_ms(started: Any, completed: Any) -> float | None:
    start = _parse_time(started)
    end = _parse_time(completed)
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds() * 1000


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 1)


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            key = str(value)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
