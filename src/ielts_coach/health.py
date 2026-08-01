from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from .storage import SCHEMA_VERSION, session_payload_hash
from .validation import validate_data


def audit_data_home(
    home: Path,
    *,
    expected_schema_version: str | None = None,
    require_configuration: bool = True,
) -> dict[str, Any]:
    """Read-only cross-store audit used by doctor, backup verification and restore."""
    home = home.resolve()
    checks: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    profile_path = home / "config" / "profile.yaml"
    settings_path = home / "config" / "settings.yaml"
    profile = _yaml_mapping(profile_path, "profile", errors)
    settings = _yaml_mapping(settings_path, "settings", errors)
    if not require_configuration:
        for message in list(errors):
            if message.startswith(("profile file is missing", "settings file is missing")):
                errors.remove(message)
                warnings.append(message)
    if profile is not None:
        try:
            validate_data(profile, "profile")
            checks["profile"] = "ok"
        except Exception as exc:
            checks["profile"] = "invalid"
            errors.append(f"profile.yaml: {exc}")
    filename = str((settings or {}).get("database_filename") or "ielts.db")
    if Path(filename).name != filename:
        errors.append("settings database_filename must be a file name")
        filename = "ielts.db"
    database = home / "database" / filename
    checks["database_path"] = str(database)
    if not database.is_file():
        errors.append(f"SQLite database is missing: {database}")
        return _result(checks, errors, warnings)

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            checks["database_integrity"] = integrity
            if integrity != "ok":
                errors.append(f"SQLite integrity_check: {integrity}")
            tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            schema_row = (
                conn.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()
                if "schema_meta" in tables
                else None
            )
            schema_version = str(schema_row["value"]) if schema_row else "legacy"
            checks["schema_version"] = schema_version
            expected_schema = expected_schema_version or str(SCHEMA_VERSION)
            if schema_version != expected_schema:
                errors.append(
                    f"Database schema is {schema_version}; expected {expected_schema}"
                )
            _audit_sessions(home, conn, checks, errors, warnings)
            _audit_corpora(home, conn, checks, errors, warnings)
            _audit_media(home, conn, checks, errors)
        finally:
            conn.close()
            conn = None
    except sqlite3.DatabaseError as exc:
        errors.append(f"SQLite database cannot be read: {exc}")
    finally:
        if conn is not None:
            conn.close()
    return _result(checks, errors, warnings)


def require_healthy_data_home(home: Path) -> dict[str, Any]:
    report = audit_data_home(home)
    if report["status"] == "failed":
        raise ValueError("Data-home health check failed: " + "; ".join(report["errors"]))
    return report


