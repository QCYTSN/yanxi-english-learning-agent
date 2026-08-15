"""
Render the Yanxi app icon from the canonical seal SVG.

Single source of truth: docs/assets/yanxi-logo.svg (the user-approved design
with KaiTi/STKaiti system fonts). This script rasterises a 512px master PNG,
derives all app-icon PNG copies, and hand-assembles a multi-frame ICO
(Pillow's ICO encoder is buggy for >1 size, so we build the ICO by hand with
PNG-embedded frames, which Vista+ supports).

Run:
    python scripts/render_app_icon.py
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

import cairosvg
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SOURCE_SVG = REPO / "docs" / "assets" / "yanxi-logo.svg"

# 512px master is the icon visual; we crop to the seal block (230,84)-(450,304)
# in the 680x500 viewBox so the desktop icon is the seal, not the whole card.
MASTER_PX = 512
VIEW_W, VIEW_H = 680, 500
SEAL_X, SEAL_Y, SEAL_W, SEAL_H = 230, 84, 220, 220

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# target app-icon copies
TARGETS_PNG = [
    REPO / "frontend" / "public" / "app-icon.png",
    REPO / "src" / "ielts_coach" / "resources" / "assets" / "app-icon.png",
    REPO / "src" / "ielts_coach" / "web" / "static" / "app-icon.png",
]
TARGET_ICO = REPO / "src" / "ielts_coach" / "resources" / "assets" / "app-icon.ico"


def render_master() -> Image.Image:
    """Render the full SVG at 2x viewBox, crop to the seal block."""
    scale = (MASTER_PX * 2) / VIEW_W  # oversample for crisp crop
    png_bytes = cairosvg.svg2png(
        url=str(SOURCE_SVG),
        output_width=int(VIEW_W * scale),
        output_height=int(VIEW_H * scale),
    )
    full = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # crop region for the seal block
    left = int(SEAL_X * scale)
    top = int(SEAL_Y * scale)
    right = int((SEAL_X + SEAL_W) * scale)
    bottom = int((SEAL_Y + SEAL_H) * scale)
    seal = full.crop((left, top, right, bottom))
    # square + upscale to master
    seal = seal.resize((MASTER_PX, MASTER_PX), Image.LANCZOS)
    return seal


def build_ico(master: Image.Image, path: Path) -> None:
    """Hand-assemble a multi-frame ICO with PNG-embedded frames."""
    frames: list[bytes] = []
    for size in ICO_SIZES:
        buf = io.BytesIO()
        img = master.resize((size, size), Image.LANCZOS)
        img.save(buf, format="PNG")
        frames.append((size, buf.getvalue()))

    # ICONDIR (6 bytes) + ICONDIRENTRY (16 bytes each) + image data
    header = struct.pack("<HHH", 0, 1, len(frames))
    entries = b""
    offset = 6 + 16 * len(frames)
    for size, data in frames:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,  # width (0 = 256)
            size if size < 256 else 0,  # height
            0,  # palette
            0,  # reserved
            1,  # planes
            32,  # bpp
            len(data),  # bytes
            offset,  # offset
        )
        offset += len(data)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(d for _, d in frames))


def main() -> None:
    if not SOURCE_SVG.exists():
        raise SystemExit(f"source SVG not found: {SOURCE_SVG}")
    master = render_master()
    master.save(TARGETS_PNG[1])  # resources/assets is the canonical master
    for target in TARGETS_PNG:
        target.parent.mkdir(parents=True, exist_ok=True)
        master.save(target)
        print(f"wrote {target.relative_to(REPO)} ({target.stat().st_size} bytes)")
    build_ico(master, TARGET_ICO)
    print(f"wrote {TARGET_ICO.relative_to(REPO)} ({TARGET_ICO.stat().st_size} bytes)")


if __name__ == "__main__":
    main()