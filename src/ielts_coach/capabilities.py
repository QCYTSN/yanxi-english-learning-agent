from __future__ import annotations

from .domain_packs import CapabilitySpec, all_capabilities


# Compatibility alias for integrations that imported the old IELTS-specific
# type. Modules are now owned by a Domain Pack and are intentionally open.
CapabilityModule = str


_TRACKED_CAPABILITIES = all_capabilities()
_CAPABILITIES = tuple(item for _, item in _TRACKED_CAPABILITIES)

CAPABILITIES = {item.capability_id: item for item in _CAPABILITIES}
CAPABILITIES_BY_CONTRACT = {item.output_contract: item for item in _CAPABILITIES}


def get_capability(capability_id: str) -> CapabilitySpec:
    try:
        return CAPABILITIES[capability_id]
    except KeyError as exc:
        raise ValueError(f"Unknown learning Capability: {capability_id}") from exc


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
            f"No learning Capability owns output contract {output_contract!r}"
        ) from exc


def capability_descriptors(track_id: str | None = None) -> list[dict[str, object]]:
    return [
        item.descriptor(track_id=owner_track_id)
        for owner_track_id, item in _TRACKED_CAPABILITIES
        if track_id is None or owner_track_id == track_id
    ]
