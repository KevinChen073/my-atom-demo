-- New Azure environment only. Times stay ISO-8601 text for the existing API.
-- GO-delimited batches run inside one migration transaction.
IF OBJECT_ID(N'dbo.myatom_schema_version', N'U') IS NULL
    CREATE TABLE dbo.myatom_schema_version (version INT NOT NULL PRIMARY KEY);
IF OBJECT_ID(N'dbo.projects', N'U') IS NULL
    CREATE TABLE dbo.projects (
        id VARCHAR(36) NOT NULL PRIMARY KEY, owner_hash CHAR(64) NOT NULL,
        title NVARCHAR(100) NOT NULL, created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL, active_version_id VARCHAR(36) NULL
    );
IF OBJECT_ID(N'dbo.runs', N'U') IS NULL
    CREATE TABLE dbo.runs (
        id VARCHAR(36) NOT NULL PRIMARY KEY, project_id VARCHAR(36) NOT NULL,
        idempotency_key NVARCHAR(255) NOT NULL, request_text NVARCHAR(MAX) NOT NULL,
        status VARCHAR(40) NOT NULL, phase VARCHAR(40) NOT NULL,
        card_json NVARCHAR(MAX) NULL, card_id VARCHAR(80) NULL,
        spec_version INT NOT NULL DEFAULT 0, approved_spec_version INT NULL,
        answers_json NVARCHAR(MAX) NULL, plan_json NVARCHAR(MAX) NULL,
        model_calls INT NOT NULL DEFAULT 0, tokens_used INT NOT NULL DEFAULT 0,
        max_model_calls INT NULL, max_total_tokens INT NULL, max_run_seconds INT NULL,
        max_fix_rounds INT NULL, active_seconds FLOAT NULL,
        execution_started_at VARCHAR(40) NULL, fix_rounds INT NOT NULL DEFAULT 0,
        cancel_requested INT NOT NULL DEFAULT 0, error NVARCHAR(MAX) NULL,
        version_id VARCHAR(36) NULL, trace_id VARCHAR(36) NOT NULL,
        created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
        run_mode VARCHAR(16) NOT NULL DEFAULT 'create', base_version_id VARCHAR(36) NULL,
        base_spec_json NVARCHAR(MAX) NULL, ordinal BIGINT IDENTITY(1,1) NOT NULL,
        CONSTRAINT uq_runs_idempotency UNIQUE (project_id, idempotency_key)
    );
IF OBJECT_ID(N'dbo.events', N'U') IS NULL
    CREATE TABLE dbo.events (
        run_id VARCHAR(36) NOT NULL, seq INT NOT NULL, event_id VARCHAR(36) NOT NULL UNIQUE,
        type VARCHAR(80) NOT NULL, payload_json NVARCHAR(MAX) NOT NULL,
        at VARCHAR(40) NOT NULL, CONSTRAINT pk_events PRIMARY KEY (run_id, seq)
    );
IF OBJECT_ID(N'dbo.decisions', N'U') IS NULL
    CREATE TABLE dbo.decisions (
        id VARCHAR(36) NOT NULL PRIMARY KEY, run_id VARCHAR(36) NOT NULL,
        idempotency_key NVARCHAR(255) NOT NULL, card_id VARCHAR(80) NOT NULL,
        spec_version INT NOT NULL, action VARCHAR(80) NOT NULL,
        payload_json NVARCHAR(MAX) NOT NULL, processed INT NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL,
        CONSTRAINT uq_decisions_idempotency UNIQUE (run_id, idempotency_key)
    );
IF OBJECT_ID(N'dbo.submissions', N'U') IS NULL
    CREATE TABLE dbo.submissions (
        id VARCHAR(36) NOT NULL PRIMARY KEY, run_id VARCHAR(36) NOT NULL,
        idempotency_key NVARCHAR(255) NOT NULL, card_id VARCHAR(80) NOT NULL,
        spec_version INT NOT NULL, [text] NVARCHAR(MAX) NOT NULL,
        answers_json NVARCHAR(MAX) NOT NULL, reply_to_interpretation_id VARCHAR(36) NULL,
        request_hash CHAR(64) NOT NULL, interpreter_version VARCHAR(40) NOT NULL DEFAULT 'stage-intent-v1',
        status VARCHAR(40) NOT NULL, reply NVARCHAR(500) NOT NULL DEFAULT '',
        interpreted_intents_json NVARCHAR(MAX) NULL, committed_action VARCHAR(80) NULL,
        decision_id VARCHAR(36) NULL, created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL, ordinal BIGINT IDENTITY(1,1) NOT NULL,
        CONSTRAINT uq_submissions_idempotency UNIQUE (run_id, idempotency_key)
    );
