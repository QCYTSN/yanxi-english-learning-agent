from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import connect, initialise_database


BUILTIN_EXECUTION_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "profile_id": "codex-managed",
        "display_name": "Codex managed runtime",
        "backend_kind": "managed_runtime",
        "backend_id": "codex-managed",
        "transport": "app_server_stdio",
        "auth_mode": "codex_managed",
    },
    {
        "profile_id": "pipeline-test",
        "display_name": "Deterministic pipeline test",
        "backend_kind": "mock",
        "backend_id": "mock",
        "transport": "in_process",
        "auth_mode": "none",
    },
)

LEGACY_ADAPTER_PROFILES = {
    item["backend_id"]: item["profile_id"] for item in BUILTIN_EXECUTION_PROFILES
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_builtin_execution_profiles(home: Path) -> None:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        for profile in BUILTIN_EXECUTION_PROFILES:
            conn.execute(
                """
                INSERT OR IGNORE INTO execution_profiles(
                  profile_id,display_name,backend_kind,backend_id,transport,
                  auth_mode,model_id,reasoning_effort,is_enabled,is_default,
                  config_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    profile["profile_id"],
                    profile["display_name"],
                    profile["backend_kind"],
                    profile["backend_id"],
                    profile["transport"],
                    profile["auth_mode"],
                    None,
                    None,
                    1,
                    0,
                    "{}",
                    now,
                    now,
                ),
            )


def _profile_row(row: Any) -> dict[str, Any]:
    return {
        "profile_id": row["profile_id"],
        "display_name": row["display_name"],
        "backend_kind": row["backend_kind"],
        "backend_id": row["backend_id"],
        "transport": row["transport"],
        "auth_mode": row["auth_mode"],
        "model_id": row["model_id"],
        "reasoning_effort": row["reasoning_effort"],
        "is_enabled": bool(row["is_enabled"]),
        "is_default": bool(row["is_default"]),
        "config": json.loads(row["config_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_execution_profiles(home: Path) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM execution_profiles
            ORDER BY is_default DESC,
              CASE backend_kind
                WHEN 'managed_runtime' THEN 0
                WHEN 'api_model' THEN 1
                WHEN 'local_http_model' THEN 2
                WHEN 'external_agent' THEN 3
                WHEN 'manual' THEN 4
                ELSE 5
              END,
              display_name
            """
        ).fetchall()
    return [_profile_row(row) for row in rows]


def get_execution_profile(
    home: Path, profile_id: str
) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM execution_profiles WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
    return _profile_row(row) if row else None


def default_execution_profile(home: Path) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            """
            SELECT * FROM execution_profiles
            WHERE is_default=1 AND is_enabled=1
            LIMIT 1
            """
        ).fetchone()
    return _profile_row(row) if row else None


def resolve_execution_profile(
    home: Path,
    *,
    profile_id: str | None = None,
    legacy_adapter_id: str | None = None,
) -> dict[str, Any]:
    selected_id = profile_id
    if not selected_id and legacy_adapter_id:
        selected_id = LEGACY_ADAPTER_PROFILES.get(legacy_adapter_id)
    profile = (
        get_execution_profile(home, selected_id)
        if selected_id
        else default_execution_profile(home)
    )
    if not profile:
        raise ValueError(
            "No AI execution profile is selected. Configure a default connection "
            "or choose one for this task."
        )
    if not profile["is_enabled"]:
        raise ValueError(f"Execution profile {profile['display_name']} is disabled")
    return profile


def update_execution_profile(
    home: Path,
    profile_id: str,
    *,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    is_enabled: bool | None = None,
    is_default: bool | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = get_execution_profile(home, profile_id)
    if not profile:
        raise ValueError(f"Unknown execution profile: {profile_id}")
    if is_default and is_enabled is False:
        raise ValueError("A disabled execution profile cannot be the default")
    if is_default and profile["backend_kind"] == "external_agent":
        raise ValueError(
            "External CLI Agents cannot be the IELTS teaching model. "
            "Configure a Model Provider instead."
        )
    clean_config = dict(profile["config"])
    if config is not None:
        allowed_keys = (
            {"executable_path"}
            if profile["backend_id"] == "codex-managed"
            else set()
        )
        unknown = set(config) - allowed_keys
        if unknown:
            raise ValueError(
                "Unsupported execution profile setting: "
                + ", ".join(sorted(unknown))
            )
        clean_config.update(config)
        if not clean_config.get("executable_path"):
            clean_config.pop("executable_path", None)
    values = {
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "is_enabled": (
            int(is_enabled) if is_enabled is not None else int(profile["is_enabled"])
        ),
        "config_json": json.dumps(clean_config, ensure_ascii=False),
        "updated_at": _now(),
    }
    with connect(home) as conn:
        if is_default:
            conn.execute(
                "UPDATE execution_profiles SET is_default=0 WHERE is_default=1"
            )
        conn.execute(
            """
            UPDATE execution_profiles
            SET model_id=?,reasoning_effort=?,is_enabled=?,is_default=?,
                config_json=?,updated_at=?
            WHERE profile_id=?
            """,
            (
                values["model_id"],
                values["reasoning_effort"],
                values["is_enabled"],
                int(is_default) if is_default is not None else int(profile["is_default"]),
                values["config_json"],
                values["updated_at"],
                profile_id,
            ),
        )
    updated = get_execution_profile(home, profile_id)
    if not updated:  # pragma: no cover - guarded by the update above
        raise RuntimeError("Execution profile disappeared during update")
    if profile["backend_id"] == "codex-managed":
        # Keep the V1.4 compatibility endpoint in sync with the new provider
        # layer without exposing Provider concerns to legacy callers.
        from .model_providers import update_model_provider

        update_model_provider(
            home,
            "openai-codex-oauth",
            model_id=updated.get("model_id"),
            reasoning_effort=updated.get("reasoning_effort"),
            role="primary" if updated["is_default"] else None,
            is_enabled=updated["is_enabled"],
            config=updated.get("config") or {},
        )
    return updated
