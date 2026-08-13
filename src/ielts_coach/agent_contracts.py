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
from .validation import validate_data_semantics, validate_schema_data
from .study_threads import add_assistant_message
from .vocabulary import ingest_taught_words


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
        _ingest_taught_words(home, result, run)
        return {
            "artifact_id": artifact["artifact_id"],
            "message_id": message["message_id"],
            "revision": None,
        }

    if contract.startswith("general-"):
        # General English contracts are conversation-first: the validated
        # result becomes a coaching artifact plus an assistant message in the
        # owning learning thread. No formal IELTS session is created.
        request = run.get("request") or {}
        thread_id = str(request.get("study_thread_id") or "")
        if not thread_id:
            raise ValueError("General English results require a learning thread")
        artifact = save_coaching_artifact(
            home,
            artifact_id=f"artifact:{run['run_id']}",
            artifact_type=contract.partition("@")[0],
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
        _ingest_taught_words(home, result, run)
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


def _ingest_taught_words(
    home: Path,
    result: dict[str, Any],
    run: dict[str, Any],
) -> None:
    """Auto-ingest words the tutor explained as candidates for confirmation.

    Conversation contracts carry an optional ``words_taught`` list; the
    dedicated vocabulary lesson carries a single ``word``. Ingestion is
    idempotent and never demotes mastered, known or dismissed words.
    """
    words = list(result.get("words_taught") or [])
    if not words and result.get("word"):
        words = [
            {
                "word": result["word"],
                "meaning": result.get("meaning"),
                "usage": result.get("usage"),
                "example": result.get("example"),
                "collocations": result.get("collocations") or [],
            }
        ]
    if not words:
        return
    track_id = str((run.get("request") or {}).get("track_id") or "general-english")
    ingest_taught_words(
        home,
        words,
        agent_run_id=str(run["run_id"]),
        track_id=track_id,
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