IF OBJECT_ID(N'dbo.node_outputs', N'U') IS NULL
    CREATE TABLE dbo.node_outputs (
        run_id VARCHAR(36) NOT NULL, node VARCHAR(80) NOT NULL,
        cache_key VARCHAR(128) NOT NULL, payload_json NVARCHAR(MAX) NOT NULL,
        CONSTRAINT pk_node_outputs PRIMARY KEY (run_id, node, cache_key)
    );
IF OBJECT_ID(N'dbo.operations', N'U') IS NULL
    CREATE TABLE dbo.operations (
        run_id VARCHAR(36) NOT NULL, operation_key NVARCHAR(255) NOT NULL,
        result_json NVARCHAR(MAX) NOT NULL,
        CONSTRAINT pk_operations PRIMARY KEY (run_id, operation_key)
    );
IF OBJECT_ID(N'dbo.versions', N'U') IS NULL
    CREATE TABLE dbo.versions (
        id VARCHAR(36) NOT NULL PRIMARY KEY, project_id VARCHAR(36) NOT NULL,
        run_id VARCHAR(36) NOT NULL UNIQUE, manifest_json NVARCHAR(MAX) NOT NULL,
        created_at VARCHAR(40) NOT NULL, ordinal BIGINT IDENTITY(1,1) NOT NULL
    );
IF OBJECT_ID(N'dbo.artifact_cleanup', N'U') IS NULL
    CREATE TABLE dbo.artifact_cleanup (
        project_id VARCHAR(36) NOT NULL, run_id VARCHAR(36) NOT NULL,
        CONSTRAINT pk_artifact_cleanup PRIMARY KEY (project_id, run_id)
    );
IF OBJECT_ID(N'dbo.exception_records', N'U') IS NULL
    CREATE TABLE dbo.exception_records (
        id VARCHAR(36) NOT NULL PRIMARY KEY, trace_id VARCHAR(36) NOT NULL,
        project_id VARCHAR(36) NULL, run_id VARCHAR(36) NULL,
        source VARCHAR(30) NOT NULL, phase VARCHAR(60) NOT NULL,
        code VARCHAR(80) NOT NULL, exception_type VARCHAR(80) NOT NULL,
        reason NVARCHAR(2000) NOT NULL, severity VARCHAR(20) NOT NULL,
        occurred_at VARCHAR(40) NOT NULL, ordinal BIGINT IDENTITY(1,1) NOT NULL
    );
IF OBJECT_ID(N'dbo.build_check_attempts', N'U') IS NULL
    CREATE TABLE dbo.build_check_attempts (
        run_id VARCHAR(36) NOT NULL, attempt INT NOT NULL,
        outcome VARCHAR(20) NOT NULL, category VARCHAR(50) NOT NULL,
        command NVARCHAR(100) NOT NULL, exit_code INT NULL,
        duration_seconds FLOAT NULL, fix_round INT NOT NULL,
        model_calls INT NULL, tokens_used INT NULL,
        fingerprints_json NVARCHAR(MAX) NOT NULL, target_files_json NVARCHAR(MAX) NOT NULL,
        error_codes_json NVARCHAR(MAX) NOT NULL, stop_code VARCHAR(40) NOT NULL,
        occurred_at VARCHAR(40) NOT NULL,
        CONSTRAINT pk_build_check_attempts PRIMARY KEY (run_id, attempt)
    );
IF OBJECT_ID(N'dbo.preview_tickets', N'U') IS NULL
    CREATE TABLE dbo.preview_tickets (
        token_hash CHAR(64) NOT NULL PRIMARY KEY, version_id VARCHAR(36) NOT NULL,
        project_id VARCHAR(36) NOT NULL, expires_at VARCHAR(40) NOT NULL,
        used INT NOT NULL DEFAULT 0
    );
IF OBJECT_ID(N'dbo.preview_sessions', N'U') IS NULL
    CREATE TABLE dbo.preview_sessions (
        token_hash CHAR(64) NOT NULL PRIMARY KEY, version_id VARCHAR(36) NOT NULL,
        project_id VARCHAR(36) NOT NULL, expires_at VARCHAR(40) NOT NULL
    );
