from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentCapabilities


class ManualAdapter:
    id = "manual"
    label = "Manual handoff"

    def probe(self) -> AgentCapabilities:
        return AgentCapabilities(
            structured_output=True,
            streaming=False,
            session_resume=False,
            image_input=False,
            audio_input=False,
            tool_execution=False,
            remote_processing=True,
        )

    def run(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
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

