from pathlib import Path


def test_six_skill_architecture_and_workflow_guards():
    root = Path(__file__).resolve().parents[1] / "skills-source"
    expected = {"ielts", "ielts-writing", "ielts-speaking", "ielts-reading", "ielts-progress", "ielts-corpus"}
    assert expected == {path.name for path in root.iterdir() if (path / "SKILL.md").exists()}

    writing = (root / "ielts-writing" / "SKILL.md").read_text(encoding="utf-8")
    assert "No full polished rewrite before the learner attempts V2" in writing
    assert "criterion_scores" in writing

    reading = (root / "ielts-reading" / "SKILL.md").read_text(encoding="utf-8")
    for mode in ("guided-solving", "wrong-answer-review", "close-reading", "context-analysis"):
        assert mode in reading
    assert "Never invent a line" in reading

    router = (root / "ielts" / "SKILL.md").read_text(encoding="utf-8")
    assert "`ielts-reading`" in router and "`ielts-corpus`" in router
