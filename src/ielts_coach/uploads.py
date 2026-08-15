from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Iterable

from .storage_quota import local_storage_status


UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class StagedUpload:
    original_name: str
    path: Path
    mime_type: str | None
    size_bytes: int
    sha256: str


async def stage_uploads(
    home: Path,
    uploads: Iterable[Any],
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    max_files: int | None = None,
    allowed_suffixes: set[str] | None = None,
) -> tuple[Path, list[StagedUpload]]:
    """Stream framework UploadFile objects into a private, bounded staging area."""
    items = list(uploads)
    if max_files is not None and len(items) > max_files:
        raise ValueError(f"A request can contain at most {max_files} files")
    stage = home / "runtime" / "uploads" / uuid.uuid4().hex
    stage.mkdir(parents=True, exist_ok=False)
    staged: list[StagedUpload] = []
    total = 0
    writable_bytes = int(local_storage_status(home)["writable_bytes"])
    try:
        for index, upload in enumerate(items):
            original_name = str(getattr(upload, "filename", None) or "upload")
            suffix = Path(original_name).suffix.casefold()
            if allowed_suffixes is not None and suffix not in allowed_suffixes:
                raise ValueError(f"Unsupported file type: {suffix or 'none'}")
            target = stage / f"{index:03d}.part"
            digest = hashlib.sha256()
            size = 0
            with target.open("xb") as handle:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    size += len(chunk)
                    total += len(chunk)
                    if size > max_file_bytes:
                        raise ValueError(
                            f"File exceeds the {max_file_bytes} byte limit: {original_name}"
                        )
                    if total > max_total_bytes:
                        raise ValueError(
                            f"Uploads exceed the {max_total_bytes} byte request limit"
                        )
                    if total > writable_bytes:
                        raise ValueError(
                            "Not enough managed local storage is available for this upload"
                        )
                    handle.write(chunk)
                    digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size <= 0:
                raise ValueError(f"Uploaded file is empty: {original_name}")
            staged.append(
                StagedUpload(
                    original_name=original_name,
                    path=target,
                    mime_type=getattr(upload, "content_type", None),
                    size_bytes=size,
                    sha256=digest.hexdigest(),
                )
            )
            await upload.close()
        return stage, staged
    except Exception:
        for upload in items:
            try:
                await upload.close()
            except Exception:
                pass
        cleanup_staging(stage)
        raise


def read_zip_member(
    path: Path,
    member: str,
    *,
    max_bytes: int = MAX_ZIP_MEMBER_BYTES,
) -> bytes:
    """Read one zip member with a decompressed-size guard.

    Zip-bomb defence: members whose declared uncompressed size exceeds
    max_bytes are rejected before any bytes are read into memory.
    """
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(member)
        if info.file_size > max_bytes:
            raise ValueError(
                f"Zip member {member!r} is {info.file_size} bytes; "
                f"the limit is {max_bytes} bytes"
            )
        return archive.read(member)


def hash_file(path: Path, *, chunk_size: int = UPLOAD_CHUNK_BYTES) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=UPLOAD_CHUNK_BYTES)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_staging(path: Path) -> None:
    resolved = path.resolve()
    if resolved.name and resolved.parent.name == "uploads" and resolved.is_dir():
        shutil.rmtree(resolved)


def cleanup_stale_uploads(home: Path, *, older_than_seconds: int = 24 * 3600) -> int:
    root = (home / "runtime" / "uploads").resolve()
    if not root.is_dir():
        return 0
    cutoff = time.time() - max(60, int(older_than_seconds))
    removed = 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if modified < cutoff:
            cleanup_staging(path)
            removed += 1
    return removed
