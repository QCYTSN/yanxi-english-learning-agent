from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from .pedagogy import is_teaching_transition_allowed
from .storage import connect, initialise_database


EVALUATOR_VERSION = 1
QUALITY_DIMENSIONS = frozenset(
    {
        "instructional_fit",
        "answer_integrity",
        "evidence_grounding",
        "active_learning",
        "memory_continuity",
        "pedagogy_control",
        "recovery",
    }
)


def run_teaching_quality_evaluation(
    home: Path,
    case_source: Path | None = None,
    *,
    suite_name: str = "teaching-quality-regression",
) -> dict[str, Any]:
    """Run deterministic teaching-policy cases and retain hashes/outcomes only."""
    source_label, cases = _load_cases(case_source)
    if not cases:
        raise ValueError("Teaching-quality evaluation suite contains no cases")
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    dimensions_seen: dict[str, set[bool]] = defaultdict(set)
    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        dimension = str(case.get("dimension") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError("Teaching-quality cases require unique case_id values")
        if dimension not in QUALITY_DIMENSIONS:
            raise ValueError(f"Unsupported teaching-quality dimension: {dimension}")
        if not isinstance(case.get("expected_pass"), bool):
            raise ValueError(f"Teaching-quality case {case_id} requires expected_pass")
        seen.add(case_id)
        expected = bool(case["expected_pass"])
        dimensions_seen[dimension].add(expected)
        evaluation = evaluate_teaching_observation(case)
        case_hash = _json_hash(case)
        results.append(
            {
                "case_id": case_id,
                "case_hash": case_hash,
                "dimension": dimension,
                "expected_pass": expected,
                "actual_pass": evaluation["acceptable"],
                "passed": evaluation["acceptable"] is expected,
                "rule_outcomes": [
                    {"code": item["code"], "passed": item["passed"]}
                    for item in evaluation["checks"]
                ],
            }
        )
    missing_dimensions = QUALITY_DIMENSIONS - set(dimensions_seen)
    if missing_dimensions:
        raise ValueError(
            "Teaching-quality suite is missing dimensions: "
            + ", ".join(sorted(missing_dimensions))
        )
    incomplete = [
        dimension
        for dimension, expected_values in dimensions_seen.items()
        if expected_values != {True, False}
    ]
    if incomplete:
        raise ValueError(
            "Teaching-quality dimensions need positive and negative controls: "
            + ", ".join(sorted(incomplete))
        )
    passed_count = sum(1 for item in results if item["passed"])
    dimension_scores = {}
    for dimension in sorted(QUALITY_DIMENSIONS):
        scoped = [item for item in results if item["dimension"] == dimension]
        matched = sum(1 for item in scoped if item["passed"])
        dimension_scores[dimension] = {
            "case_count": len(scoped),
            "passed_count": matched,
            "score": round(matched / len(scoped), 4),
        }
    completed_at = _now()
    status = "passed" if passed_count == len(results) else "failed"
    score = round(passed_count / len(results), 4)
    report_body = {
        "suite_name": suite_name,
        "source_label": source_label,
        "evaluator_version": EVALUATOR_VERSION,
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "status": status,
        "score": score,
        "dimension_scores": dimension_scores,
        "cases": results,
    }
    report_hash = _json_hash(report_body)
    evaluation_id = f"teaching-evaluation-{uuid.uuid4().hex}"
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO teaching_quality_evaluation_runs(
              evaluation_id,suite_name,source_label,evaluator_version,case_count,
              passed_count,failed_count,status,score,dimension_scores_json,
              report_hash,report_json,created_at,completed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                evaluation_id,
                suite_name,
                source_label,
                EVALUATOR_VERSION,
                len(results),
                passed_count,
                len(results) - passed_count,
                status,
                score,
                json.dumps(dimension_scores, ensure_ascii=False, separators=(",", ":")),
                report_hash,
                json.dumps(report_body, ensure_ascii=False, separators=(",", ":")),
                completed_at,
                completed_at,
            ),
        )
    return {
        "evaluation_id": evaluation_id,
        **report_body,
        "report_hash": report_hash,
        "created_at": completed_at,
        "completed_at": completed_at,
        "content_retention": "case_hashes_rule_outcomes_and_scores_only",
    }


