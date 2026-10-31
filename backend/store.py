from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE = {"clarifying", "planning", "building"}
WAITING = {"awaiting_clarification", "awaiting_plan"}


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
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_hash, updated_at);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    request_text TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
                    card_json TEXT, card_id TEXT, spec_version INTEGER NOT NULL DEFAULT 0,
                    approved_spec_version INTEGER, answers_json TEXT, plan_json TEXT,
                    model_calls INTEGER NOT NULL DEFAULT 0, tokens_used INTEGER NOT NULL DEFAULT 0,
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
                CREATE UNIQUE INDEX IF NOT EXISTS exceptions_run_terminal ON exception_records(run_id)
                  WHERE run_id IS NOT NULL AND source IN ('agent', 'build');
            """)

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def record_exception(self, *, trace_id: str, source: str, phase: str, code: str,
                         exception_type: str, project_id: str | None = None,
                         run_id: str | None = None) -> None:
        """Persist only pre-classified metadata; terminal run failures are idempotent."""
        from .exceptions import REASONS, safe_phase

        allowed = {"agent": {"model_output_invalid", "model_call_failed", "budget_exceeded", "unsafe_source", "agent_unhandled"},
                   "build": {"build_failed"}, "api": {"api_unhandled"}}
        if code not in allowed.get(source, set()):
            raise ValueError("unsupported exception source")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exception_type):
            exception_type = "Exception"
        with self.lock, self._conn() as db:
            db.execute("""
                INSERT OR IGNORE INTO exception_records
                (id, trace_id, project_id, run_id, source, phase, code,
                 exception_type, reason, severity, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'error', ?)
            """, (str(uuid.uuid4()), trace_id, project_id, run_id, source,
                  safe_phase(phase) if source != "api" else "UnhandledRequest",
                  code, exception_type, REASONS[code], now()))

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("card_json", "answers_json", "plan_json", "manifest_json", "payload_json", "result_json"):
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
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (project_id, owner_hash, title[:100], timestamp, timestamp))
        return self.get_project(project_id, owner_hash)

    def list_projects(self, owner_hash: str) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute("""
                SELECT p.*,
                  (SELECT status FROM runs WHERE project_id=p.id ORDER BY created_at DESC LIMIT 1) AS latest_status,
                  (SELECT phase FROM runs WHERE project_id=p.id ORDER BY created_at DESC LIMIT 1) AS latest_phase,
                  (SELECT id FROM versions WHERE project_id=p.id ORDER BY created_at DESC LIMIT 1) AS latest_version_id
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
            project["versions"] = [self._dict(r) for r in db.execute("SELECT * FROM versions WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()]
            return project

    def create_run(self, project_id: str, request_text: str, idempotency_key: str) -> tuple[dict[str, Any], bool]:
        run_id, timestamp = str(uuid.uuid4()), now()
        with self.lock, self._conn() as db:
            existing = db.execute("SELECT * FROM runs WHERE project_id=? AND idempotency_key=?", (project_id, idempotency_key)).fetchone()
            if existing:
                return self._dict(existing), False
            active = db.execute("SELECT id FROM runs WHERE project_id=? AND status IN ('clarifying','planning','building','awaiting_clarification','awaiting_plan')", (project_id,)).fetchone()
            if active:
                raise Conflict("此项目已有进行中的任务")
            db.execute("INSERT INTO runs (id, project_id, idempotency_key, request_text, status, phase, trace_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (run_id, project_id, idempotency_key, request_text, "clarifying", "Clarify", str(uuid.uuid4()), timestamp, timestamp))
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id))
            self._append_event(db, run_id, "run_created", {"phase": "Clarify"})
        return self.get_run(run_id), True

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise NotFound("任务不存在")
            return self._dict(row)

    def get_recoverable_runs(self) -> list[dict[str, Any]]:
        with self._conn() as db:
            return [self._dict(r) for r in db.execute("SELECT * FROM runs WHERE status IN ('clarifying','planning','building')").fetchall()]

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
                return self._dict(duplicate), False
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["card_id"] != card_id or run["spec_version"] != spec_version:
                raise Conflict("决策卡已更新，请核对最新内容")
            expected = {"awaiting_clarification": {"confirm_clarification", "revise_clarification"}, "awaiting_plan": {"approve_plan", "revise_plan", "return_to_clarification"}}
            if action not in expected.get(run["status"], set()):
                raise Conflict("当前阶段无法执行此操作")
            decision_id = str(uuid.uuid4())
            db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)", (decision_id, run_id, key, card_id, spec_version, action, dumps(payload), 0, now()))
            next_status = "building" if action == "approve_plan" else "clarifying" if action in {"revise_clarification", "return_to_clarification"} else "planning"
            next_phase = "Prepare" if action == "approve_plan" else "Clarify" if next_status == "clarifying" else "Plan"
            db.execute("UPDATE runs SET status=?, phase=?, approved_spec_version=?, request_text=?, updated_at=? WHERE id=?",
                       (next_status, next_phase, spec_version if action == "approve_plan" else run["approved_spec_version"],
                        payload["request_text"] if action == "revise_clarification" else run["request_text"], now(), run_id))
            self._append_event(db, run_id, "decision_submitted", {"action": action, "spec_version": spec_version})
        return self.get_decision(decision_id), True

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        with self._conn() as db:
            return self._dict(db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())

    def pending_decision(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as db:
            return self._dict(db.execute("SELECT * FROM decisions WHERE run_id=? AND processed=0 ORDER BY created_at LIMIT 1", (run_id,)).fetchone())

    def mark_decision_processed(self, decision_id: str) -> None:
        with self.lock, self._conn() as db:
            db.execute("UPDATE decisions SET processed=1 WHERE id=?", (decision_id,))

    def save_version(self, project_id: str, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self._conn() as db:
            existing = db.execute("SELECT * FROM versions WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                return self._dict(existing)
            version_id = str(uuid.uuid4())
            db.execute("INSERT INTO versions VALUES (?,?,?,?,?)", (version_id, project_id, run_id, dumps(manifest), now()))
            db.execute("UPDATE runs SET version_id=?, updated_at=? WHERE id=?", (version_id, now(), run_id))
            self._append_event(db, run_id, "version_saved", {"version_id": version_id, "files": manifest.get("files", [])})
        return self.get_version(version_id)

    def get_version(self, version_id: str) -> dict[str, Any]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
            if not row:
                raise NotFound("版本不存在")
            return self._dict(row)
