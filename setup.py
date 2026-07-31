from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    """Build a clean package and copy canonical Skill sources into it."""

    def run(self) -> None:
        package_root = Path(self.build_lib) / "ielts_coach"
        if package_root.exists():
            # Hashed Vite assets change on every build.  Clearing the package
            # output prevents old bundles from leaking into later wheels.
            shutil.rmtree(package_root)
        super().run()
        project_root = Path(__file__).resolve().parent
        source = project_root / "skills-source"
        target = (
            Path(self.build_lib)
            / "ielts_coach"
            / "resources"
            / "skills"
        )
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)


setup(cmdclass={"build_py": build_py})
