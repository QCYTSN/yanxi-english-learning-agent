from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--scale", type=float, default=2.2)
    parser.add_argument("--rec-model")
    args = parser.parse_args()

    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageOps
    from rapidocr_onnxruntime import RapidOCR

    pages = sorted({
        int(value)
        for value in args.pages.split(",")
        if value.strip()
    })
    engine = (
        RapidOCR(rec_model_path=args.rec_model)
        if args.rec_model
        else RapidOCR()
    )
    results: dict[str, dict[str, object]] = {}
    input_path = Path(args.input)
    is_pdf = input_path.suffix.casefold() == ".pdf"
    document = pdfium.PdfDocument(args.input) if is_pdf else None
    try:
        for page_number in pages:
            if document is not None:
                page = document[page_number - 1]
                bitmap = page.render(
                    scale=max(1.0, min(float(args.scale), 4.0))
                )
                try:
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
                    page.close()
            else:
                if page_number != 1:
                    raise ValueError("Image OCR only supports page 1")
                with Image.open(input_path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
            raw_result, _ = engine(np.asarray(image))
            lines: list[str] = []
            scores: list[float] = []
            layout_lines: list[dict[str, object]] = []
            for item in raw_result or []:
                if len(item) < 3:
                    continue
                text = str(item[1]).strip()
                if not text:
                    continue
                lines.append(text)
                box = [
                    [round(float(point[0]), 2), round(float(point[1]), 2)]
                    for point in item[0]
                ]
                layout_lines.append({
                    "text": text,
                    "box": box,
                    "score": round(float(item[2]), 4),
                })
                try:
                    scores.append(float(item[2]))
                except (TypeError, ValueError):
                    pass
            results[str(page_number)] = {
                "text": "\n".join(lines),
                "confidence": (
                    round(sum(scores) / len(scores), 4)
                    if scores
                    else None
                ),
                "layout_lines": layout_lines,
            }
    finally:
        if document is not None:
            document.close()
    Path(args.output).write_text(
        json.dumps({"pages": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
