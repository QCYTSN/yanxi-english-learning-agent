from __future__ import annotations

from .base import AgentAdapter, describe_adapter
from .manual import ManualAdapter
from .mock import MockAdapter
from .process import ClaudeProcessAdapter, OpenCodeProcessAdapter


_ADAPTERS: dict[str, AgentAdapter] = {
    "mock": MockAdapter(),
    "manual": ManualAdapter(),
    "opencode": OpenCodeProcessAdapter(),
    "claude": ClaudeProcessAdapter(),
}


def get_adapter(adapter_id: str) -> AgentAdapter:
    try:
        return _ADAPTERS[adapter_id]
    except KeyError as exc:
        raise ValueError(f"Unknown Agent adapter: {adapter_id}") from exc


def adapter_descriptors() -> list[dict[str, object]]:
    return [describe_adapter(adapter) for adapter in _ADAPTERS.values()]


def adapter_diagnostics() -> list[dict[str, object]]:
    results = []
    for adapter in _ADAPTERS.values():
        descriptor = describe_adapter(adapter)
        diagnostic = getattr(adapter, "diagnostics", None)
        details = diagnostic() if callable(diagnostic) else {
            "available": descriptor["available"],
            "model_call_test": "not_run",
            "boundary": "This adapter does not expose a local process preflight.",
        }
        results.append({**descriptor, "diagnostics": details})
    return results
