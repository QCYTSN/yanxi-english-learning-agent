from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
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


class AgentAdapter(Protocol):
    id: str
    label: str

    def probe(self) -> AgentCapabilities: ...

    def run(self, home: Path, request: dict[str, Any]) -> dict[str, Any]: ...


def describe_adapter(adapter: AgentAdapter) -> dict[str, Any]:
    return {
        "id": adapter.id,
        "label": adapter.label,
        "available": True,
        "capabilities": asdict(adapter.probe()),
    }

