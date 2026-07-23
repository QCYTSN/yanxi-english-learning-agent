from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentCapabilities, AgentIdentity


class ManualAdapter:
    id = "manual"
    label = "Manual handoff"

    def identity(self) -> AgentIdentity:
        return AgentIdentity(
            agent_provider=None,
            agent_version=None,
            model_id=None,
            model_display_name=None,
            launcher_kind="manual_handoff",
            calibration_status="unknown",
        )

    def probe(self) -> AgentCapabilities:
        return AgentCapabilities(
            structured_output=True,
            streaming=False,
            session_resume=False,
            image_input=False,
            audio_input=False,
            tool_execution=False,
            remote_processing=True,
            cancellation=False,
            timeout_control=False,
        )

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        folder = home / "exports" / "agent-requests"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{request['request_id']}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "awaiting_import",
            "request_id": request["request_id"],
            "package_path": str(path),
            "request": request,
        }

    run = start

    def stream(self, home: Path, execution_ref: str) -> list[dict[str, Any]]:
        return []

    def cancel(self, home: Path, execution_ref: str) -> bool:
        return False

    def resume(
        self, home: Path, execution_ref: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        return self.start(home, request)
