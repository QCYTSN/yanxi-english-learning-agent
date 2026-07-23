from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentCapabilities:
    structured_output: bool
    streaming: bool
    session_resume: bool
    image_input: bool
    audio_input: bool
    tool_execution: bool
    remote_processing: bool
    cancellation: bool = False
    timeout_control: bool = False


@dataclass(frozen=True)
class AgentIdentity:
    agent_provider: str | None
    agent_version: str | None
    model_id: str | None
    model_display_name: str | None
    launcher_kind: str
    calibration_status: str


class AgentAdapter(Protocol):
    id: str
    label: str

    def probe(self) -> AgentCapabilities: ...

    def identity(self) -> AgentIdentity: ...

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]: ...

    def stream(
        self, home: Path, execution_ref: str
    ) -> Iterable[dict[str, Any]]: ...

    def cancel(self, home: Path, execution_ref: str) -> bool: ...

    def resume(
        self, home: Path, execution_ref: str, request: dict[str, Any]
    ) -> dict[str, Any]: ...


def describe_adapter(adapter: AgentAdapter) -> dict[str, Any]:
    identity = asdict(adapter.identity())
    available = getattr(adapter, "available", lambda: True)()
    return {
        "id": adapter.id,
        "label": adapter.label,
        "available": bool(available),
        "capabilities": asdict(adapter.probe()),
        "identity": identity,
    }