def evaluate_teaching_observation(case: dict[str, Any]) -> dict[str, Any]:
    dimension = str(case.get("dimension") or "")
    context = dict(case.get("context") or {})
    response = dict(case.get("response") or {})
    trace = dict(case.get("trace") or {})
    checks: list[dict[str, Any]] = []

    def check(code: str, condition: Any) -> None:
        checks.append({"code": code, "passed": bool(condition)})

    if dimension == "instructional_fit":
        allowed_moves = {str(item) for item in context.get("allowed_moves") or []}
        move = str(response.get("teaching_move") or "")
        check("teaching_move_allowed", bool(move) and move in allowed_moves)
        check("next_action_present", bool(str(response.get("next_action") or "").strip()))
        requested_depth = str(context.get("requested_depth") or "")
        check(
            "response_depth_matched",
            not requested_depth or str(response.get("response_depth") or "") == requested_depth,
        )
    elif dimension == "answer_integrity":
        policy = str(context.get("answer_policy") or "not_applicable")
        answer_status = str(response.get("answer_status") or "not_applicable")
        request_kind = str(response.get("request_kind") or "teacher_dialogue")
        check(
            "protected_answer_not_verified",
            policy not in {"progressive_hint", "locked"} or answer_status != "verified",
        )
        check(
            "mock_explanation_locked",
            policy != "locked"
            or request_kind not in {"question_explanation", "close_reading"},
        )
        check(
            "unkeyed_answer_unverified",
            bool(context.get("authoritative_key_available", True))
            or answer_status != "verified",
        )
    elif dimension == "evidence_grounding":
        evidence = response.get("evidence") or []
        sufficient = str(response.get("evidence_status") or "") == "sufficient"
        check("sufficient_claim_has_evidence", not sufficient or bool(evidence))
        check(
            "evidence_has_claim_and_source",
            all(
                isinstance(item, dict)
                and bool(str(item.get("claim") or "").strip())
                and bool(str(item.get("source") or "").strip())
                for item in evidence
            ),
        )
        check(
            "required_quotes_present",
            not bool(context.get("quote_required"))
            or (
                bool(evidence)
                and all(bool(str(item.get("quote") or "").strip()) for item in evidence)
            ),
        )
    elif dimension == "active_learning":
        revision_count = int(context.get("learner_revision_count") or 0)
        model_alternative = bool(trace.get("model_alternative_shown"))
        stages = [str(item) for item in trace.get("stages") or []]
        check(
            "model_alternative_after_revision",
            not model_alternative or revision_count >= 2,
        )
        if model_alternative:
            required = ["evidence", "priorities", "learner_revision", "model_alternative"]
            positions = [stages.index(item) if item in stages else -1 for item in required]
            check(
                "writing_feedback_order",
                all(position >= 0 for position in positions) and positions == sorted(positions),
            )
        else:
            check("writing_feedback_order", True)
        check("learner_action_present", bool(str(response.get("next_action") or "").strip()))
    elif dimension == "memory_continuity":
        required = {str(item) for item in context.get("required_memory_ids") or []}
        loaded = {str(item) for item in trace.get("loaded_memory_ids") or []}
        used = {str(item) for item in trace.get("used_memory_ids") or []}
        excluded = {
            str(item)
            for item in (trace.get("expired_memory_ids") or [])
            + (trace.get("conflicted_memory_ids") or [])
        }
        check("required_memory_loaded", required <= loaded)
        check("only_loaded_memory_used", used <= loaded)
        check("invalid_memory_not_used", not bool(used & excluded))
    elif dimension == "pedagogy_control":
        from_phase = str(trace.get("from_phase") or "")
        to_phase = str(trace.get("to_phase") or "")
        mutation_actor = str(trace.get("mutation_actor") or "")
        check(
            "phase_transition_allowed",
            from_phase == to_phase or is_teaching_transition_allowed(from_phase, to_phase),
        )
        check("runtime_or_learner_owns_mutation", mutation_actor in {"runtime", "learner"})
        check(
            "learner_transition_confirmed",
            mutation_actor != "learner" or bool(trace.get("confirmed")),
        )
        check("revision_checked", bool(trace.get("expected_revision_matches")))
    elif dimension == "recovery":
        check("raw_content_not_retained", not bool(trace.get("raw_content_retained")))
        check("learner_error_redacted", bool(trace.get("error_message_redacted")))
        check(
            "bounded_retry",
            0 <= int(trace.get("attempt_count") or 0) <= int(context.get("max_attempts") or 3),
        )
        check(
            "recovery_action_available",
            str(trace.get("learner_action") or "")
            in {"retry", "reconnect", "change_provider", "manual_handoff"},
        )
    else:
        raise ValueError(f"Unsupported teaching-quality dimension: {dimension}")
    return {"acceptable": bool(checks) and all(item["passed"] for item in checks), "checks": checks}


def list_teaching_quality_evaluations(
    home: Path,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM teaching_quality_evaluation_runs
            ORDER BY created_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [
        {
            "evaluation_id": row["evaluation_id"],
            "suite_name": row["suite_name"],
            "source_label": row["source_label"],
            "evaluator_version": int(row["evaluator_version"]),
            "case_count": int(row["case_count"]),
            "passed_count": int(row["passed_count"]),
            "failed_count": int(row["failed_count"]),
            "status": row["status"],
            "score": float(row["score"]),
            "dimension_scores": json.loads(row["dimension_scores_json"] or "{}"),
            "report_hash": row["report_hash"],
            "report": json.loads(row["report_json"] or "{}"),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "content_retention": "case_hashes_rule_outcomes_and_scores_only",
        }
        for row in rows
    ]


def _load_cases(case_source: Path | None) -> tuple[str, list[dict[str, Any]]]:
    if case_source is None:
        resource = files("ielts_coach.resources").joinpath(
            "evaluations", "teaching-quality.json"
        )
        raw = resource.read_text(encoding="utf-8")
        label = "built-in-teaching-quality"
    else:
        source = Path(case_source).resolve()
        if source.is_dir():
            paths = sorted(source.glob("*.json"))
            if not paths:
                raise ValueError(f"No teaching-quality JSON cases found in {source}")
            cases = []
            for path in paths:
                value = json.loads(path.read_text(encoding="utf-8"))
                cases.extend(value.get("cases", []) if isinstance(value, dict) else [value])
            return source.name, cases
        if not source.is_file():
            raise ValueError(f"Teaching-quality case source does not exist: {source}")
        raw = source.read_text(encoding="utf-8")
        label = source.name
    value = json.loads(raw)
    if isinstance(value, dict):
        value = value.get("cases")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Teaching-quality case source must contain a cases array")
    return label, value


def _json_hash(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
