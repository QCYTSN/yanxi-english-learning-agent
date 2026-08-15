import zipfile
from pathlib import Path

import pytest

from ielts_coach.uploads import read_zip_member


def test_read_zip_member_rejects_oversized_declared_size(tmp_path: Path):
    archive = tmp_path / "bomb.docx"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("word/document.xml", "x" * 5000)
    with pytest.raises(ValueError, match="the limit is"):
        read_zip_member(archive, "word/document.xml", max_bytes=1000)


def test_read_zip_member_allows_normal_members(tmp_path: Path):
    archive = tmp_path / "ok.docx"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("word/document.xml", "<document>hello</document>")
    payload = read_zip_member(archive, "word/document.xml")
    assert payload == b"<document>hello</document>"


def test_user_facing_text_is_valid_utf8_without_known_mojibake():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "README.md", root / "RELEASE_NOTES.md"]
    for folder in (root / "docs", root / "skills-source", root / "src" / "ielts_coach"):
        paths.extend(path for path in folder.rglob("*") if path.suffix in {".md", ".py", ".json", ".yaml"})
    known_mojibake = ("鍐欎綔", "闃呰", "鏆傛棤", "锛坽", "鈫?")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "\ufffd" not in text, path
        for marker in known_mojibake:
            assert marker not in text, f"{path}: {marker}"
