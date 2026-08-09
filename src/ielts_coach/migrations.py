from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


MigrationAction = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    migration_id: str
    description: str
    apply: MigrationAction

    @property
    def checksum(self) -> str:
        source = f"{self.version}|{self.migration_id}|{self.description}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _v28_agent_run_lifecycle(_: sqlite3.Connection) -> None:
    # The legacy compatibility pass in storage.py performs the idempotent
    # column additions. This marker establishes the versioned migration chain
    # for existing installations without replaying destructive DDL.
    return


def _v29_local_workers_and_search(conn: sqlite3.Connection) -> None:
    _install_learning_history_search(conn)


def _v30_provider_resilience(_: sqlite3.Connection) -> None:
    # The table is created by the idempotent base schema before this migration
    # runs. Keep the marker explicit so future changes can depend on it.
    return


def _v31_learning_agent_kernel(conn: sqlite3.Connection) -> None:
    for table in (
        "sessions",
        "study_threads",
        "learner_memories",
        "practice_units",
        "review_tasks",
    ):
        columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if "track_id" in columns:
            conn.execute(
                f"UPDATE {table} SET track_id='ielts-academic' "
                "WHERE track_id IS NULL OR TRIM(track_id)=''"
            )


def _v32_memory_pedagogy_and_quality(conn: sqlite3.Connection) -> None:
    now = _now()
    singleton_memory_types = {
        "preferred_name",
        "feedback_language",
        "interface_language",
        "target_band",
        "explanation_order",
        "timezone",
    }
    rows = conn.execute(
        "SELECT * FROM learner_memories ORDER BY created_at,memory_id"
    ).fetchall()
    for row in rows:
        statement = " ".join(str(row["statement"] or "").strip().split())
        content_hash = hashlib.sha256(statement.casefold().encode("utf-8")).hexdigest()
        memory_key = str(row["memory_key"] or "").strip()
        if not memory_key:
            if str(row["memory_type"]) in singleton_memory_types:
                memory_key = f"{row['scope']}:{row['memory_type']}"[:160]
            else:
                key_seed = f"{row['scope']}|{row['memory_type']}|{content_hash[:20]}"
                digest = hashlib.sha256(key_seed.encode("utf-8")).hexdigest()[:32]
                memory_key = f"memory:{digest}"
        valid_from = str(row["valid_from"] or row["created_at"] or now)
        conn.execute(
            """
            UPDATE learner_memories
            SET memory_key=?,content_hash=?,valid_from=?,revision=MAX(1,revision),
                source_kind=COALESCE(NULLIF(source_kind,''),'learner_confirmed')
            WHERE memory_id=?
            """,
            (memory_key, content_hash, valid_from, row["memory_id"]),
        )
        refreshed = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?",
            (row["memory_id"],),
        ).fetchone()
        conn.execute(
            """
            INSERT OR IGNORE INTO learner_memory_revisions(
              memory_id,revision,statement,content_hash,confidence,
              evidence_refs_json,memory_key,scope,status,validity_status,
              source_kind,expires_at,change_reason,changed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                refreshed["memory_id"],
                int(refreshed["revision"]),
                refreshed["statement"],
                refreshed["content_hash"],
                float(refreshed["confidence"]),
                refreshed["evidence_refs_json"],
                refreshed["memory_key"],
                refreshed["scope"],
                refreshed["status"],
                refreshed["validity_status"],
                refreshed["source_kind"],
                refreshed["expires_at"],
                "v32_backfill",
                refreshed["updated_at"] or now,
            ),
        )


MIGRATIONS = (
    Migration(
        28,
        "v28-agent-run-lifecycle",
        "Link Tutor runs to study threads and compact private request envelopes.",
        _v28_agent_run_lifecycle,
    ),
    Migration(
        29,
        "v29-local-workers-and-search",
        "Add durable isolated local jobs and indexed learning-history search.",
        _v29_local_workers_and_search,
    ),
    Migration(
        30,
        "v30-provider-resilience",
        "Persist provider circuit-breaker health and normalized failures.",
        _v30_provider_resilience,
    ),
    Migration(
        31,
        "v31-learning-agent-kernel",
        "Add learning tracks, objectives, activities, mastery evidence and review schedules.",
        _v31_learning_agent_kernel,
    ),
    Migration(
        32,
        "v32-memory-pedagogy-quality",
        "Version learner memory and add teaching cycles and teaching-quality evaluations.",
        _v32_memory_pedagogy_and_quality,
    ),
)


def apply_versioned_migrations(
    conn: sqlite3.Connection,
    previous_version: str | None,
    target_version: int,
) -> None:
    previous = int(previous_version) if str(previous_version).isdigit() else 0
    for migration in MIGRATIONS:
        if migration.version <= previous or migration.version > target_version:
            continue
        existing = conn.execute(
            "SELECT status,checksum FROM schema_migration_journal WHERE migration_id=?",
            (migration.migration_id,),
        ).fetchone()
        if existing and str(existing["status"]) == "completed":
            if str(existing["checksum"]) != migration.checksum:
                raise RuntimeError(
                    f"Completed migration checksum changed: {migration.migration_id}"
                )
            continue
        conn.execute(
            """
            INSERT INTO schema_migration_journal(
              migration_id,from_version,to_version,checksum,status,started_at,
              completed_at,error_message
            ) VALUES(?,?,?,?, 'started',?,NULL,NULL)
            ON CONFLICT(migration_id) DO UPDATE SET
              from_version=excluded.from_version,
              to_version=excluded.to_version,
              checksum=excluded.checksum,
              status='started',started_at=excluded.started_at,
              completed_at=NULL,error_message=NULL
            """,
            (
                migration.migration_id,
                previous,
                migration.version,
                migration.checksum,
                _now(),
            ),
        )
        conn.commit()
        try:
            migration.apply(conn)
            conn.execute(
                """
                UPDATE schema_migration_journal
                SET status='completed',completed_at=?,error_message=NULL
                WHERE migration_id=?
                """,
                (_now(), migration.migration_id),
            )
            conn.commit()
        except BaseException as exc:
            conn.rollback()
            conn.execute(
                """
                UPDATE schema_migration_journal
                SET status='failed',completed_at=?,error_message=?
                WHERE migration_id=?
                """,
                (_now(), str(exc)[-2000:], migration.migration_id),
            )
            conn.commit()
            raise
        previous = migration.version


def _install_learning_history_search(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS learning_history_fts")
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE learning_history_fts USING fts5(
              source_type UNINDEXED,
              source_id UNINDEXED,
              title,
              content,
              created_at UNINDEXED,
              tokenize='trigram'
            )
            """
        )
        tokenizer = "trigram"
    except sqlite3.OperationalError:
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE learning_history_fts USING fts5(
                  source_type UNINDEXED,
                  source_id UNINDEXED,
                  title,
                  content,
                  created_at UNINDEXED,
                  tokenize='unicode61'
                )
                """
            )
            tokenizer = "unicode61"
        except sqlite3.OperationalError:
            conn.execute(
                """
                INSERT INTO schema_meta(key,value) VALUES('learning_history_tokenizer','unavailable')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """
            )
            return

    conn.execute(
        """
        INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
        SELECT 'study_message',m.message_id,t.title,m.content,m.created_at
        FROM study_messages m JOIN study_threads t USING(thread_id)
        """
    )
    conn.execute(
        """
        INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
        SELECT 'writing_version',w.session_id || ':' || w.version_label,
               'Writing ' || w.version_label,w.content,w.created_at
        FROM writing_versions w
        """
    )
    conn.execute(
        """
        INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
        SELECT 'error_record',CAST(e.id AS TEXT),e.tag,COALESCE(e.evidence,''),
               s.occurred_at
        FROM errors e JOIN sessions s USING(session_id)
        """
    )
    for trigger in (
        "learning_fts_study_message_insert",
        "learning_fts_study_message_update",
        "learning_fts_study_message_delete",
        "learning_fts_thread_title_update",
        "learning_fts_writing_insert",
        "learning_fts_writing_update",
        "learning_fts_writing_delete",
        "learning_fts_error_insert",
        "learning_fts_error_update",
        "learning_fts_error_delete",
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    statements = (
        """
        CREATE TRIGGER learning_fts_study_message_insert AFTER INSERT ON study_messages BEGIN
          INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
          VALUES('study_message',new.message_id,
            COALESCE((SELECT title FROM study_threads WHERE thread_id=new.thread_id),''),
            new.content,new.created_at);
        END
        """,
        """
        CREATE TRIGGER learning_fts_study_message_update AFTER UPDATE ON study_messages BEGIN
          DELETE FROM learning_history_fts WHERE source_type='study_message' AND source_id=old.message_id;
          INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
          VALUES('study_message',new.message_id,
            COALESCE((SELECT title FROM study_threads WHERE thread_id=new.thread_id),''),
            new.content,new.created_at);
        END
        """,
        """
        CREATE TRIGGER learning_fts_study_message_delete AFTER DELETE ON study_messages BEGIN
          DELETE FROM learning_history_fts WHERE source_type='study_message' AND source_id=old.message_id;
        END
        """,
        """
        CREATE TRIGGER learning_fts_thread_title_update AFTER UPDATE OF title ON study_threads BEGIN
          UPDATE learning_history_fts SET title=new.title
          WHERE source_type='study_message' AND source_id IN (
            SELECT message_id FROM study_messages WHERE thread_id=new.thread_id
          );
        END
        """,
        """
        CREATE TRIGGER learning_fts_writing_insert AFTER INSERT ON writing_versions BEGIN
          INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
          VALUES('writing_version',new.session_id || ':' || new.version_label,
            'Writing ' || new.version_label,new.content,new.created_at);
        END
        """,
        """
        CREATE TRIGGER learning_fts_writing_update AFTER UPDATE ON writing_versions BEGIN
          DELETE FROM learning_history_fts
          WHERE source_type='writing_version' AND source_id=old.session_id || ':' || old.version_label;
          INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
          VALUES('writing_version',new.session_id || ':' || new.version_label,
            'Writing ' || new.version_label,new.content,new.created_at);
        END
        """,
        """
        CREATE TRIGGER learning_fts_writing_delete AFTER DELETE ON writing_versions BEGIN
          DELETE FROM learning_history_fts
          WHERE source_type='writing_version' AND source_id=old.session_id || ':' || old.version_label;
        END
        """,
        """
        CREATE TRIGGER learning_fts_error_insert AFTER INSERT ON errors BEGIN
          INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
          VALUES('error_record',CAST(new.id AS TEXT),new.tag,COALESCE(new.evidence,''),
            COALESCE((SELECT occurred_at FROM sessions WHERE session_id=new.session_id),''));
        END
        """,
        """
        CREATE TRIGGER learning_fts_error_update AFTER UPDATE ON errors BEGIN
          DELETE FROM learning_history_fts WHERE source_type='error_record' AND source_id=CAST(old.id AS TEXT);
          INSERT INTO learning_history_fts(source_type,source_id,title,content,created_at)
          VALUES('error_record',CAST(new.id AS TEXT),new.tag,COALESCE(new.evidence,''),
            COALESCE((SELECT occurred_at FROM sessions WHERE session_id=new.session_id),''));
        END
        """,
        """
        CREATE TRIGGER learning_fts_error_delete AFTER DELETE ON errors BEGIN
          DELETE FROM learning_history_fts WHERE source_type='error_record' AND source_id=CAST(old.id AS TEXT);
        END
        """,
    )
    for statement in statements:
        conn.execute(statement)
    conn.execute(
        """
        INSERT INTO schema_meta(key,value) VALUES('learning_history_tokenizer',?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (tokenizer,),
    )
