from __future__ import annotations

import hashlib
import io
import uuid
import wave
from pathlib import Path
from typing import Any

from .errors import MediaError, MediaNotFoundError
from .storage import get_media_asset, register_media_asset


MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_AUDIO_BYTES = 500 * 1024 * 1024
MAX_MEDIA_PIXELS = 40_000_000
ALLOWED_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
}
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
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


def import_audio_bytes(
    home: Path,
    content: bytes,
    *,
    filename: str,
    mime_type: str,
    duration_seconds: float | None = None,
    transcript: str | None = None,
    timestamps: list[dict[str, Any]] | None = None,
    owner_type: str | None = None,
    owner_id: str | None = None,
    privacy_status: str = "local_only",
    allow_agent_processing: bool = False,
) -> dict[str, Any]:
    """Register user-owned IELTS audio without exposing arbitrary local paths."""
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise MediaError(f"Audio must be between 1 byte and {MAX_AUDIO_BYTES} bytes")
    normalised_mime = mime_type.split(";", 1)[0].strip().casefold()
    suffix = ALLOWED_AUDIO_TYPES.get(normalised_mime)
    if not suffix:
        raise MediaError("Only MP3, WAV, M4A and OGG audio is supported")
    detected_duration = duration_seconds
    if suffix == ".wav":
        try:
            with wave.open(io.BytesIO(content), "rb") as stream:
                rate = stream.getframerate()
                detected_duration = stream.getnframes() / rate if rate else None
        except (wave.Error, EOFError) as exc:
            raise MediaError("The uploaded WAV file is unreadable") from exc
    if detected_duration is None or float(detected_duration) <= 0:
        raise MediaError("Audio duration_seconds is required when it cannot be read locally")
    clean_timestamps = timestamps or []
    for item in clean_timestamps:
        start = float(item.get("start_seconds", -1))
        end = float(item.get("end_seconds", -1))
        if start < 0 or end < start or end > float(detected_duration):
            raise MediaError("Transcript timestamps must fall within the audio duration")
    digest = hashlib.sha256(content).hexdigest()
    folder = (home / "media" / digest[:2]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest}{suffix}"
    if not target.exists():
        target.write_bytes(content)
    return register_media_asset(
        home,
        {
            "media_id": f"audio_{uuid.uuid4().hex}",
            "owner_type": owner_type,
            "owner_id": owner_id,
            "media_type": "audio",
            "mime_type": normalised_mime,
            "local_path": str(target),
            "content_hash": digest,
            "alt_text": filename.strip() or "IELTS Listening audio",
            "privacy_status": privacy_status,
            "metadata": {
                "original_name": filename,
                "size_bytes": len(content),
                "duration_seconds": round(float(detected_duration), 3),
                "transcript": transcript,
                "timestamps": clean_timestamps,
                "allow_agent_processing": bool(allow_agent_processing),
            },
        },
    )
