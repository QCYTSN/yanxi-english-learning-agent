from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path
from typing import Any

from .errors import MediaError, MediaNotFoundError
from .storage import get_media_asset, register_media_asset


MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_MEDIA_PIXELS = 40_000_000
ALLOWED_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
}


def import_image_bytes(
    home: Path,
    content: bytes,
    *,
    alt_text: str,
    owner_type: str | None = None,
    owner_id: str | None = None,
    privacy_status: str = "local_only",
) -> dict[str, Any]:
    if not content or len(content) > MAX_MEDIA_BYTES:
        raise MediaError(f"Image must be between 1 byte and {MAX_MEDIA_BYTES} bytes")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise MediaError("Image support requires the optional ui dependency") from exc
    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaError("The uploaded file is not a readable image") from exc
    if image_format not in ALLOWED_FORMATS:
        raise MediaError("Only PNG, JPEG and WebP images are supported")
    if width <= 0 or height <= 0 or width * height > MAX_MEDIA_PIXELS:
        raise MediaError("Image pixel dimensions exceed the supported limit")
    mime_type, suffix = ALLOWED_FORMATS[image_format]
    digest = hashlib.sha256(content).hexdigest()
    folder = (home / "media" / digest[:2]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest}{suffix}"
    if not target.exists():
        target.write_bytes(content)
    return register_media_asset(
        home,
        {
            "media_id": f"media_{uuid.uuid4().hex}",
            "owner_type": owner_type,
            "owner_id": owner_id,
            "media_type": "image",
            "mime_type": mime_type,
            "local_path": str(target),
            "content_hash": digest,
            "width": width,
            "height": height,
            "alt_text": alt_text.strip() or "IELTS Task 1 visual",
            "privacy_status": privacy_status,
            "metadata": {"format": image_format, "size_bytes": len(content)},
        },
    )


def resolve_media_file(home: Path, media_id: str) -> tuple[dict[str, Any], Path]:
    asset = get_media_asset(home, media_id)
    if not asset:
        raise MediaNotFoundError(f"Unknown media asset: {media_id}")
    root = (home / "media").resolve()
    path = Path(str(asset["local_path"])).resolve()
    if root not in path.parents or not path.is_file():
        raise MediaNotFoundError("Registered media file is unavailable")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != asset["content_hash"]:
        raise MediaError("Registered media hash no longer matches the file")
    return asset, path

