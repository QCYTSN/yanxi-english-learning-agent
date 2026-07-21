from pathlib import Path

from ielts_coach.session_io import load_session_file


def test_markdown_frontmatter(tmp_path: Path):
    path = tmp_path / "session.md"
    path.write_text(
        "---\nsession_id: W-1\nmodule: writing\nband: 6.5\n---\n# Essay\nText",
        encoding="utf-8",
    )
    data = load_session_file(path)
    assert data["session_id"] == "W-1"
    assert "# Essay" in data["document_body"]


def test_yaml_timestamp_can_be_recorded(tmp_path: Path):
    from ielts_coach.init_home import initialise_home
    from ielts_coach.storage import record_session

    home = tmp_path / "home"
    initialise_home(home)
    path = tmp_path / "session.yaml"
    path.write_text(
        "session_id: L-1\nmodule: listening\noccurred_at: 2026-07-21T19:00:00\nband: 7.5\n",
        encoding="utf-8",
    )
    data = load_session_file(path)
    record_session(home, data)
