from __future__ import annotations

import json
import os
import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .credential_store import credential_protection
from .data_lifecycle import audit_orphaned_media
from .model_providers import list_model_providers, provider_health_status
from .storage import SCHEMA_VERSION, connect, db_path, initialise_database


SENSITIVE_KEY = re.compile(
    r"(secret|token|password|credential|authorization|api[_-]?key|content|prompt|request|result|transcript|evidence)",
    re.IGNORECASE,
)
BEARER_VALUE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+")


def build_support_diagnostics(home: Path) -> dict[str, Any]:
    """Return a content-free diagnostic snapshot suitable for bug reports."""

    initialise_database(home)
    database = db_path(home)
    with connect(home) as conn:
        integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        schema_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        migration_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT migration_id,from_version,to_version,status,started_at,
                       completed_at,error_message
                FROM schema_migration_journal ORDER BY to_version,migration_id
                """
            ).fetchall()
        ]
        agent_status = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                "SELECT status,COUNT(*) count FROM agent_runs GROUP BY status"
            ).fetchall()
        }
        agent_errors = [
            dict(row)
            for row in conn.execute(
                """
                SELECT error_code,COUNT(*) count
                FROM agent_runs WHERE error_code IS NOT NULL
                GROUP BY error_code ORDER BY count DESC LIMIT 20
                """
            ).fetchall()
        ]
        background_status = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                "SELECT status,COUNT(*) count FROM local_background_jobs GROUP BY status"
            ).fetchall()
        }
        provider_attempts = [
            dict(row)
            for row in conn.execute(
                """
                SELECT provider_id,status,failure_stage,error_code,COUNT(*) count
                FROM provider_attempts
                GROUP BY provider_id,status,failure_stage,error_code
                ORDER BY count DESC LIMIT 40
                """
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for table in (
            "sessions",
            "questions",
            "study_threads",
            "study_messages",
            "study_thread_attachments",
            "media_assets",
            "content_import_jobs",
            "agent_runs",
        ):
            counts[table] = int(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )

    providers = []
    for provider in list_model_providers(home, diagnostics=False):
        providers.append(
            {
                "provider_id": provider["provider_id"],
                "provider_kind": provider["provider_kind"],
                "transport": provider["transport"],
                "auth_mode": provider["auth_mode"],
                "model_id": provider.get("model_id"),
                "role": provider["role"],
                "is_enabled": provider["is_enabled"],
                "available": provider["available"],
                "credential_configured": provider["credential_configured"],
                "credential_protection": provider["credential_protection"],
                "health": provider_health_status(home, str(provider["provider_id"])),
            }
        )

    roots = {
        name: _directory_size(home / name)
        for name in ("database", "media", "corpus", "study-threads", "runtime")
    }
    orphaned = audit_orphaned_media(home)
    payload = {
        "diagnostic_format": "ielts-study-desk-support@1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application": {
            "version": __version__,
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "process_bits": 64 if sys.maxsize > 2**32 else 32,
            "locale": os.environ.get("LANG") or os.environ.get("LC_ALL"),
        },
        "database": {
            "schema_version": str(schema_row["value"]) if schema_row else None,
            "expected_schema_version": SCHEMA_VERSION,
            "quick_check": integrity,
            "size_bytes": database.stat().st_size if database.is_file() else 0,
            "counts": counts,
            "migrations": migration_rows,
        },
        "storage": {
            "root_sizes_bytes": roots,
            "orphaned_media": {
                "registered": int(orphaned.get("registered") or 0),
                "unreferenced_count": len(
                    orphaned.get("unreferenced_media_ids") or []
                ),
                "missing_count": len(orphaned.get("missing_media_ids") or []),
                "orphan_file_count": len(orphaned.get("orphan_files") or []),
            },
        },
        "jobs": {
            "agent_status_counts": agent_status,
            "agent_error_counts": agent_errors,
            "background_status_counts": background_status,
            "provider_attempt_counts": provider_attempts,
        },
        "providers": providers,
        "credential_protection": credential_protection(),
        "privacy": {
            "contains_learner_content": False,
            "contains_credentials": False,
            "contains_absolute_data_home": False,
        },
    }
    return _redact_home_path(redact_diagnostic_payload(payload), str(home.resolve()))


def create_support_bundle(home: Path) -> Path:
    payload = build_support_diagnostics(home)
    export_root = home / "exports" / "support"
    export_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = export_root / f"ielts-support-{stamp}.zip"
    temporary = destination.with_suffix(".tmp")
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )
        archive.writestr(
            "README.txt",
            "This bundle contains system metadata and aggregate counts only. "
            "It excludes learner text, attachments, prompts and credentials.\n",
        )
    os.replace(temporary, destination)
    older = sorted(export_root.glob("ielts-support-*.zip"), reverse=True)[5:]
    for item in older:
        try:
            item.unlink()
        except OSError:
            pass
    return destination


def redact_diagnostic_payload(value: Any, *, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        if key.lower() in {
            "error_code",
            "last_error_code",
            "contains_learner_content",
            "contains_credentials",
        }:
            return value
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_diagnostic_payload(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_diagnostic_payload(item, key=key) for item in value]
    if isinstance(value, str):
        return BEARER_VALUE.sub("Bearer [redacted]", value)
    return value


def _directory_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _redact_home_path(value: Any, home_path: str) -> Any:
    if isinstance(value, dict):
        return {key: _redact_home_path(item, home_path) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_home_path(item, home_path) for item in value]
    if isinstance(value, str):
        return value.replace(home_path, "[data-home]").replace(
            home_path.replace("\\", "/"), "[data-home]"
        )
    return value
