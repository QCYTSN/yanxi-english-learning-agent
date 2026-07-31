from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_gateway import get_adapter
from .storage import connect, initialise_database


BUILTIN_EXTERNAL_AGENTS: tuple[dict[str, str], ...] = (
    {
        "agent_profile_id": "claude-materials",
        "display_name": "Claude Code",
        "adapter_id": "claude",
        "purpose": "material_operations",
    },
    {
        "agent_profile_id": "opencode-materials",
        "display_name": "OpenCode",
        "adapter_id": "opencode",
        "purpose": "material_operations",
    },
    {
        "agent_profile_id": "manual-handoff",
        "display_name": "Manual handoff",
        "adapter_id": "manual",
        "purpose": "manual_handoff",
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_builtin_external_agents(home: Path) -> None:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        for profile in BUILTIN_EXTERNAL_AGENTS:
            conn.execute(
                """
                INSERT OR IGNORE INTO external_agent_profiles(
                  agent_profile_id,display_name,adapter_id,purpose,is_enabled,
                  config_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    profile["agent_profile_id"],
                    profile["display_name"],
                    profile["adapter_id"],
                    profile["purpose"],
                    1,
                    "{}",
                    now,
                    now,
                ),
            )


def list_external_agent_profiles(
    home: Path,
    *,
    diagnostics: bool = False,
) -> list[dict[str, Any]]:
    ensure_builtin_external_agents(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM external_agent_profiles
            ORDER BY CASE purpose
              WHEN 'material_operations' THEN 0
              WHEN 'format_conversion' THEN 1
              WHEN 'corpus_maintenance' THEN 2
              WHEN 'developer_tools' THEN 3
              ELSE 4 END,
              display_name
            """
        ).fetchall()
    result = []
    for row in rows:
        adapter = get_adapter(str(row["adapter_id"]))
        available = bool(getattr(adapter, "available", lambda: True)())
        descriptor = {
            "agent_profile_id": row["agent_profile_id"],
            "display_name": row["display_name"],
            "adapter_id": row["adapter_id"],
            "purpose": row["purpose"],
            "is_enabled": bool(row["is_enabled"]),
            "config": json.loads(row["config_json"]),
            "available": available,
            "capabilities": asdict(adapter.probe()),
            "identity": asdict(adapter.identity()),
            "teaching_model_eligible": False,
            "boundary": (
                "External Agents are optional material and developer tools. "
                "They cannot be selected as the IELTS teaching model."
            ),
        }
        if diagnostics:
            diagnostic = getattr(adapter, "diagnostics", None)
            descriptor["diagnostics"] = (
                diagnostic() if callable(diagnostic) else {"available": available}
            )
        result.append(descriptor)
    return result
