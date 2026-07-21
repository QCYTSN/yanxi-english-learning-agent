from pathlib import Path
import shutil

from ielts_coach.sync import SKILLS, TARGETS, sync_skills


def test_sync_skills(tmp_path: Path):
    source_repo = Path(__file__).resolve().parents[1]
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(source_repo / "skills-source", repo / "skills-source")
    written = sync_skills(repo)
    assert len(written) == len(SKILLS) * len(TARGETS)
    for target in TARGETS:
        for skill in SKILLS:
            assert (repo / target / skill / "SKILL.md").exists()
