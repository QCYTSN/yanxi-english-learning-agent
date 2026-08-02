from __future__ import annotations

from pathlib import Path
from typing import Any

from .capabilities import CAPABILITIES_BY_CONTRACT
from .storage import save_coaching_artifact
from .study_runtime import (
    apply_reading_review,
    apply_writing_review,
    mutate_session,
)
from .assessment_runtime import (
    bind_speaking_result,
    persist_writing_mock_review,
)
from .validation import validate_data_semantics, validate_schema_data
from .study_threads import add_assistant_message


CONTRACT_SCHEMAS = {
    contract: contract.partition("@")[0]
    for contract in CAPABILITIES_BY_CONTRACT
}
INTERNAL_CONTRACT_SCHEMAS = {"tutor-turn-plan@1": "tutor-turn-plan"}

CONTRACT_SKILLS = {
    contract: capability.skill
    for contract, capability in CAPABILITIES_BY_CONTRACT.items()
}
INTERNAL_CONTRACT_SKILLS = {"tutor-turn-plan@1": "ielts-study-help"}


class AgentContractValidationError(ValueError):
    """A provider candidate failed a named contract validation boundary."""

    def __init__(self, message: str, *, stage: str, code: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code


def _contract_schema(contract: str) -> str:
    schemas = {**CONTRACT_SCHEMAS, **INTERNAL_CONTRACT_SCHEMAS}
    schema = schemas.get(contract)
    if not schema:
        name, _, version = contract.partition("@")
        if name in {item.partition("@")[0] for item in schemas}:
            raise AgentContractValidationError(
                f"Unsupported {name} contract version {version or 'missing'}",
                stage="contract",
                code="AGENT_OUTPUT_CONTRACT_UNSUPPORTED",
            )
        raise AgentContractValidationError(
            f"Unknown Agent output contract: {contract}",
            stage="contract",
            code="AGENT_OUTPUT_CONTRACT_UNKNOWN",
        )
    return schema


def contract_schema_name(contract: str) -> str:
    """Return the schema for a public capability or internal worker contract."""
    return _contract_schema(contract)


def validate_agent_contract_schema(
    contract: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    schema = _contract_schema(contract)
    try:
        return validate_schema_data(result, schema)
    except Exception as exc:
        raise AgentContractValidationError(
            str(exc),
            stage="schema",
            code="AGENT_OUTPUT_SCHEMA_INVALID",
        ) from exc


def validate_agent_contract_domain(
    contract: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    schema = _contract_schema(contract)
    try:
        validated = validate_data_semantics(result, schema)
        _semantic_validation(contract, validated)
    except AgentContractValidationError:
        raise
    except Exception as exc:
        raise AgentContractValidationError(
            str(exc),
            stage="domain",
            code="AGENT_OUTPUT_DOMAIN_INVALID",
        ) from exc
    return validated


def validate_agent_contract(contract: str, result: dict[str, Any]) -> dict[str, Any]:
    structured = validate_agent_contract_schema(contract, result)
    return validate_agent_contract_domain(contract, structured)


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
    if contract == "writing-mock-review@1":
        return persist_writing_mock_review(
            home,
            result,
            expected_revision=run.get("base_revision"),
            idempotency_key=f"agent:{run['run_id']}",
            agent_request=run.get("request") or {},
            evaluator_identity={
                "agent_provider": run.get("agent_provider"),
                "agent_version": run.get("agent_version"),
                "model_id": run.get("model_id"),
                "model_display_name": run.get("model_display_name"),
                "calibration_status": run.get("calibration_status"),
            },
        )
    if contract == "reading-review@1":
        return apply_reading_review(home, str(session_id), result, **common)
    if contract == "listening-review@1":
        return _persist_listening_review(home, str(session_id), result, **common)
    if contract == "speaking-evaluation@1":
        canonical = _persist_speaking_evaluation(
            home,
            str(session_id),
            result,
            evaluator_identity={
                "agent_provider": run.get("agent_provider"),
                "agent_version": run.get("agent_version"),
                "model_id": run.get("model_id"),
                "model_display_name": run.get("model_display_name"),
                "agent_session_id": run.get("agent_session_id"),
                "calibration_status": run.get("calibration_status"),
            },
            **common,
        )
        assessment_run_id = canonical.get("assessment_run_id")
        if assessment_run_id:
            completed = bind_speaking_result(
                home, str(assessment_run_id), canonical
            )
            return {
                "session_id": session_id,
                "assessment_run_id": assessment_run_id,
                "revision": canonical.get("revision"),
                "assessment_status": completed["status"],
            }
        return canonical
    if contract == "study-help@1":
        request = run.get("request") or {}
        thread_id = str(request.get("study_thread_id") or "")
        if not thread_id:
            raise ValueError("Study help result is missing its learning thread")
        artifact = save_coaching_artifact(
            home,
            artifact_id=f"artifact:{run['run_id']}",
            artifact_type="study-help",
            contract_version=1,
            payload=result,
            study_session_id=None,
            agent_run_id=run["run_id"],
        )
        message = add_assistant_message(
            home,
            thread_id=thread_id,
            result=result,
            agent_run_id=str(run["run_id"]),
        )
        return {
            "artifact_id": artifact["artifact_id"],
            "message_id": message["message_id"],
            "revision": None,
        }

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
    *,
    evaluator_identity: dict[str, Any] | None = None,
    **common: Any,
) -> dict[str, Any]:
    identity = evaluator_identity or {}

    def apply(data: dict[str, Any]) -> None:
        if data["module"] != "speaking":
            raise ValueError("Speaking evaluation requires a Speaking Session")
        data["speaking_evaluation"] = result
        data["score_kind"] = result["score_kind"]
        data["score_confidence"] = result["confidence"]
        data["band"] = result.get("band")
        data["rubric"] = result["rubric"]
        data["evaluator_model"] = identity.get("model_display_name") or identity.get(
            "model_id"
        )
        data["agent_identity"] = identity
        data["calibration_status"] = (
            identity.get("calibration_status") or "unknown"
        )
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
    if contract == "writing-mock-review@1":
        _validate_writing_mock(data)
    elif contract == "listening-review@1":
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


def _validate_writing_mock(data: dict[str, Any]) -> None:
    if data["task1"]["task"] != "task1" or data["task2"]["task"] != "task2":
        raise ValueError("Writing mock reviews must keep Task 1 and Task 2 separate")
    for task_name, required in (("task1", {"TA", "CC", "LR", "GRA"}), ("task2", {"TR", "CC", "LR", "GRA"})):
        criteria = data[task_name]["criteria"]
        names = [str(item["criterion"]) for item in criteria]
        if len(names) != len(set(names)) or set(names) != required:
            raise ValueError(
                f"{task_name} requires exactly {', '.join(sorted(required))}"
            )
    visual = data["visual_evidence"]
    task1_scores = {
        str(item["criterion"]): item.get("score")
        for item in data["task1"]["criteria"]
    }
    if visual["status"] == "insufficient":
        if task1_scores["TA"] is not None:
            raise ValueError(
                "Task 1 TA must be null when visual evidence is insufficient"
            )
        if not visual["limitations"]:
            raise ValueError(
                "Insufficient Task 1 visual evidence requires an explicit limitation"
            )
    elif any(value is None for value in task1_scores.values()):
        raise ValueError(
            "Sufficient Task 1 visual evidence requires all four criterion scores"
        )
    if any(item.get("score") is None for item in data["task2"]["criteria"]):
        raise ValueError("Task 2 requires all four criterion scores")
