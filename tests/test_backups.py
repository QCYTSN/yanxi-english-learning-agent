from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ielts_coach.backups import (
    backup_download_path,
    create_backup,
    list_backups,
    restore_backup,
    run_automatic_backup_sweep,
    verify_backup,
)
from ielts_coach.init_home import initialise_home


def test_backup_create_verify_and_restore_with_safety_snapshot(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    marker = home / "story-bank" / "marker.txt"
    marker.write_text("before backup", encoding="utf-8")

    created = create_backup(home, kind="test-manual")
    assert Path(created["path"]).is_file()
    assert created["database_integrity"] == "ok"
    assert any(item["path"] == "story-bank/marker.txt" for item in created["files"])

    verified = verify_backup(home, created["backup_id"])
    assert verified["valid"] is True
    assert verified["database_integrity"] == "ok"

    marker.write_text("after backup", encoding="utf-8")
    restored = restore_backup(home, created["backup_id"], confirmed=True)
    assert restored["restored"] is True
    assert marker.read_text(encoding="utf-8") == "before backup"
    assert restored["safety_backup_id"] != created["backup_id"]
    assert {item["backup_id"] for item in list_backups(home)} >= {
        created["backup_id"], restored["safety_backup_id"]
    }


def test_restore_requires_confirmation_and_tampered_backup_is_rejected(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    created = create_backup(home)
    with pytest.raises(ValueError, match="explicit confirmation"):
        restore_backup(home, created["backup_id"])

    source = Path(created["path"])
    tampered = home / "backups" / "ielts-backup-tampered.zip"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(tampered, "w") as changed:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename.startswith("payload/config/profile.yaml"):
                data += b"\ntampered: true\n"
            changed.writestr(info, data)
    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        verify_backup(home, tampered)
    marker = home / "story-bank" / "restore-guard.txt"
    marker.write_text("must survive", encoding="utf-8")
    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        restore_backup(home, tampered, confirmed=True)
    assert marker.read_text(encoding="utf-8") == "must survive"


def test_backup_manifest_does_not_include_runtime_exports_or_prior_backups(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    (home / "exports" / "secret.txt").write_text("temporary", encoding="utf-8")
    (home / "runtime" / "state.json").write_text("{}", encoding="utf-8")
    created = create_backup(home)
    paths = {str(item["path"]) for item in created["files"]}
    assert not any(path.startswith("exports/") for path in paths)
    assert not any(path.startswith("runtime/") for path in paths)
    assert not any(path.startswith("backups/") for path in paths)

    with zipfile.ZipFile(created["path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["backup_format_version"] == 1
    assert manifest["backup_id"] == created["backup_id"]


def test_automatic_sweep_creates_when_stale_and_respects_freshness(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    (home / "story-bank" / "marker.txt").write_text("kept", encoding="utf-8")

    # Nothing recent yet: the sweep creates one automatic backup.
    created = run_automatic_backup_sweep(home, interval_seconds=3600)
    assert created is not None
    assert created["kind"] == "automatic"

    # The fresh backup satisfies the interval: no new backup is created.
    assert run_automatic_backup_sweep(home, interval_seconds=3600) is None

    # A fresh manual backup also satisfies freshness (any kind counts).
    create_backup(home, kind="test-manual")
    assert run_automatic_backup_sweep(home, interval_seconds=3600) is None


def test_automatic_sweep_prunes_only_automatic_beyond_keep(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    create_backup(home, kind="test-manual")

    # interval 0 forces every sweep to create, so pruning is exercised.
    for _ in range(7):
        run_automatic_backup_sweep(home, interval_seconds=0, keep=3)
    automatic = [
        item
        for item in list_backups(home)
        if item.get("kind") == "automatic" and item.get("status") == "available"
    ]
    manual = [
        item
        for item in list_backups(home)
        if item.get("kind") == "test-manual" and item.get("status") == "available"
    ]
    assert len(automatic) == 3
    assert len(manual) == 1


def test_automatic_sweep_skips_without_database(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    # No database file yet: nothing to back up, no crash.
    assert run_automatic_backup_sweep(home) is None


def test_backup_download_path_resolves_stored_id(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    created = create_backup(home)
    path = backup_download_path(home, created["backup_id"])
    assert path == Path(created["path"])
    assert path.is_file()
    with pytest.raises(ValueError, match="stored backup ID only"):
        backup_download_path(home, "/etc/passwd")


def test_wipe_learner_data_keeps_settings_and_removes_progress(tmp_path: Path):
    from ielts_coach.data_lifecycle import wipe_learner_data
    from ielts_coach.storage import connect

    home = tmp_path / "home"
    initialise_home(home)
    settings = home / "config" / "settings.yaml"
    settings.write_text("model: kept\n", encoding="utf-8")
    (home / "story-bank" / "note.txt").write_text("learner content", encoding="utf-8")
    (home / "media" / "audio.mp3").write_text("fake audio", encoding="utf-8")
    with connect(home) as conn:
        conn.execute(
            "INSERT INTO vocabulary_items (item_id,word,status,track_id,source_type,created_at,updated_at)"
            " VALUES ('v1','sunshine','learning','general-english','learner_input',datetime('now'),datetime('now'))"
        )

    with pytest.raises(ValueError, match="explicit confirmation"):
        wipe_learner_data(home)

    result = wipe_learner_data(home, confirmed=True)
    assert result["wiped"] is True
    assert "database" in result["removed"]
    assert "story-bank" in result["removed"]
    assert "media" in result["removed"]

    # Settings survive; learner data is gone; DB is recreated empty.
    assert settings.read_text(encoding="utf-8") == "model: kept\n"
    assert not (home / "story-bank").exists()
    assert not (home / "media").exists()
    with connect(home) as conn:
        count = conn.execute("SELECT COUNT(*) FROM vocabulary_items").fetchone()[0]
        assert count == 0
        session_rows = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert session_rows == 0
    # Learning profile is reset with the rest of the data.
    assert not (home / "config" / "profile.yaml").exists()
