from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .validation import normalise_json_value, validate_data
from .config import load_settings

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    module TEXT NOT NULL CHECK(module IN ('listening','reading','writing','speaking')),
    occurred_at TEXT NOT NULL,
    source_id TEXT,
    question_id TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    raw_score REAL,
    band REAL,
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

CREATE TABLE IF NOT EXISTS corpora (
    corpus_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    local_path TEXT,
    redistribution_allowed INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

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
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, version_label, criterion),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_criteria ON criterion_scores(criterion);

CREATE TABLE IF NOT EXISTS speaking_reports (
    session_id TEXT PRIMARY KEY,
    mode TEXT,
    transcript TEXT,
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
"""


def db_path(home: Path) -> Path:
    try:
        filename = str(load_settings(home).get("database_filename", "ielts.db"))
    except FileNotFoundError:
        filename = "ielts.db"
    if Path(filename).name != filename:
        raise ValueError("database_filename must be a file name, not a path")
    return home / "database" / filename


def connect(home: Path) -> sqlite3.Connection:
    path = db_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    # V0.1 databases remain usable without destructive migration.
    session_columns = _columns(conn, "sessions")
    additions = {
        "question_id": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'completed'",
        "updated_at": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in session_columns:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {declaration}")
    conn.execute("UPDATE sessions SET status='completed' WHERE status IS NULL")
    conn.execute("UPDATE sessions SET updated_at=created_at WHERE updated_at IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_question ON sessions(question_id)")
    allocation_columns = _columns(conn, "allocation_history")
    if "period_key" not in allocation_columns:
        conn.execute("ALTER TABLE allocation_history ADD COLUMN period_key TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_allocation_period ON allocation_history(period_key)")
    calibration_columns = _columns(conn, "calibration_results")
    if "tolerance" not in calibration_columns:
        conn.execute("ALTER TABLE calibration_results ADD COLUMN tolerance REAL NOT NULL DEFAULT 0.5")


def initialise_database(home: Path) -> Path:
    path = db_path(home)
    with connect(home) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    return path


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
              session_id,module,occurred_at,source_id,question_id,status,raw_score,band,
              duration_minutes,payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
              module=excluded.module,occurred_at=excluded.occurred_at,
              source_id=excluded.source_id,question_id=excluded.question_id,
              status=excluded.status,raw_score=excluded.raw_score,band=excluded.band,
              duration_minutes=excluded.duration_minutes,payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (
                session_id, module, occurred_at, data.get("source_id"), data.get("question_id"),
                data.get("status", "completed"), raw_score,
                data.get("band", data.get("estimated_overall")), data.get("duration_minutes"),
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
                  confidence,evidence_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id, str(item.get("version", item.get("version_label", "final"))),
                    criterion, item.get("score_low"), item.get("score_high"), item.get("score"),
                    item.get("confidence"),
                    json.dumps(item.get("evidence", []), ensure_ascii=False, default=str), created_at,
                ),
            )

        conn.execute("DELETE FROM question_attempts WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM reading_answers WHERE session_id=?", (session_id,))
        for item in data.get("questions", []) or []:
            correct_flag = item.get("is_correct")
            if correct_flag is None and item.get("user_answer") is not None and item.get("correct_answer") is not None:
                correct_flag = str(item.get("user_answer")).strip().casefold() == str(item.get("correct_answer")).strip().casefold()
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
                INSERT INTO speaking_reports(session_id,mode,transcript,report_json,created_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET
                  mode=excluded.mode,transcript=excluded.transcript,
                  report_json=excluded.report_json,created_at=excluded.created_at
                """,
                (
                    session_id, report.get("mode"), report.get("transcript"),
                    json.dumps(report, ensure_ascii=False, default=str), created_at,
                ),
            )


def get_session(home: Path, session_id: str) -> sqlite3.Row | None:
    initialise_database(home)
    with connect(home) as conn:
        return conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()


def list_sessions(home: Path, module: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
    initialise_database(home)
    sql = "SELECT session_id,module,occurred_at,status,band,duration_minutes,question_id FROM sessions"
    params: list[Any] = []
    if module:
        sql += " WHERE module=?"
        params.append(module)
    sql += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(limit)
    with connect(home) as conn:
        return conn.execute(sql, params).fetchall()


def recent_bands(home: Path, module: str, limit: int = 3) -> list[float]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT band FROM sessions WHERE module=? AND status='completed' AND band IS NOT NULL ORDER BY occurred_at DESC LIMIT ?",
            (module, limit),
        ).fetchall()
    return [float(row["band"]) for row in rows]


def recent_criterion_average(home: Path, module: str, criterion: str, limit: int = 5) -> float | None:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(cs.score,(cs.score_low+cs.score_high)/2.0) value
            FROM criterion_scores cs JOIN sessions s ON s.session_id=cs.session_id
            WHERE s.module=? AND cs.criterion=?
            ORDER BY cs.created_at DESC LIMIT ?
            """,
            (module, criterion, limit),
        ).fetchall()
    values = [float(row["value"]) for row in rows if row["value"] is not None]
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
              passage_id,topics_text,source_type,authenticity,review_status,content_hash,
              payload_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(question_id) DO UPDATE SET
              corpus_id=excluded.corpus_id,module=excluded.module,task=excluded.task,part=excluded.part,
              question_number=excluded.question_number,question_type=excluded.question_type,
              title=excluded.title,content=excluded.content,passage_id=excluded.passage_id,
              topics_text=excluded.topics_text,source_type=excluded.source_type,
              authenticity=excluded.authenticity,review_status=excluded.review_status,
              content_hash=excluded.content_hash,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (
                question_id, question.get("corpus_id"), question["module"], question.get("task"),
                _as_text(question.get("part")), _as_text(question.get("question_number")),
                question.get("question_type"), question.get("title"), question["content"],
                question.get("passage_id"), " ".join(map(str, topics)), question["source_type"],
                question.get("authenticity"), question.get("review_status"), q_hash,
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
    corpus_id: str | None = None, exclude_completed: bool = False, limit: int = 50,
) -> list[sqlite3.Row]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("q.module", module), ("q.task", task), ("q.question_type", question_type),
        ("q.source_type", source_type), ("q.corpus_id", corpus_id),
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
    sql = "SELECT q.question_id,q.module,q.task,q.part,q.question_type,q.title,q.content,q.passage_id,q.topics_text,q.source_type,q.authenticity,q.corpus_id FROM questions q"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY q.question_id LIMIT ?"
    params.append(limit)
    with connect(home) as conn:
        return conn.execute(sql, params).fetchall()


def get_question(home: Path, question_id: str, include_answer: bool = False) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute("SELECT * FROM questions WHERE question_id=?", (question_id,)).fetchone()
        if not row:
            return None
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
