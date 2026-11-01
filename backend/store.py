from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .budget import DEFAULT_LIMITS, EXTENSION_STEPS, LIMIT_COLUMNS, effective_limits


ACTIVE = {"clarifying", "planning", "building"}
WAITING = {"awaiting_clarification", "awaiting_plan", "awaiting_repair", "awaiting_budget"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self._conn() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    active_version_id TEXT
                );
                CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_hash, updated_at);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    request_text TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
                    card_json TEXT, card_id TEXT, spec_version INTEGER NOT NULL DEFAULT 0,
                    approved_spec_version INTEGER, answers_json TEXT, plan_json TEXT,
                    run_mode TEXT NOT NULL DEFAULT 'create', base_version_id TEXT, base_spec_json TEXT,
                    model_calls INTEGER NOT NULL DEFAULT 0, tokens_used INTEGER NOT NULL DEFAULT 0,
                    max_model_calls INTEGER, max_total_tokens INTEGER,
                    max_run_seconds INTEGER, max_fix_rounds INTEGER,
                    active_seconds REAL, execution_started_at TEXT,
                    fix_rounds INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error TEXT, version_id TEXT, trace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, created_at);
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL,
                    type TEXT NOT NULL, payload_json TEXT NOT NULL, at TEXT NOT NULL,
                    PRIMARY KEY(run_id, seq), UNIQUE(event_id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    card_id TEXT NOT NULL, spec_version INTEGER NOT NULL,
                    action TEXT NOT NULL, payload_json TEXT NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    UNIQUE(run_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    card_id TEXT NOT NULL, spec_version INTEGER NOT NULL,
                    text TEXT NOT NULL, answers_json TEXT NOT NULL, reply_to_interpretation_id TEXT,
                    request_hash TEXT NOT NULL, interpreter_version TEXT NOT NULL DEFAULT 'stage-intent-v1',
                    status TEXT NOT NULL, reply TEXT NOT NULL DEFAULT '',
                    interpreted_intents_json TEXT, committed_action TEXT, decision_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
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
                    manifest_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS version_files (
                    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL, text_content TEXT NOT NULL,
                    utf8_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
                    kind TEXT NOT NULL, mime_type TEXT NOT NULL,
                    PRIMARY KEY(version_id, relative_path)
                );
                CREATE TABLE IF NOT EXISTS artifact_cleanup (
                    project_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, run_id)
                );
                CREATE TABLE IF NOT EXISTS exception_records (
                    id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
                    project_id TEXT, run_id TEXT, source TEXT NOT NULL,
                    phase TEXT NOT NULL, code TEXT NOT NULL,
                    exception_type TEXT NOT NULL, reason TEXT NOT NULL,
                    severity TEXT NOT NULL, occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS exceptions_recent ON exception_records(occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS exceptions_project_recent ON exception_records(project_id, occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS exceptions_trace ON exception_records(trace_id);
                CREATE INDEX IF NOT EXISTS exceptions_run_recent ON exception_records(run_id, occurred_at DESC);
                CREATE TABLE IF NOT EXISTS build_check_attempts (
                    run_id TEXT NOT NULL, attempt INTEGER NOT NULL, outcome TEXT NOT NULL,
                    category TEXT NOT NULL, command TEXT NOT NULL, exit_code INTEGER,
                    duration_seconds REAL, fix_round INTEGER NOT NULL,
                    model_calls INTEGER, tokens_used INTEGER,
                    fingerprints_json TEXT NOT NULL, target_files_json TEXT NOT NULL,
                    error_codes_json TEXT NOT NULL, stop_code TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, PRIMARY KEY(run_id, attempt)
                );
                CREATE INDEX IF NOT EXISTS build_checks_recent ON build_check_attempts(occurred_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS exceptions_run_terminal ON exception_records(run_id)
                  WHERE run_id IS NOT NULL AND source IN ('agent', 'build') AND code NOT IN ('budget_exceeded', 'build_check_failed');
            """)
            # Serialize schema inspection and ALTER across independent service starts.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(projects)")}
            if "active_version_id" not in columns:
                db.execute("ALTER TABLE projects ADD COLUMN active_version_id TEXT")
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            if "run_mode" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN run_mode TEXT NOT NULL DEFAULT 'create'")
            if "base_version_id" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN base_version_id TEXT")
            if "base_spec_json" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN base_spec_json TEXT")
            if "active_seconds" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN active_seconds REAL")
            if "execution_started_at" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN execution_started_at TEXT")
            for column in LIMIT_COLUMNS.values():
                if column not in run_columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {column} INTEGER")
            # Budget pauses can recur and may be followed by a different terminal error.
            db.execute("DROP INDEX IF EXISTS exceptions_run_terminal")
            db.execute("""CREATE UNIQUE INDEX exceptions_run_terminal ON exception_records(run_id)
                WHERE run_id IS NOT NULL AND source IN ('agent', 'build') AND code NOT IN ('budget_exceeded', 'build_check_failed')""")
            submission_columns = {row[1] for row in db.execute("PRAGMA table_info(submissions)")}
            if "reply_to_interpretation_id" not in submission_columns:
                db.execute("ALTER TABLE submissions ADD COLUMN reply_to_interpretation_id TEXT")
            if "interpreter_version" not in submission_columns:
                db.execute("ALTER TABLE submissions ADD COLUMN interpreter_version TEXT NOT NULL DEFAULT 'stage-intent-v1'")
            db.execute("""UPDATE projects SET active_version_id=(
                SELECT id FROM versions WHERE project_id=projects.id ORDER BY rowid DESC LIMIT 1
            ) WHERE active_version_id IS NULL""")
            for project in db.execute("SELECT id FROM projects").fetchall():
                versions = db.execute("SELECT id, run_id FROM versions WHERE project_id=? ORDER BY rowid", (project[0],)).fetchall()
                for old in versions[:max(0, len(versions) - 5)]:
                    db.execute("DELETE FROM versions WHERE id=?", (old["id"],))
                    db.execute("INSERT OR IGNORE INTO artifact_cleanup VALUES (?,?)", (project[0], old["run_id"]))
        self._backfill_build_checks()
        self._import_legacy_artifacts()

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _lock_project(db: sqlite3.Connection, project_id: str) -> None:
        """SQLite's writer lock already serializes project mutations."""

    def record_exception(self, *, trace_id: str, source: str, phase: str, code: str,
                         exception_type: str, project_id: str | None = None,
                         run_id: str | None = None,
                         budget_detail: tuple[str, int, int] | None = None,
                         source_validation_codes: tuple[str, ...] | None = None,
                         plan_validation_code: str | None = None,
                         model_output_reason_code: str | None = None) -> None:
        """Persist only pre-classified metadata; terminal run failures are idempotent."""
        from .budget import budget_reason
        from .exceptions import MODEL_OUTPUT_REASONS, PLAN_VALIDATION_REASONS, REASONS, safe_phase, source_validation_reason

        allowed = {"agent": {"model_output_invalid", "model_call_failed", "plan_validation_failed", "budget_exceeded", "unsafe_source", "agent_unhandled", "preview_failed"},
                   "build": {"build_failed", "build_no_progress", "build_recurring_error", "build_repair_limit"},
                   "api": {"api_unhandled"}}
        if code not in allowed.get(source, set()):
            raise ValueError("unsupported exception source")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exception_type):
            exception_type = "Exception"
        reason = REASONS[code]
        if code == "budget_exceeded" and budget_detail is not None:
            reason = budget_reason(*budget_detail)
        if code == "unsafe_source" and source_validation_codes:
            reason = source_validation_reason(source_validation_codes)
        if code == "plan_validation_failed":
            reason = PLAN_VALIDATION_REASONS.get(plan_validation_code, REASONS[code])
        if code == "model_output_invalid":
            reason = MODEL_OUTPUT_REASONS.get(model_output_reason_code, REASONS[code])
        with self.lock, self._conn() as db:
            db.execute("""
                INSERT OR IGNORE INTO exception_records
                (id, trace_id, project_id, run_id, source, phase, code,
                 exception_type, reason, severity, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'error', ?)
            """, (str(uuid.uuid4()), trace_id, project_id, run_id, source,
                  safe_phase(phase) if source != "api" else "UnhandledRequest",
                  code, exception_type, reason, now()))

    def latest_exception_code(self, run_id: str) -> str | None:
        with self._conn() as db:
            row = db.execute("SELECT code FROM exception_records WHERE run_id=? ORDER BY occurred_at DESC, rowid DESC LIMIT 1",
                             (run_id,)).fetchone()
            return row[0] if row else None

    def record_build_check(self, run_id: str, *, attempt: int, outcome: str, category: str,
                           command: str, exit_code: int | None, duration_seconds: float | None,
                           fix_round: int, fingerprints: list[str], target_files: list[str],
                           error_codes: list[str], stop_code: str, historical: bool = False,
                           occurred_at: str | None = None) -> None:
        """Persist allowlisted build telemetry and one warning per failed attempt."""
        from .source_harness import GENERATED_FILE

        category = category if category in {"passed", "source_compile", "dependency_install", "environment_failure", "build_unknown"} else "build_unknown"
        command = command if command in {"npm run build", "npm ci --ignore-scripts --no-audit --no-fund"} else "other"
        outcome = "passed" if outcome == "passed" else "failed"
        fingerprints = [item for item in fingerprints[:24] if re.fullmatch(r"[a-f0-9]{20}", item)]
        target_files = [item for item in target_files[:12] if GENERATED_FILE.fullmatch(item)]
        error_codes = [item for item in error_codes[:24] if re.fullmatch(r"TS\d{4}", item)]
        stop_code = stop_code if stop_code in {"", "no_progress", "recurring_error", "repair_limit"} else ""
        with self.lock, self._conn() as db:
            run = db.execute("SELECT trace_id, project_id, model_calls, tokens_used FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise NotFound("任务不存在")
            at = occurred_at or now()
            db.execute("""INSERT OR IGNORE INTO build_check_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (run_id, max(1, attempt), outcome, category, command,
                        exit_code if isinstance(exit_code, int) else None,
                        round(max(0.0, duration_seconds), 3) if isinstance(duration_seconds, (float, int)) else None,
                        max(0, fix_round), None if historical else run["model_calls"],
                        None if historical else run["tokens_used"], dumps(fingerprints), dumps(target_files),
                        dumps(error_codes), stop_code, at))
            if outcome == "failed":
                labels = {"source_compile": "源码编译或类型检查", "dependency_install": "依赖安装",
                          "environment_failure": "构建环境", "build_unknown": "未归类的构建检查"}
                reason = f"第 {max(1, attempt)} 次构建检查未通过：{labels.get(category, labels['build_unknown'])}。"
                db.execute("""INSERT OR IGNORE INTO exception_records
                    (id, trace_id, project_id, run_id, source, phase, code,
                     exception_type, reason, severity, occurred_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                           (str(uuid.uuid5(uuid.NAMESPACE_URL, f"myatom:build:{run_id}:{max(1, attempt)}")),
                            run["trace_id"], run["project_id"], run_id, "build", "BuildTest", "build_check_failed",
                            "BuildCheckFailure", reason, "warning", at))

    def _backfill_build_checks(self) -> None:
        """Project old build failures into the new safe table without copying diagnostics."""
        with self._conn() as db:
            rows = db.execute("""SELECT e.run_id, e.seq, e.payload_json, e.at FROM events e
                WHERE e.type='build_harness' AND NOT EXISTS (
                  SELECT 1 FROM build_check_attempts b WHERE b.run_id=e.run_id
                  AND b.attempt=CAST(json_extract(e.payload_json, '$.attempt') AS INTEGER))
                ORDER BY e.run_id, e.seq""").fetchall()
            for row in rows:
                try:
                    harness = json.loads(row["payload_json"])
                    attempt = int(harness["attempt"])
                    result = db.execute("SELECT payload_json FROM events WHERE run_id=? AND seq>? AND type='build_result' ORDER BY seq LIMIT 1",
                                        (row["run_id"], row["seq"])).fetchone()
                    diagnosis = db.execute("SELECT payload_json FROM events WHERE run_id=? AND seq>? AND type='build_diagnosis' ORDER BY seq LIMIT 1",
                                           (row["run_id"], row["seq"])).fetchone()
                    result_data = json.loads(result[0]) if result else {}
                    diagnosis_data = json.loads(diagnosis[0]) if diagnosis else {}
                    steps = result_data.get("steps") or []
                    last_step = steps[-1] if steps else {}
                    duration = sum(float(step.get("seconds") or 0) for step in steps)
                    self.record_build_check(row["run_id"], attempt=attempt, outcome="failed",
                        category=diagnosis_data.get("category", "build_unknown"),
                        command=diagnosis_data.get("command") or last_step.get("command", ""),
                        exit_code=diagnosis_data.get("exit_code", last_step.get("exit_code")),
                        duration_seconds=duration, fix_round=int(harness.get("automatic_repairs") or 0),
                        fingerprints=harness.get("fingerprints") or [], target_files=[], error_codes=[],
                        stop_code=harness.get("stop_code") or "", historical=True, occurred_at=row["at"])
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    continue

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("card_json", "answers_json", "plan_json", "base_spec_json", "manifest_json", "payload_json", "result_json", "interpreted_intents_json"):
            if key in result:
                result[key.removesuffix("_json")] = json.loads(result.pop(key)) if result[key] else None
        return result

    @staticmethod
    def _append_event(db: sqlite3.Connection, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
        trace = db.execute("SELECT trace_id FROM runs WHERE id=?", (run_id,)).fetchone()
        safe_payload = {**payload, "trace_id": trace[0] if trace else None}
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (run_id, seq, str(uuid.uuid4()), event_type, dumps(safe_payload), now()))
        return seq

    def create_project(self, owner_hash: str, title: str) -> dict[str, Any]:
        project_id, timestamp = str(uuid.uuid4()), now()
        with self.lock, self._conn() as db:
            db.execute("INSERT INTO projects (id, owner_hash, title, created_at, updated_at) VALUES (?,?,?,?,?)", (project_id, owner_hash, title[:100], timestamp, timestamp))
        return self.get_project(project_id, owner_hash)

    def list_projects(self, owner_hash: str) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute("""
                SELECT p.*,
                  (SELECT status FROM runs WHERE project_id=p.id ORDER BY created_at DESC LIMIT 1) AS latest_status,
                  (SELECT phase FROM runs WHERE project_id=p.id ORDER BY created_at DESC LIMIT 1) AS latest_phase,
                  (SELECT id FROM versions WHERE project_id=p.id ORDER BY rowid DESC LIMIT 1) AS latest_version_id
                FROM projects p WHERE p.owner_hash=? ORDER BY p.updated_at DESC
            """, (owner_hash,)).fetchall()
            return [dict(r) for r in rows]

    def get_project(self, project_id: str, owner_hash: str) -> dict[str, Any]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM projects WHERE id=? AND owner_hash=?", (project_id, owner_hash)).fetchone()
            if row is None:
                raise NotFound("项目不存在或无权访问")
            project = dict(row)
            project["runs"] = [self._dict(r) for r in db.execute("SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()]
            project["versions"] = [self._dict(r) for r in db.execute("SELECT * FROM versions WHERE project_id=? ORDER BY rowid DESC", (project_id,)).fetchall()]
            project["decisions"] = [self._dict(r) for r in db.execute("""
                SELECT d.id, d.run_id, d.card_id, d.spec_version, d.action, d.payload_json, d.created_at
                FROM decisions d JOIN runs r ON r.id=d.run_id
                WHERE r.project_id=? ORDER BY d.created_at, d.id
            """, (project_id,)).fetchall()]
            return project

    def create_run(self, project_id: str, request_text: str, idempotency_key: str,
                   limits: dict[str, int] | None = None, mode: str = "auto") -> tuple[dict[str, Any], bool]:
        run_id, timestamp = str(uuid.uuid4()), now()
        limits = limits or DEFAULT_LIMITS
        if mode not in {"auto", "create", "iterate"}:
            raise ValueError("无效的运行模式")
        with self.lock, self._conn() as db:
            self._lock_project(db, project_id)
            existing = db.execute("SELECT * FROM runs WHERE project_id=? AND idempotency_key=?", (project_id, idempotency_key)).fetchone()
            if existing:
                return self._dict(existing), False
            active = db.execute("SELECT id FROM runs WHERE project_id=? AND status IN ('clarifying','planning','building','awaiting_clarification','awaiting_plan','awaiting_repair','awaiting_budget')", (project_id,)).fetchone()
            if active:
                raise Conflict("此项目已有进行中的任务")
            project = db.execute("SELECT active_version_id FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                raise NotFound("项目不存在")
            base_version_id = project["active_version_id"]
            if mode == "auto":
                mode = "iterate" if base_version_id else "create"
            if mode == "iterate" and not base_version_id:
                raise Conflict("此项目尚无可迭代版本")
            if mode == "create" and base_version_id:
                raise Conflict("已有可用版本的项目须从当前版本继续迭代")
            base_spec = None
            if base_version_id:
                version = db.execute("SELECT manifest_json, run_id FROM versions WHERE id=? AND project_id=?", (base_version_id, project_id)).fetchone()
                if not version:
                    raise Conflict("当前版本不可读取")
                manifest = json.loads(version["manifest_json"])
                base_spec = manifest.get("effective_spec")
                if not isinstance(base_spec, dict):
                    previous = db.execute("SELECT request_text, plan_json FROM runs WHERE id=?", (version["run_id"],)).fetchone()
                    base_spec = {"request_text": previous["request_text"], "plan": json.loads(previous["plan_json"] or "{}") } if previous else None
                if not base_spec or not base_spec.get("plan"):
                    raise Conflict("当前版本缺少可继承的已确认计划")
            db.execute("""INSERT INTO runs (id, project_id, idempotency_key, request_text, status, phase,
                trace_id, created_at, updated_at, active_seconds, max_model_calls, max_total_tokens,
                max_run_seconds, max_fix_rounds, run_mode, base_version_id, base_spec_json) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?)""",
                       (run_id, project_id, idempotency_key, request_text, "clarifying", "Clarify", str(uuid.uuid4()),
                        timestamp, timestamp, *(int(limits[kind]) for kind in LIMIT_COLUMNS), mode,
                        base_version_id, dumps(base_spec) if base_spec else None))
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id))
            self._append_event(db, run_id, "run_created", {"phase": "Clarify", "request_text": request_text})
        return self.get_run(run_id), True

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("任务不存在")
            return self._dict(row)

    def can_reopen_failed_run(self, run_id: str) -> bool:
        with self._conn() as db:
            row = db.execute("SELECT project_id, status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] != "failed":
                return False
            latest = db.execute("SELECT id FROM runs WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (row["project_id"],)).fetchone()
            active = db.execute("SELECT id FROM runs WHERE project_id=? AND id<>? AND status IN ('clarifying','planning','building','awaiting_clarification','awaiting_plan','awaiting_repair','awaiting_budget') LIMIT 1",
                                (row["project_id"], run_id)).fetchone()
            return bool(latest and latest["id"] == run_id and not active)

    def budget_pause_phase(self, run_id: str) -> str | None:
        with self._conn() as db:
            row = db.execute("""SELECT phase FROM exception_records
                WHERE run_id=? AND code='budget_exceeded' ORDER BY occurred_at DESC, rowid DESC LIMIT 1""",
                (run_id,)).fetchone()
            return str(row[0]) if row else None

    def can_offer_budget(self, run_id: str) -> bool:
        with self._conn() as db:
            row = db.execute("SELECT project_id, status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] != "budget_exceeded":
                return False
            latest = db.execute("SELECT id FROM runs WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                (row["project_id"],)).fetchone()
            active = db.execute("""SELECT id FROM runs WHERE project_id=? AND id<>?
                AND status IN ('clarifying','planning','building','awaiting_clarification','awaiting_plan','awaiting_repair','awaiting_budget') LIMIT 1""",
                (row["project_id"], run_id)).fetchone()
            return bool(latest and latest["id"] == run_id and not active)

    def extend_budget(self, run_id: str, *, key: str, card_id: str, spec_version: int,
                      selected: dict[str, bool]) -> tuple[dict[str, Any], bool]:
        increments = {kind: EXTENSION_STEPS[kind] if selected.get(kind) is True else 0
                      for kind in EXTENSION_STEPS}
        if not any(increments.values()) or set(selected) != set(EXTENSION_STEPS) or any(type(value) is not bool for value in selected.values()):
            raise ValueError("请至少选择一项有效的额度调整")
        with self.lock, self._conn() as db:
            duplicate = db.execute("SELECT * FROM decisions WHERE run_id=? AND idempotency_key=?", (run_id, key)).fetchone()
            if duplicate:
                if (duplicate["card_id"] != card_id or duplicate["spec_version"] != spec_version
                        or duplicate["action"] != "extend_budget" or json.loads(duplicate["payload_json"]) != increments):
                    raise Conflict("该幂等键已用于另一项决定")
                return self._dict(duplicate), False
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["status"] != "awaiting_budget" or run["card_id"] != card_id or run["spec_version"] != spec_version:
                raise Conflict("额度确认卡已更新，请核对最新内容")
            card = json.loads(run["card_json"] or "{}")
            if card.get("type") != "budget_extension" or "extend_budget" not in card.get("actions", []):
                raise Conflict("当前阶段不能扩展额度")
            exhausted = (card.get("payload") or {}).get("budget_kind")
            required = "total_tokens" if exhausted == "output_reserve" else exhausted
            if required in EXTENSION_STEPS and not selected[required]:
                raise ValueError("请先增加当前已耗尽的额度，再确认继续")
            latest = db.execute("SELECT id FROM runs WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                (run["project_id"],)).fetchone()
            if not latest or latest["id"] != run_id:
                raise Conflict("只能继续当前项目最近一次任务")
            before = effective_limits(dict(run))
            after = {kind: before[kind] + increments[kind] for kind in before}
            payload = card.get("payload") or {}
            resume_status = payload.get("resume_status")
            resume_phase = payload.get("resume_phase")
            if resume_status not in ACTIVE or not isinstance(resume_phase, str) or not resume_phase:
                raise Conflict("原任务检查点无法恢复")
            decision_id, timestamp = str(uuid.uuid4()), now()
            db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                       (decision_id, run_id, key, card_id, spec_version, "extend_budget", dumps(increments), 1, timestamp))
            db.execute("""UPDATE runs SET max_model_calls=?, max_total_tokens=?, max_run_seconds=?, max_fix_rounds=?,
                status=?, phase=?, card_json=?, error=NULL, updated_at=? WHERE id=?""",
                (*(after[kind] for kind in LIMIT_COLUMNS), resume_status, resume_phase,
                 dumps({**card, "status": "confirmed", "actions": []}), timestamp, run_id))
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (timestamp, run["project_id"]))
            self._append_event(db, run_id, "decision_submitted", {"decision_id": decision_id,
                               "action": "extend_budget", "spec_version": spec_version})
            self._append_event(db, run_id, "budget_extended", {"added": increments, "limits": after})
        return self.get_decision(decision_id), True

    def get_recoverable_runs(self) -> list[dict[str, Any]]:
        with self._conn() as db:
            return [self._dict(r) for r in db.execute("SELECT * FROM runs WHERE status IN ('clarifying','planning','building')").fetchall()]

    def get_waiting_repair_runs(self) -> list[dict[str, Any]]:
        with self._conn() as db:
            return [self._dict(r) for r in db.execute("SELECT * FROM runs WHERE status='awaiting_repair'").fetchall()]

    def recover_execution_timers(self) -> None:
        """Discard stale in-flight intervals; persisted heartbeats retain completed work."""
        with self.lock, self._conn() as db:
            db.execute("UPDATE runs SET execution_started_at=NULL WHERE execution_started_at IS NOT NULL")

    def begin_execution(self, run_id: str, *, allow_waiting: bool = False) -> bool:
        with self.lock, self._conn() as db:
            row = db.execute("SELECT status, execution_started_at FROM runs WHERE id=?", (run_id,)).fetchone()
            allowed = ACTIVE | WAITING if allow_waiting else ACTIVE
            if row is None or row["status"] not in allowed or row["execution_started_at"] is not None:
                return False
            db.execute("UPDATE runs SET active_seconds=COALESCE(active_seconds, 0), execution_started_at=? WHERE id=?",
                       (now(), run_id))
            return True

    def _settle_execution(self, run_id: str, *, keep_running: bool) -> float:
        timestamp = now()
        with self.lock, self._conn() as db:
            row = db.execute("SELECT active_seconds, execution_started_at FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("任务不存在")
            accumulated = float(row["active_seconds"] or 0)
            if row["execution_started_at"] is None:
                return accumulated
            delta = max(0.0, (datetime.fromisoformat(timestamp) -
                              datetime.fromisoformat(row["execution_started_at"])).total_seconds())
            accumulated += delta
            db.execute("UPDATE runs SET active_seconds=?, execution_started_at=? WHERE id=?",
                       (accumulated, timestamp if keep_running else None, run_id))
            return accumulated

    def checkpoint_execution(self, run_id: str) -> float:
        return self._settle_execution(run_id, keep_running=True)

    def finish_execution(self, run_id: str) -> float:
        return self._settle_execution(run_id, keep_running=False)

    def active_elapsed_seconds(self, run_id: str) -> float:
        with self._conn() as db:
            row = db.execute("SELECT active_seconds, execution_started_at FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFound("任务不存在")
        elapsed = float(row["active_seconds"] or 0)
        if row["execution_started_at"] is not None:
            elapsed += max(0.0, (datetime.now(timezone.utc) -
                                 datetime.fromisoformat(row["execution_started_at"])).total_seconds())
        return elapsed

    def update_run(self, run_id: str, *, event_type: str | None = None, event_payload: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "phase", "card_json", "card_id", "spec_version", "approved_spec_version", "answers_json", "plan_json", "model_calls", "tokens_used", "fix_rounds", "cancel_requested", "error", "version_id", "request_text"}
        if set(fields) - allowed:
            raise ValueError("unsupported run field")
        with self.lock, self._conn() as db:
            if fields:
                fields["updated_at"] = now()
                assignments = ", ".join(f"{key}=?" for key in fields)
                db.execute(f"UPDATE runs SET {assignments} WHERE id=?", (*fields.values(), run_id))
            if event_type:
                self._append_event(db, run_id, event_type, event_payload or {})
            project_id = db.execute("SELECT project_id FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        return self.get_run(run_id)

    def record_model_attempt(self, run_id: str, node: str) -> None:
        with self.lock, self._conn() as db:
            db.execute("UPDATE runs SET model_calls=model_calls+1, updated_at=? WHERE id=?", (now(), run_id))
            self._append_event(db, run_id, "model_started", {"node": node})

    def add_usage(self, run_id: str, tokens: int) -> dict[str, Any]:
        with self.lock, self._conn() as db:
            db.execute("UPDATE runs SET tokens_used=tokens_used+?, updated_at=? WHERE id=?", (tokens, now(), run_id))
            self._append_event(db, run_id, "model_used", {"tokens": tokens})
        return self.get_run(run_id)

    def record_model_response(self, run_id: str, metadata: dict[str, Any]) -> None:
        """Keep response diagnostics without persisting model text or reasoning."""
        with self.lock, self._conn() as db:
            self._append_event(db, run_id, "model_response", metadata)

    def record_model_output_issue(self, run_id: str, *, node: str, attempt: int, reason_code: str) -> None:
        """Record only a fixed reason code; never persist the malformed model response."""
        if reason_code not in {"length", "finish_reason", "invalid_json", "not_object", "invalid_output"}:
            reason_code = "invalid_output"
        with self.lock, self._conn() as db:
            self._append_event(db, run_id, "model_output_issue", {"node": node, "attempt": attempt,
                                                                  "reason_code": reason_code})

    def events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after_seq)).fetchall()
            return [{**self._dict(r), "schema_version": 1} for r in rows]

    def cache_get(self, run_id: str, node: str, cache_key: str) -> dict[str, Any] | None:
        with self._conn() as db:
            row = db.execute("SELECT payload_json FROM node_outputs WHERE run_id=? AND node=? AND cache_key=?", (run_id, node, cache_key)).fetchone()
            return json.loads(row[0]) if row else None

    def cache_set(self, run_id: str, node: str, cache_key: str, payload: dict[str, Any]) -> None:
        with self.lock, self._conn() as db:
            db.execute("INSERT OR IGNORE INTO node_outputs VALUES (?,?,?,?)", (run_id, node, cache_key, dumps(payload)))

    def operation_get(self, run_id: str, key: str) -> dict[str, Any] | None:
        with self._conn() as db:
            row = db.execute("SELECT result_json FROM operations WHERE run_id=? AND operation_key=?", (run_id, key)).fetchone()
            return json.loads(row[0]) if row else None

    def operation_set(self, run_id: str, key: str, result: dict[str, Any]) -> None:
        with self.lock, self._conn() as db:
            db.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?)", (run_id, key, dumps(result)))

    def submit_decision(self, run_id: str, *, key: str, card_id: str, spec_version: int, action: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self.lock, self._conn() as db:
            duplicate = db.execute("SELECT * FROM decisions WHERE run_id=? AND idempotency_key=?", (run_id, key)).fetchone()
            if duplicate:
                if duplicate["card_id"] != card_id or duplicate["spec_version"] != spec_version or duplicate["action"] != action or json.loads(duplicate["payload_json"]) != payload:
                    raise Conflict("该幂等键已用于另一项决定")
                return self._dict(duplicate), False
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            decision_id = self._commit_decision(db, run, run_id, key, card_id, spec_version, action, payload)
        return self.get_decision(decision_id), True

    def _commit_decision(self, db: sqlite3.Connection, run: sqlite3.Row | None, run_id: str,
                         key: str, card_id: str, spec_version: int, action: str, payload: dict[str, Any]) -> str:
        if not run or run["card_id"] != card_id or run["spec_version"] != spec_version:
            raise Conflict("决策卡已更新，请核对最新内容")
        expected = {"awaiting_clarification": {"confirm_clarification", "revise_clarification"}, "awaiting_plan": {"approve_plan", "revise_plan"},
                    "awaiting_repair": {"continue_repair", "guided_repair", "rebuild", "extend_auto_repair"}}
        if action not in expected.get(run["status"], set()):
            raise Conflict("当前阶段无法执行此操作")
        card = json.loads(run["card_json"] or "{}")
        if action not in card.get("actions", []):
            raise Conflict("当前失败类型不支持此修复动作")
        decision_id = str(uuid.uuid4())
        db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)", (decision_id, run_id, key, card_id, spec_version, action, dumps(payload), 0, now()))
        next_status = "building" if action in {"approve_plan", "continue_repair", "guided_repair", "rebuild", "extend_auto_repair"} else "clarifying" if action in {"revise_clarification", "confirm_clarification"} else "planning"
        next_phase = "Prepare" if action == "approve_plan" else "Clarify" if next_status == "clarifying" else "BuildTest" if action == "rebuild" else "CodeLoop" if action in {"continue_repair", "guided_repair", "extend_auto_repair"} else "Plan"
        next_fix_limit = (effective_limits(dict(run))["fix_rounds"] + EXTENSION_STEPS["fix_rounds"]
                          if action == "extend_auto_repair" else run["max_fix_rounds"])
        db.execute("UPDATE runs SET status=?, phase=?, approved_spec_version=?, request_text=?, max_fix_rounds=?, updated_at=? WHERE id=?",
                   (next_status, next_phase, spec_version if action == "approve_plan" else run["approved_spec_version"],
                    payload["request_text"] if action == "revise_clarification" else run["request_text"], next_fix_limit, now(), run_id))
        self._append_event(db, run_id, "decision_submitted", {"decision_id": decision_id, "action": action, "spec_version": spec_version})
        return decision_id

    def create_submission(self, run_id: str, *, submission_id: str, key: str, card_id: str,
                          spec_version: int, text: str, answers: dict[str, str],
                          reply_to_interpretation_id: str | None = None) -> tuple[dict[str, Any], bool]:
        request_hash = hashlib.sha256(dumps({"card_id": card_id, "spec_version": spec_version,
                                              "text": text, "answers": answers,
                                              "reply_to_interpretation_id": reply_to_interpretation_id}).encode()).hexdigest()
        with self.lock, self._conn() as db:
            duplicate = db.execute("SELECT * FROM submissions WHERE run_id=? AND idempotency_key=?", (run_id, key)).fetchone()
            if duplicate:
                if duplicate["request_hash"] != request_hash or duplicate["id"] != submission_id:
                    raise Conflict("该幂等键已用于另一条消息")
                return self._dict(duplicate), False
            run = db.execute("SELECT status, card_id, spec_version FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["status"] not in {"awaiting_clarification", "awaiting_plan", "awaiting_repair"} or run["card_id"] != card_id or run["spec_version"] != spec_version:
                raise Conflict("决策卡已更新，请核对最新内容")
            if reply_to_interpretation_id:
                previous = db.execute("SELECT run_id, card_id, spec_version, status FROM submissions WHERE id=?", (reply_to_interpretation_id,)).fetchone()
                if not previous or previous["run_id"] != run_id or previous["card_id"] != card_id or previous["spec_version"] != spec_version or previous["status"] != "needs_clarification":
                    raise Conflict("要回复的消息不属于当前待决卡")
            timestamp = now()
            db.execute("""INSERT INTO submissions
                (id, run_id, idempotency_key, card_id, spec_version, text, answers_json,
                 reply_to_interpretation_id, request_hash, interpreter_version, status, reply, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,'stage-intent-v1','interpreting','',?,?)""",
                (submission_id, run_id, key, card_id, spec_version, text, dumps(answers),
                 reply_to_interpretation_id, request_hash, timestamp, timestamp))
            self._append_event(db, run_id, "message_submitted", {"submission_id": submission_id})
        return self.get_submission(submission_id), True

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if row is None:
            raise NotFound("消息不存在")
        return self._dict(row)

    def list_submissions(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as db:
            return [self._dict(row) for row in db.execute("SELECT * FROM submissions WHERE run_id=? ORDER BY created_at, rowid", (run_id,))]

    def pending_submissions(self) -> list[str]:
        with self._conn() as db:
            return [row[0] for row in db.execute("SELECT id FROM submissions WHERE status='interpreting' ORDER BY created_at, rowid")]

    def resolve_submission(self, submission_id: str, *, action: str | None, payload: dict[str, Any],
                           intents: list[str], reply: str) -> dict[str, Any]:
        with self.lock, self._conn() as db:
            message = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
            if not message:
                raise NotFound("消息不存在")
            if message["status"] != "interpreting":
                return self._dict(message)
            run = db.execute("SELECT * FROM runs WHERE id=?", (message["run_id"],)).fetchone()
            status, decision_id = "needs_clarification", None
            if not run or run["card_id"] != message["card_id"] or run["spec_version"] != message["spec_version"] or run["status"] not in {"awaiting_clarification", "awaiting_plan", "awaiting_repair"}:
                status, action, reply = "rejected", None, "卡片已更新；这条消息未执行，请核对最新内容。"
            elif action:
                try:
                    decision_id = self._commit_decision(db, run, message["run_id"], f"message:{submission_id}",
                                                        message["card_id"], message["spec_version"], action, payload)
                    status = "committed"
                except Conflict as exc:
                    status, action, reply = "rejected", None, str(exc)
            db.execute("UPDATE submissions SET status=?, reply=?, interpreted_intents_json=?, committed_action=?, decision_id=?, updated_at=? WHERE id=?",
                       (status, reply[:500], dumps(intents[:5]), action, decision_id, now(), submission_id))
            self._append_event(db, message["run_id"], "message_interpreted", {"submission_id": submission_id, "status": status})
        return self.get_submission(submission_id)

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        with self._conn() as db:
            return self._dict(db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())

    def get_decision_by_key(self, run_id: str, key: str) -> dict[str, Any] | None:
        with self._conn() as db:
            return self._dict(db.execute("SELECT * FROM decisions WHERE run_id=? AND idempotency_key=?",
                                         (run_id, key)).fetchone())

    def pending_decision(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as db:
            return self._dict(db.execute("SELECT * FROM decisions WHERE run_id=? AND processed=0 ORDER BY created_at LIMIT 1", (run_id,)).fetchone())

    def mark_decision_processed(self, decision_id: str) -> None:
        with self.lock, self._conn() as db:
            db.execute("UPDATE decisions SET processed=1 WHERE id=?", (decision_id,))

    def commit_version(self, project_id: str, run_id: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        removed_runs: list[str] = []
        with self.lock, self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            self._lock_project(db, project_id)
            existing = db.execute("SELECT * FROM versions WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                return self._dict(existing), removed_runs
            run = db.execute("SELECT base_version_id FROM runs WHERE id=? AND project_id=?", (run_id, project_id)).fetchone()
            current = db.execute("SELECT active_version_id FROM projects WHERE id=?", (project_id,)).fetchone()
            if not run or not current or run["base_version_id"] != current["active_version_id"]:
                raise Conflict("当前版本已变化，请以最新版本开始新一轮")
            version_id = str(uuid.uuid4())
            db.execute("INSERT INTO versions (id, project_id, run_id, manifest_json, created_at) VALUES (?,?,?,?,?)",
                       (version_id, project_id, run_id, dumps(manifest), now()))
            db.execute("UPDATE runs SET version_id=?, updated_at=? WHERE id=?", (version_id, now(), run_id))
            db.execute("UPDATE projects SET active_version_id=?, updated_at=? WHERE id=?", (version_id, now(), project_id))
            versions = db.execute("SELECT id, run_id FROM versions WHERE project_id=? ORDER BY rowid", (project_id,)).fetchall()
            for old in versions[:max(0, len(versions) - 5)]:
                if old["id"] == version_id:
                    continue
                db.execute("DELETE FROM versions WHERE id=?", (old["id"],))
                db.execute("INSERT OR IGNORE INTO artifact_cleanup VALUES (?,?)", (project_id, old["run_id"]))
                removed_runs.append(old["run_id"])
            self._append_event(db, run_id, "version_saved", {"version_id": version_id, "files": manifest.get("files", [])})
        return self.get_version(version_id), removed_runs

    def commit_version_with_files(self, project_id: str, run_id: str, manifest: dict[str, Any],
                                  files: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
        """Atomically save a complete SQLite snapshot before exposing its pointer."""
        from .azure_artifacts import validate_snapshot_files

        validate_snapshot_files(manifest, files)
        removed_runs: list[str] = []
        with self.lock, self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM versions WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                return self._dict(existing), removed_runs
            run = db.execute("SELECT base_version_id FROM runs WHERE id=? AND project_id=?", (run_id, project_id)).fetchone()
            current = db.execute("SELECT active_version_id FROM projects WHERE id=?", (project_id,)).fetchone()
            if not run or not current or run["base_version_id"] != current["active_version_id"]:
                raise Conflict("当前版本已变化，请以最新版本开始新一轮")
            version_id = str(uuid.uuid4())
            db.execute("INSERT INTO versions (id, project_id, run_id, manifest_json, created_at) VALUES (?,?,?,?,?)",
                       (version_id, project_id, run_id, dumps(manifest), now()))
            db.executemany("INSERT INTO version_files VALUES (?,?,?,?,?,?,?)",
                           [(version_id, row["path"], row["content"], row["utf8_bytes"], row["sha256"],
                             row["kind"], row["mime_type"]) for row in files])
            db.execute("UPDATE runs SET version_id=?, updated_at=? WHERE id=?", (version_id, now(), run_id))
            db.execute("UPDATE projects SET active_version_id=?, updated_at=? WHERE id=?", (version_id, now(), project_id))
            versions = db.execute("SELECT id, run_id FROM versions WHERE project_id=? ORDER BY rowid", (project_id,)).fetchall()
            for old in versions[:max(0, len(versions) - 5)]:
                if old["id"] == version_id:
                    continue
                db.execute("DELETE FROM versions WHERE id=?", (old["id"],))
                db.execute("INSERT OR IGNORE INTO artifact_cleanup VALUES (?,?)", (project_id, old["run_id"]))
                removed_runs.append(old["run_id"])
            self._append_event(db, run_id, "version_saved", {"version_id": version_id, "files": manifest["files"]})
        return self.get_version(version_id), removed_runs

    def get_version_file(self, version_id: str, name: str) -> tuple[str, str]:
        from .azure_artifacts import valid_snapshot_path, verify_stored_file

        if not valid_snapshot_path(name):
            raise NotFound("版本文件不存在")
        with self._conn() as db:
            row = db.execute("SELECT text_content, utf8_bytes, sha256, mime_type FROM version_files "
                             "WHERE version_id=? AND relative_path=?", (version_id, name)).fetchone()
        if row is None:
            raise NotFound("版本文件不存在")
        return verify_stored_file(dict(row)), row["mime_type"]

    def _import_legacy_artifacts(self) -> None:
        """Import retained disk snapshots once; the database becomes authoritative."""
        from .azure_artifacts import collect_candidate_files

        with self.lock, self._conn() as db:
            rows = db.execute("SELECT id, project_id, run_id, manifest_json FROM versions "
                              "WHERE NOT EXISTS (SELECT 1 FROM version_files WHERE version_id=versions.id)").fetchall()
            for row in rows:
                root = self.path.parent / "artifacts" / row["project_id"] / row["run_id"]
                if not root.exists():
                    continue
                manifest = json.loads(row["manifest_json"])
                if "build_files" not in manifest:
                    # Early local snapshots recorded source hashes but kept
                    # only built files on disk. Reconstruct and verify those
                    # bytes before making SQLite the authority.
                    build_files = []
                    for path in sorted((root / "dist").rglob("*")):
                        if not path.is_file():
                            continue
                        data = path.read_bytes()
                        build_files.append({"path": path.relative_to(root).as_posix(),
                                            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
                    manifest["build_files"] = build_files
                files = collect_candidate_files(root, manifest)
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE versions SET manifest_json=? WHERE id=?", (dumps(manifest), row["id"]))
                db.executemany("INSERT INTO version_files VALUES (?,?,?,?,?,?,?)",
                               [(row["id"], item["path"], item["content"], item["utf8_bytes"], item["sha256"],
                                 item["kind"], item["mime_type"]) for item in files])
                db.commit()

    def save_version(self, project_id: str, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        version, _ = self.commit_version(project_id, run_id, manifest)
        return version

    def activate_version(self, project_id: str, version_id: str) -> dict[str, Any]:
        with self.lock, self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            self._lock_project(db, project_id)
            version = db.execute("SELECT id FROM versions WHERE id=? AND project_id=?", (version_id, project_id)).fetchone()
            if not version:
                raise NotFound("可用版本不存在或已被淘汰")
            db.execute("UPDATE projects SET active_version_id=?, updated_at=? WHERE id=?", (version_id, now(), project_id))
        return self.get_version(version_id)

    def version_run_ids(self, project_id: str) -> set[str]:
        with self._conn() as db:
            return {row[0] for row in db.execute("SELECT run_id FROM versions WHERE project_id=?", (project_id,))}

    def pending_artifact_cleanup(self) -> list[tuple[str, str]]:
        with self._conn() as db:
            return [(row[0], row[1]) for row in db.execute("SELECT project_id, run_id FROM artifact_cleanup")]

    def mark_artifact_cleaned(self, project_id: str, run_id: str) -> None:
        with self.lock, self._conn() as db:
            db.execute("DELETE FROM artifact_cleanup WHERE project_id=? AND run_id=?", (project_id, run_id))

    def get_version(self, version_id: str) -> dict[str, Any]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
            if not row:
                raise NotFound("版本不存在")
            return self._dict(row)
