from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .base import AgentCapabilities, AgentIdentity
from ..media import resolve_media_file


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
            image_input=True,
            audio_input=False,
            tool_execution=False,
            remote_processing=True,
            cancellation=False,
            timeout_control=False,
        )

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        root = (home / "exports" / "agent-requests").resolve()
        folder = (root / str(request["request_id"])).resolve()
        if root not in folder.parents:
            raise ValueError("Invalid Manual Agent request id")
        folder.mkdir(parents=True, exist_ok=True)
        public_request = json.loads(json.dumps(request, ensure_ascii=False))
        attachments = []
        for index, ref in enumerate(public_request.get("media_refs") or [], start=1):
            if not ref.get("available_to_agent") or ref.get("media_type") != "image":
                continue
            asset, source = resolve_media_file(home, str(ref["media_id"]))
            target = folder / f"{ref['media_id']}-{index}{source.suffix.lower()}"
            shutil.copy2(source, target)
            ref["package_file"] = target.name
            attachments.append(
                {
                    "media_id": asset["media_id"],
                    "file": target.name,
                    "content_hash": asset["content_hash"],
                    "mime_type": asset["mime_type"],
                }
            )
        public_request["manual_package"] = {
            "folder": str(folder),
            "attachments": attachments,
            "instruction": (
                "Send request.json and every listed attachment to the selected "
                "Agent. Do not replace media_id values or edit file contents."
            ),
        }
        path = folder / "request.json"
        path.write_text(
            json.dumps(public_request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "status": "awaiting_import",
            "request_id": request["request_id"],
            "package_path": str(path),
            "attachments": attachments,
            "request": public_request,
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
