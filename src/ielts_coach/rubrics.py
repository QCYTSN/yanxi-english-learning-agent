from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import connect, initialise_database
from .validation import validate_data


DEFAULT_RUBRICS = (
    {
        "rubric_id": "ielts-writing-public-descriptors",
        "module": "writing",
        "publisher": "IELTS",
        "standard": "IELTS Writing Band Descriptors",
        "version": "updated-2023",
        "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf",
        "local_path": None,
        "permissions": {"bundled": False, "redistribution_allowed": False},
    },
    {
        "rubric_id": "ielts-speaking-public-descriptors",
        "module": "speaking",
        "publisher": "IELTS",
        "standard": "IELTS Speaking Band Descriptors",
        "version": None,
        "source_reference": "https://ielts.org/cdn/ielts-guides/ielts-speaking-band-descriptors.pdf",
        "local_path": None,
        "permissions": {"bundled": False, "redistribution_allowed": False},
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def register_rubric(home: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_data(manifest, "rubric-manifest")
    local_path_value = manifest.get("local_path")
    content_hash: str | None = None
    availability = "reference_only"
    if local_path_value:
        local_path = Path(str(local_path_value)).expanduser()
        if not local_path.is_absolute():
            local_path = (home / local_path).resolve()
        if local_path.is_file():
            content_hash = _sha256(local_path)
            expected = manifest.get("expected_sha256")
            if expected and content_hash.casefold() != str(expected).casefold():
                raise ValueError("Rubric file SHA-256 does not match expected_sha256")
            availability = "local_verified"
        else:
            availability = "local_missing"
        manifest["local_path"] = str(local_path)
    now = _now()
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO rubric_registry(
              rubric_id,module,publisher,standard,version,source_reference,local_path,
              content_hash,availability,permissions_json,manifest_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(rubric_id) DO UPDATE SET
              module=excluded.module,publisher=excluded.publisher,standard=excluded.standard,
              version=excluded.version,source_reference=excluded.source_reference,
              local_path=excluded.local_path,content_hash=excluded.content_hash,
              availability=excluded.availability,permissions_json=excluded.permissions_json,
              manifest_json=excluded.manifest_json,updated_at=excluded.updated_at
            """,
            (
                manifest["rubric_id"], manifest["module"], manifest["publisher"],
                manifest["standard"], manifest.get("version"), manifest["source_reference"],
                manifest.get("local_path"), content_hash, availability,
                json.dumps(manifest.get("permissions") or {}, ensure_ascii=False),
                json.dumps(manifest, ensure_ascii=False), now, now,
            ),
        )
    return {**manifest, "availability": availability, "content_hash": content_hash}


def ensure_default_rubrics(home: Path) -> None:
    for manifest in DEFAULT_RUBRICS:
        register_rubric(home, dict(manifest))


def list_rubrics(home: Path) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT rubric_id,module,publisher,standard,version,source_reference,
                   local_path,content_hash,availability,updated_at
            FROM rubric_registry ORDER BY module,rubric_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_rubric(home: Path, rubric_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute("SELECT * FROM rubric_registry WHERE rubric_id=?", (rubric_id,)).fetchone()
    return dict(row) if row else None


def require_rubric(home: Path, rubric_id: str, module: str) -> dict[str, Any]:
    row = get_rubric(home, rubric_id)
    if not row:
        raise ValueError(f"Rubric is not registered: {rubric_id}")
    if row["module"] != module:
        raise ValueError(f"Rubric {rubric_id} is registered for {row['module']}, not {module}")
    if row["availability"] == "local_missing":
        raise ValueError(f"Rubric local file is missing: {row['local_path']}")
    return row
