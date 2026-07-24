from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from .validation import normalise_json_value, validate_data
from .config import load_settings

SCHEMA_VERSION = 15

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    module TEXT NOT NULL CHECK(module IN ('listening','reading','writing','speaking')),
    occurred_at TEXT NOT NULL,
    source_id TEXT,
    question_id TEXT,
    passage_id TEXT,
    assessment_pack_id TEXT,
    mode TEXT,
    practice_mode TEXT,
    conformance_status TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    raw_score REAL,
    band REAL,
    score_kind TEXT,
    score_confidence TEXT,
    answer_key_source TEXT,
    band_conversion_source TEXT,
    rubric_json TEXT NOT NULL DEFAULT '{}',
    time_limit_minutes REAL,
    started_at TEXT,
    submitted_at TEXT,
    answer_revealed_at TEXT,
    hints_used INTEGER NOT NULL DEFAULT 0,
    duration_minutes REAL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_module_time ON sessions(module, occurred_at DESC);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','resolved','monitoring')),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_errors_tag ON errors(tag);
CREATE INDEX IF NOT EXISTS idx_errors_status_tag ON errors(status, tag);

CREATE TABLE IF NOT EXISTS corpora (
    corpus_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    local_path TEXT,
    redistribution_allowed INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_import_jobs (
    import_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    authenticity TEXT,
    rights_status TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_import_jobs_status
ON content_import_jobs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS content_import_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    file_kind TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(import_id) REFERENCES content_import_jobs(import_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_content_import_files_job ON content_import_files(import_id);

CREATE TABLE IF NOT EXISTS question_passages (
    passage_id TEXT PRIMARY KEY,
    corpus_id TEXT,
    title TEXT,
    body TEXT NOT NULL,
    source_type TEXT NOT NULL,
    topics_text TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(corpus_id) REFERENCES corpora(corpus_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    corpus_id TEXT,
    module TEXT NOT NULL CHECK(module IN ('listening','reading','writing','speaking')),
    task TEXT,
    part TEXT,
    question_number TEXT,
    question_type TEXT,
    title TEXT,
    content TEXT NOT NULL,
    passage_id TEXT,
    topics_text TEXT,
    source_type TEXT NOT NULL,
    authenticity TEXT,
    review_status TEXT,
    practice_mode TEXT,
    standard_profile TEXT,
    conformance_status TEXT,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(corpus_id) REFERENCES corpora(corpus_id) ON DELETE SET NULL,
    FOREIGN KEY(passage_id) REFERENCES question_passages(passage_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_filters ON questions(module,task,question_type,source_type);
CREATE INDEX IF NOT EXISTS idx_questions_hash ON questions(content_hash);
CREATE INDEX IF NOT EXISTS idx_questions_passage ON questions(passage_id);

CREATE TABLE IF NOT EXISTS assessment_packs (
    pack_id TEXT PRIMARY KEY,
    corpus_id TEXT,
    module TEXT NOT NULL CHECK(module IN ('listening','reading','writing','speaking')),
    title TEXT NOT NULL,
    practice_mode TEXT NOT NULL,
    standard_profile TEXT NOT NULL,
    standard_version TEXT,
    source_type TEXT NOT NULL,
    authenticity TEXT,
    rights_status TEXT NOT NULL,
    review_status TEXT NOT NULL,
    conformance_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(corpus_id) REFERENCES corpora(corpus_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_assessment_packs_filters
ON assessment_packs(module,practice_mode,conformance_status);

CREATE TABLE IF NOT EXISTS content_reviews (
    review_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK(target_type IN ('question','passage','assessment_pack')),
    target_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('approved','changes_requested','rejected')),
    checklist_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    created_at TEXT NOT NULL,
    superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_content_reviews_target
ON content_reviews(target_type,target_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_reviews_current
ON content_reviews(target_type,target_id,content_hash,decision);

CREATE TABLE IF NOT EXISTS question_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    option_key TEXT,
    option_text TEXT NOT NULL,
    is_correct INTEGER,
    FOREIGN KEY(question_id) REFERENCES questions(question_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS question_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    question_id TEXT,
    question_number TEXT,
    question_type TEXT,
    user_answer TEXT,
    correct_answer TEXT,
    is_correct INTEGER,
    duration_seconds REAL,
    evidence_location TEXT,
    explanation TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(question_id) REFERENCES questions(question_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON question_attempts(question_id);

CREATE TABLE IF NOT EXISTS reading_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    question_id TEXT,
    question_number TEXT,
    question_type TEXT NOT NULL,
    user_answer TEXT,
    correct_answer TEXT,
    is_correct INTEGER,
    duration_seconds REAL,
    evidence_location TEXT,
    error_tags_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(question_id) REFERENCES questions(question_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_reading_type ON reading_answers(question_type);

CREATE TABLE IF NOT EXISTS writing_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    version_label TEXT NOT NULL,
    content TEXT NOT NULL,
    word_count INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, version_label),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS criterion_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT 'final',
    criterion TEXT NOT NULL,
    score_low REAL,
    score_high REAL,
    score REAL,
    confidence TEXT,
    assessment_role TEXT NOT NULL DEFAULT 'local_rubric',
    evidence_source TEXT,
    rubric_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, version_label, criterion),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_criteria ON criterion_scores(criterion);

CREATE TABLE IF NOT EXISTS speaking_reports (
    session_id TEXT PRIMARY KEY,
    report_version INTEGER NOT NULL DEFAULT 1,
    mode TEXT,
    transcript TEXT,
    raw_report_json TEXT NOT NULL DEFAULT '{}',
    source_model_estimate_json TEXT NOT NULL DEFAULT '{}',
    local_evaluation_json TEXT NOT NULL DEFAULT '{}',
    evidence_types_json TEXT NOT NULL DEFAULT '[]',
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS allocation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calculated_at TEXT NOT NULL,
    listening REAL NOT NULL,
    reading REAL NOT NULL,
    writing REAL NOT NULL,
    speaking REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    period_key TEXT
);

CREATE TABLE IF NOT EXISTS calibration_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    module TEXT NOT NULL,
    criterion TEXT NOT NULL DEFAULT 'overall',
    model TEXT NOT NULL,
    official_score REAL NOT NULL,
    predicted_low REAL,
    predicted_high REAL,
    predicted_score REAL,
    absolute_error REAL NOT NULL,
    passed INTEGER NOT NULL,
    tolerance REAL NOT NULL DEFAULT 0.5,
    notes TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(case_id,model,criterion)
);

CREATE TABLE IF NOT EXISTS calibration_cases (
    case_id TEXT PRIMARY KEY,
    module TEXT NOT NULL CHECK(module IN ('writing','speaking')),
    task TEXT,
    criterion TEXT NOT NULL DEFAULT 'overall',
    official_score REAL NOT NULL,
    source_reference TEXT NOT NULL,
    input_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    permissions_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnostic_runs (
    diagnostic_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('quick','full')),
    status TEXT NOT NULL CHECK(status IN ('active','completed','cancelled')),
    exam_type TEXT NOT NULL DEFAULT 'academic',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    session_ids_json TEXT NOT NULL DEFAULT '[]',
    plan_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rubric_registry (
    rubric_id TEXT PRIMARY KEY,
    module TEXT NOT NULL CHECK(module IN ('writing','speaking')),
    publisher TEXT NOT NULL,
    standard TEXT NOT NULL,
    version TEXT,
    source_reference TEXT NOT NULL,
    local_path TEXT,
    content_hash TEXT,
    availability TEXT NOT NULL CHECK(availability IN ('reference_only','local_verified','local_missing')),
    permissions_json TEXT NOT NULL DEFAULT '{}',
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    session_id TEXT,
    module TEXT,
    event_type TEXT NOT NULL,
    revision INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_runtime_events_session ON runtime_events(session_id,created_at);

CREATE TABLE IF NOT EXISTS runtime_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    module TEXT,
    session_id TEXT,
    model_label TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms REAL,
    tool_calls INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_telemetry_time ON runtime_telemetry(created_at DESC);

CREATE TABLE IF NOT EXISTS study_drafts (
    session_id TEXT NOT NULL,
    draft_kind TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(session_id,draft_kind),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(scope,idempotency_key)
);

CREATE TABLE IF NOT EXISTS media_assets (
    media_id TEXT PRIMARY KEY,
    owner_type TEXT,
    owner_id TEXT,
    media_type TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    local_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    alt_text TEXT,
    privacy_status TEXT NOT NULL DEFAULT 'local_only',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(content_hash,mime_type)
);
CREATE INDEX IF NOT EXISTS idx_media_assets_owner
ON media_assets(owner_type,owner_id,created_at DESC);

CREATE TABLE IF NOT EXISTS media_bindings (
    media_id TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'evidence',
    created_at TEXT NOT NULL,
    PRIMARY KEY(media_id,owner_type,owner_id,purpose),
    FOREIGN KEY(media_id) REFERENCES media_assets(media_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_bindings_owner
ON media_bindings(owner_type,owner_id,created_at DESC);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    study_session_id TEXT,
    adapter_id TEXT NOT NULL,
    agent_provider TEXT,
    agent_version TEXT,
    model_id TEXT,
    model_display_name TEXT,
    agent_session_id TEXT,
    launcher_kind TEXT NOT NULL DEFAULT 'unknown',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    calibration_status TEXT NOT NULL DEFAULT 'unknown',
    action TEXT NOT NULL,
    output_contract TEXT NOT NULL,
    base_revision INTEGER,
    status TEXT NOT NULL,
    error_code TEXT,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    timeout_seconds INTEGER NOT NULL DEFAULT 120,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT,
    recovery_action TEXT,
    execution_ref TEXT,
    FOREIGN KEY(study_session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(study_session_id,created_at DESC);

CREATE TABLE IF NOT EXISTS agent_run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id,sequence),
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coaching_artifacts (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    contract_version INTEGER NOT NULL,
    study_session_id TEXT,
    agent_run_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(study_session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY(agent_run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_coaching_artifacts_type
ON coaching_artifacts(artifact_type,created_at DESC);

CREATE TABLE IF NOT EXISTS ui_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listening_items (
    item_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    subcategory TEXT,
    expression TEXT NOT NULL,
    meaning_zh TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    source_type TEXT NOT NULL DEFAULT 'project_original',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listening_items_category
ON listening_items(category,priority,item_id);

CREATE TABLE IF NOT EXISTS assessment_runs (
    run_id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL CHECK(module IN ('listening','reading','writing','speaking')),
    practice_mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
      'active','paused','reviewing','submitted','completed','cancelled','expired'
    )),
    revision INTEGER NOT NULL DEFAULT 0,
    pack_hash TEXT NOT NULL,
    pack_snapshot_json TEXT NOT NULL,
    time_limit_seconds INTEGER,
    elapsed_active_seconds REAL NOT NULL DEFAULT 0,
    resumed_at TEXT,
    paused_at TEXT,
    submitted_at TEXT,
    navigation_json TEXT NOT NULL DEFAULT '{}',
    submission_json TEXT NOT NULL DEFAULT '{}',
    media_state_json TEXT NOT NULL DEFAULT '{}',
    score_result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(pack_id) REFERENCES assessment_packs(pack_id) ON DELETE RESTRICT,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_assessment_runs_status
ON assessment_runs(status,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_assessment_runs_pack
ON assessment_runs(pack_id,created_at DESC);

CREATE TABLE IF NOT EXISTS section_runs (
    run_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_started',
    revision INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    submitted_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(run_id,section_key),
    FOREIGN KEY(run_id) REFERENCES assessment_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS question_responses (
    run_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    response_json TEXT NOT NULL DEFAULT '{}',
    flagged INTEGER NOT NULL DEFAULT 0,
    answered_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(run_id,question_id),
    FOREIGN KEY(run_id) REFERENCES assessment_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_question_responses_section
ON question_responses(run_id,section_key);

CREATE TABLE IF NOT EXISTS audio_playback_leases (
    lease_hash TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_accessed_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY(run_id) REFERENCES assessment_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(media_id) REFERENCES media_assets(media_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_audio_playback_leases_run
ON audio_playback_leases(run_id,media_id,expires_at DESC);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path(home: Path) -> Path:
    try:
        filename = str(load_settings(home).get("database_filename", "ielts.db"))
    except FileNotFoundError:
        filename = "ielts.db"
    if Path(filename).name != filename:
        raise ValueError("database_filename must be a file name, not a path")
    return home / "database" / filename


class ManagedConnection(sqlite3.Connection):
    """A transaction context that also releases the SQLite file handle."""

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


def connect(home: Path) -> sqlite3.Connection:
    path = db_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -32768")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection, previous_version: str | None = None) -> None:
    # V0.1 databases remain usable without destructive migration.
    session_columns = _columns(conn, "sessions")
    additions = {
        "question_id": "TEXT",
        "passage_id": "TEXT",
        "assessment_pack_id": "TEXT",
        "mode": "TEXT",
        "practice_mode": "TEXT",
        "conformance_status": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'completed'",
        "updated_at": "TEXT",
        "score_kind": "TEXT",
        "score_confidence": "TEXT",
        "answer_key_source": "TEXT",
        "band_conversion_source": "TEXT",
        "rubric_json": "TEXT NOT NULL DEFAULT '{}'",
        "time_limit_minutes": "REAL",
        "started_at": "TEXT",
        "submitted_at": "TEXT",
        "answer_revealed_at": "TEXT",
        "hints_used": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, declaration in additions.items():
        if name not in session_columns:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {declaration}")
    question_columns = _columns(conn, "questions")
    question_additions = {
        "practice_mode": "TEXT",
        "standard_profile": "TEXT",
        "conformance_status": "TEXT",
    }
    for name, declaration in question_additions.items():
        if name not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {name} {declaration}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_questions_conformance "
        "ON questions(practice_mode,conformance_status)"
    )
    conn.execute("UPDATE sessions SET status='completed' WHERE status IS NULL")
    conn.execute("UPDATE sessions SET updated_at=created_at WHERE updated_at IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_question ON sessions(question_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_status_time "
        "ON sessions(status,occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_errors_status_tag ON errors(status,tag)"
    )
    allocation_columns = _columns(conn, "allocation_history")
    if "period_key" not in allocation_columns:
        conn.execute("ALTER TABLE allocation_history ADD COLUMN period_key TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_allocation_period ON allocation_history(period_key)")
    calibration_columns = _columns(conn, "calibration_results")
    if "tolerance" not in calibration_columns:
        conn.execute("ALTER TABLE calibration_results ADD COLUMN tolerance REAL NOT NULL DEFAULT 0.5")
    criterion_columns = _columns(conn, "criterion_scores")
    criterion_additions = {
        "assessment_role": "TEXT NOT NULL DEFAULT 'local_rubric'",
        "evidence_source": "TEXT",
        "rubric_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, declaration in criterion_additions.items():
        if name not in criterion_columns:
            conn.execute(f"ALTER TABLE criterion_scores ADD COLUMN {name} {declaration}")
    report_columns = _columns(conn, "speaking_reports")
    report_additions = {
        "report_version": "INTEGER NOT NULL DEFAULT 1",
        "raw_report_json": "TEXT NOT NULL DEFAULT '{}'",
        "source_model_estimate_json": "TEXT NOT NULL DEFAULT '{}'",
        "local_evaluation_json": "TEXT NOT NULL DEFAULT '{}'",
        "evidence_types_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, declaration in report_additions.items():
        if name not in report_columns:
            conn.execute(f"ALTER TABLE speaking_reports ADD COLUMN {name} {declaration}")
    agent_columns = _columns(conn, "agent_runs")
    agent_additions = {
        "agent_provider": "TEXT",
        "agent_version": "TEXT",
        "model_id": "TEXT",
        "model_display_name": "TEXT",
        "launcher_kind": "TEXT NOT NULL DEFAULT 'unknown'",
        "capabilities_json": "TEXT NOT NULL DEFAULT '{}'",
        "calibration_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "timeout_seconds": "INTEGER NOT NULL DEFAULT 120",
        "attempt_count": "INTEGER NOT NULL DEFAULT 1",
        "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
        "heartbeat_at": "TEXT",
        "recovery_action": "TEXT",
        "execution_ref": "TEXT",
    }
    for name, declaration in agent_additions.items():
        if name not in agent_columns:
            conn.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {declaration}")
    conn.execute(
        """
        INSERT OR IGNORE INTO media_bindings(media_id,owner_type,owner_id,purpose,created_at)
        SELECT media_id,owner_type,owner_id,'evidence',created_at
        FROM media_assets
        WHERE owner_type IS NOT NULL AND owner_id IS NOT NULL
        """
    )
    previous_number = int(previous_version) if str(previous_version).isdigit() else 0
    if previous_version is not None and previous_number < 10:
        # Pre-v10 review_status was an importable declaration, not an auditable
        # local approval. Preserve it as source metadata and require re-review.
        for table, key, pending_status in (
            ("questions", "question_id", "unreviewed"),
            ("assessment_packs", "pack_id", "in_review"),
        ):
            rows = conn.execute(
                f"SELECT {key},payload_json FROM {table}"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                if payload.get("review_status") is not None:
                    payload.setdefault(
                        "source_review_status",
                        str(payload["review_status"]),
                    )
                if payload.get("conformance_status") is not None:
                    payload.setdefault(
                        "source_conformance_status",
                        str(payload["conformance_status"]),
                    )
                payload["review_status"] = pending_status
                payload["conformance_status"] = (
                    "skill_only"
                    if payload.get("practice_mode") == "skill_drill"
                    else "provisional"
                )
                payload.pop("conformance_report", None)
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET review_status=?,conformance_status=?,payload_json=?,updated_at=?
                    WHERE {key}=?
                    """,
                    (
                        payload["review_status"],
                        payload["conformance_status"],
                        json.dumps(payload, ensure_ascii=False, default=str),
                        _now(),
                        row[key],
                    ),
                )
    conn.execute(
        f"INSERT INTO schema_meta(key,value) VALUES('schema_version','{SCHEMA_VERSION}') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def initialise_database(home: Path) -> Path:
    path = db_path(home)
    if _existing_schema_version(path) == str(SCHEMA_VERSION):
        return path
    lock_path = home / "runtime" / "locks" / "database-migration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path), timeout=30):
        existing_version = _existing_schema_version(path)
        if existing_version == str(SCHEMA_VERSION):
            return path
        if path.is_file() and existing_version != str(SCHEMA_VERSION):
            from .backups import create_backup

            create_backup(
                home,
                kind=f"pre-migration-{existing_version or 'legacy'}-to-{SCHEMA_VERSION}",
            )
        with connect(home) as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode = WAL")
            _migrate(conn, existing_version)
    return path


def _existing_schema_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if not table:
            return "legacy"
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        return str(row[0]) if row else "legacy"
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Existing IELTS database is unreadable: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def record_session(home: Path, data: dict[str, Any]) -> None:
    initialise_database(home)
    data = validate_data(data, "session")
    session_id = str(data["session_id"])
    module = str(data["module"]).lower()
    occurred_at = str(data.get("occurred_at") or _now())
    created_at = _now()
    errors = data.get("errors", data.get("error_tags", [])) or []
    score = data.get("score") or {}
    raw_score = data.get("raw_score")
    if raw_score is None and isinstance(score, dict) and score.get("correct") is not None:
        raw_score = score.get("correct")

    with connect(home) as conn:
        existing_session = conn.execute(
            "SELECT module FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if existing_session and existing_session["module"] != module:
            raise ValueError(
                f"Session ID {session_id!r} already belongs to module "
                f"{existing_session['module']!r}, not {module!r}"
            )
        conn.execute(
            """
            INSERT INTO sessions(
              session_id,module,occurred_at,source_id,question_id,passage_id,assessment_pack_id,mode,practice_mode,conformance_status,status,raw_score,band,
              score_kind,score_confidence,answer_key_source,band_conversion_source,
              rubric_json,time_limit_minutes,started_at,submitted_at,answer_revealed_at,hints_used,
              duration_minutes,payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
              module=excluded.module,occurred_at=excluded.occurred_at,
              source_id=excluded.source_id,question_id=excluded.question_id,
              passage_id=excluded.passage_id,assessment_pack_id=excluded.assessment_pack_id,
              mode=excluded.mode,practice_mode=excluded.practice_mode,
              conformance_status=excluded.conformance_status,
              status=excluded.status,raw_score=excluded.raw_score,band=excluded.band,
              score_kind=excluded.score_kind,score_confidence=excluded.score_confidence,
              answer_key_source=excluded.answer_key_source,
              band_conversion_source=excluded.band_conversion_source,
              rubric_json=excluded.rubric_json,
              time_limit_minutes=excluded.time_limit_minutes,started_at=excluded.started_at,
              submitted_at=excluded.submitted_at,answer_revealed_at=excluded.answer_revealed_at,
              hints_used=excluded.hints_used,
              duration_minutes=excluded.duration_minutes,payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (
                session_id, module, occurred_at, data.get("source_id"), data.get("question_id"),
                data.get("passage_id"), data.get("assessment_pack_id"), data.get("mode"),
                data.get("practice_mode"), data.get("conformance_status"),
                data.get("status", "completed"), raw_score,
                data.get("band", data.get("estimated_overall")), data.get("score_kind"),
                data.get("score_confidence"),
                data.get("answer_key_source"), data.get("band_conversion_source"),
                json.dumps(data.get("rubric", {}), ensure_ascii=False, default=str),
                data.get("time_limit_minutes"), data.get("started_at"), data.get("submitted_at"),
                data.get("answer_revealed_at"), int(data.get("hints_used") or 0),
                data.get("duration_minutes"),
                json.dumps(data, ensure_ascii=False, default=str), created_at, created_at,
            ),
        )
        conn.execute("DELETE FROM errors WHERE session_id=?", (session_id,))
        for item in errors:
            if isinstance(item, str):
                tag, count, evidence, status = item, 1, None, "active"
            elif isinstance(item, dict):
                tag = str(item.get("tag", "")).strip()
                count = int(item.get("count", 1))
                evidence = _as_text(item.get("evidence"))
                status = str(item.get("status", "active"))
            else:
                continue
            if tag:
                conn.execute(
                    "INSERT INTO errors(session_id,tag,count,evidence,status) VALUES(?,?,?,?,?)",
                    (session_id, tag, count, evidence, status),
                )

        conn.execute("DELETE FROM writing_versions WHERE session_id=?", (session_id,))
        for version in data.get("versions", []) or []:
            label = str(version.get("label", version.get("version", "v1")))
            content = str(version.get("content", ""))
            if not content:
                continue
            word_count = version.get("word_count")
            if word_count is None:
                word_count = len(content.split())
            conn.execute(
                "INSERT INTO writing_versions(session_id,version_label,content,word_count,created_at) VALUES(?,?,?,?,?)",
                (session_id, label, content, int(word_count), created_at),
            )

        conn.execute("DELETE FROM criterion_scores WHERE session_id=?", (session_id,))
        for item in data.get("criterion_scores", []) or []:
            criterion = str(item.get("criterion", "")).strip()
            if not criterion:
                continue
            conn.execute(
                """
                INSERT INTO criterion_scores(
                  session_id,version_label,criterion,score_low,score_high,score,
                  confidence,assessment_role,evidence_source,rubric_json,evidence_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id, str(item.get("version", item.get("version_label", "final"))),
                    criterion, item.get("score_low"), item.get("score_high"), item.get("score"),
                    item.get("confidence"), item.get("assessment_role", "local_rubric"),
                    item.get("evidence_source"),
                    json.dumps(item.get("rubric", data.get("rubric", {})), ensure_ascii=False, default=str),
                    json.dumps(item.get("evidence", []), ensure_ascii=False, default=str), created_at,
                ),
            )

        conn.execute("DELETE FROM question_attempts WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM reading_answers WHERE session_id=?", (session_id,))
        for item in data.get("questions", []) or []:
            correct_flag = item.get("is_correct")
            payload = json.dumps(item, ensure_ascii=False, default=str)
            conn.execute(
                """
                INSERT INTO question_attempts(
                  session_id,question_id,question_number,question_type,user_answer,correct_answer,
                  is_correct,duration_seconds,evidence_location,explanation,payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id, item.get("question_id"), _as_text(item.get("question_number")),
                    item.get("question_type"), _as_text(item.get("user_answer")),
                    _as_text(item.get("correct_answer")), None if correct_flag is None else int(bool(correct_flag)),
                    item.get("duration_seconds"), item.get("evidence_location"),
                    item.get("explanation"), payload, created_at,
                ),
            )
            if module == "reading":
                tags = item.get("error_tags", []) or []
                conn.execute(
                    """
                    INSERT INTO reading_answers(
                      session_id,question_id,question_number,question_type,user_answer,correct_answer,
                      is_correct,duration_seconds,evidence_location,error_tags_json,payload_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        session_id, item.get("question_id"), _as_text(item.get("question_number")),
                        str(item.get("question_type", "unknown")), _as_text(item.get("user_answer")),
                        _as_text(item.get("correct_answer")), None if correct_flag is None else int(bool(correct_flag)),
                        item.get("duration_seconds"), item.get("evidence_location"),
                        json.dumps(tags, ensure_ascii=False), payload,
                    ),
                )

        if module == "speaking" and data.get("speaking_report"):
            report = data["speaking_report"]
            conn.execute(
                """
                INSERT INTO speaking_reports(
                  session_id,report_version,mode,transcript,raw_report_json,
                  source_model_estimate_json,local_evaluation_json,evidence_types_json,
                  report_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET
                  report_version=excluded.report_version,mode=excluded.mode,
                  transcript=excluded.transcript,raw_report_json=excluded.raw_report_json,
                  source_model_estimate_json=excluded.source_model_estimate_json,
                  local_evaluation_json=excluded.local_evaluation_json,
                  evidence_types_json=excluded.evidence_types_json,
                  report_json=excluded.report_json,created_at=excluded.created_at
                """,
                (
                    session_id, report.get("report_version", 2), report.get("mode"),
                    (report.get("source_observations") or {}).get("transcript"),
                    json.dumps(data.get("speaking_raw_report", report), ensure_ascii=False, default=str),
                    json.dumps(report.get("source_model_estimate", {}), ensure_ascii=False, default=str),
                    json.dumps(report.get("local_evaluation", {}), ensure_ascii=False, default=str),
                    json.dumps((report.get("source_observations") or {}).get("evidence_types", []), ensure_ascii=False),
                    json.dumps(report, ensure_ascii=False, default=str), created_at,
                ),
            )


def get_session(home: Path, session_id: str) -> sqlite3.Row | None:
    initialise_database(home)
    with connect(home) as conn:
        return conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()


def list_sessions(
    home: Path,
    module: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    initialise_database(home)
    sql = (
        "SELECT session_id,module,occurred_at,status,mode,band,score_kind,score_confidence,"
        "duration_minutes,question_id,passage_id FROM sessions"
    )
    params: list[Any] = []
    if module:
        sql += " WHERE module=?"
        params.append(module)
    sql += " ORDER BY occurred_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(home) as conn:
        return conn.execute(sql, params).fetchall()


def latest_active_session(home: Path) -> sqlite3.Row | None:
    initialise_database(home)
    with connect(home) as conn:
        return conn.execute(
            """
            SELECT session_id,module,occurred_at,status,mode,band,score_kind,
                   score_confidence,duration_minutes,question_id,passage_id
            FROM sessions
            WHERE status NOT IN ('completed','cancelled')
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        ).fetchone()


def recent_bands(home: Path, module: str, limit: int = 3) -> list[float]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM sessions
            WHERE module=? AND status='completed' AND band IS NOT NULL
            ORDER BY occurred_at DESC LIMIT ?
            """,
            (module, max(limit * 5, 25)),
        ).fetchall()
    from .score_results import build_score_result

    values: list[float] = []
    for row in rows:
        result = build_score_result(json.loads(row["payload_json"]))
        if result["eligible_for_progress"] and result["band"] is not None:
            values.append(float(result["band"]))
        if len(values) >= limit:
            break
    return values


def recent_criterion_average(
    home: Path,
    module: str,
    criterion: str,
    limit: int = 5,
    *,
    eligible_only: bool = False,
) -> float | None:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0) value,
                   s.payload_json
            FROM criterion_scores cs JOIN sessions s ON s.session_id=cs.session_id
            WHERE s.module=? AND cs.criterion=? AND s.status='completed'
              AND COALESCE(cs.assessment_role,'local_rubric')='local_rubric'
              AND COALESCE(cs.confidence,'medium') IN ('medium','high')
            ORDER BY cs.created_at DESC LIMIT ?
            """,
            (module, criterion, max(limit * 5, 25)),
        ).fetchall()
    from .score_results import build_score_result

    values = []
    for row in rows:
        if row["value"] is None:
            continue
        if eligible_only and not build_score_result(
            json.loads(row["payload_json"])
        )["eligible_for_progress"]:
            continue
        values.append(float(row["value"]))
        if len(values) >= limit:
            break
    return sum(values) / len(values) if values else None


def days_since_last_session(home: Path, module: str) -> int | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT occurred_at FROM sessions WHERE module=? AND status='completed' ORDER BY occurred_at DESC LIMIT 1",
            (module,),
        ).fetchone()
    if not row:
        return None
    try:
        occurred = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - occurred).days)
    except ValueError:
        return None


def sessions_since(home: Path, iso_cutoff: str) -> list[sqlite3.Row]:
    initialise_database(home)
    with connect(home) as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE occurred_at>=? AND status='completed' ORDER BY occurred_at DESC",
            (iso_cutoff,),
        ).fetchall()


def error_counts_since(home: Path, iso_cutoff: str) -> list[sqlite3.Row]:
    initialise_database(home)
    with connect(home) as conn:
        return conn.execute(
            """
            SELECT e.tag,SUM(e.count) total
            FROM errors e JOIN sessions s ON s.session_id=e.session_id
            WHERE s.occurred_at>=? AND e.status<>'resolved'
            GROUP BY e.tag ORDER BY total DESC,e.tag
            """,
            (iso_cutoff,),
        ).fetchall()


def upsert_corpus(home: Path, manifest: dict[str, Any]) -> None:
    initialise_database(home)
    storage = manifest.get("storage") or {}
    permissions = manifest.get("permissions") or {}
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO corpora(corpus_id,title,source_type,local_path,redistribution_allowed,manifest_json,imported_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(corpus_id) DO UPDATE SET
              title=excluded.title,source_type=excluded.source_type,local_path=excluded.local_path,
              redistribution_allowed=excluded.redistribution_allowed,
              manifest_json=excluded.manifest_json,imported_at=excluded.imported_at
            """,
            (
                manifest["corpus_id"], manifest["title"], manifest["source_type"],
                storage.get("local_path"), int(bool(permissions.get("redistribution_allowed", False))),
                json.dumps(manifest, ensure_ascii=False, default=str), _now(),
            ),
        )


def list_corpora(home: Path) -> list[sqlite3.Row]:
    initialise_database(home)
    with connect(home) as conn:
        return conn.execute(
            "SELECT corpus_id,title,source_type,local_path,redistribution_allowed FROM corpora ORDER BY title"
        ).fetchall()


def create_content_import_job(home: Path, job: dict[str, Any], files: list[dict[str, Any]]) -> None:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO content_import_jobs(
              import_id,title,source_type,authenticity,rights_status,status,error_message,
              summary_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job["import_id"], job["title"], job["source_type"], job.get("authenticity"),
                job["rights_status"], job["status"], job.get("error_message"),
                json.dumps(job.get("summary") or {}, ensure_ascii=False, default=str), now, now,
            ),
        )
        for item in files:
            conn.execute(
                """
                INSERT INTO content_import_files(
                  import_id,original_name,stored_name,file_kind,mime_type,size_bytes,sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    job["import_id"], item["original_name"], item["stored_name"],
                    item["file_kind"], item.get("mime_type"), int(item["size_bytes"]),
                    item["sha256"], now,
                ),
            )


def update_content_import_job(
    home: Path,
    import_id: str,
    *,
    status: str,
    error_message: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    initialise_database(home)
    with connect(home) as conn:
        cursor = conn.execute(
            """
            UPDATE content_import_jobs
            SET status=?,error_message=?,summary_json=?,updated_at=?
            WHERE import_id=?
            """,
            (
                status, error_message,
                json.dumps(summary or {}, ensure_ascii=False, default=str), _now(), import_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Unknown content import: {import_id}")


def get_content_import_job(home: Path, import_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM content_import_jobs WHERE import_id=?", (import_id,)
        ).fetchone()
        if not row:
            return None
        files = conn.execute(
            """
            SELECT original_name,stored_name,file_kind,mime_type,size_bytes,sha256
            FROM content_import_files WHERE import_id=? ORDER BY id
            """,
            (import_id,),
        ).fetchall()
    result = dict(row)
    result["summary"] = json.loads(result.pop("summary_json") or "{}")
    result["files"] = [dict(item) for item in files]
    return result


def list_content_import_jobs(home: Path, limit: int = 100) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        ids = [
            str(row["import_id"])
            for row in conn.execute(
                "SELECT import_id FROM content_import_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        ]
    return [item for import_id in ids if (item := get_content_import_job(home, import_id))]


def upsert_assessment_pack(home: Path, pack: dict[str, Any]) -> None:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO assessment_packs(
              pack_id,corpus_id,module,title,practice_mode,standard_profile,standard_version,
              source_type,authenticity,rights_status,review_status,conformance_status,
              payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(pack_id) DO UPDATE SET
              corpus_id=excluded.corpus_id,module=excluded.module,title=excluded.title,
              practice_mode=excluded.practice_mode,standard_profile=excluded.standard_profile,
              standard_version=excluded.standard_version,source_type=excluded.source_type,
              authenticity=excluded.authenticity,rights_status=excluded.rights_status,
              review_status=excluded.review_status,conformance_status=excluded.conformance_status,
              payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (
                pack["pack_id"], pack.get("corpus_id"), pack["module"], pack["title"],
                pack["practice_mode"], pack["standard_profile"], pack.get("standard_version"),
                pack["source_type"], pack.get("authenticity"), pack["rights_status"],
                pack["review_status"], pack["conformance_status"],
                json.dumps(pack, ensure_ascii=False, default=str), now, now,
            ),
        )


def get_assessment_pack(home: Path, pack_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT payload_json FROM assessment_packs WHERE pack_id=?", (pack_id,)
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def list_assessment_packs(
    home: Path,
    *,
    module: str | None = None,
    practice_mode: str | None = None,
    conformance_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("module", module),
        ("practice_mode", practice_mode),
        ("conformance_status", conformance_status),
    ):
        if value:
            clauses.append(f"{column}=?")
            params.append(value)
    sql = "SELECT payload_json FROM assessment_packs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY title LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def upsert_passage(home: Path, passage: dict[str, Any]) -> None:
    initialise_database(home)
    passage_id = str(passage["passage_id"])
    topics = passage.get("topics", passage.get("topic", []))
    if isinstance(topics, str):
        topics = [topics]
    body = passage.get("body")
    if isinstance(body, list):
        body = "\n\n".join(str(x) for x in body)
    if not body:
        raise ValueError(f"Passage {passage_id} has no body")
    with connect(home) as conn:
        existing = conn.execute(
            "SELECT corpus_id FROM question_passages WHERE passage_id=?", (passage_id,)
        ).fetchone()
        if existing and existing["corpus_id"] != passage.get("corpus_id"):
            raise ValueError(
                f"Passage ID {passage_id!r} already belongs to corpus {existing['corpus_id']!r}; "
                "use globally unique IDs (prefer <corpus-id>:<local-id>)"
            )
        conn.execute(
            """
            INSERT INTO question_passages(passage_id,corpus_id,title,body,source_type,topics_text,payload_json,created_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(passage_id) DO UPDATE SET
              corpus_id=excluded.corpus_id,title=excluded.title,body=excluded.body,
              source_type=excluded.source_type,topics_text=excluded.topics_text,payload_json=excluded.payload_json
            """,
            (
                passage_id, passage.get("corpus_id"), passage.get("title"), str(body),
                passage.get("source_type", "personal"), " ".join(map(str, topics)),
                json.dumps(passage, ensure_ascii=False, default=str), _now(),
            ),
        )


def upsert_question(home: Path, question: dict[str, Any], *, force: bool = False) -> bool:
    initialise_database(home)
    question_id = str(question["question_id"])
    q_hash = str(question["content_hash"])
    with connect(home) as conn:
        existing = conn.execute(
            "SELECT corpus_id FROM questions WHERE question_id=?", (question_id,)
        ).fetchone()
        if existing and existing["corpus_id"] != question.get("corpus_id"):
            raise ValueError(
                f"Question ID {question_id!r} already belongs to corpus {existing['corpus_id']!r}; "
                "use globally unique IDs (prefer <corpus-id>:<local-id>)"
            )
        duplicate = conn.execute(
            "SELECT question_id FROM questions WHERE content_hash=? AND question_id<>? LIMIT 1",
            (q_hash, question_id),
        ).fetchone()
        if duplicate and not force:
            return False
        topics = question.get("topics", question.get("topic", []))
        if isinstance(topics, str):
            topics = [topics]
        now = _now()
        conn.execute(
            """
            INSERT INTO questions(
              question_id,corpus_id,module,task,part,question_number,question_type,title,content,
              passage_id,topics_text,source_type,authenticity,review_status,practice_mode,
              standard_profile,conformance_status,content_hash,
              payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(question_id) DO UPDATE SET
              corpus_id=excluded.corpus_id,module=excluded.module,task=excluded.task,part=excluded.part,
              question_number=excluded.question_number,question_type=excluded.question_type,
              title=excluded.title,content=excluded.content,passage_id=excluded.passage_id,
              topics_text=excluded.topics_text,source_type=excluded.source_type,
              authenticity=excluded.authenticity,review_status=excluded.review_status,
              practice_mode=excluded.practice_mode,standard_profile=excluded.standard_profile,
              conformance_status=excluded.conformance_status,
              content_hash=excluded.content_hash,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (
                question_id, question.get("corpus_id"), question["module"], question.get("task"),
                _as_text(question.get("part")), _as_text(question.get("question_number")),
                question.get("question_type"), question.get("title"), question["content"],
                question.get("passage_id"), " ".join(map(str, topics)), question["source_type"],
                question.get("authenticity"), question.get("review_status"),
                question.get("practice_mode"), question.get("standard_profile"),
                question.get("conformance_status"), q_hash,
                json.dumps(question, ensure_ascii=False, default=str), now, now,
            ),
        )
        conn.execute("DELETE FROM question_options WHERE question_id=?", (question_id,))
        options = question.get("options", []) or []
        correct_answer = question.get("correct_answer")
        if isinstance(options, dict):
            options = [{"key": key, "text": value} for key, value in options.items()]
        for index, option in enumerate(options):
            if isinstance(option, str):
                key, text = chr(65 + index), option
            else:
                key = str(option.get("key", chr(65 + index)))
                text = str(option.get("text", option.get("content", "")))
            is_correct = None if correct_answer is None else int(str(correct_answer).casefold() == key.casefold())
            conn.execute(
                "INSERT INTO question_options(question_id,option_key,option_text,is_correct) VALUES(?,?,?,?)",
                (question_id, key, text, is_correct),
            )
    return True


def list_questions(
    home: Path,
    *, query: str | None = None, module: str | None = None, task: str | None = None,
    question_type: str | None = None, topic: str | None = None, source_type: str | None = None,
    corpus_id: str | None = None, passage_id: str | None = None,
    exclude_completed: bool = False, limit: int = 50, offset: int = 0,
) -> list[sqlite3.Row]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("q.module", module), ("q.task", task), ("q.question_type", question_type),
        ("q.source_type", source_type), ("q.corpus_id", corpus_id),
        ("q.passage_id", passage_id),
    ):
        if value:
            clauses.append(f"{column}=?")
            params.append(value)
    if topic:
        clauses.append("LOWER(q.topics_text) LIKE ?")
        params.append(f"%{topic.lower()}%")
    if query:
        clauses.append("(LOWER(q.content) LIKE ? OR LOWER(COALESCE(q.title,'')) LIKE ? OR LOWER(q.topics_text) LIKE ?)")
        value = f"%{query.lower()}%"
        params.extend([value, value, value])
    if exclude_completed:
        clauses.append(
            "NOT EXISTS(SELECT 1 FROM sessions s WHERE s.question_id=q.question_id AND s.status='completed') AND NOT EXISTS(SELECT 1 FROM question_attempts qa JOIN sessions s2 ON s2.session_id=qa.session_id WHERE qa.question_id=q.question_id AND s2.status='completed')"
        )
    sql = "SELECT q.question_id,q.module,q.task,q.part,q.question_type,q.title,q.content,q.passage_id,q.topics_text,q.source_type,q.authenticity,q.corpus_id,q.review_status,q.practice_mode,q.standard_profile,q.conformance_status FROM questions q"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY q.question_id LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(home) as conn:
        return conn.execute(sql, params).fetchall()


def get_question(home: Path, question_id: str, include_answer: bool = False) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute("SELECT * FROM questions WHERE question_id=?", (question_id,)).fetchone()
        if not row:
            return None
        if include_answer:
            active_timed = None
            if row["passage_id"]:
                active_timed = conn.execute(
                    """
                    SELECT 1 FROM sessions
                    WHERE module='reading' AND mode='timed-practice'
                      AND passage_id=? AND status NOT IN ('completed','cancelled')
                      AND submitted_at IS NULL
                    LIMIT 1
                    """,
                    (row["passage_id"],),
                ).fetchone()
            if not active_timed:
                active_pack_rows = conn.execute(
                    """
                    SELECT p.payload_json
                    FROM sessions s
                    JOIN assessment_packs p ON p.pack_id=s.assessment_pack_id
                    WHERE s.module='reading' AND s.practice_mode='full_mock'
                      AND s.status NOT IN ('completed','cancelled')
                      AND s.submitted_at IS NULL
                    """
                ).fetchall()
                active_timed = any(
                    question_id in (json.loads(item["payload_json"]).get("question_ids") or [])
                    for item in active_pack_rows
                )
            if active_timed:
                raise ValueError(
                    "Reading answers are locked until the active timed-practice Session is submitted"
                )
        data = json.loads(row["payload_json"])
        if row["passage_id"]:
            passage = conn.execute("SELECT passage_id,title,body FROM question_passages WHERE passage_id=?", (row["passage_id"],)).fetchone()
            if passage:
                data["passage"] = dict(passage)
        options = conn.execute(
            "SELECT option_key,option_text,is_correct FROM question_options WHERE question_id=? ORDER BY id",
            (question_id,),
        ).fetchall()
        if options:
            data["options"] = [
                {"key": item["option_key"], "text": item["option_text"]}
                for item in options
            ]
        if not include_answer:
            data = _redact_answer_data(data)
        return data


def get_question_for_grading(home: Path, question_id: str) -> dict[str, Any] | None:
    """Load the private answer payload for an in-process submission grader.

    This deliberately bypasses the learner-facing reveal lock, but is not exposed
    through the HTTP API. Callers must only persist or return the result after the
    learner has submitted the attempt.
    """
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT payload_json FROM questions WHERE question_id=?", (question_id,)
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


_SENSITIVE_ANSWER_KEYS = {
    "answer", "answers", "answer_key", "correct_answer", "correct_answers",
    "is_correct", "solution", "solutions", "rationale", "explanation",
    "evidence_location",
}


def _redact_answer_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_answer_data(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_ANSWER_KEYS
        }
    if isinstance(value, list):
        return [_redact_answer_data(item) for item in value]
    return value


def redact_answer_data(value: Any) -> Any:
    """Return learner-visible question data without answer or rationale fields."""
    return _redact_answer_data(value)


def question_attempted(home: Path, question_id: str) -> bool:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions s WHERE s.question_id=? AND s.status='completed' UNION SELECT 1 FROM question_attempts qa JOIN sessions s2 ON s2.session_id=qa.session_id WHERE qa.question_id=? AND s2.status='completed' LIMIT 1",
            (question_id, question_id),
        ).fetchone()
    return row is not None


def save_allocation(
    home: Path,
    allocation: dict[str, float],
    reasons: list[str],
    evidence: dict[str, Any],
    period_key: str,
) -> None:
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO allocation_history(
              calculated_at,listening,reading,writing,speaking,reasons_json,evidence_json,period_key
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(period_key) DO UPDATE SET
              calculated_at=excluded.calculated_at,listening=excluded.listening,
              reading=excluded.reading,writing=excluded.writing,speaking=excluded.speaking,
              reasons_json=excluded.reasons_json,evidence_json=excluded.evidence_json
            """,
            (
                _now(), allocation["listening"], allocation["reading"], allocation["writing"],
                allocation["speaking"], json.dumps(reasons, ensure_ascii=False),
                json.dumps(evidence, ensure_ascii=False, default=str),
                period_key,
            ),
        )


def latest_allocation(home: Path, *, exclude_period: str | None = None) -> dict[str, float] | None:
    initialise_database(home)
    with connect(home) as conn:
        if exclude_period is None:
            row = conn.execute(
                "SELECT listening,reading,writing,speaking FROM allocation_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT listening,reading,writing,speaking FROM allocation_history
                WHERE period_key IS NULL OR period_key<>? ORDER BY id DESC LIMIT 1
                """,
                (exclude_period,),
            ).fetchone()
    return dict(row) if row else None


def list_error_profile(home: Path, status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
    initialise_database(home)
    clauses = "WHERE e.status=?" if status else ""
    params: list[Any] = [status] if status else []
    params.append(limit)
    with connect(home) as conn:
        return conn.execute(
            f"""
            SELECT e.tag,e.status,SUM(e.count) total,COUNT(DISTINCT e.session_id) sessions,
                   MAX(s.occurred_at) last_seen
            FROM errors e JOIN sessions s ON s.session_id=e.session_id
            {clauses}
            GROUP BY e.tag,e.status ORDER BY total DESC,e.tag LIMIT ?
            """,
            params,
        ).fetchall()


def update_error_status(home: Path, tag: str, status: str) -> int:
    if status not in {"active", "resolved", "monitoring"}:
        raise ValueError("status must be active, resolved, or monitoring")
    initialise_database(home)
    with connect(home) as conn:
        cursor = conn.execute("UPDATE errors SET status=? WHERE tag=?", (status, tag))
        return cursor.rowcount


def upsert_listening_items(home: Path, items: list[dict[str, Any]]) -> None:
    initialise_database(home)
    now = _now()
    values: list[tuple[Any, ...]] = []
    for item in items:
        item_id = str(item["item_id"])
        category = str(item["category"])
        expression = str(item["expression"]).strip()
        meaning_zh = str(item["meaning_zh"]).strip()
        if not item_id or not category or not expression or not meaning_zh:
            raise ValueError("Listening item requires item_id, category, expression, and meaning_zh")
        values.append(
            (
                item_id,
                category,
                item.get("subcategory"),
                expression,
                meaning_zh,
                int(item.get("priority", 1)),
                str(item.get("source_type", "project_original")),
                json.dumps(item, ensure_ascii=False, default=str),
                now,
                now,
            )
        )
    with connect(home) as conn:
        conn.executemany(
            """
            INSERT INTO listening_items(
              item_id,category,subcategory,expression,meaning_zh,priority,
              source_type,payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(item_id) DO UPDATE SET
              category=excluded.category,subcategory=excluded.subcategory,
              expression=excluded.expression,meaning_zh=excluded.meaning_zh,
              priority=excluded.priority,source_type=excluded.source_type,
              payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            values,
        )


def upsert_listening_item(home: Path, item: dict[str, Any]) -> None:
    upsert_listening_items(home, [item])


def get_listening_item(home: Path, item_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT payload_json FROM listening_items WHERE item_id=?", (item_id,)
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def list_listening_items(
    home: Path,
    *,
    category: str | None = None,
    query: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if category:
        clauses.append("category=?")
        params.append(category)
    if query:
        clauses.append("(LOWER(expression) LIKE ? OR meaning_zh LIKE ? OR LOWER(payload_json) LIKE ?)")
        value = f"%{query.casefold()}%"
        params.extend([value, f"%{query}%", value])
    sql = "SELECT payload_json FROM listening_items"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY priority,item_id LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def listening_attempt_rows(home: Path) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT qa.is_correct,qa.payload_json
            FROM question_attempts qa
            JOIN sessions s ON s.session_id=qa.session_id
            WHERE s.module='listening' AND qa.question_type='high_frequency_expression'
            ORDER BY qa.created_at,qa.id
            """
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        result.append(
            {
                "item_id": payload.get("item_id"),
                "is_correct": None if row["is_correct"] is None else bool(row["is_correct"]),
                "payload": payload,
            }
        )
    return result


def record_runtime_event(
    home: Path,
    *,
    event_id: str,
    event_type: str,
    session_id: str | None = None,
    module: str | None = None,
    revision: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Record an idempotent local runtime event without storing learner prose."""
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO runtime_events(event_id,session_id,module,event_type,revision,payload_json,created_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO NOTHING
            """,
            (
                event_id,
                session_id,
                module,
                event_type,
                revision,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                _now(),
            ),
        )


def record_runtime_telemetry(home: Path, event: dict[str, Any]) -> None:
    """Persist metadata-only cost/latency observations; raw prompts are forbidden."""
    initialise_database(home)
    event = validate_data(event, "telemetry-event")
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO runtime_telemetry(
              event_type,module,session_id,model_label,input_tokens,output_tokens,
              latency_ms,tool_calls,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                event["event_type"], event.get("module"), event.get("session_id"),
                event.get("model_label"), event.get("input_tokens"), event.get("output_tokens"),
                event.get("latency_ms"), event.get("tool_calls"), event.get("created_at") or _now(),
            ),
        )


def telemetry_summary(home: Path, days: int = 30) -> list[sqlite3.Row]:
    initialise_database(home)
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    with connect(home) as conn:
        return conn.execute(
            """
            SELECT COALESCE(module,'unspecified') module,COUNT(*) events,
                   SUM(COALESCE(input_tokens,0)) input_tokens,
                   SUM(COALESCE(output_tokens,0)) output_tokens,
                   ROUND(AVG(latency_ms),1) average_latency_ms,
                   SUM(COALESCE(tool_calls,0)) tool_calls
            FROM runtime_telemetry WHERE created_at>=?
            GROUP BY COALESCE(module,'unspecified') ORDER BY module
            """,
            (cutoff_iso,),
        ).fetchall()


def get_study_draft(home: Path, session_id: str, draft_kind: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT revision,payload_json,updated_at FROM study_drafts WHERE session_id=? AND draft_kind=?",
            (session_id, draft_kind),
        ).fetchone()
    if not row:
        return None
    return {
        "session_id": session_id,
        "draft_kind": draft_kind,
        "revision": int(row["revision"]),
        "payload": json.loads(row["payload_json"]),
        "updated_at": row["updated_at"],
    }


def save_study_draft(
    home: Path,
    session_id: str,
    draft_kind: str,
    payload: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        row = conn.execute(
            "SELECT revision FROM study_drafts WHERE session_id=? AND draft_kind=?",
            (session_id, draft_kind),
        ).fetchone()
        current = int(row["revision"]) if row else 0
        if expected_revision is not None and current != expected_revision:
            from .errors import SessionRevisionConflictError

            raise SessionRevisionConflictError(
                f"Stale draft revision: expected {expected_revision}, current {current}",
                details={"expected": expected_revision, "current": current},
            )
        revision = current + 1
        conn.execute(
            """
            INSERT INTO study_drafts(session_id,draft_kind,revision,payload_json,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(session_id,draft_kind) DO UPDATE SET
              revision=excluded.revision,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (session_id, draft_kind, revision, json.dumps(payload, ensure_ascii=False), now),
        )
    return {
        "session_id": session_id,
        "draft_kind": draft_kind,
        "revision": revision,
        "payload": payload,
        "updated_at": now,
    }


def get_idempotency_record(home: Path, scope: str, key: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT operation,response_json,created_at FROM idempotency_records WHERE scope=? AND idempotency_key=?",
            (scope, key),
        ).fetchone()
    if not row:
        return None
    return {
        "operation": row["operation"],
        "response": json.loads(row["response_json"]),
        "created_at": row["created_at"],
    }


def save_idempotency_record(
    home: Path, scope: str, key: str, operation: str, response: dict[str, Any]
) -> None:
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO idempotency_records(scope,idempotency_key,operation,response_json,created_at)
            VALUES(?,?,?,?,?) ON CONFLICT(scope,idempotency_key) DO NOTHING
            """,
            (scope, key, operation, json.dumps(response, ensure_ascii=False, default=str), _now()),
        )


def register_media_asset(home: Path, asset: dict[str, Any]) -> dict[str, Any]:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        existing = conn.execute(
            "SELECT * FROM media_assets WHERE content_hash=? AND mime_type=?",
            (asset["content_hash"], asset["mime_type"]),
        ).fetchone()
        if existing:
            _bind_media_owner(conn, str(existing["media_id"]), asset, now)
            return _media_row(existing)
        conn.execute(
            """
            INSERT INTO media_assets(
              media_id,owner_type,owner_id,media_type,mime_type,local_path,content_hash,
              width,height,alt_text,privacy_status,metadata_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                asset["media_id"], asset.get("owner_type"), asset.get("owner_id"),
                asset["media_type"], asset["mime_type"], asset["local_path"],
                asset["content_hash"], asset.get("width"), asset.get("height"),
                asset.get("alt_text"), asset.get("privacy_status", "local_only"),
                json.dumps(asset.get("metadata") or {}, ensure_ascii=False), now,
            ),
        )
        _bind_media_owner(conn, str(asset["media_id"]), asset, now)
        row = conn.execute("SELECT * FROM media_assets WHERE media_id=?", (asset["media_id"],)).fetchone()
    return _media_row(row)


def bind_media_asset(
    home: Path,
    media_id: str,
    *,
    owner_type: str,
    owner_id: str,
    purpose: str = "evidence",
) -> dict[str, Any]:
    """Bind a registered asset to another owner without duplicating the file."""
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM media_assets WHERE media_id=?", (media_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown media asset: {media_id}")
        _bind_media_owner(
            conn,
            media_id,
            {
                "owner_type": owner_type,
                "owner_id": owner_id,
                "purpose": purpose,
            },
            _now(),
        )
    return _media_row(row)


def _bind_media_owner(
    conn: sqlite3.Connection,
    media_id: str,
    asset: dict[str, Any],
    created_at: str,
) -> None:
    owner_type = asset.get("owner_type")
    owner_id = asset.get("owner_id")
    if not owner_type or not owner_id:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO media_bindings(
          media_id,owner_type,owner_id,purpose,created_at
        ) VALUES(?,?,?,?,?)
        """,
        (
            media_id,
            str(owner_type),
            str(owner_id),
            str(asset.get("purpose") or "evidence"),
            created_at,
        ),
    )


def _media_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "media_id": row["media_id"],
        "owner_type": row["owner_type"],
        "owner_id": row["owner_id"],
        "media_type": row["media_type"],
        "mime_type": row["mime_type"],
        "local_path": row["local_path"],
        "content_hash": row["content_hash"],
        "width": row["width"],
        "height": row["height"],
        "alt_text": row["alt_text"],
        "privacy_status": row["privacy_status"],
        "metadata": json.loads(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def get_media_asset(home: Path, media_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute("SELECT * FROM media_assets WHERE media_id=?", (media_id,)).fetchone()
    return _media_row(row) if row else None


def list_media_assets(
    home: Path,
    limit: int = 100,
    *,
    owner_type: str | None = None,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    initialise_database(home)
    params: list[Any] = []
    sql = "SELECT DISTINCT m.* FROM media_assets m"
    clauses: list[str] = []
    if owner_type or owner_id:
        sql += " JOIN media_bindings b ON b.media_id=m.media_id"
        if owner_type:
            clauses.append("b.owner_type=?")
            params.append(owner_type)
        if owner_id:
            clauses.append("b.owner_id=?")
            params.append(owner_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_media_row(row) for row in rows]


def create_agent_run(home: Path, run: dict[str, Any]) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO agent_runs(
              run_id,study_session_id,adapter_id,agent_provider,agent_version,model_id,
              model_display_name,agent_session_id,launcher_kind,capabilities_json,
              calibration_status,action,output_contract,
              base_revision,status,error_code,request_json,result_json,usage_json,
              created_at,started_at,completed_at,timeout_seconds,attempt_count,
              cancel_requested,heartbeat_at,recovery_action,execution_ref
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run["run_id"], run.get("study_session_id"), run["adapter_id"],
                run.get("agent_provider"), run.get("agent_version"), run.get("model_id"),
                run.get("model_display_name"), run.get("agent_session_id"),
                run.get("launcher_kind", "unknown"),
                json.dumps(run.get("capabilities") or {}, ensure_ascii=False),
                run.get("calibration_status", "unknown"),
                run["action"], run["output_contract"],
                run.get("base_revision"), run["status"], run.get("error_code"),
                json.dumps(run.get("request") or {}, ensure_ascii=False),
                json.dumps(run.get("result"), ensure_ascii=False) if run.get("result") is not None else None,
                json.dumps(run.get("usage") or {}, ensure_ascii=False),
                run.get("created_at") or _now(), run.get("started_at"), run.get("completed_at"),
                int(run.get("timeout_seconds") or 120),
                int(run.get("attempt_count") or 1),
                int(bool(run.get("cancel_requested", False))),
                run.get("heartbeat_at"), run.get("recovery_action"),
                run.get("execution_ref"),
            ),
        )
    return get_agent_run(home, run["run_id"]) or run


def update_agent_run(home: Path, run_id: str, **changes: Any) -> dict[str, Any]:
    allowed = {
        "agent_provider", "agent_version", "model_id", "model_display_name",
        "agent_session_id", "launcher_kind", "capabilities_json",
        "calibration_status", "status", "error_code", "result_json", "usage_json",
        "started_at", "completed_at", "timeout_seconds", "attempt_count",
        "cancel_requested", "heartbeat_at", "recovery_action", "execution_ref",
        "base_revision",
    }
    columns: list[str] = []
    values: list[Any] = []
    for key, value in changes.items():
        column = key
        if key == "result":
            column, value = "result_json", json.dumps(value, ensure_ascii=False)
        elif key == "usage":
            column, value = "usage_json", json.dumps(value, ensure_ascii=False)
        elif key == "capabilities":
            column, value = "capabilities_json", json.dumps(value, ensure_ascii=False)
        if column not in allowed:
            continue
        columns.append(f"{column}=?")
        values.append(value)
    if not columns:
        return get_agent_run(home, run_id) or {}
    values.append(run_id)
    with connect(home) as conn:
        conn.execute(f"UPDATE agent_runs SET {','.join(columns)} WHERE run_id=?", values)
    return get_agent_run(home, run_id) or {}


def get_agent_run(home: Path, run_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return None
    return _agent_run_row(row)


def _agent_run_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "study_session_id": row["study_session_id"],
        "adapter_id": row["adapter_id"],
        "agent_provider": row["agent_provider"],
        "agent_version": row["agent_version"],
        "model_id": row["model_id"],
        "model_display_name": row["model_display_name"],
        "agent_session_id": row["agent_session_id"],
        "launcher_kind": row["launcher_kind"],
        "capabilities": json.loads(row["capabilities_json"]),
        "calibration_status": row["calibration_status"],
        "action": row["action"],
        "output_contract": row["output_contract"],
        "base_revision": row["base_revision"],
        "status": row["status"],
        "error_code": row["error_code"],
        "request": json.loads(row["request_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "usage": json.loads(row["usage_json"]),
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "timeout_seconds": int(row["timeout_seconds"]),
        "attempt_count": int(row["attempt_count"]),
        "cancel_requested": bool(row["cancel_requested"]),
        "heartbeat_at": row["heartbeat_at"],
        "recovery_action": row["recovery_action"],
        "execution_ref": row["execution_ref"],
    }


def list_agent_runs(
    home: Path,
    *,
    study_session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    params: list[Any] = []
    sql = "SELECT * FROM agent_runs"
    if study_session_id:
        sql += " WHERE study_session_id=?"
        params.append(study_session_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_agent_run_row(row) for row in rows]


def append_agent_run_event(
    home: Path, run_id: str, event_type: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 AS next_sequence FROM agent_run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
        sequence = int(row["next_sequence"])
        created_at = _now()
        conn.execute(
            "INSERT INTO agent_run_events(run_id,sequence,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
            (run_id, sequence, event_type, json.dumps(payload or {}, ensure_ascii=False), created_at),
        )
    return {
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "payload": payload or {},
        "created_at": created_at,
    }


def list_agent_run_events(home: Path, run_id: str, after: int = 0) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_run_events WHERE run_id=? AND sequence>? ORDER BY sequence",
            (run_id, after),
        ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "sequence": int(row["sequence"]),
            "type": row["event_type"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def save_coaching_artifact(
    home: Path,
    *,
    artifact_id: str,
    artifact_type: str,
    contract_version: int,
    payload: dict[str, Any],
    study_session_id: str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    initialise_database(home)
    created_at = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO coaching_artifacts(
              artifact_id,artifact_type,contract_version,study_session_id,
              agent_run_id,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(artifact_id) DO UPDATE SET
              payload_json=excluded.payload_json,contract_version=excluded.contract_version
            """,
            (
                artifact_id,
                artifact_type,
                int(contract_version),
                study_session_id,
                agent_run_id,
                json.dumps(payload, ensure_ascii=False),
                created_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM coaching_artifacts WHERE artifact_id=?", (artifact_id,)
        ).fetchone()
    return {
        **dict(row),
        "payload": json.loads(row["payload_json"]),
    }


def list_coaching_artifacts(
    home: Path, *, artifact_type: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    initialise_database(home)
    sql = "SELECT * FROM coaching_artifacts"
    params: list[Any] = []
    if artifact_type:
        sql += " WHERE artifact_type=?"
        params.append(artifact_type)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload_json"])}
        for row in rows
    ]
