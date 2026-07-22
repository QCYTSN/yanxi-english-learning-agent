from pathlib import Path


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
