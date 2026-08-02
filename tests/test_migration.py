from pathlib import Path
import shutil
import sqlite3

import pytest

import ielts_coach.storage as storage
from ielts_coach.backups import list_backups, verify_backup
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import db_path, initialise_database


def test_v01_database_is_migrated_without_data_loss(tmp_path: Path):
    home = tmp_path / "home"
    path = db_path(home)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
              session_id TEXT PRIMARY KEY,module TEXT NOT NULL,occurred_at TEXT NOT NULL,
              source_id TEXT,raw_score REAL,band REAL,duration_minutes REAL,
              payload_json TEXT NOT NULL,created_at TEXT NOT NULL
            );
            CREATE TABLE errors (
              id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,tag TEXT NOT NULL,
              count INTEGER NOT NULL DEFAULT 1,evidence TEXT,status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE corpora (
              corpus_id TEXT PRIMARY KEY,title TEXT NOT NULL,source_type TEXT NOT NULL,
              local_path TEXT,redistribution_allowed INTEGER NOT NULL DEFAULT 0,
              manifest_json TEXT NOT NULL,imported_at TEXT NOT NULL
            );
            INSERT INTO sessions VALUES('W-OLD','writing','2026-07-01',NULL,NULL,6.0,NULL,'{}','2026-07-01');
            """
        )
    initialise_database(home)
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert {
            "question_id", "passage_id", "mode", "status", "updated_at",
            "score_kind", "rubric_json", "answer_key_source",
            "band_conversion_source", "time_limit_minutes", "started_at",
            "submitted_at", "answer_revealed_at", "hints_used",
        }.issubset(columns)
        assert conn.execute("SELECT band,status FROM sessions WHERE session_id='W-OLD'").fetchone() == (6.0, "completed")
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone() == ("27",)
        assert {"assessment_pack_id", "practice_mode", "conformance_status"}.issubset(columns)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='listening_items'"
        ).fetchone() == ("listening_items",)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "study_drafts",
            "idempotency_records",
            "media_assets",
            "agent_runs",
            "agent_run_events",
            "audit_events",
            "provider_attempts",
            "execution_profiles",
            "ui_settings",
            "study_threads",
            "study_messages",
            "study_thread_attachments",
            "study_thread_summaries",
            "learner_memories",
            "capability_evaluation_runs",
        }.issubset(tables)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='diagnostic_runs'"
        ).fetchone() == ("diagnostic_runs",)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='calibration_cases'"
        ).fetchone() == ("calibration_cases",)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='assessment_packs'"
        ).fetchone() == ("assessment_packs",)
        assert {"content_import_jobs", "content_import_files", "content_reviews"}.issubset(tables)
    backups = list_backups(home)
    assert len(backups) == 1
    assert backups[0]["kind"] == "pre-migration-legacy-to-27"
    assert verify_backup(home, backups[0]["backup_id"])["valid"] is True


@pytest.mark.parametrize("version", ["1", "5", "9", "19"])
def test_historical_version_markers_migrate_to_current_schema(
    version: str, tmp_path: Path
):
    home = tmp_path / f"schema-{version}"
    path = db_path(home)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            f"""
            CREATE TABLE sessions (
              session_id TEXT PRIMARY KEY,module TEXT NOT NULL,occurred_at TEXT NOT NULL,
              source_id TEXT,raw_score REAL,band REAL,duration_minutes REAL,
              payload_json TEXT NOT NULL,created_at TEXT NOT NULL
            );
            CREATE TABLE errors (
              id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,tag TEXT NOT NULL,
              count INTEGER NOT NULL DEFAULT 1,evidence TEXT,status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE corpora (
              corpus_id TEXT PRIMARY KEY,title TEXT NOT NULL,source_type TEXT NOT NULL,
              local_path TEXT,redistribution_allowed INTEGER NOT NULL DEFAULT 0,
              manifest_json TEXT NOT NULL,imported_at TEXT NOT NULL
            );
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES('schema_version','{version}');
            INSERT INTO sessions VALUES(
              'R-{version}','reading','2026-07-01',NULL,7,6.0,20,'{{}}','2026-07-01'
            );
            """
        )
    initialise_database(home)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone() == ("27",)
        assert conn.execute(
            "SELECT session_id FROM sessions WHERE session_id=?", (f"R-{version}",)
        ).fetchone() == (f"R-{version}",)
    backups = list_backups(home)
    assert backups[0]["kind"] == f"pre-migration-{version}-to-27"
    assert verify_backup(home, backups[0]["backup_id"])["valid"] is True


def test_schema10_agent_runs_gain_identity_without_losing_runs(tmp_path: Path):
    home = tmp_path / "schema-10"
    path = db_path(home)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE agent_runs (
              run_id TEXT PRIMARY KEY,study_session_id TEXT,adapter_id TEXT NOT NULL,
              agent_session_id TEXT,action TEXT NOT NULL,output_contract TEXT NOT NULL,
              base_revision INTEGER,status TEXT NOT NULL,error_code TEXT,
              request_json TEXT NOT NULL DEFAULT '{}',result_json TEXT,
              usage_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,
              started_at TEXT,completed_at TEXT
            );
            INSERT INTO agent_runs(
              run_id,adapter_id,action,output_contract,status,created_at
            ) VALUES('run-old','manual','review','writing-review@1','persisted','2026-07-01');
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES('schema_version','10');
            """
        )
    initialise_database(home)
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_runs)")}
        assert {
            "agent_provider",
            "agent_version",
            "model_id",
            "model_display_name",
            "launcher_kind",
            "capabilities_json",
            "calibration_status",
        }.issubset(columns)
        assert conn.execute(
            "SELECT run_id,status FROM agent_runs WHERE run_id='run-old'"
        ).fetchone() == ("run-old", "persisted")


def test_interrupted_migration_creates_recoverable_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "interrupted"
    seed = tmp_path / "configuration-seed"
    initialise_home(seed)
    shutil.copytree(seed / "config", home / "config")
    path = db_path(home)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
              session_id TEXT PRIMARY KEY,module TEXT NOT NULL,occurred_at TEXT NOT NULL,
              source_id TEXT,raw_score REAL,band REAL,duration_minutes REAL,
              payload_json TEXT NOT NULL,created_at TEXT NOT NULL
            );
            CREATE TABLE errors (
              id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,tag TEXT NOT NULL,
              count INTEGER NOT NULL DEFAULT 1,evidence TEXT,status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE corpora (
              corpus_id TEXT PRIMARY KEY,title TEXT NOT NULL,source_type TEXT NOT NULL,
              local_path TEXT,redistribution_allowed INTEGER NOT NULL DEFAULT 0,
              manifest_json TEXT NOT NULL,imported_at TEXT NOT NULL
            );
            INSERT INTO sessions VALUES(
              'W-SAFE','writing','2026-07-01',NULL,NULL,NULL,NULL,'{}','2026-07-01'
            );
            """
        )
    original_migrate = storage._migrate

    def interrupted(conn, previous_version=None):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(storage, "_migrate", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        initialise_database(home)
    backup = list_backups(home)[0]
    assert backup["kind"] == "pre-migration-legacy-to-27"
    assert verify_backup(home, backup["backup_id"])["valid"] is True

    monkeypatch.setattr(storage, "_migrate", original_migrate)
    from ielts_coach.backups import restore_backup

    restored = restore_backup(home, backup["backup_id"], confirmed=True)
    assert restored["post_restore_health"]["status"] != "failed"
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT session_id FROM sessions WHERE session_id='W-SAFE'"
        ).fetchone() == ("W-SAFE",)
