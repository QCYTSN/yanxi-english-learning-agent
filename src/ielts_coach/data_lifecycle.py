from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable

from .storage import connect, initialise_database
from .storage_quota import invalidate_storage_usage


def delete_study_thread_data(home: Path, thread_id: str) -> dict[str, Any]:
    """Delete a dialogue and every private artifact owned only by that dialogue."""
    initialise_database(home)
    storage_root = (home / "study-threads").resolve()
    thread_storage = (storage_root / thread_id).resolve()
    if thread_storage.parent != storage_root:
        raise ValueError("Unsafe study thread path")

    tombstone: Path | None = None
    if thread_storage.is_dir():
        trash_root = storage_root / ".deleted"
        trash_root.mkdir(parents=True, exist_ok=True)
        tombstone = trash_root / f"{thread_id}-{uuid.uuid4().hex}"
        thread_storage.replace(tombstone)

    try:
        with connect(home) as conn:
            if not conn.execute(
                "SELECT 1 FROM study_threads WHERE thread_id=?", (thread_id,)
            ).fetchone():
                raise ValueError("Study thread not found")
            media_ids = {
                str(row["media_id"])
                for row in conn.execute(
                    "SELECT media_id FROM study_thread_attachments "
                    "WHERE thread_id=? AND media_id IS NOT NULL",
                    (thread_id,),
                ).fetchall()
            }
            run_ids = _thread_run_ids(conn, thread_id)
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                conn.execute(
                    f"DELETE FROM coaching_artifacts WHERE agent_run_id IN ({placeholders})",
                    tuple(run_ids),
                )
                conn.execute(
                    f"DELETE FROM agent_runs WHERE run_id IN ({placeholders})",
                    tuple(run_ids),
                )
            conn.execute(
                "DELETE FROM media_bindings WHERE owner_type='study_thread' AND owner_id=?",
                (thread_id,),
            )
            conn.execute("DELETE FROM study_threads WHERE thread_id=?", (thread_id,))
    except BaseException:
        if tombstone and tombstone.is_dir() and not thread_storage.exists():
            tombstone.replace(thread_storage)
        raise

    if tombstone and tombstone.is_dir():
        try:
            shutil.rmtree(tombstone)
        except OSError:
            pass
    purge_unreferenced_media(home, media_ids=media_ids)
    invalidate_storage_usage(home)
    # Keep the public deletion contract stable. A failed physical cleanup is
    # retried from the tombstone directory on the next service start.
    return {"thread_id": thread_id, "deleted": True}


