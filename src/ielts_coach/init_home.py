from __future__ import annotations

import os
from pathlib import Path

from .config import DEFAULT_PROFILE, DEFAULT_SETTINGS, migrate_configuration, write_yaml
from .corpus import (
    corpus_index_is_complete,
    import_manifest,
    install_original_mock_corpus,
    install_starter_corpus,
)
from .storage import initialise_database
from .rubrics import ensure_default_rubrics
from .listening_corpus import install_starter_listening
from .learning_model import ensure_learning_model
from .domain_packs import domain_pack_descriptors
from .execution_profiles import ensure_builtin_execution_profiles
from .model_providers import ensure_builtin_model_providers

DIRECTORIES = (
    "config", "database", "corpus/manifests", "corpus/official-user-imported",
    "corpus/cambridge-private", "corpus/seasonal-private", "corpus/personal",
    "corpus/synthetic", "sessions/listening", "sessions/reading", "sessions/writing",
    "sessions/speaking", "story-bank", "reports/weekly", "reports/monthly",
    "exports", "backups", "calibration/cases", "calibration/results",
    "media", "private", "private/codex-managed", "private/runtimes",
    "private/provider-credentials",
    "runtime/locks",
    "runtime/codex-workspace", "exports/agent-requests", "exports/agent-results",
)


def initialise_home(
    home: Path,
    force: bool = False,
    *,
    include_demo_content: bool | None = None,
) -> None:
    """Create or migrate a user data home.

    Public installs deliberately start with an empty question bank. The
    bundled project-original corpus is retained only as an opt-in development
    fixture so tests can exercise complete learning flows without publishing
    it into a learner's database.
    """
    if include_demo_content is None:
        include_demo_content = os.environ.get(
            "IELTS_COACH_INCLUDE_DEMO_CONTENT", ""
        ).strip().casefold() in {"1", "true", "yes"}
    for relative in DIRECTORIES:
        (home / relative).mkdir(parents=True, exist_ok=True)
    for private_path in (
        home / "private",
        home / "private" / "codex-managed",
        home / "private" / "runtimes",
    ):
        try:
            private_path.chmod(0o700)
        except OSError:
            # Windows ACLs are inherited from the user-owned IELTS_HOME.
            pass
    write_yaml(home / "config" / "profile.yaml", DEFAULT_PROFILE, force=force)
    write_yaml(home / "config" / "settings.yaml", DEFAULT_SETTINGS, force=force)
    if not force:
        migrate_configuration(home)
    initialise_database(home)
    for pack in domain_pack_descriptors():
        ensure_learning_model(home, str(pack["track_id"]))
    ensure_builtin_execution_profiles(home)
    ensure_builtin_model_providers(home)
    ensure_default_rubrics(home)
    if not include_demo_content:
        return
    install_starter_listening(home)
    starter_changed = install_starter_corpus(home, force=force)
    manifest_path = home / "corpus" / "starter-open" / "manifest.yaml"
    if manifest_path.exists() and (
        force or starter_changed or not corpus_index_is_complete(home, manifest_path)
    ):
        import_manifest(
            home,
            manifest_path,
            index=True,
            force=force,
            refresh_reviews=False,
        )
    original_changed = install_original_mock_corpus(home, force=force)
    original_manifest = home / "corpus" / "original-mocks" / "manifest.yaml"
    if original_manifest.exists() and (
        force
        or original_changed
        or not corpus_index_is_complete(home, original_manifest)
    ):
        import_manifest(
            home,
            original_manifest,
            index=True,
            force=force,
            refresh_reviews=False,
        )
