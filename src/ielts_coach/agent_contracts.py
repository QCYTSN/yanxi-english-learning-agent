from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import save_coaching_artifact
from .study_runtime import (
    apply_reading_review,
    apply_writing_review,
    mutate_session,
)
from .validation import validate_data


CONTRACT_SCHEMAS = {
    "writing-review@1": "writing-review",
    "reading-review@1": "reading-review",
    "listening-review@1": "listening-review",
    "speaking-evaluation@1": "speaking-evaluation",
    "study-plan@1": "study-plan",
    "diagnostic-summary@1": "diagnostic-summary",
    "weekly-coaching@1": "weekly-coaching",
}

CONTRACT_SKILLS = {
    "writing-review@1": "ielts-writing",
    "reading-review@1": "ielts-reading",
    "listening-review@1": "ielts-progress",
    "speaking-evaluation@1": "ielts-speaking",
    "study-plan@1": "ielts",
    "diagnostic-summary@1": "ielts",
    "weekly-coaching@1": "ielts-progress",
}


def validate_agent_contract(contract: str, result: dict[str, Any]) -> dict[str, Any]:
    schema = CONTRACT_SCHEMAS.get(contract)
    if not schema:
        name, _, version = contract.partition("@")
        if name in {item.partition("@")[0] for item in CONTRACT_SCHEMAS}:
            raise ValueError(
                f"Unsupported {name} contract version {version or 'missing'}"
            )
        raise ValueError(f"Unknown Agent output contract: {contract}")
    validated = validate_data(result, schema)
    _semantic_validation(contract, validated)
    return validated


def persist_agent_contract(
    home: Path,
    run: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    contract = str(run["output_contract"])
    result = validate_agent_contract(contract, result)
    session_id = run.get("study_session_id")
    common = {
        "expected_revision": run.get("base_revision"),
        "idempotency_key": f"agent:{run['run_id']}",
    }
    if contract == "writing-review@1":
        return apply_writing_review(home, str(session_id), result, **common)
    if contract == "reading-review@1":
        return apply_reading_review(home, str(session_id), result, **common)
    if contract == "listening-review@1":
        return _persist_listening_review(home, str(session_id), result, **common)
    if contract == "speaking-evaluation@1":
        return _persist_speaking_evaluation(home, str(session_id), result, **common)

    artifact = save_coaching_artifact(
        home,
        artifact_id=f"artifact:{run['run_id']}",
        artifact_type=contract.partition("@")[0],
        contract_version=int(contract.partition("@")[2]),
        payload=result,
        study_session_id=session_id,
        agent_run_id=run["run_id"],
    )
    return {
        "artifact_id": artifact["artifact_id"],
        "revision": run.get("base_revision"),
    }


def _persist_listening_review(
    home: Path,
    session_id: str,
    result: dict[str, Any],
    **common: Any,
) -> dict[str, Any]:
    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "listening":
            raise ValueError("Listening review requires a Listening Session")
        data["listening_review"] = result
        data.setdefault("errors", []).extend(
            {
                "tag": tag,
                "count": 1,
                "evidence": str(item.get("explanation") or ""),
                "status": "active",
            }
            for item in result["items"]
            for tag in item.get("error_tags") or []
        )
        data["status"] = "awaiting_revision"

    return mutate_session(
        home,
        session_id,
        "listening_review_applied",
        apply,
        **common,
    )


def _persist_speaking_evaluation(
    home: Path,
    session_id: str,
    result: dict[str, Any],
    **common: Any,
) -> dict[str, Any]:
    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "speaking":
            raise ValueError("Speaking evaluation requires a Speaking Session")
        data["speaking_evaluation"] = result
        data["score_kind"] = result["score_kind"]
        data["score_confidence"] = result["confidence"]
        data["band"] = result.get("band")
        data["rubric"] = result["rubric"]
        data["criterion_scores"] = [
            {
                **item,
                "assessment_role": "local_rubric",
            }
            for item in result["criteria"]
        ]
        data["status"] = "awaiting_revision"

    return mutate_session(
        home,
        session_id,
        "speaking_evaluation_applied",
        apply,
        **common,
    )


def _semantic_validation(contract: str, data: dict[str, Any]) -> None:
    if contract == "listening-review@1":
        numbers = [str(item["question_number"]) for item in data["items"]]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Listening review question numbers must be unique")
    elif contract == "speaking-evaluation@1":
        criteria = [item["criterion"] for item in data["criteria"]]
        if len(criteria) != len(set(criteria)):
            raise ValueError("Speaking criteria must be unique")
        if data.get("band") is not None:
            if set(criteria) != {"FC", "LR", "GRA", "PRON"}:
                raise ValueError(
                    "A Speaking overall band requires all four criteria"
                )
            pron = next(item for item in data["criteria"] if item["criterion"] == "PRON")
            if pron["evidence_source"] not in {
                "audio",
                "voice_model_observation",
                "mixed",
            }:
                raise ValueError(
                    "A Speaking overall band requires audio-based Pronunciation evidence"
                )
    elif contract == "study-plan@1":
        if abs(sum(float(value) for value in data["allocation"].values()) - 1) > 0.001:
            raise ValueError("Study plan allocation must sum to 1")
    elif contract == "diagnostic-summary@1":
        if set(data["module_status"]) != {
            "listening",
            "reading",
            "writing",
            "speaking",
        }:
            raise ValueError("Diagnostic summary requires exactly four IELTS modules")
