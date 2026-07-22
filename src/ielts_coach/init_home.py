from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_PROFILE, DEFAULT_SETTINGS, migrate_configuration, write_yaml
from .corpus import import_manifest, install_starter_corpus
from .storage import initialise_database
from .rubrics import ensure_default_rubrics

DIRECTORIES = (
    "config", "database", "corpus/manifests", "corpus/official-user-imported",
    "corpus/cambridge-private", "corpus/seasonal-private", "corpus/personal",
    "corpus/synthetic", "sessions/listening", "sessions/reading", "sessions/writing",
    "sessions/speaking", "story-bank", "reports/weekly", "reports/monthly",
    "exports", "backups", "calibration/cases", "calibration/results",
    "media", "runtime/locks", "exports/agent-requests", "exports/agent-results",
)


def initialise_home(home: Path, force: bool = False) -> None:
    for relative in DIRECTORIES:
        (home / relative).mkdir(parents=True, exist_ok=True)
    write_yaml(home / "config" / "profile.yaml", DEFAULT_PROFILE, force=force)
    write_yaml(home / "config" / "settings.yaml", DEFAULT_SETTINGS, force=force)
    if not force:
        migrate_configuration(home)
    initialise_database(home)
    ensure_default_rubrics(home)
    install_starter_corpus(home, force=force)
    manifest_path = home / "corpus" / "starter-open" / "manifest.yaml"
    if manifest_path.exists():
        import_manifest(home, manifest_path, index=True, force=force)