IF OBJECT_ID(N'dbo.myatom_checkpoints', N'U') IS NULL
    CREATE TABLE dbo.myatom_checkpoints (
        thread_id VARCHAR(255) NOT NULL, checkpoint_ns VARCHAR(255) NOT NULL,
        checkpoint_id VARCHAR(80) NOT NULL, parent_checkpoint_id VARCHAR(80) NULL,
        data_type VARCHAR(40) NOT NULL, [checkpoint] VARBINARY(MAX) NOT NULL,
        metadata NVARCHAR(MAX) NOT NULL,
        CONSTRAINT pk_myatom_checkpoints PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    );
IF OBJECT_ID(N'dbo.myatom_checkpoint_writes', N'U') IS NULL
    CREATE TABLE dbo.myatom_checkpoint_writes (
        thread_id VARCHAR(255) NOT NULL, checkpoint_ns VARCHAR(255) NOT NULL,
        checkpoint_id VARCHAR(80) NOT NULL, task_id VARCHAR(255) NOT NULL,
        task_path NVARCHAR(255) NOT NULL DEFAULT '', idx INT NOT NULL,
        channel NVARCHAR(255) NOT NULL, data_type VARCHAR(40) NOT NULL,
        value VARBINARY(MAX) NOT NULL,
        CONSTRAINT pk_myatom_checkpoint_writes PRIMARY KEY
            (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    );
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_projects_owner' AND object_id=OBJECT_ID('dbo.projects'))
    CREATE INDEX ix_projects_owner ON dbo.projects(owner_hash, updated_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_runs_project' AND object_id=OBJECT_ID('dbo.runs'))
    CREATE INDEX ix_runs_project ON dbo.runs(project_id, created_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ux_runs_one_active' AND object_id=OBJECT_ID('dbo.runs'))
    CREATE UNIQUE INDEX ux_runs_one_active ON dbo.runs(project_id)
    WHERE status IN ('clarifying','planning','building','awaiting_clarification',
                     'awaiting_plan','awaiting_repair','awaiting_budget');
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_submissions_run' AND object_id=OBJECT_ID('dbo.submissions'))
    CREATE INDEX ix_submissions_run ON dbo.submissions(run_id, created_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_versions_project_order' AND object_id=OBJECT_ID('dbo.versions'))
    CREATE INDEX ix_versions_project_order ON dbo.versions(project_id, ordinal DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_exceptions_recent' AND object_id=OBJECT_ID('dbo.exception_records'))
    CREATE INDEX ix_exceptions_recent ON dbo.exception_records(occurred_at DESC, id DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_exceptions_project_recent' AND object_id=OBJECT_ID('dbo.exception_records'))
    CREATE INDEX ix_exceptions_project_recent ON dbo.exception_records(project_id, occurred_at DESC, id DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_exceptions_trace' AND object_id=OBJECT_ID('dbo.exception_records'))
    CREATE INDEX ix_exceptions_trace ON dbo.exception_records(trace_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_exceptions_run_recent' AND object_id=OBJECT_ID('dbo.exception_records'))
    CREATE INDEX ix_exceptions_run_recent ON dbo.exception_records(run_id, occurred_at DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ux_exceptions_run_terminal' AND object_id=OBJECT_ID('dbo.exception_records'))
    CREATE UNIQUE INDEX ux_exceptions_run_terminal ON dbo.exception_records(run_id)
    WHERE run_id IS NOT NULL AND source IN ('agent','build')
      AND code <> 'budget_exceeded' AND code <> 'build_check_failed';
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_build_checks_recent' AND object_id=OBJECT_ID('dbo.build_check_attempts'))
    CREATE INDEX ix_build_checks_recent ON dbo.build_check_attempts(occurred_at DESC);
GO
CREATE OR ALTER VIEW dbo.ops_exception_records AS
    SELECT id, trace_id, project_id, run_id, source, phase, code,
           exception_type, reason, severity, occurred_at FROM dbo.exception_records;
GO
CREATE OR ALTER VIEW dbo.ops_run_metrics AS
    SELECT id, created_at, active_seconds, model_calls, tokens_used FROM dbo.runs;
GO
CREATE OR ALTER VIEW dbo.ops_event_timeline AS
    SELECT run_id, seq, type, at FROM dbo.events;
GO
CREATE OR ALTER VIEW dbo.ops_build_checks AS
    SELECT run_id, attempt, outcome, category, command, exit_code, duration_seconds,
           fix_round, model_calls, tokens_used, fingerprints_json,
           target_files_json, error_codes_json, stop_code, occurred_at
    FROM dbo.build_check_attempts;
GO
IF NOT EXISTS (SELECT 1 FROM dbo.myatom_schema_version WHERE version=1)
    INSERT INTO dbo.myatom_schema_version(version) VALUES (1);
