from pathlib import Path
import sqlite3

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
        assert {"question_id", "status", "updated_at"}.issubset(columns)
        assert conn.execute("SELECT band,status FROM sessions WHERE session_id='W-OLD'").fetchone() == (6.0, "completed")
