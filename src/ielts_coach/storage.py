from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from .validation import normalise_json_value, validate_data
from .config import load_settings

SCHEMA_VERSION = 27

_CACHE_LOCK = threading.RLock()
_DB_FILENAME_CACHE: dict[Path, tuple[tuple[int, int] | None, str]] = {}
_DATABASE_READY_CACHE: dict[Path, tuple[int, int]] = {}

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
    practice_unit_id TEXT,
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
    payload_hash TEXT,
    mirror_status TEXT NOT NULL DEFAULT 'unknown',
    mirror_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_module_time ON sessions(module, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_occurred ON sessions(occurred_at DESC);

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
CREATE INDEX IF NOT EXISTS idx_questions_module_type_id ON questions(module,question_type,question_id);
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
    result_json TEXT NOT NULL DEFAULT '{}',
    practice_unit_id TEXT
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

CREATE TABLE IF NOT EXISTS execution_profiles (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    backend_kind TEXT NOT NULL CHECK(
        backend_kind IN (
            'managed_runtime','api_model','local_http_model',
            'external_agent','manual','mock'
        )
    ),
    backend_id TEXT NOT NULL,
    transport TEXT NOT NULL,
    auth_mode TEXT NOT NULL DEFAULT 'none',
    model_id TEXT,
    reasoning_effort TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_profiles_default
ON execution_profiles(is_default) WHERE is_default=1;

CREATE TABLE IF NOT EXISTS model_providers (
    provider_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider_kind TEXT NOT NULL CHECK(
        provider_kind IN (
            'codex_oauth_bridge','openai_compatible','local_http'
        )
    ),
    transport TEXT NOT NULL CHECK(
        transport IN ('codex_app_server','http')
    ),
    auth_mode TEXT NOT NULL CHECK(
        auth_mode IN ('oauth','api_key','none')
    ),
    base_url TEXT,
    model_id TEXT,
    reasoning_effort TEXT,
    role TEXT NOT NULL DEFAULT 'disabled' CHECK(
        role IN ('primary','fallback','disabled')
    ),
    fallback_order INTEGER,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    credential_ref TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_providers_primary
ON model_providers(role) WHERE role='primary' AND is_enabled=1;
CREATE INDEX IF NOT EXISTS idx_model_providers_route
ON model_providers(role,fallback_order,display_name);

CREATE TABLE IF NOT EXISTS external_agent_profiles (
    agent_profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    adapter_id TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'material_operations' CHECK(
        purpose IN (
            'material_operations','format_conversion',
            'corpus_maintenance','developer_tools','manual_handoff'
        )
    ),
    is_enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    study_session_id TEXT,
    adapter_id TEXT NOT NULL,
    capability_id TEXT,
    execution_profile_id TEXT,
    model_provider_id TEXT,
    backend_kind TEXT NOT NULL DEFAULT 'external_agent',
    transport TEXT,
    auth_mode TEXT,
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
    skill_hash TEXT,
    inference_route_json TEXT NOT NULL DEFAULT '[]',
    checkpoint TEXT NOT NULL DEFAULT 'queued',
    input_hash TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    resume_count INTEGER NOT NULL DEFAULT 0,
    persistence_json TEXT NOT NULL DEFAULT '{}',
    orchestration_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(study_session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(execution_profile_id) REFERENCES execution_profiles(profile_id) ON DELETE SET NULL,
    FOREIGN KEY(model_provider_id) REFERENCES model_providers(provider_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(study_session_id,created_at DESC);

CREATE TABLE IF NOT EXISTS agent_run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'unknown',
    display_message TEXT NOT NULL DEFAULT '',
    recoverable INTEGER NOT NULL DEFAULT 0,
    payload_hash TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id,sequence),
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_run_events_type
ON agent_run_events(run_id,event_type,sequence);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    actor_type TEXT NOT NULL DEFAULT 'local_user',
    subject_type TEXT,
    subject_id TEXT,
    session_id TEXT,
    run_id TEXT,
    capability_id TEXT,
    request_id TEXT,
    payload_hash TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_time
ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_subject
ON audit_events(subject_type,subject_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_run
ON audit_events(run_id,created_at);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events are append-only');
END;

CREATE TABLE IF NOT EXISTS provider_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL,
    run_attempt INTEGER NOT NULL DEFAULT 1,
    provider_id TEXT NOT NULL,
    provider_kind TEXT,
    model_id TEXT,
    fallback_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    failure_stage TEXT,
    error_code TEXT,
    error_message TEXT,
    result_hash TEXT,
    identity_json TEXT NOT NULL DEFAULT '{}',
    usage_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id,attempt_index),
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_provider_attempts_run
ON provider_attempts(run_id,attempt_index);

CREATE TABLE IF NOT EXISTS privacy_receipts (
    receipt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    authorization_kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    remote_processing INTEGER NOT NULL,
    private_source INTEGER NOT NULL,
    source_type TEXT,
    provider_ids_json TEXT NOT NULL DEFAULT '[]',
    scope_hash TEXT NOT NULL,
    policy_json TEXT NOT NULL DEFAULT '{}',
    reusable INTEGER NOT NULL DEFAULT 0 CHECK(reusable=0),
    created_at TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_privacy_receipts_created
ON privacy_receipts(created_at DESC);

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

CREATE TABLE IF NOT EXISTS study_threads (
    thread_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT 'mixed',
    status TEXT NOT NULL DEFAULT 'active',
    model_provider_id TEXT,
    source_context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(model_provider_id) REFERENCES model_providers(provider_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_study_threads_updated
ON study_threads(status,updated_at DESC);

CREATE TABLE IF NOT EXISTS tutor_thread_states (
    thread_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    state_json TEXT NOT NULL DEFAULT '{}',
    last_message_id TEXT,
    last_agent_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES study_threads(thread_id) ON DELETE CASCADE,
    FOREIGN KEY(last_message_id) REFERENCES study_messages(message_id) ON DELETE SET NULL,
    FOREIGN KEY(last_agent_run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tutor_proposals (
    proposal_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    source_message_id TEXT,
    agent_run_id TEXT,
    proposal_type TEXT NOT NULL CHECK(
      proposal_type IN ('practice_session','review_item','learner_memory','material_promotion')
    ),
    title TEXT NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(
      status IN ('pending','confirmed','dismissed','executed','failed')
    ),
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(thread_id) REFERENCES study_threads(thread_id) ON DELETE CASCADE,
    FOREIGN KEY(source_message_id) REFERENCES study_messages(message_id) ON DELETE SET NULL,
    FOREIGN KEY(agent_run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_tutor_proposals_thread
ON tutor_proposals(thread_id,status,created_at DESC);

CREATE TABLE IF NOT EXISTS tutor_turn_commits (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    state_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(thread_id) REFERENCES study_threads(thread_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS study_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'complete',
    context_json TEXT NOT NULL DEFAULT '{}',
    agent_run_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES study_threads(thread_id) ON DELETE CASCADE,
    FOREIGN KEY(agent_run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_study_messages_thread
ON study_messages(thread_id,created_at);

CREATE TABLE IF NOT EXISTS study_thread_attachments (
    attachment_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    message_id TEXT,
    original_name TEXT NOT NULL,
    stored_name TEXT,
    mime_type TEXT,
    file_kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    media_id TEXT,
    extracted_text TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'not_applicable',
    created_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES study_threads(thread_id) ON DELETE CASCADE,
    FOREIGN KEY(message_id) REFERENCES study_messages(message_id) ON DELETE SET NULL,
    FOREIGN KEY(media_id) REFERENCES media_assets(media_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_study_attachments_thread
ON study_thread_attachments(thread_id,created_at);

CREATE TABLE IF NOT EXISTS study_thread_summaries (
    thread_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    through_message_id TEXT,
    summary_hash TEXT NOT NULL,
    generated_by TEXT NOT NULL DEFAULT 'deterministic',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES study_threads(thread_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS learner_memories (
    memory_id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    statement TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'teaching_style',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','dismissed')),
    source_thread_id TEXT,
    source_session_id TEXT,
    created_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_thread_id) REFERENCES study_threads(thread_id) ON DELETE SET NULL,
    FOREIGN KEY(source_session_id) REFERENCES sessions(session_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_learner_memories_active
ON learner_memories(status,memory_type,updated_at DESC);

CREATE TABLE IF NOT EXISTS capability_evaluation_runs (
    evaluation_id TEXT PRIMARY KEY,
    suite_name TEXT NOT NULL,
    source_label TEXT NOT NULL,
    case_count INTEGER NOT NULL,
    passed_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('passed','failed')),
    report_hash TEXT NOT NULL,
    report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_evaluations_time
ON capability_evaluation_runs(created_at DESC);

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
    practice_unit_id TEXT,
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

CREATE TABLE IF NOT EXISTS practice_units (
    unit_id TEXT PRIMARY KEY,
    unit_kind TEXT NOT NULL CHECK(unit_kind IN ('diagnostic','practice','review')),
    module TEXT CHECK(module IN ('listening','reading','writing','speaking') OR module IS NULL),
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('planned','in_progress','completed','cancelled')),
    scheduled_for TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL UNIQUE,
    route TEXT NOT NULL,
    estimated_minutes INTEGER,
    diagnostic_id TEXT,
    session_id TEXT,
    assessment_run_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(diagnostic_id) REFERENCES diagnostic_runs(diagnostic_id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY(assessment_run_id) REFERENCES assessment_runs(run_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_units_day
ON practice_units(scheduled_for,status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_practice_units_session
ON practice_units(session_id);

CREATE TABLE IF NOT EXISTS review_tasks (
    review_task_id TEXT PRIMARY KEY,
    stable_key TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL CHECK(module IN ('listening','reading','writing','speaking')),
    review_kind TEXT NOT NULL CHECK(review_kind IN (
      'error_review','listening_expression','writing_revision','reading_wrong_answer'
    )),
    status TEXT NOT NULL CHECK(status IN ('pending','in_progress','completed','dismissed')),
    priority INTEGER NOT NULL DEFAULT 50,
    due_at TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    session_id TEXT,
    title TEXT NOT NULL,
    action TEXT NOT NULL,
    route TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    practice_unit_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(practice_unit_id) REFERENCES practice_units(unit_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_review_tasks_queue
ON review_tasks(status,due_at,priority DESC,created_at);
CREATE INDEX IF NOT EXISTS idx_review_tasks_session
ON review_tasks(session_id,status);

CREATE TABLE IF NOT EXISTS weekly_reports (
    report_id TEXT PRIMARY KEY,
    period_key TEXT NOT NULL UNIQUE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    markdown TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weekly_reports_period
ON weekly_reports(period_start DESC);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path(home: Path) -> Path:
    resolved_home = home.resolve()
    settings_path = resolved_home / "config" / "settings.yaml"
    try:
        stat = settings_path.stat()
        fingerprint: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        fingerprint = None
    with _CACHE_LOCK:
        cached = _DB_FILENAME_CACHE.get(resolved_home)
    if cached and cached[0] == fingerprint:
        filename = cached[1]
    else:
        try:
            filename = str(load_settings(resolved_home).get("database_filename", "ielts.db"))
        except FileNotFoundError:
            filename = "ielts.db"
        with _CACHE_LOCK:
            _DB_FILENAME_CACHE[resolved_home] = (fingerprint, filename)
    if Path(filename).name != filename:
        raise ValueError("database_filename must be a file name, not a path")
    return resolved_home / "database" / filename


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
        "practice_unit_id": "TEXT",
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
        "payload_hash": "TEXT",
        "mirror_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "mirror_checked_at": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in session_columns:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {declaration}")
    diagnostic_columns = _columns(conn, "diagnostic_runs")
    if "practice_unit_id" not in diagnostic_columns:
        conn.execute("ALTER TABLE diagnostic_runs ADD COLUMN practice_unit_id TEXT")
    assessment_columns = _columns(conn, "assessment_runs")
    if "practice_unit_id" not in assessment_columns:
        conn.execute("ALTER TABLE assessment_runs ADD COLUMN practice_unit_id TEXT")
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
    for row in conn.execute(
        "SELECT session_id,payload_json FROM sessions WHERE payload_hash IS NULL"
    ).fetchall():
        try:
            payload = json.loads(str(row["payload_json"]))
            digest = session_payload_hash(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        conn.execute(
            "UPDATE sessions SET payload_hash=? WHERE session_id=?",
            (digest, row["session_id"]),
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_question ON sessions(question_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_occurred "
        "ON sessions(occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_status_time "
        "ON sessions(status,occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_questions_module_type_id "
        "ON questions(module,question_type,question_id)"
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
        "capability_id": "TEXT",
        "execution_profile_id": "TEXT",
        "model_provider_id": "TEXT",
        "backend_kind": "TEXT NOT NULL DEFAULT 'external_agent'",
        "transport": "TEXT",
        "auth_mode": "TEXT",
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
        "skill_hash": "TEXT",
        "inference_route_json": "TEXT NOT NULL DEFAULT '[]'",
        "checkpoint": "TEXT NOT NULL DEFAULT 'queued'",
        "input_hash": "TEXT",
        "lease_owner": "TEXT",
        "lease_expires_at": "TEXT",
        "resume_count": "INTEGER NOT NULL DEFAULT 0",
        "persistence_json": "TEXT NOT NULL DEFAULT '{}'",
        "orchestration_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, declaration in agent_additions.items():
        if name not in agent_columns:
            conn.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {declaration}")
    event_columns = _columns(conn, "agent_run_events")
    event_additions = {
        "stage": "TEXT NOT NULL DEFAULT 'unknown'",
        "display_message": "TEXT NOT NULL DEFAULT ''",
        "recoverable": "INTEGER NOT NULL DEFAULT 0",
        "payload_hash": "TEXT",
    }
    for name, declaration in event_additions.items():
        if name not in event_columns:
            conn.execute(
                f"ALTER TABLE agent_run_events ADD COLUMN {name} {declaration}"
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_run_events_type "
        "ON agent_run_events(run_id,event_type,sequence)"
    )
    conn.execute(
        """
        UPDATE agent_runs
        SET backend_kind = CASE adapter_id
          WHEN 'mock' THEN 'mock'
          WHEN 'manual' THEN 'manual'
          WHEN 'codex-managed' THEN 'managed_runtime'
          ELSE 'external_agent'
        END
        WHERE backend_kind IS NULL
           OR backend_kind='external_agent'
        """
    )
    conn.execute(
        """
        UPDATE agent_runs
        SET capability_id = CASE output_contract
          WHEN 'writing-review@1' THEN 'writing_review'
          WHEN 'writing-mock-review@1' THEN 'writing_mock_review'
          WHEN 'reading-review@1' THEN 'reading_explanation'
          WHEN 'listening-review@1' THEN 'listening_review'
          WHEN 'speaking-evaluation@1' THEN 'speaking_evaluation'
          WHEN 'study-plan@1' THEN 'study_plan'
          WHEN 'diagnostic-summary@1' THEN 'diagnostic_summary'
          WHEN 'weekly-coaching@1' THEN 'weekly_coaching'
          ELSE capability_id
        END
        WHERE capability_id IS NULL
        """
    )
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
    identity = _database_identity(path)
    with _CACHE_LOCK:
        if identity is not None and _DATABASE_READY_CACHE.get(path) == identity:
            return path
    if _existing_schema_version(path) == str(SCHEMA_VERSION):
        _mark_database_ready(path)
        return path
    lock_path = home / "runtime" / "locks" / "database-migration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path), timeout=30):
        existing_version = _existing_schema_version(path)
        if existing_version == str(SCHEMA_VERSION):
            _mark_database_ready(path)
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
    _mark_database_ready(path)
    return path


def _database_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (int(stat.st_dev), int(stat.st_ino))


def _mark_database_ready(path: Path) -> None:
    identity = _database_identity(path)
    if identity is None:
        return
    with _CACHE_LOCK:
        _DATABASE_READY_CACHE[path] = identity


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


def session_payload_hash(data: dict[str, Any]) -> str:
    """Hash the revisioned Session payload shared by Markdown and SQLite."""
    payload = dict(data)
    payload.pop("document_body", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def set_session_mirror_status(
    home: Path,
    session_id: str,
    status: str,
) -> None:
    if status not in {"unknown", "synced", "conflict", "database_only"}:
        raise ValueError(f"Unsupported Session mirror status: {status}")
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE sessions
            SET mirror_status=?,mirror_checked_at=?
            WHERE session_id=?
            """,
            (status, _now(), session_id),
        )


def record_session(
    home: Path,
    data: dict[str, Any],
    *,
    mirror_status: str = "unknown",
) -> None:
    initialise_database(home)
    data = validate_data(data, "session")
    if mirror_status not in {"unknown", "synced", "conflict", "database_only"}:
        raise ValueError(f"Unsupported Session mirror status: {mirror_status}")
    session_id = str(data["session_id"])
    module = str(data["module"]).lower()
    occurred_at = str(data.get("occurred_at") or _now())
    created_at = _now()
    errors = data.get("errors", data.get("error_tags", [])) or []
    score = data.get("score") or {}
    raw_score = data.get("raw_score")
    if raw_score is None and isinstance(score, dict) and score.get("correct") is not None:
        raw_score = score.get("correct")
    payload_json = json.dumps(data, ensure_ascii=False, default=str)
    payload_hash = session_payload_hash(data)
    mirror_checked_at = created_at if mirror_status != "unknown" else None

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
              duration_minutes,payload_json,payload_hash,mirror_status,mirror_checked_at,
              created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
              payload_hash=excluded.payload_hash,mirror_status=excluded.mirror_status,
              mirror_checked_at=excluded.mirror_checked_at,
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
                payload_json, payload_hash, mirror_status, mirror_checked_at,
                created_at, created_at,
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


def content_import_storage_bytes(home: Path) -> int:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM content_import_files"
        ).fetchone()
    return int(row["total"] if row else 0)


def delete_content_import_job(home: Path, import_id: str) -> None:
    initialise_database(home)
    with connect(home) as conn:
        cursor = conn.execute(
            "DELETE FROM content_import_jobs WHERE import_id=?",
            (import_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Unknown content import: {import_id}")


def upsert_assessment_pack(
    home: Path,
    pack: dict[str, Any],
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    now = _now()
    if connection is not None:
        _upsert_assessment_pack(connection, pack, now=now)
        return
    initialise_database(home)
    with connect(home) as conn:
        _upsert_assessment_pack(conn, pack, now=now)


def _upsert_assessment_pack(
    conn: sqlite3.Connection,
    pack: dict[str, Any],
    *,
    now: str,
) -> None:
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
    learner_ready: bool = False,
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
    if learner_ready:
        clauses.extend(("review_status='reviewed'", "conformance_status='verified'"))
    sql = "SELECT payload_json FROM assessment_packs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY title LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def upsert_passage(
    home: Path,
    passage: dict[str, Any],
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    passage_id = str(passage["passage_id"])
    topics = passage.get("topics", passage.get("topic", []))
    if isinstance(topics, str):
        topics = [topics]
    body = passage.get("body")
    if isinstance(body, list):
        body = "\n\n".join(str(x) for x in body)
    if not body:
        raise ValueError(f"Passage {passage_id} has no body")
    if connection is not None:
        _upsert_passage(connection, passage, passage_id, topics, str(body))
        return
    initialise_database(home)
    with connect(home) as conn:
        _upsert_passage(conn, passage, passage_id, topics, str(body))


def _upsert_passage(
    conn: sqlite3.Connection,
    passage: dict[str, Any],
    passage_id: str,
    topics: list[Any],
    body: str,
) -> None:
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
            passage_id, passage.get("corpus_id"), passage.get("title"), body,
            passage.get("source_type", "personal"), " ".join(map(str, topics)),
            json.dumps(passage, ensure_ascii=False, default=str), _now(),
        ),
    )


def upsert_question(
    home: Path,
    question: dict[str, Any],
    *,
    force: bool = False,
    connection: sqlite3.Connection | None = None,
) -> bool:
    question_id = str(question["question_id"])
    q_hash = str(question["content_hash"])
    if connection is not None:
        return _upsert_question(connection, question, question_id, q_hash, force=force)
    initialise_database(home)
    with connect(home) as conn:
        return _upsert_question(conn, question, question_id, q_hash, force=force)


def _upsert_question(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    question_id: str,
    q_hash: str,
    *,
    force: bool,
) -> bool:
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
        is_correct = None if correct_answer is None else int(
            str(correct_answer).casefold() == key.casefold()
        )
        conn.execute(
            "INSERT INTO question_options(question_id,option_key,option_text,is_correct) VALUES(?,?,?,?)",
            (question_id, key, text, is_correct),
        )
    return True


def list_questions(
    home: Path,
    *, query: str | None = None, module: str | None = None, task: str | None = None,
    part: int | str | None = None, question_type: str | None = None,
    topic: str | None = None, source_type: str | None = None,
    corpus_id: str | None = None, passage_id: str | None = None,
    exclude_completed: bool = False, learner_ready: bool = False,
    limit: int = 50, offset: int = 0,
) -> list[sqlite3.Row]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("q.module", module), ("q.task", task), ("q.part", part),
        ("q.question_type", question_type),
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
        clauses.append(
            "(LOWER(q.content) LIKE ? OR LOWER(COALESCE(q.title,'')) LIKE ? "
            "OR LOWER(COALESCE(p.title,'')) LIKE ? OR LOWER(q.topics_text) LIKE ?)"
        )
        value = f"%{query.lower()}%"
        params.extend([value, value, value, value])
    if exclude_completed:
        clauses.append(
            "NOT EXISTS(SELECT 1 FROM sessions s WHERE s.question_id=q.question_id AND s.status='completed') AND NOT EXISTS(SELECT 1 FROM question_attempts qa JOIN sessions s2 ON s2.session_id=qa.session_id WHERE qa.question_id=q.question_id AND s2.status='completed')"
        )
    if learner_ready:
        clauses.extend(("q.review_status='reviewed'", "q.conformance_status='verified'"))
    sql = (
        "SELECT q.question_id,q.module,q.task,q.part,q.question_type,q.title,"
        "q.content,q.passage_id,p.title AS passage_title,q.topics_text,"
        "q.source_type,q.authenticity,q.corpus_id,q.review_status,"
        "q.practice_mode,q.standard_profile,q.conformance_status "
        "FROM questions q "
        "LEFT JOIN question_passages p ON p.passage_id=q.passage_id"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY q.question_id LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(home) as conn:
        return conn.execute(sql, params).fetchall()


def count_questions(
    home: Path,
    *, query: str | None = None, module: str | None = None, task: str | None = None,
    part: int | str | None = None, question_type: str | None = None,
    topic: str | None = None, source_type: str | None = None,
    corpus_id: str | None = None, passage_id: str | None = None,
    exclude_completed: bool = False, learner_ready: bool = False,
) -> int:
    """Count the current question selection without materialising its rows."""
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("q.module", module), ("q.task", task), ("q.part", part),
        ("q.question_type", question_type),
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
        clauses.append(
            "(LOWER(q.content) LIKE ? OR LOWER(COALESCE(q.title,'')) LIKE ? "
            "OR LOWER(COALESCE(p.title,'')) LIKE ? OR LOWER(q.topics_text) LIKE ?)"
        )
        value = f"%{query.lower()}%"
        params.extend([value, value, value, value])
    if exclude_completed:
        clauses.append(
            "NOT EXISTS(SELECT 1 FROM sessions s "
            "WHERE s.question_id=q.question_id AND s.status='completed') "
            "AND NOT EXISTS(SELECT 1 FROM question_attempts qa "
            "JOIN sessions s2 ON s2.session_id=qa.session_id "
            "WHERE qa.question_id=q.question_id AND s2.status='completed')"
        )
    if learner_ready:
        clauses.extend(("q.review_status='reviewed'", "q.conformance_status='verified'"))
    sql = (
        "SELECT COUNT(*) FROM questions q "
        "LEFT JOIN question_passages p ON p.passage_id=q.passage_id"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    with connect(home) as conn:
        return int(conn.execute(sql, params).fetchone()[0])


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
        # Indexed review columns are the transactional learner-access authority.
        # Overlay them so stale imported payload metadata cannot bypass the gate.
        data["review_status"] = row["review_status"]
        data["conformance_status"] = row["conformance_status"]
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
    inferred_backend_kind = {
        "mock": "mock",
        "manual": "manual",
        "codex-managed": "managed_runtime",
    }.get(str(run["adapter_id"]), "external_agent")
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO agent_runs(
              run_id,study_session_id,adapter_id,capability_id,execution_profile_id,
              model_provider_id,backend_kind,transport,auth_mode,agent_provider,agent_version,model_id,
              model_display_name,agent_session_id,launcher_kind,capabilities_json,
              calibration_status,action,output_contract,
              base_revision,status,error_code,request_json,result_json,usage_json,
              created_at,started_at,completed_at,timeout_seconds,attempt_count,
              cancel_requested,heartbeat_at,recovery_action,execution_ref,skill_hash,
              inference_route_json,checkpoint,input_hash,lease_owner,
              lease_expires_at,resume_count,persistence_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run["run_id"], run.get("study_session_id"), run["adapter_id"],
                run.get("capability_id"), run.get("execution_profile_id"),
                run.get("model_provider_id"),
                run.get("backend_kind", inferred_backend_kind), run.get("transport"),
                run.get("auth_mode"),
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
                run.get("skill_hash"),
                json.dumps(run.get("inference_route") or [], ensure_ascii=False),
                run.get("checkpoint", "queued"),
                run.get("input_hash") or json_payload_hash(run.get("request") or {}),
                run.get("lease_owner"),
                run.get("lease_expires_at"),
                int(run.get("resume_count") or 0),
                json.dumps(run.get("persistence") or {}, ensure_ascii=False),
            ),
        )
        receipt = run.get("privacy_receipt")
        if receipt:
            if str(receipt.get("run_id") or run["run_id"]) != str(run["run_id"]):
                raise ValueError("Privacy receipt run_id does not match Agent run")
            conn.execute(
                """
                INSERT INTO privacy_receipts(
                  receipt_id,run_id,authorization_kind,reason,remote_processing,
                  private_source,source_type,provider_ids_json,scope_hash,
                  policy_json,reusable,created_at,consumed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)
                """,
                (
                    receipt["receipt_id"],
                    run["run_id"],
                    receipt["authorization_kind"],
                    receipt["reason"],
                    int(bool(receipt.get("remote_processing"))),
                    int(bool(receipt.get("private_source"))),
                    receipt.get("source_type"),
                    json.dumps(receipt.get("provider_ids") or [], ensure_ascii=False),
                    receipt["scope_hash"],
                    json.dumps(receipt.get("policy") or {}, ensure_ascii=False),
                    receipt.get("created_at") or _now(),
                    receipt.get("consumed_at") or _now(),
                ),
            )
    return get_agent_run(home, run["run_id"]) or run


def update_agent_run(home: Path, run_id: str, **changes: Any) -> dict[str, Any]:
    allowed = {
        "capability_id", "execution_profile_id", "model_provider_id",
        "backend_kind", "transport",
        "auth_mode",
        "agent_provider", "agent_version", "model_id", "model_display_name",
        "agent_session_id", "launcher_kind", "capabilities_json",
        "calibration_status", "status", "error_code", "result_json", "usage_json",
        "started_at", "completed_at", "timeout_seconds", "attempt_count",
        "cancel_requested", "heartbeat_at", "recovery_action", "execution_ref",
        "base_revision", "skill_hash", "inference_route_json",
        "checkpoint", "input_hash", "lease_owner", "lease_expires_at",
        "resume_count", "persistence_json", "orchestration_json",
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
        elif key == "inference_route":
            column, value = "inference_route_json", json.dumps(
                value, ensure_ascii=False
            )
        elif key == "persistence":
            column, value = "persistence_json", json.dumps(
                value or {}, ensure_ascii=False
            )
        elif key == "orchestration":
            column, value = "orchestration_json", json.dumps(
                value or {}, ensure_ascii=False
            )
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
        receipt = conn.execute(
            "SELECT * FROM privacy_receipts WHERE run_id=?", (run_id,)
        ).fetchone()
    if not row:
        return None
    result = _agent_run_row(row)
    result["privacy_receipt"] = _privacy_receipt_row(receipt) if receipt else None
    return result


def _agent_run_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "study_session_id": row["study_session_id"],
        "adapter_id": row["adapter_id"],
        "capability_id": row["capability_id"],
        "execution_profile_id": row["execution_profile_id"],
        "model_provider_id": row["model_provider_id"],
        "backend_kind": row["backend_kind"],
        "transport": row["transport"],
        "auth_mode": row["auth_mode"],
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
        "skill_hash": row["skill_hash"],
        "inference_route": json.loads(row["inference_route_json"]),
        "checkpoint": row["checkpoint"],
        "input_hash": row["input_hash"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "resume_count": int(row["resume_count"]),
        "persistence": json.loads(row["persistence_json"]),
        "orchestration": json.loads(row["orchestration_json"]),
    }


def _privacy_receipt_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "receipt_id": row["receipt_id"],
        "run_id": row["run_id"],
        "authorization_kind": row["authorization_kind"],
        "reason": row["reason"],
        "remote_processing": bool(row["remote_processing"]),
        "private_source": bool(row["private_source"]),
        "source_type": row["source_type"],
        "provider_ids": json.loads(row["provider_ids_json"]),
        "scope_hash": row["scope_hash"],
        "policy": json.loads(row["policy_json"]),
        "reusable": bool(row["reusable"]),
        "created_at": row["created_at"],
        "consumed_at": row["consumed_at"],
    }


def get_privacy_receipt(home: Path, run_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM privacy_receipts WHERE run_id=?", (run_id,)
        ).fetchone()
    return _privacy_receipt_row(row) if row else None


def json_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim_agent_run(
    home: Path,
    run_id: str,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> dict[str, Any] | None:
    """Atomically claim one queued run for a single local worker instance."""
    initialise_database(home)
    now = _now()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))
    ).isoformat()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_owner=?,lease_expires_at=?,heartbeat_at=?
            WHERE run_id=? AND status='queued' AND cancel_requested=0
              AND (
                lease_owner IS NULL OR lease_owner=? OR lease_expires_at IS NULL
                OR lease_expires_at<=?
              )
            """,
            (lease_owner, expires_at, now, run_id, lease_owner, now),
        )
        claimed = cursor.rowcount == 1
    return get_agent_run(home, run_id) if claimed else None


def claim_agent_run_recovery(
    home: Path,
    run_id: str,
    *,
    expected_status: str,
    lease_owner: str,
    lease_seconds: int,
) -> dict[str, Any] | None:
    """Atomically reserve one expired, unfinished run for recovery."""
    if expected_status not in {"queued", "running", "validating", "persisting"}:
        return None
    initialise_database(home)
    now = _now()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))
    ).isoformat()
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_owner=?,lease_expires_at=?,heartbeat_at=?
            WHERE run_id=? AND status=? AND cancel_requested=0
              AND (lease_expires_at IS NULL OR lease_expires_at<=?)
            """,
            (lease_owner, expires_at, now, run_id, expected_status, now),
        )
        claimed = cursor.rowcount == 1
    return get_agent_run(home, run_id) if claimed else None


def renew_agent_run_lease(
    home: Path,
    run_id: str,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> bool:
    now = _now()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))
    ).isoformat()
    with connect(home) as conn:
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_expires_at=?,heartbeat_at=?
            WHERE run_id=? AND lease_owner=?
              AND status IN ('queued','running','validating','persisting')
            """,
            (expires_at, now, run_id, lease_owner),
        )
    return cursor.rowcount == 1


def release_agent_run_lease(
    home: Path,
    run_id: str,
    *,
    lease_owner: str,
) -> bool:
    with connect(home) as conn:
        cursor = conn.execute(
            """
            UPDATE agent_runs
            SET lease_owner=NULL,lease_expires_at=NULL
            WHERE run_id=? AND lease_owner=?
            """,
            (run_id, lease_owner),
        )
    return cursor.rowcount == 1


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


_AGENT_EVENT_NAMES = {
    "queued": "job_queued",
    "running": "provider_started",
    "awaiting_import": "awaiting_user",
    "validating": "schema_validation_started",
    "resuming_validation": "schema_validation_started",
    "domain_validating": "domain_validation_started",
    "persisting": "persistence_started",
    "persisted": "persisted",
    "test_passed": "pipeline_test_passed",
    "connecting_model": "provider_started",
    "schema_validation": "schema_validation_started",
    "domain_validation": "domain_validation_started",
    "provider_validated": "provider_completed",
    "provider_failed": "provider_failed",
    "provider_skipped": "provider_failed",
    "fallback_started": "fallback_started",
}

_AGENT_EVENT_MESSAGES = {
    "job_queued": "任务已进入本地队列",
    "context_preparing": "正在整理本次学习所需内容",
    "context_ready": "学习上下文已准备完成",
    "skill_compiled": "教学规则已加载",
    "provider_started": "模型正在生成反馈",
    "provider_stream_delta": "模型正在继续生成",
    "provider_progress": "模型任务正在处理",
    "provider_completed": "模型结果已返回",
    "provider_failed": "当前模型调用失败",
    "fallback_started": "正在尝试备用模型",
    "schema_validation_started": "正在检查结果格式",
    "schema_validation_failed": "结果格式未通过检查",
    "domain_validation_started": "正在检查 IELTS 教学规则",
    "domain_validation_failed": "结果未通过教学规则检查",
    "awaiting_user": "等待用户导入结构化结果",
    "persistence_started": "正在保存正式学习记录",
    "persisted": "反馈已验证并保存",
    "pipeline_test_passed": "本地反馈管线验证通过",
    "job_cancelled": "任务已取消",
    "job_failed": "任务未能完成",
}


def _normalise_agent_event(
    event_type: str,
    payload: dict[str, Any],
) -> tuple[str, str, str, bool]:
    stage = str(payload.get("stage") or event_type or "unknown")
    if event_type == "status":
        canonical = _AGENT_EVENT_NAMES.get(stage, "provider_progress")
    elif event_type == "progress":
        if stage == "provider_rejected":
            canonical = (
                "schema_validation_failed"
                if payload.get("failure_stage") == "schema"
                else "domain_validation_failed"
                if payload.get("failure_stage") == "domain"
                else "provider_failed"
            )
        else:
            canonical = _AGENT_EVENT_NAMES.get(
                stage,
                "provider_stream_delta"
                if any(key in payload for key in ("delta", "text_delta", "content_delta"))
                else "provider_progress",
            )
    elif event_type == "completed":
        canonical = "persisted"
        stage = "persisted"
    elif event_type == "cancelled":
        canonical = "job_cancelled"
        stage = "cancelled"
    elif event_type == "failed":
        canonical = "job_failed"
        stage = "failed"
    elif event_type == "test_passed":
        canonical = "pipeline_test_passed"
        stage = "test_passed"
    else:
        canonical = event_type
    display_message = str(
        payload.get("display_message")
        or payload.get("label")
        or _AGENT_EVENT_MESSAGES.get(canonical, "任务状态已更新")
    )[:240]
    recoverable = bool(
        payload.get("recoverable")
        if "recoverable" in payload
        else canonical
        in {
            "provider_failed",
            "schema_validation_failed",
            "domain_validation_failed",
            "job_failed",
            "job_cancelled",
        }
    )
    return canonical, stage[:80], display_message, recoverable


def append_agent_run_event(
    home: Path, run_id: str, event_type: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    initialise_database(home)
    event_payload = dict(payload or {})
    canonical, stage, display_message, recoverable = _normalise_agent_event(
        event_type, event_payload
    )
    payload_hash = json_payload_hash(event_payload)
    with connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 AS next_sequence FROM agent_run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
        sequence = int(row["next_sequence"])
        created_at = _now()
        conn.execute(
            """
            INSERT INTO agent_run_events(
              run_id,sequence,event_type,stage,display_message,recoverable,
              payload_hash,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                sequence,
                canonical,
                stage,
                display_message,
                int(recoverable),
                payload_hash,
                json.dumps(event_payload, ensure_ascii=False),
                created_at,
            ),
        )
        run = conn.execute(
            "SELECT study_session_id,capability_id FROM agent_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        audit_metadata = {
            key: event_payload[key]
            for key in (
                "code",
                "recovery_action",
                "provider_id",
                "attempt",
                "model_called",
                "model_called_again",
                "skill_hash",
                "contract",
            )
            if key in event_payload
        }
        outcome = (
            "failed"
            if canonical.endswith("_failed") or canonical == "job_failed"
            else "cancelled"
            if canonical == "job_cancelled"
            else "succeeded"
            if canonical in {"persisted", "pipeline_test_passed"}
            else "recorded"
        )
        actor_type = (
            "local_user"
            if canonical == "job_queued"
            else "model_provider"
            if canonical.startswith("provider_") or canonical == "fallback_started"
            else "teaching_runtime"
        )
        _insert_audit_event(
            conn,
            category="agent_job",
            action=canonical,
            outcome=outcome,
            actor_type=actor_type,
            subject_type="agent_run",
            subject_id=run_id,
            session_id=str(run["study_session_id"]) if run and run["study_session_id"] else None,
            run_id=run_id,
            capability_id=str(run["capability_id"]) if run and run["capability_id"] else None,
            request_id=None,
            payload_hash=payload_hash,
            metadata={"sequence": sequence, "stage": stage, **audit_metadata},
            created_at=created_at,
        )
    return {
        "run_id": run_id,
        "sequence": sequence,
        "type": canonical,
        "stage": stage,
        "display_message": display_message,
        "recoverable": recoverable,
        "payload_hash": payload_hash,
        "payload": event_payload,
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
            "stage": row["stage"],
            "display_message": row["display_message"],
            "recoverable": bool(row["recoverable"]),
            "payload_hash": row["payload_hash"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _insert_audit_event(
    conn: sqlite3.Connection,
    *,
    category: str,
    action: str,
    outcome: str,
    actor_type: str,
    subject_type: str | None,
    subject_id: str | None,
    session_id: str | None,
    run_id: str | None,
    capability_id: str | None,
    request_id: str | None,
    payload_hash: str | None,
    metadata: dict[str, Any],
    created_at: str,
) -> str:
    audit_id = f"audit_{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO audit_events(
          audit_id,category,action,outcome,actor_type,subject_type,subject_id,
          session_id,run_id,capability_id,request_id,payload_hash,
          metadata_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            audit_id,
            category,
            action,
            outcome,
            actor_type,
            subject_type,
            subject_id,
            session_id,
            run_id,
            capability_id,
            request_id,
            payload_hash,
            json.dumps(metadata, ensure_ascii=False, default=str),
            created_at,
        ),
    )
    return audit_id


def record_audit_event(
    home: Path,
    *,
    category: str,
    action: str,
    outcome: str = "recorded",
    actor_type: str = "local_user",
    subject_type: str | None = None,
    subject_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    capability_id: str | None = None,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a privacy-safe audit fact without storing learner content."""
    initialise_database(home)
    payload_hash = json_payload_hash(payload) if payload is not None else None
    created_at = _now()
    with connect(home) as conn:
        audit_id = _insert_audit_event(
            conn,
            category=category,
            action=action,
            outcome=outcome,
            actor_type=actor_type,
            subject_type=subject_type,
            subject_id=subject_id,
            session_id=session_id,
            run_id=run_id,
            capability_id=capability_id,
            request_id=request_id,
            payload_hash=payload_hash,
            metadata=dict(metadata or {}),
            created_at=created_at,
        )
    return {
        "audit_id": audit_id,
        "category": category,
        "action": action,
        "outcome": outcome,
        "payload_hash": payload_hash,
        "created_at": created_at,
    }


def list_audit_events(
    home: Path,
    *,
    category: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses: list[str] = []
    params: list[Any] = []
    if category:
        clauses.append("category=?")
        params.append(category)
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    sql = "SELECT * FROM audit_events"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            **{key: row[key] for key in row.keys() if key != "metadata_json"},
            "metadata": json.loads(row["metadata_json"]),
        }
        for row in rows
    ]


def save_thread_summary(
    home: Path,
    *,
    thread_id: str,
    summary: str,
    message_count: int,
    through_message_id: str | None,
    generated_by: str = "deterministic",
) -> dict[str, Any]:
    initialise_database(home)
    clean = summary.strip()
    if not clean:
        raise ValueError("Thread summary cannot be empty")
    now = _now()
    summary_hash = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO study_thread_summaries(
              thread_id,summary,message_count,through_message_id,summary_hash,
              generated_by,updated_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(thread_id) DO UPDATE SET
              summary=excluded.summary,
              message_count=excluded.message_count,
              through_message_id=excluded.through_message_id,
              summary_hash=excluded.summary_hash,
              generated_by=excluded.generated_by,
              updated_at=excluded.updated_at
            """,
            (
                thread_id,
                clean,
                max(0, int(message_count)),
                through_message_id,
                summary_hash,
                generated_by,
                now,
            ),
        )
    return get_thread_summary(home, thread_id) or {}


def get_thread_summary(home: Path, thread_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM study_thread_summaries WHERE thread_id=?", (thread_id,)
        ).fetchone()
    return dict(row) if row else None


def create_learner_memory(
    home: Path,
    *,
    memory_type: str,
    statement: str,
    confidence: float,
    evidence_refs: list[str] | None = None,
    scope: str = "teaching_style",
    source_thread_id: str | None = None,
    source_session_id: str | None = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    initialise_database(home)
    clean = " ".join(statement.strip().split())
    if not clean:
        raise ValueError("Learner memory statement cannot be empty")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ValueError("Learner memory confidence must be between 0 and 1")
    memory_id = memory_id or f"memory_{uuid.uuid4().hex}"
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO learner_memories(
              memory_id,memory_type,statement,confidence,evidence_refs_json,
              scope,status,source_thread_id,source_session_id,created_at,
              last_confirmed_at,updated_at
            ) VALUES(?,?,?,?,?,?,'active',?,?,?,?,?)
            """,
            (
                memory_id,
                memory_type[:80],
                clean[:2000],
                confidence,
                json.dumps(evidence_refs or [], ensure_ascii=False),
                scope[:80],
                source_thread_id,
                source_session_id,
                now,
                now,
                now,
            ),
        )
    return get_learner_memory(home, memory_id) or {}


def get_learner_memory(home: Path, memory_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM learner_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
    return _learner_memory_row(row) if row else None


def list_learner_memories(
    home: Path,
    *,
    status: str = "active",
    memory_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    initialise_database(home)
    clauses = ["status=?"]
    params: list[Any] = [status]
    if memory_type:
        clauses.append("memory_type=?")
        params.append(memory_type)
    params.append(max(1, min(int(limit), 200)))
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT * FROM learner_memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY confidence DESC,updated_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_learner_memory_row(row) for row in rows]


def update_learner_memory(
    home: Path,
    memory_id: str,
    *,
    statement: str | None = None,
    confidence: float | None = None,
    status: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    existing = get_learner_memory(home, memory_id)
    if not existing:
        raise ValueError("Learner memory not found")
    if status is not None and status not in {"active", "dismissed"}:
        raise ValueError("Unsupported learner memory status")
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise ValueError("Learner memory confidence must be between 0 and 1")
    values = {
        "statement": (
            " ".join(statement.strip().split())[:2000]
            if statement is not None
            else existing["statement"]
        ),
        "confidence": float(confidence) if confidence is not None else existing["confidence"],
        "status": status or existing["status"],
        "scope": scope[:80] if scope is not None else existing["scope"],
    }
    if not values["statement"]:
        raise ValueError("Learner memory statement cannot be empty")
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            UPDATE learner_memories
            SET statement=?,confidence=?,status=?,scope=?,last_confirmed_at=?,updated_at=?
            WHERE memory_id=?
            """,
            (
                values["statement"],
                values["confidence"],
                values["status"],
                values["scope"],
                now,
                now,
                memory_id,
            ),
        )
    return get_learner_memory(home, memory_id) or {}


def delete_learner_memory(home: Path, memory_id: str) -> bool:
    initialise_database(home)
    with connect(home) as conn:
        cursor = conn.execute(
            "DELETE FROM learner_memories WHERE memory_id=?", (memory_id,)
        )
    return cursor.rowcount == 1


def _learner_memory_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        **{key: row[key] for key in row.keys() if key != "evidence_refs_json"},
        "confidence": float(row["confidence"]),
        "evidence_refs": json.loads(row["evidence_refs_json"]),
    }


def search_learning_history(
    home: Path,
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Search local conversations, writing versions and error evidence.

    Structured answers and scores remain outside this fuzzy retrieval path.
    """
    initialise_database(home)
    clean = " ".join(query.strip().split())[:240]
    if not clean:
        return []
    escaped = clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    bounded = max(1, min(int(limit), 50))
    with connect(home) as conn:
        message_rows = conn.execute(
            """
            SELECT 'study_message' source_type,m.message_id source_id,
                   t.title title,m.content content,m.created_at created_at
            FROM study_messages m JOIN study_threads t USING(thread_id)
            WHERE m.content LIKE ? ESCAPE '\\'
            ORDER BY m.created_at DESC LIMIT ?
            """,
            (pattern, bounded),
        ).fetchall()
        writing_rows = conn.execute(
            """
            SELECT 'writing_version' source_type,
                   w.session_id || ':' || w.version_label source_id,
                   'Writing ' || w.version_label title,w.content content,
                   w.created_at created_at
            FROM writing_versions w
            WHERE w.content LIKE ? ESCAPE '\\'
            ORDER BY w.created_at DESC LIMIT ?
            """,
            (pattern, bounded),
        ).fetchall()
        error_rows = conn.execute(
            """
            SELECT 'error_record' source_type,
                   CAST(e.id AS TEXT) source_id,e.tag title,
                   COALESCE(e.evidence,'') content,s.occurred_at created_at
            FROM errors e JOIN sessions s USING(session_id)
            WHERE e.tag LIKE ? ESCAPE '\\' OR COALESCE(e.evidence,'') LIKE ? ESCAPE '\\'
            ORDER BY s.occurred_at DESC LIMIT ?
            """,
            (pattern, pattern, bounded),
        ).fetchall()
    combined = [dict(row) for row in (*message_rows, *writing_rows, *error_rows)]
    combined.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return [
        {
            **item,
            "content": str(item.get("content") or "")[:1200],
        }
        for item in combined[:bounded]
    ]


def create_provider_attempt(
    home: Path,
    *,
    run_id: str,
    provider_id: str,
    provider_kind: str | None,
    model_id: str | None,
    fallback_index: int,
) -> dict[str, Any]:
    """Start an auditable provider candidate attempt for an Agent run."""
    initialise_database(home)
    started_at = _now()
    with connect(home) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(attempt_index),0)+1 AS next_index "
            "FROM provider_attempts WHERE run_id=?",
            (run_id,),
        ).fetchone()
        attempt_index = int(row["next_index"])
        run_row = conn.execute(
            "SELECT attempt_count FROM agent_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not run_row:
            raise ValueError(f"Unknown Agent run: {run_id}")
        attempt_id = f"{run_id}:provider:{attempt_index}"
        conn.execute(
            """
            INSERT INTO provider_attempts(
              attempt_id,run_id,attempt_index,run_attempt,provider_id,
              provider_kind,model_id,fallback_index,status,started_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                attempt_id,
                run_id,
                attempt_index,
                int(run_row["attempt_count"] or 1),
                provider_id,
                provider_kind,
                model_id,
                int(fallback_index),
                "running",
                started_at,
            ),
        )
    return get_provider_attempt(home, attempt_id) or {
        "attempt_id": attempt_id,
        "run_id": run_id,
        "attempt_index": attempt_index,
    }


def update_provider_attempt(
    home: Path,
    attempt_id: str,
    **changes: Any,
) -> dict[str, Any]:
    allowed = {
        "status",
        "failure_stage",
        "error_code",
        "error_message",
        "result_hash",
        "identity_json",
        "usage_json",
        "completed_at",
    }
    columns: list[str] = []
    values: list[Any] = []
    for key, value in changes.items():
        column = key
        if key == "identity":
            column, value = "identity_json", json.dumps(value or {}, ensure_ascii=False)
        elif key == "usage":
            column, value = "usage_json", json.dumps(value or {}, ensure_ascii=False)
        if column not in allowed:
            continue
        columns.append(f"{column}=?")
        values.append(value)
    if columns:
        values.append(attempt_id)
        with connect(home) as conn:
            conn.execute(
                f"UPDATE provider_attempts SET {','.join(columns)} "
                "WHERE attempt_id=? AND completed_at IS NULL",
                values,
            )
    return get_provider_attempt(home, attempt_id) or {}


def close_open_provider_attempts(
    home: Path,
    run_id: str,
    *,
    status: str,
    failure_stage: str,
    error_code: str,
    error_message: str,
) -> int:
    """Close unfinished attempts when their owning job stops unexpectedly."""
    initialise_database(home)
    with connect(home) as conn:
        cursor = conn.execute(
            """
            UPDATE provider_attempts
            SET status=?,failure_stage=?,error_code=?,error_message=?,completed_at=?
            WHERE run_id=? AND completed_at IS NULL
            """,
            (
                status,
                failure_stage,
                error_code,
                error_message[-2000:],
                _now(),
                run_id,
            ),
        )
    return int(cursor.rowcount)


def get_provider_attempt(home: Path, attempt_id: str) -> dict[str, Any] | None:
    initialise_database(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM provider_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
    return _provider_attempt_row(row) if row else None


def list_provider_attempts(home: Path, run_id: str) -> list[dict[str, Any]]:
    initialise_database(home)
    with connect(home) as conn:
        rows = conn.execute(
            "SELECT * FROM provider_attempts WHERE run_id=? ORDER BY attempt_index",
            (run_id,),
        ).fetchall()
    return [_provider_attempt_row(row) for row in rows]


def _provider_attempt_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "attempt_id": row["attempt_id"],
        "run_id": row["run_id"],
        "attempt_index": int(row["attempt_index"]),
        "run_attempt": int(row["run_attempt"]),
        "provider_id": row["provider_id"],
        "provider_kind": row["provider_kind"],
        "model_id": row["model_id"],
        "fallback_index": int(row["fallback_index"]),
        "status": row["status"],
        "failure_stage": row["failure_stage"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "result_hash": row["result_hash"],
        "identity": json.loads(row["identity_json"]),
        "usage": json.loads(row["usage_json"]),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


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
