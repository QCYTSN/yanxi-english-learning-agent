from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


CapabilityModule = Literal[
    "listening",
    "reading",
    "writing",
    "speaking",
    "progress",
    "cross_module",
]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """One versioned AI-assisted IELTS workflow.

    A Capability is a product workflow, not a model, CLI process, Skill or
    tool.  It owns the minimum context boundary and the output contract while
    the Inference Broker chooses how that contract is executed.
    """

    capability_id: str
    title: str
    module: CapabilityModule
    output_contract: str
    skill: str
    privacy_scope: Literal["learning_record", "private_material"]
    media_types: tuple[Literal["image", "audio"], ...] = ()
    default_timeout_seconds: int = 300

    def descriptor(self) -> dict[str, object]:
        value = asdict(self)
        value["media_types"] = list(self.media_types)
        return value


_CAPABILITIES = (
    CapabilitySpec(
        capability_id="writing_review",
        title="Writing evidence review",
        module="writing",
        output_contract="writing-review@1",
        skill="ielts-writing",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="writing_mock_review",
        title="Writing full mock review",
        module="writing",
        output_contract="writing-mock-review@1",
        skill="ielts-writing",
        privacy_scope="private_material",
        media_types=("image",),
        default_timeout_seconds=600,
    ),
    CapabilitySpec(
        capability_id="reading_explanation",
        title="Reading wrong-answer explanation",
        module="reading",
        output_contract="reading-review@1",
        skill="ielts-reading",
        privacy_scope="learning_record",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="study_material_help",
        title="Persistent IELTS teacher dialogue",
        module="cross_module",
        output_contract="study-help@1",
        skill="ielts-study-help",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="listening_review",
        title="Listening error review",
        module="listening",
        output_contract="listening-review@1",
        skill="ielts-progress",
        privacy_scope="learning_record",
        media_types=("audio",),
    ),
    CapabilitySpec(
        capability_id="speaking_evaluation",
        title="Speaking evidence evaluation",
        module="speaking",
        output_contract="speaking-evaluation@1",
        skill="ielts-speaking",
        privacy_scope="private_material",
        media_types=("audio",),
        default_timeout_seconds=600,
    ),
    CapabilitySpec(
        capability_id="study_plan",
        title="Evidence-aware study plan",
        module="cross_module",
        output_contract="study-plan@1",
        skill="ielts",
        privacy_scope="learning_record",
    ),
    CapabilitySpec(
        capability_id="diagnostic_summary",
        title="Diagnostic summary",
        module="cross_module",
        output_contract="diagnostic-summary@1",
        skill="ielts",
        privacy_scope="learning_record",
    ),
    CapabilitySpec(
        capability_id="weekly_coaching",
        title="Weekly coaching explanation",
        module="progress",
        output_contract="weekly-coaching@1",
        skill="ielts-progress",
        privacy_scope="learning_record",
    ),
)

CAPABILITIES = {item.capability_id: item for item in _CAPABILITIES}
CAPABILITIES_BY_CONTRACT = {item.output_contract: item for item in _CAPABILITIES}


def get_capability(capability_id: str) -> CapabilitySpec:
    try:
        return CAPABILITIES[capability_id]
    except KeyError as exc:
        raise ValueError(f"Unknown IELTS Capability: {capability_id}") from exc


def capability_for_contract(output_contract: str) -> CapabilitySpec:
    try:
        return CAPABILITIES_BY_CONTRACT[output_contract]
    except KeyError as exc:
        name, _, version = output_contract.partition("@")
        known_name = any(
            item.output_contract.partition("@")[0] == name for item in _CAPABILITIES
        )
        if known_name:
            raise ValueError(
                f"Unsupported {name} Capability contract version "
                f"{version or 'missing'}"
            ) from exc
        raise ValueError(
            f"No IELTS Capability owns output contract {output_contract!r}"
        ) from exc


def capability_descriptors() -> list[dict[str, object]]:
    return [item.descriptor() for item in _CAPABILITIES]
