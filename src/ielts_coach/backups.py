from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from filelock import FileLock

from . import __version__
from .storage import db_path


BACKUP_FORMAT_VERSION = 1
BACKUP_PREFIX = "ielts-backup-"
MANAGED_ROOTS = (
    "config",
    "corpus",
    "sessions",
    "study-threads",
    "story-bank",
    "reports",
    "calibration",
    "media",
)
MAX_ARCHIVE_FILES = 200_000
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024 * 1024


def create_backup(
    home: Path,
    *,
    kind: str = "manual",
    allow_missing_database: bool = False,
) -> dict[str, Any]:
    home = home.resolve()
    backup_dir = home / "backups"
    lock_dir = home / "runtime" / "locks"
    backup_dir.mkdir(parents=True, exist_ok=True)
    lock_dir.mkdir(parents=True, exist_ok=True)
    safe_kind = _safe_label(kind)
    created_at = datetime.now(timezone.utc)
    backup_id = (
        f"{BACKUP_PREFIX}{created_at.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{safe_kind}-{uuid.uuid4().hex[:8]}"
    )
    final_path = backup_dir / f"{backup_id}.zip"

    with FileLock(str(lock_dir / "backup.lock"), timeout=30):
        with tempfile.TemporaryDirectory(prefix=".backup-stage-", dir=backup_dir) as temporary:
            stage = Path(temporary)
            payload = stage / "payload"
            payload.mkdir()
            database_relative_path, integrity = _snapshot_database(
                home, payload, allow_missing=allow_missing_database
            )
            _copy_managed_files(home, payload)
            files = _inventory(payload)
            schema_version = _database_schema_version(
                payload / database_relative_path if database_relative_path else None
            )
            manifest = {
                "backup_format_version": BACKUP_FORMAT_VERSION,
                "backup_id": backup_id,
                "kind": safe_kind,
                "created_at": created_at.isoformat(),
                "app_version": __version__,
                "source_home": str(home),
                "schema_version": schema_version,
                "database_relative_path": database_relative_path,
                "database_integrity": integrity,
                "managed_roots": list(MANAGED_ROOTS),
                "files": files,
            }
            manifest_path = stage / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_zip = stage / "backup.zip"
            with zipfile.ZipFile(
                temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.write(manifest_path, "manifest.json")
                for item in files:
                    relative = str(item["path"])
                    archive.write(payload / Path(relative), f"payload/{PurePosixPath(relative)}")
            os.replace(temporary_zip, final_path)
    return {**manifest, "path": str(final_path), "size_bytes": final_path.stat().st_size}


def list_backups(home: Path) -> list[dict[str, Any]]:
    folder = home.resolve() / "backups"
    if not folder.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.glob(f"{BACKUP_PREFIX}*.zip"), reverse=True):
        try:
            manifest = _read_manifest(path)
            rows.append(
                {
                    "backup_id": manifest.get("backup_id") or path.stem,
                    "kind": manifest.get("kind", "unknown"),
                    "created_at": manifest.get("created_at"),
                    "app_version": manifest.get("app_version"),
                    "schema_version": manifest.get("schema_version"),
                    "file_count": len(manifest.get("files") or []),
                    "size_bytes": path.stat().st_size,
                    "status": "available",
                    "path": str(path),
                }
            )
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            rows.append(
                {
                    "backup_id": path.stem,
                    "kind": "unknown",
                    "created_at": None,
                    "file_count": 0,
                    "size_bytes": path.stat().st_size,
                    "status": "invalid",
                    "error": str(exc),
                    "path": str(path),
                }
            )
    return rows


