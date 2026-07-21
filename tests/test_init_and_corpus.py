from pathlib import Path

from ielts_coach.init_home import initialise_home
from ielts_coach.storage import db_path, list_corpora


def test_initialise_home(tmp_path: Path):
    home = tmp_path / "ielts-home"
    initialise_home(home)
    assert (home / "config" / "profile.yaml").exists()
    assert db_path(home).exists()
    assert (home / "corpus" / "starter-open" / "writing-task2.jsonl").exists()
    rows = list_corpora(home)
    assert any(row["corpus_id"] == "ielts-ai-coach-starter" for row in rows)
