from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_contracts import CONTRACT_SCHEMAS
from .capabilities import CapabilitySpec
from .validation import load_schema


@dataclass(frozen=True, slots=True)
class SkillEnvelope:
    envelope_version: int
    skill: str
    source: str
    source_hash: str
    instructions: str
    references: tuple[dict[str, str], ...]
    allowed_tools: tuple[str, ...]
    context_policy: dict[str, Any]
    output_contract: str
    output_schema: dict[str, Any]

    def descriptor(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["references"] = list(self.references)
        payload["allowed_tools"] = list(self.allowed_tools)
        return payload


# Which references each skill loads per teaching phase. Unknown skills or
# phases fall back to the full reference set so older callers stay safe.
STAGE_REFERENCE_SELECTION: dict[str, dict[str, tuple[str, ...]]] = {
    "ielts-writing": {
        "diagnose": ("references/workflow.md",),
        "teach": ("references/workflow.md",),
        "guided_practice": (
            "references/workflow.md",
            "references/session-template.md",
        ),
        "independent_practice": (
            "references/workflow.md",
            "references/session-template.md",
        ),
        "assess": (
            "references/workflow.md",
            "references/scoring-policy.md",
        ),
        "review": (
            "references/error-taxonomy.md",
            "references/scoring-policy.md",
        ),
        "consolidate": ("references/error-taxonomy.md",),
    },
    "ielts-reading": {
        "diagnose": ("references/question-types.md",),
        "teach": ("references/question-types.md",),
        "guided_practice": (
            "references/guided-review.md",
            "references/question-types.md",
        ),
        "independent_practice": (
            "references/timed-practice.md",
            "references/session-template.md",
        ),
        "assess": ("references/session-template.md",),
        "review": (
            "references/error-taxonomy.md",
            "references/close-reading.md",
        ),
        "consolidate": ("references/error-taxonomy.md",),
    },
    "ielts-speaking": {
        "diagnose": ("references/session-template.md",),
        "teach": ("references/session-template.md",),
        "guided_practice": ("references/session-template.md",),
        "independent_practice": ("references/mock-policy.md",),
        "assess": ("references/evaluation-policy.md",),
        "review": (
            "references/error-taxonomy.md",
            "references/evaluation-policy.md",
        ),
        "consolidate": ("references/error-taxonomy.md",),
    },
    "ielts-progress": {
        "review": (
            "references/error-taxonomy.md",
            "references/allocation-policy.md",
        ),
        "consolidate": ("references/calibration-policy.md",),
    },
}


def compile_skill_envelope(
    capability: CapabilitySpec,
    *,
    source_root: Path | None = None,
    stage: str | None = None,
) -> SkillEnvelope:
    root = source_root or resolve_skills_source()
    skill_dir = (root / capability.skill).resolve()
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(
            f"Skill source is missing for {capability.skill}: {skill_file}"
        )
    instructions = skill_file.read_text(encoding="utf-8").strip()
    references: list[dict[str, str]] = []
    reference_dir = skill_dir / "references"
    if reference_dir.is_dir():
        selection = STAGE_REFERENCE_SELECTION.get(capability.skill, {}).get(
            stage or ""
        )
        allowed = (
            {(skill_dir / item).resolve() for item in selection}
            if selection is not None
            else None
        )
        for path in sorted(reference_dir.rglob("*.md")):
            if allowed is not None and path.resolve() not in allowed:
                continue
            references.append(
                {
                    "path": path.relative_to(skill_dir).as_posix(),
                    "content": path.read_text(encoding="utf-8").strip(),
                }
            )
    schema_name = CONTRACT_SCHEMAS[capability.output_contract]
    output_schema = dict(load_schema(schema_name))
    source_material = json.dumps(
        {
            "skill": capability.skill,
            "instructions": instructions,
            "references": references,
            "policy": _context_policy(capability),
            "schema": output_schema,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return SkillEnvelope(
        envelope_version=1,
        skill=capability.skill,
        source=str(skill_file),
        source_hash=hashlib.sha256(source_material.encode("utf-8")).hexdigest(),
        instructions=instructions,
        references=tuple(references),
        # Core teaching providers receive evidence and a schema, never broad
        # filesystem, shell or database authority.
        allowed_tools=(),
        context_policy=_context_policy(capability),
        output_contract=capability.output_contract,
        output_schema=output_schema,
    )


def build_provider_prompt(request: dict[str, Any]) -> tuple[str, str]:
    skill = request.get("skill_envelope") or {}
    context_policy = skill.get("context_policy") or {}
    references = "\n\n".join(
        f"## Reference: {item.get('path')}\n{item.get('content')}"
        for item in skill.get("references") or []
    )
    planning = context_policy.get("response_mode") == "tool_plan"
    worker_boundary = (
        "Select only from the supplied IELTS tool descriptors. Return a tool "
        "plan as JSON; do not execute tools yourself and do not invent tool "
        "observations. The Runtime will execute accepted calls and return results. "
        if planning
        else
        "Return one JSON object matching the supplied output schema. Never call "
        "tools, inspect files, alter learning records, reveal hidden answers during "
        "guided practice, or invent evidence. "
    )
    system = (
        "You are the constrained teaching worker inside 言蹊 (Yanxi). "
        "The Teaching Runtime owns workflow state, persistence, answer integrity "
        "and final validation. Follow the compiled Skill policy below exactly. "
        + worker_boundary
        + "AI scores are training estimates, "
        "not official examiner results.\n\n"
        f"# Compiled Skill: {skill.get('skill')}\n"
        f"{skill.get('instructions') or ''}\n\n"
        f"{references}\n\n"
        "# Capability policy\n"
        + json.dumps(context_policy, ensure_ascii=False, indent=2)
    )
    payload = {
        key: value
        for key, value in request.items()
        if key not in {"skill_envelope", "execution_profile"}
    }
    user = (
        (
            "Plan the next bounded tutor step. Use only the allowlisted descriptors "
            "and canonical context. Return JSON only.\n\n"
            if planning
            else
            "Complete this one IELTS capability. Use only the canonical evidence in "
            "the request. Return JSON only.\n\n"
        )
        + json.dumps(payload, ensure_ascii=False)
    )
    return system, user


def provider_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Compile canonical JSON Schema into the strict provider subset.

    Canonical contracts intentionally use concise JSON Schema such as
    ``{"const": 1}`` and optional nullable fields. OpenAI structured outputs
    require an explicit type for enum/const nodes and every object property to
    appear in ``required``. This compiler adapts only the provider copy; Runtime
    validation continues to use the canonical schema unchanged.
    """

    def normalise(value: Any) -> Any:
        if isinstance(value, list):
            return [normalise(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: normalise(item) for key, item in value.items()}
        result.pop("$schema", None)
        if "type" not in result:
            inferred = (
                _schema_value_type(result.get("const"))
                if "const" in result
                else None
            )
            if inferred is None and isinstance(result.get("enum"), list):
                enum_types = {
                    _schema_value_type(item) for item in result["enum"]
                }
                enum_types.discard(None)
                if len(enum_types) == 1:
                    inferred = next(iter(enum_types))
                elif enum_types:
                    inferred = sorted(
                        enum_types,
                        key=lambda item: (item == "null", str(item)),
                    )
            if inferred:
                result["type"] = inferred
            elif isinstance(result.get("properties"), dict):
                result["type"] = "object"
            elif "items" in result:
                result["type"] = "array"
        if result.get("type") == "object" and isinstance(
            result.get("properties"), dict
        ):
            result["required"] = list(result["properties"])
            result["additionalProperties"] = False
        return result

    return normalise(schema)


def _schema_value_type(value: Any) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def resolve_skills_source() -> Path:
    configured = os.environ.get("IELTS_SKILLS_SOURCE")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(__file__).resolve().parents[2] / "skills-source",
        Path(__file__).resolve().parent / "resources" / "skills",
        Path.cwd() / "skills-source",
    ]
    for candidate in candidates:
        if candidate and (candidate / "ielts-writing" / "SKILL.md").is_file():
            return candidate.resolve()
    raise ValueError(
        "skills-source is unavailable. Run 言蹊 (Yanxi) from the project "
        "checkout or set IELTS_SKILLS_SOURCE."
    )


def _context_policy(capability: CapabilitySpec) -> dict[str, Any]:
    return {
        "capability_id": capability.capability_id,
        "module": capability.module,
        "privacy_scope": capability.privacy_scope,
        "allowed_media_types": list(capability.media_types),
        "allowed_context_roots": [
            "canonical_session",
            "registered_media",
            "rubric_metadata",
        ],
        "forbidden_authority": [
            "database_write",
            "session_transition",
            "answer_key_override",
            "filesystem_access",
            "shell_execution",
        ],
        "persistence_owner": "ielts_teaching_runtime",
        "response_mode": "single_json_object",
    }


def strip_json_fence(value: str) -> str:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return fenced.group(1) if fenced else text
