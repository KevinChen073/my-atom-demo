-- Run explicitly with python -m backend.migrate_postgres. All platform times
-- remain ISO-8601 text to preserve the existing API and SQLite import format.
CREATE TABLE IF NOT EXISTS myatom_schema_version (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, title TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, active_version_id TEXT
);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_hash, updated_at);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    request_text TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
    card_json TEXT, card_id TEXT, spec_version INTEGER NOT NULL DEFAULT 0,
    approved_spec_version INTEGER, answers_json TEXT, plan_json TEXT,
    model_calls INTEGER NOT NULL DEFAULT 0, tokens_used INTEGER NOT NULL DEFAULT 0,
    max_model_calls INTEGER, max_total_tokens INTEGER, max_run_seconds INTEGER,
    max_fix_rounds INTEGER, active_seconds DOUBLE PRECISION,
    execution_started_at TEXT, fix_rounds INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT, version_id TEXT,
    trace_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    ordinal BIGINT GENERATED ALWAYS AS IDENTITY,
    UNIQUE(project_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS runs_one_active ON runs(project_id)
    WHERE status IN ('clarifying','planning','building','awaiting_clarification',
                     'awaiting_plan','awaiting_repair','awaiting_budget');
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL, payload_json TEXT NOT NULL, at TEXT NOT NULL,
    PRIMARY KEY(run_id, seq)
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    card_id TEXT NOT NULL, spec_version INTEGER NOT NULL, action TEXT NOT NULL,
    payload_json TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, UNIQUE(run_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    card_id TEXT NOT NULL, spec_version INTEGER NOT NULL, text TEXT NOT NULL,
    answers_json TEXT NOT NULL, reply_to_interpretation_id TEXT,
    request_hash TEXT NOT NULL, interpreter_version TEXT NOT NULL DEFAULT 'stage-intent-v1',
    status TEXT NOT NULL, reply TEXT NOT NULL DEFAULT '',
    interpreted_intents_json TEXT, committed_action TEXT, decision_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    ordinal BIGINT GENERATED ALWAYS AS IDENTITY,
    UNIQUE(run_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS submissions_run ON submissions(run_id, created_at);
CREATE TABLE IF NOT EXISTS node_outputs (
    run_id TEXT NOT NULL, node TEXT NOT NULL, cache_key TEXT NOT NULL,
    payload_json TEXT NOT NULL, PRIMARY KEY(run_id, node, cache_key)
);
CREATE TABLE IF NOT EXISTS operations (
    run_id TEXT NOT NULL, operation_key TEXT NOT NULL, result_json TEXT NOT NULL,
    PRIMARY KEY(run_id, operation_key)
);
CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE,
    manifest_json TEXT NOT NULL, created_at TEXT NOT NULL,
    ordinal BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX IF NOT EXISTS versions_project_order ON versions(project_id, ordinal DESC);
CREATE TABLE IF NOT EXISTS artifact_cleanup (
    project_id TEXT NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY(project_id, run_id)
);
CREATE TABLE IF NOT EXISTS exception_records (
    id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, project_id TEXT, run_id TEXT,
    source TEXT NOT NULL, phase TEXT NOT NULL, code TEXT NOT NULL,
    exception_type TEXT NOT NULL, reason TEXT NOT NULL, severity TEXT NOT NULL,
    occurred_at TEXT NOT NULL, ordinal BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX IF NOT EXISTS exceptions_recent ON exception_records(occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS exceptions_project_recent ON exception_records(project_id, occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS exceptions_trace ON exception_records(trace_id);
CREATE INDEX IF NOT EXISTS exceptions_run_recent ON exception_records(run_id, occurred_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS exceptions_run_terminal ON exception_records(run_id)
    WHERE run_id IS NOT NULL AND source IN ('agent', 'build')
      AND code NOT IN ('budget_exceeded', 'build_check_failed');
CREATE TABLE IF NOT EXISTS build_check_attempts (
    run_id TEXT NOT NULL, attempt INTEGER NOT NULL, outcome TEXT NOT NULL,
    category TEXT NOT NULL, command TEXT NOT NULL, exit_code INTEGER,
    duration_seconds DOUBLE PRECISION, fix_round INTEGER NOT NULL,
    model_calls INTEGER, tokens_used INTEGER, fingerprints_json TEXT NOT NULL,
    target_files_json TEXT NOT NULL, error_codes_json TEXT NOT NULL,
    stop_code TEXT NOT NULL, occurred_at TEXT NOT NULL,
    PRIMARY KEY(run_id, attempt)
);
CREATE INDEX IF NOT EXISTS build_checks_recent ON build_check_attempts(occurred_at DESC);
CREATE TABLE IF NOT EXISTS preview_tickets (
    token_hash TEXT PRIMARY KEY, version_id TEXT NOT NULL, project_id TEXT NOT NULL,
    expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS preview_sessions (
    token_hash TEXT PRIMARY KEY, version_id TEXT NOT NULL, project_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
-- Security-barrier views omit generated source, user messages and event payloads.
CREATE OR REPLACE VIEW ops_exception_records WITH (security_barrier=true) AS
    SELECT id, trace_id, project_id, run_id, source, phase, code,
           exception_type, reason, severity, occurred_at FROM exception_records;
CREATE OR REPLACE VIEW ops_run_metrics WITH (security_barrier=true) AS
    SELECT id, created_at, active_seconds, model_calls, tokens_used FROM runs;
CREATE OR REPLACE VIEW ops_event_timeline WITH (security_barrier=true) AS
    SELECT run_id, seq, type, at FROM events;
CREATE OR REPLACE VIEW ops_build_checks WITH (security_barrier=true) AS
    SELECT run_id, attempt, outcome, category, command, exit_code, duration_seconds,
           fix_round, model_calls, tokens_used, fingerprints_json,
           target_files_json, error_codes_json, stop_code, occurred_at
    FROM build_check_attempts;
INSERT INTO myatom_schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;
