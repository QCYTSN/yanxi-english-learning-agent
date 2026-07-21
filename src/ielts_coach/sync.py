from __future__ import annotations

import shutil
import hashlib
from pathlib import Path

import yaml

SKILLS = ("ielts", "ielts-writing", "ielts-speaking", "ielts-reading", "ielts-progress", "ielts-corpus")
TARGETS = (Path(".claude/skills"), Path(".agents/skills"), Path(".opencode/skills"))


def _validate_skill(skill_dir: Path) -> None:
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"Missing YAML frontmatter in {path}")
    parts = text.split("---", 2)
    metadata = yaml.safe_load(parts[1])
    if metadata.get("name") != skill_dir.name:
        raise ValueError(f"Skill name {metadata.get('name')!r} does not match directory {skill_dir.name!r}")
    description = metadata.get("description")
    if not description or not 1 <= len(str(description)) <= 1024:
        raise ValueError(f"Invalid description in {path}")


def sync_skills(project_root: Path) -> list[Path]:
    source_root = project_root / "skills-source"
    written: list[Path] = []
    for skill in SKILLS:
        source = source_root / skill
        _validate_skill(source)
        for relative in TARGETS:
            target = project_root / relative / skill
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
            written.append(target)
    return written


def skill_tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def skills_are_synced(project_root: Path, target: Path) -> bool:
    source_root = project_root / "skills-source"
    target_root = project_root / target
    return all(
        (target_root / skill / "SKILL.md").exists()
        and skill_tree_digest(source_root / skill) == skill_tree_digest(target_root / skill)
        for skill in SKILLS
    )
