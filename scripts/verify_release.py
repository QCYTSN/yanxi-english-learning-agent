from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pdf", ".mp3", ".m4a", ".wav"}
FORBIDDEN_PARTS = {"private-data", "sessions", "backups", "provider-credentials"}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode("utf-8")
    return [Path(item) for item in output.split("\0") if item]


def verify_source() -> None:
    problems: list[str] = []
    for relative in tracked_files():
        lowered_parts = {part.casefold() for part in relative.parts}
        if relative.suffix.casefold() in FORBIDDEN_SUFFIXES:
            problems.append(f"forbidden tracked artifact: {relative}")
        if lowered_parts & FORBIDDEN_PARTS:
            problems.append(f"private data path is tracked: {relative}")
    required = [
        ROOT / "src/ielts_coach/resources/assets/app-icon.ico",
        ROOT / "src/ielts_coach/web/static/index.html",
        ROOT / "LICENSE",
        ROOT / "DATA_LICENSE.md",
    ]
    problems.extend(f"missing release asset: {path.relative_to(ROOT)}" for path in required if not path.is_file())
    if problems:
        raise SystemExit("\n".join(problems))


def verify_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    forbidden = [
        name
        for name in names
        if "/starter-corpus/" in name or "/original-mocks/" in name
    ]
    if forbidden:
        raise SystemExit("Question-bank files leaked into the wheel:\n" + "\n".join(forbidden))
    word_files = [
        "yanxi-starter-100.json",
        "yanxi-frequency-3000.json",
        "yanxi-cet4.json",
        "yanxi-cet6.json",
        "yanxi-toefl.json",
        "yanxi-ielts-academic.json",
    ]
    missing = [
        f"ielts_coach/resources/words/{name}"
        for name in word_files
        if f"ielts_coach/resources/words/{name}" not in names
    ]
    if missing:
        raise SystemExit("Bundled word lists missing from the wheel: " + ", ".join(missing))


def verify_empty_home() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from ielts_coach.init_home import initialise_home
    from ielts_coach.storage import connect

    with tempfile.TemporaryDirectory(prefix="ielts-release-") as temp:
        home = Path(temp) / "data"
        initialise_home(home, include_demo_content=False)
        with connect(home) as conn:
            counts = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("questions", "question_passages", "listening_items")
            }
        if any(counts.values()):
            raise SystemExit(f"Fresh public data home is not empty: {counts}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    verify_source()
    verify_empty_home()
    if args.wheel:
        verify_wheel(args.wheel)
    elif not args.source_only:
        wheels = sorted((ROOT / "dist").glob("ielts_ai_coach-*.whl"))
        if not wheels:
            raise SystemExit("No release wheel found under dist/.")
        verify_wheel(wheels[-1])
    print("Release boundary verified: no personal data and no bundled question bank.")


if __name__ == "__main__":
    main()