def verify_backup(
    home: Path,
    backup: str | Path,
    *,
    allow_external_path: bool = True,
) -> dict[str, Any]:
    path = _resolve_backup(home, backup, allow_external_path=allow_external_path)
    manifest = _read_manifest(path)
    expected = manifest.get("files")
    if not isinstance(expected, list):
        raise ValueError("Backup manifest does not contain a file inventory")
    if len(expected) > MAX_ARCHIVE_FILES:
        raise ValueError("Backup contains too many files")
    expected_by_path: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for item in expected:
        if not isinstance(item, dict):
            raise ValueError("Backup file inventory contains an invalid entry")
        relative = _safe_relative_path(str(item.get("path", "")))
        if relative in expected_by_path:
            raise ValueError(f"Backup inventory contains duplicate path: {relative}")
        size = int(item.get("size_bytes", -1))
        if size < 0:
            raise ValueError(f"Backup inventory has invalid size: {relative}")
        total_bytes += size
        expected_by_path[relative] = item
    if total_bytes > MAX_ARCHIVE_BYTES:
        raise ValueError("Backup expands beyond the supported size limit")

    with zipfile.ZipFile(path) as archive:
        archive_files: dict[str, zipfile.ZipInfo] = {}
        for info in archive.infolist():
            if info.is_dir() or info.filename == "manifest.json":
                continue
            relative = _payload_relative(info.filename)
            if relative in archive_files:
                raise ValueError(f"Backup archive contains duplicate path: {relative}")
            archive_files[relative] = info
        if set(archive_files) != set(expected_by_path):
            missing = sorted(set(expected_by_path) - set(archive_files))
            extra = sorted(set(archive_files) - set(expected_by_path))
            raise ValueError(f"Backup inventory mismatch: missing={missing[:5]}, extra={extra[:5]}")
        for relative, item in expected_by_path.items():
            info = archive_files[relative]
            if info.file_size != int(item["size_bytes"]):
                raise ValueError(f"Backup size mismatch: {relative}")
            with archive.open(info) as handle:
                digest = _hash_stream(handle)
            if digest != item.get("sha256"):
                raise ValueError(f"Backup hash mismatch: {relative}")

        database_relative = manifest.get("database_relative_path")
        integrity = "not_present"
        if database_relative:
            database_relative = _safe_relative_path(str(database_relative))
            if database_relative not in archive_files:
                raise ValueError("Backup database is not present in the file inventory")
            with tempfile.TemporaryDirectory(prefix="ielts-backup-verify-") as temporary:
                database_path = Path(temporary) / Path(database_relative).name
                with archive.open(archive_files[database_relative]) as source:
                    with database_path.open("wb") as target:
                        shutil.copyfileobj(source, target)
                integrity = _sqlite_integrity(database_path)
                if integrity != "ok":
                    raise ValueError(f"Backup database integrity check failed: {integrity}")
        with tempfile.TemporaryDirectory(prefix="ielts-backup-audit-") as temporary:
            audit_home = Path(temporary)
            _extract_payload(path, audit_home)
            _rebase_restored_paths(
                audit_home,
                source_home=str(manifest.get("source_home") or ""),
            )
            from .health import audit_data_home

            consistency = audit_data_home(
                audit_home,
                expected_schema_version=str(manifest.get("schema_version") or "legacy"),
                require_configuration=any(
                    str(item["path"]).startswith("config/")
                    for item in expected
                ),
            )
            if consistency["status"] == "failed":
                raise ValueError(
                    "Backup cross-store audit failed: "
                    + "; ".join(consistency["errors"])
                )
    return {
        "backup_id": manifest["backup_id"],
        "valid": True,
        "path": str(path),
        "created_at": manifest.get("created_at"),
        "kind": manifest.get("kind"),
        "schema_version": manifest.get("schema_version"),
        "file_count": len(expected_by_path),
        "payload_bytes": total_bytes,
        "database_integrity": integrity,
        "consistency": consistency,
    }


