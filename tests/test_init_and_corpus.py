from pathlib import Path

from ielts_coach import corpus
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import connect, db_path, list_corpora


def test_initialise_home(tmp_path: Path):
    home = tmp_path / "ielts-home"
    initialise_home(home)
    assert (home / "config" / "profile.yaml").exists()
    assert db_path(home).exists()
    assert (home / "corpus" / "starter-open" / "writing-task2.jsonl").exists()
    rows = list_corpora(home)
    assert any(row["corpus_id"] == "ielts-ai-coach-starter" for row in rows)


def test_optional_original_mock_corpus_can_be_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(corpus, "_resource_file", lambda _relative: tmp_path / "missing")

    assert corpus.install_original_mock_corpus(tmp_path / "ielts-home") is False
    assert not (tmp_path / "ielts-home" / "corpus" / "original-mocks").exists()


def test_public_initialise_home_starts_with_empty_question_bank(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("IELTS_COACH_INCLUDE_DEMO_CONTENT", raising=False)
    home = tmp_path / "clean-public-home"

    initialise_home(home)

    with connect(home) as conn:
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM question_passages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM listening_items").fetchone()[0] == 0
    assert not (home / "corpus" / "starter-open" / "manifest.yaml").exists()
    assert not (home / "corpus" / "original-mocks" / "manifest.yaml").exists()