def _audit_sessions(
    home: Path,
    conn: sqlite3.Connection,
    checks: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    if "sessions" not in {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        return
    session_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    strict_projection_guard = "payload_hash" in session_columns
    payload_hash_expression = (
        "payload_hash" if "payload_hash" in session_columns else "NULL AS payload_hash"
    )
    mirror_status_expression = (
        "mirror_status"
        if "mirror_status" in session_columns
        else "'unknown' AS mirror_status"
    )
    database_sessions = {
        str(row["session_id"]): row
        for row in conn.execute(
            "SELECT session_id,module,payload_json,"
            f"{payload_hash_expression},{mirror_status_expression} FROM sessions"
        ).fetchall()
    }
    file_sessions: dict[str, dict[str, Any]] = {}
    for path in (home / "sessions").glob("*/*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                raise ValueError("missing YAML frontmatter")
            parts = text.split("---", 2)
            payload = yaml.safe_load(parts[1]) or {}
            session_id = str(payload.get("session_id") or path.stem)
            module = str(payload.get("module") or path.parent.name)
            file_sessions[session_id] = {"module": module, "payload": payload}
        except Exception as exc:
            warnings.append(f"Unreadable Session Markdown {path.name}: {exc}")
    db_only = sorted(set(database_sessions) - set(file_sessions))
    file_only = sorted(set(file_sessions) - set(database_sessions))
    mismatched = sorted(
        session_id
        for session_id in set(database_sessions) & set(file_sessions)
        if str(database_sessions[session_id]["module"])
        != str(file_sessions[session_id]["module"])
    )
    revision_mismatches: list[str] = []
    content_mismatches: list[str] = []
    stored_hash_mismatches: list[str] = []
    unreadable_database_payloads: list[str] = []
    for session_id in set(database_sessions) & set(file_sessions):
        row = database_sessions[session_id]
        try:
            db_payload = json.loads(str(row["payload_json"]))
            db_hash = session_payload_hash(db_payload)
            file_payload = file_sessions[session_id]["payload"]
            file_hash = session_payload_hash(file_payload)
            db_revision = int(db_payload.get("revision", 0))
            file_revision = int(file_payload.get("revision", 0))
        except Exception:
            unreadable_database_payloads.append(session_id)
            continue
        if row["payload_hash"] and str(row["payload_hash"]) != db_hash:
            stored_hash_mismatches.append(session_id)
        if db_revision != file_revision:
            revision_mismatches.append(session_id)
        elif db_hash != file_hash:
            content_mismatches.append(session_id)
    checks["sessions"] = {
        "database": len(database_sessions),
        "markdown": len(file_sessions),
        "database_only": len(db_only),
        "markdown_only": len(file_only),
        "module_mismatches": len(mismatched),
        "revision_mismatches": len(revision_mismatches),
        "content_mismatches": len(content_mismatches),
        "stored_hash_mismatches": len(stored_hash_mismatches),
        "unreadable_database_payloads": len(unreadable_database_payloads),
    }
    if db_only:
        warnings.append(
            f"{len(db_only)} Session records have no Markdown mirror (first: {db_only[0]})"
        )
    if file_only:
        warnings.append(
            f"{len(file_only)} Session Markdown files are not indexed (first: {file_only[0]})"
        )
    if mismatched:
        warnings.append(
            f"{len(mismatched)} Session module mappings disagree (first: {mismatched[0]})"
        )
    if revision_mismatches:
        target = errors if strict_projection_guard else warnings
        target.append(
            f"{len(revision_mismatches)} Session revisions disagree "
            f"(first: {revision_mismatches[0]})"
        )
    if content_mismatches:
        target = errors if strict_projection_guard else warnings
        target.append(
            f"{len(content_mismatches)} same-revision Session payloads diverge "
            f"(first: {content_mismatches[0]})"
        )
    if stored_hash_mismatches:
        errors.append(
            f"{len(stored_hash_mismatches)} SQLite Session payload hashes mismatch "
            f"(first: {stored_hash_mismatches[0]})"
        )
    if unreadable_database_payloads:
        errors.append(
            f"{len(unreadable_database_payloads)} SQLite Session payloads are unreadable "
            f"(first: {unreadable_database_payloads[0]})"
        )


def _audit_corpora(
    home: Path,
    conn: sqlite3.Connection,
    checks: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    if not _has_table(conn, "corpora"):
        return
    database_ids = {
        str(row["corpus_id"])
        for row in conn.execute("SELECT corpus_id FROM corpora").fetchall()
    }
    manifest_ids: set[str] = set()
    for path in (home / "corpus" / "manifests").glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            corpus_id = str(data.get("corpus_id") or "")
            if not corpus_id:
                raise ValueError("corpus_id is missing")
            manifest_ids.add(corpus_id)
        except Exception as exc:
            errors.append(f"Invalid Corpus Manifest {path.name}: {exc}")
    db_only = sorted(database_ids - manifest_ids)
    file_only = sorted(manifest_ids - database_ids)
    checks["corpora"] = {
        "database": len(database_ids),
        "manifests": len(manifest_ids),
        "database_only": len(db_only),
        "manifest_only": len(file_only),
    }
    if db_only:
        warnings.append(
            f"{len(db_only)} corpora have no managed Manifest mirror (first: {db_only[0]})"
        )
    if file_only:
        warnings.append(
            f"{len(file_only)} Corpus Manifests are not indexed (first: {file_only[0]})"
        )


def _audit_media(
    home: Path,
    conn: sqlite3.Connection,
    checks: dict[str, Any],
    errors: list[str],
) -> None:
    if not _has_table(conn, "media_assets"):
        return
    rows = conn.execute(
        "SELECT media_id,local_path,content_hash FROM media_assets"
    ).fetchall()
    missing: list[str] = []
    mismatched: list[str] = []
    media_root = (home / "media").resolve()
    for row in rows:
        path = Path(str(row["local_path"])).resolve()
        if media_root not in path.parents or not path.is_file():
            missing.append(str(row["media_id"]))
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != str(row["content_hash"]):
            mismatched.append(str(row["media_id"]))
    checks["media"] = {
        "registered": len(rows),
        "missing": len(missing),
        "hash_mismatches": len(mismatched),
    }
    if missing:
        errors.append(
            f"{len(missing)} registered media files are missing (first: {missing[0]})"
        )
    if mismatched:
        errors.append(
            f"{len(mismatched)} registered media hashes mismatch (first: {mismatched[0]})"
        )


def _yaml_mapping(
    path: Path,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"{label} file is missing: {path}")
        return None
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{label} file cannot be parsed: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} file must contain a mapping")
        return None
    return value


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _result(
    checks: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "status": "failed" if errors else "degraded" if warnings else "ok",
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