def restore_backup(
    home: Path,
    backup: str | Path,
    *,
    confirmed: bool = False,
    allow_external_path: bool = True,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("Restore requires explicit confirmation")
    home = home.resolve()
    path = _resolve_backup(home, backup, allow_external_path=allow_external_path)
    verification = verify_backup(home, path, allow_external_path=True)
    lock_dir = home / "runtime" / "locks"
    backup_dir = home / "backups"
    lock_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    with FileLock(str(lock_dir / "restore.lock"), timeout=30):
        safety = create_backup(home, kind="pre-restore", allow_missing_database=True)
        with tempfile.TemporaryDirectory(prefix=".restore-stage-", dir=backup_dir) as temporary:
            stage = Path(temporary)
            payload = stage / "payload"
            payload.mkdir()
            _extract_payload(path, payload)
            roots = list(MANAGED_ROOTS)
            quarantine = stage / "previous"
            quarantine.mkdir()
            moved_old: list[str] = []
            installed_new: list[str] = []
            database_attempted = False
            try:
                for root in roots:
                    target = _managed_target(home, root)
                    restored = payload / root
                    # Older backups may not contain roots introduced by later
                    # releases. Preserve the current root instead of deleting
                    # it when the archive has no replacement.
                    if not restored.exists():
                        continue
                    if target.exists():
                        previous = quarantine / root
                        previous.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(target, previous)
                        moved_old.append(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(restored, target)
                    installed_new.append(root)
                database_relative = _read_manifest(path).get("database_relative_path")
                if not database_relative:
                    raise ValueError("A restorable IELTS backup must contain a database")
                database_relative = _safe_relative_path(str(database_relative))
                database_attempted = True
                _install_database(payload / database_relative, home / database_relative)
                _rebase_restored_paths(
                    home,
                    source_home=str(_read_manifest(path).get("source_home") or ""),
                )
                from .storage import initialise_database
                from .health import require_healthy_data_home

                initialise_database(home)
                post_restore_health = require_healthy_data_home(home)
            except Exception:
                for root in reversed(installed_new):
                    target = _managed_target(home, root)
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists():
                        target.unlink()
                for root in reversed(moved_old):
                    previous = quarantine / root
                    if previous.exists():
                        target = _managed_target(home, root)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(previous, target)
                if database_attempted:
                    _install_database_from_archive(Path(str(safety["path"])), home)
                raise
    return {
        **verification,
        "restored": True,
        "safety_backup_id": safety["backup_id"],
        "restart_recommended": True,
        "post_restore_health": post_restore_health,
    }


def _snapshot_database(
    home: Path, payload: Path, *, allow_missing: bool
) -> tuple[str | None, str]:
    source_path = db_path(home)
    if not source_path.is_file():
        if allow_missing:
            return None, "not_present"
        raise FileNotFoundError(f"IELTS database not found: {source_path}")
    relative = Path("database") / source_path.name
    destination_path = payload / relative
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.execute("PRAGMA busy_timeout = 5000")
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    integrity = _sqlite_integrity(destination_path)
    if integrity != "ok":
        raise ValueError(f"Database snapshot integrity check failed: {integrity}")
    return relative.as_posix(), integrity


def _copy_managed_files(home: Path, payload: Path) -> None:
    for root in MANAGED_ROOTS:
        source_root = _managed_target(home, root)
        if not source_root.exists():
            continue
        if source_root.is_symlink():
            raise ValueError(f"Managed data root cannot be a symbolic link: {source_root}")
        for source in sorted(source_root.rglob("*")):
            if source.is_dir():
                continue
            if source.is_symlink():
                raise ValueError(f"Backup refuses symbolic links: {source}")
            relative = source.relative_to(home)
            destination = payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _inventory(payload: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in payload.rglob("*") if item.is_file()):
        relative = path.relative_to(payload).as_posix()
        rows.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _hash_file(path),
            }
        )
    return rows


def _extract_payload(archive_path: Path, payload: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.filename == "manifest.json":
                continue
            relative = _payload_relative(info.filename)
            destination = payload / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)


def _install_database(source_path: Path, target_path: Path) -> None:
    if not source_path.is_file():
        raise ValueError("Restored payload does not contain its declared database")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(target_path)
    try:
        destination.execute("PRAGMA busy_timeout = 5000")
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    integrity = _sqlite_integrity(target_path)
    if integrity != "ok":
        raise ValueError(f"Restored database integrity check failed: {integrity}")


def _install_database_from_archive(archive_path: Path, home: Path) -> None:
    manifest = _read_manifest(archive_path)
    relative = manifest.get("database_relative_path")
    if not relative:
        return
    relative = _safe_relative_path(str(relative))
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo(f"payload/{relative}")
        with tempfile.TemporaryDirectory(prefix="ielts-db-rollback-") as temporary:
            source_path = Path(temporary) / Path(relative).name
            with archive.open(info) as source, source_path.open("wb") as target:
                shutil.copyfileobj(source, target)
            _install_database(source_path, home / relative)