def purge_unreferenced_media(
    home: Path,
    *,
    media_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Remove registry rows and hashed files that have no remaining owner."""
    initialise_database(home)
    requested = {str(item) for item in media_ids or [] if item}
    removed_files: list[str] = []
    removed_rows: list[str] = []
    with connect(home) as conn:
        if requested:
            placeholders = ",".join("?" for _ in requested)
            rows = conn.execute(
                f"SELECT * FROM media_assets WHERE media_id IN ({placeholders})",
                tuple(sorted(requested)),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM media_assets").fetchall()
        for row in rows:
            media_id = str(row["media_id"])
            bound = conn.execute(
                "SELECT 1 FROM media_bindings WHERE media_id=? LIMIT 1", (media_id,)
            ).fetchone()
            attached = conn.execute(
                "SELECT 1 FROM study_thread_attachments WHERE media_id=? LIMIT 1",
                (media_id,),
            ).fetchone()
            leased = conn.execute(
                "SELECT 1 FROM audio_playback_leases WHERE media_id=? LIMIT 1",
                (media_id,),
            ).fetchone()
            if bound or attached or leased:
                continue
            path = Path(str(row["local_path"])).resolve()
            conn.execute("DELETE FROM media_assets WHERE media_id=?", (media_id,))
            removed_rows.append(media_id)
            shared = conn.execute(
                "SELECT 1 FROM media_assets WHERE local_path=? LIMIT 1", (str(path),)
            ).fetchone()
            media_root = (home / "media").resolve()
            if not shared and media_root in path.parents and path.is_file():
                path.unlink(missing_ok=True)
                removed_files.append(str(path))
    _remove_empty_media_directories(home)
    if removed_files:
        invalidate_storage_usage(home)
    return {
        "media_rows_deleted": len(removed_rows),
        "media_files_deleted": len(removed_files),
        "deleted_media_ids": removed_rows,
    }


def audit_orphaned_media(home: Path) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute("SELECT media_id,local_path FROM media_assets").fetchall()
        unreferenced = []
        missing = []
        registered_paths = set()
        for row in rows:
            media_id = str(row["media_id"])
            path = Path(str(row["local_path"])).resolve()
            registered_paths.add(path)
            if not path.is_file():
                missing.append(media_id)
            binding = conn.execute(
                "SELECT 1 FROM media_bindings WHERE media_id=? LIMIT 1", (media_id,)
            ).fetchone()
            attachment = conn.execute(
                "SELECT 1 FROM study_thread_attachments WHERE media_id=? LIMIT 1",
                (media_id,),
            ).fetchone()
            lease = conn.execute(
                "SELECT 1 FROM audio_playback_leases WHERE media_id=? LIMIT 1",
                (media_id,),
            ).fetchone()
            if not binding and not attachment and not lease:
                unreferenced.append(media_id)
    media_root = (home / "media").resolve()
    disk_orphans = [
        str(path)
        for path in media_root.rglob("*")
        if path.is_file() and path.resolve() not in registered_paths
    ] if media_root.is_dir() else []
    return {
        "registered": len(rows),
        "unreferenced_media_ids": unreferenced,
        "missing_media_ids": missing,
        "orphan_files": disk_orphans,
    }


def purge_deleted_storage(home: Path) -> dict[str, Any]:
    """Explicit privacy maintenance: collect orphans and rewrite free DB pages."""
    deleted_threads = cleanup_deleted_thread_storage(home)
    media = purge_unreferenced_media(home)
    with connect(home) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with connect(home) as conn:
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
    return {
        "database_compacted": True,
        "deleted_thread_directories": deleted_threads,
        **media,
    }


def cleanup_deleted_thread_storage(home: Path) -> int:
    """Retry removal of thread directories tombstoned by an earlier deletion."""
    root = (home / "study-threads" / ".deleted").resolve()
    expected_parent = (home / "study-threads").resolve()
    if root.parent != expected_parent or not root.is_dir():
        return 0
    removed = 0
    for path in list(root.iterdir()):
        resolved = path.resolve()
        if resolved.parent != root:
            continue
        try:
            if resolved.is_dir():
                shutil.rmtree(resolved)
            elif resolved.is_file():
                resolved.unlink()
            removed += 1
        except OSError:
            continue
    try:
        root.rmdir()
    except OSError:
        pass
    if removed:
        invalidate_storage_usage(home)
    return removed


def _thread_run_ids(conn: Any, thread_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT run_id,study_thread_id,request_json FROM agent_runs"
    ).fetchall()
    found: list[str] = []
    for row in rows:
        if str(row["study_thread_id"] or "") == thread_id:
            found.append(str(row["run_id"]))
            continue
        try:
            request = json.loads(row["request_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if str(request.get("study_thread_id") or "") == thread_id:
            found.append(str(row["run_id"]))
    return found


def _remove_empty_media_directories(home: Path) -> None:
    root = (home / "media").resolve()
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and path != root:
            try:
                path.rmdir()
            except OSError:
                pass


def wipe_learner_data(home: Path, *, confirmed: bool = False) -> dict[str, Any]:
    """Delete every learner-generated record while keeping app configuration.

    Removes the SQLite database, all managed study/content roots, and the
    learning profile. Keeps ``config/settings.yaml`` (model connections) and
    any existing backups. The database is recreated empty, so the next launch
    re-enters onboarding instead of showing stale progress.
    """
    if not confirmed:
        raise ValueError("Wiping all learner data requires explicit confirmation")
    home = home.resolve()
    removed: list[str] = []

    database_dir = home / "database"
    if database_dir.is_dir():
        shutil.rmtree(database_dir)
        removed.append("database")

    from .backups import MANAGED_ROOTS

    for root in MANAGED_ROOTS:
        if root == "config":
            continue
        target = (home / root).resolve()
        if target.parent != home or home not in target.parents:
            raise ValueError(f"Managed data path escapes IELTS_HOME: {root}")
        if target.is_symlink():
            target.unlink()
            removed.append(root)
        elif target.is_dir():
            shutil.rmtree(target)
            removed.append(root)

    profile_path = home / "config" / "profile.yaml"
    if profile_path.is_file():
        profile_path.unlink()
        removed.append("config/profile.yaml")

    initialise_database(home)
    invalidate_storage_usage(home)
    return {"wiped": True, "removed": removed}