def _rebase_restored_paths(home: Path, *, source_home: str) -> None:
    database = db_path(home)
    if not database.is_file():
        return
    source_root = Path(source_home).resolve() if source_home else None
    media_root = (home / "media").resolve()
    conn = sqlite3.connect(database)
    try:
        conn.row_factory = sqlite3.Row
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "media_assets" in tables:
            for row in conn.execute(
                "SELECT media_id,local_path,content_hash FROM media_assets"
            ).fetchall():
                old_path = Path(str(row["local_path"]))
                candidate: Path | None = None
                if source_root:
                    try:
                        relative = old_path.resolve().relative_to(source_root)
                        mapped = (home / relative).resolve()
                        if mapped.is_file():
                            candidate = mapped
                    except ValueError:
                        pass
                if candidate is None:
                    matches = list(media_root.rglob(f"{row['content_hash']}.*"))
                    candidate = matches[0].resolve() if matches else None
                if candidate is not None:
                    conn.execute(
                        "UPDATE media_assets SET local_path=? WHERE media_id=?",
                        (str(candidate), row["media_id"]),
                    )
        if "corpora" in tables and source_root:
            for row in conn.execute(
                "SELECT corpus_id,local_path,manifest_json FROM corpora"
            ).fetchall():
                manifest = json.loads(row["manifest_json"])
                storage = manifest.get("storage") or {}
                changed = False
                local_path = row["local_path"]
                new_local_path = local_path
                for key in ("local_path", "resolved_base_path"):
                    value = storage.get(key)
                    mapped = _rebase_path_value(value, source_root, home)
                    if mapped != value:
                        storage[key] = mapped
                        changed = True
                mapped_local = _rebase_path_value(local_path, source_root, home)
                if mapped_local != local_path:
                    new_local_path = mapped_local
                    changed = True
                if changed:
                    manifest["storage"] = storage
                    conn.execute(
                        "UPDATE corpora SET local_path=?,manifest_json=? WHERE corpus_id=?",
                        (
                            new_local_path,
                            json.dumps(manifest, ensure_ascii=False),
                            row["corpus_id"],
                        ),
                    )
        conn.commit()
    finally:
        conn.close()
    if source_root:
        for manifest_path in (home / "corpus" / "manifests").glob("*.yaml"):
            try:
                import yaml

                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                storage = manifest.get("storage") or {}
                changed = False
                for key in ("local_path", "resolved_base_path"):
                    value = storage.get(key)
                    mapped = _rebase_path_value(value, source_root, home)
                    if mapped != value:
                        storage[key] = mapped
                        changed = True
                if changed:
                    manifest["storage"] = storage
                    manifest_path.write_text(
                        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
                        encoding="utf-8",
                    )
            except (OSError, ValueError):
                continue


def _rebase_path_value(
    value: Any,
    source_root: Path,
    target_root: Path,
) -> Any:
    if not value:
        return value
    try:
        relative = Path(str(value)).resolve().relative_to(source_root)
    except ValueError:
        return value
    return str((target_root / relative).resolve())


def _read_manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        try:
            raw = archive.read("manifest.json")
        except KeyError as exc:
            raise ValueError("Backup does not contain manifest.json") from exc
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Backup manifest must be an object")
    if data.get("backup_format_version") != BACKUP_FORMAT_VERSION:
        raise ValueError("Unsupported backup format version")
    backup_id = str(data.get("backup_id", ""))
    if not re.fullmatch(r"ielts-backup-[A-Za-z0-9_-]+", backup_id):
        raise ValueError("Backup manifest has an invalid backup_id")
    return data


def _resolve_backup(
    home: Path,
    backup: str | Path,
    *,
    allow_external_path: bool,
) -> Path:
    value = Path(backup)
    if not allow_external_path:
        backup_id = value.name.removesuffix(".zip")
        if value.parent != Path(".") or not re.fullmatch(r"ielts-backup-[A-Za-z0-9_-]+", backup_id):
            raise ValueError("The local API accepts a stored backup ID only")
        path = (home.resolve() / "backups" / f"{backup_id}.zip").resolve()
    elif value.is_absolute() or value.parent != Path("."):
        path = value.expanduser().resolve()
    else:
        name = value.name
        if not name.endswith(".zip"):
            name += ".zip"
        path = (home.resolve() / "backups" / name).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Backup not found: {path}")
    return path


def _managed_target(home: Path, root: str) -> Path:
    if root not in {*MANAGED_ROOTS, "database"}:
        raise ValueError(f"Unsupported managed root: {root}")
    target = (home / root).resolve()
    if target.parent != home and home not in target.parents:
        raise ValueError("Managed data path escapes IELTS_HOME")
    return target


def _payload_relative(name: str) -> str:
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] != "payload":
        raise ValueError(f"Unexpected backup entry: {name}")
    return _safe_relative_path(PurePosixPath(*path.parts[1:]).as_posix())


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"Unsafe backup path: {value!r}")
    if path.parts[0] not in {*MANAGED_ROOTS, "database"}:
        raise ValueError(f"Backup path is outside managed data roots: {value}")
    return path.as_posix()


def _hash_file(path: Path) -> str:
    with path.open("rb") as handle:
        return _hash_stream(handle)


def _hash_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sqlite_integrity(path: Path) -> str:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        row = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        return f"database_error:{exc}"
    finally:
        if connection is not None:
            connection.close()
    return str(row[0]) if row else "no_result"


def _database_schema_version(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if not table:
            return "legacy"
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        return str(row[0]) if row else "legacy"
    except sqlite3.DatabaseError:
        return None
    finally:
        if connection is not None:
            connection.close()


def _safe_label(value: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:40]
    return label or "manual"
