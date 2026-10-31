from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .store import Conflict, NotFound, now


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class AppDataService:
    """Local adapter for scoped preview access and schema-checked business records."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self._conn() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS preview_tickets (
                    token_hash TEXT PRIMARY KEY, version_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS preview_sessions (
                    token_hash TEXT PRIMARY KEY, version_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_records (
                    project_id TEXT NOT NULL, entity TEXT NOT NULL, id TEXT NOT NULL,
                    data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, entity, id)
                );
                CREATE INDEX IF NOT EXISTS app_records_entity ON app_records(project_id, entity, created_at);
                CREATE TABLE IF NOT EXISTS app_data_ops (
                    project_id TEXT NOT NULL, entity TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL, record_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, entity, idempotency_key)
                );
            """)

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def issue_ticket(self, version_id: str, project_id: str) -> tuple[str, str]:
        ticket = secrets.token_urlsafe(32)
        expires = _expiry(2)
        with self.lock, self._conn() as db:
            db.execute("DELETE FROM preview_tickets WHERE expires_at<? OR used=1", (now(),))
            db.execute("DELETE FROM preview_sessions WHERE expires_at<?", (now(),))
            db.execute("INSERT INTO preview_tickets VALUES (?,?,?,?,0)", (_hash(ticket), version_id, project_id, expires))
        return ticket, expires

    def consume_ticket(self, ticket: str, version_id: str) -> tuple[str, str] | None:
        session = secrets.token_urlsafe(32)
        expires = _expiry(60)
        with self.lock, self._conn() as db:
            row = db.execute("SELECT * FROM preview_tickets WHERE token_hash=? AND version_id=? AND used=0 AND expires_at>?",
                             (_hash(ticket), version_id, now())).fetchone()
            if not row:
                return None
            db.execute("UPDATE preview_tickets SET used=1 WHERE token_hash=?", (_hash(ticket),))
            db.execute("INSERT INTO preview_sessions VALUES (?,?,?,?)", (_hash(session), version_id, row["project_id"], expires))
        return session, expires

    def session_project(self, token: str | None, version_id: str) -> str | None:
        if not token:
            return None
        with self._conn() as db:
            row = db.execute("SELECT project_id FROM preview_sessions WHERE token_hash=? AND version_id=? AND expires_at>?",
                             (_hash(token), version_id, now())).fetchone()
            return row[0] if row else None

    @staticmethod
    def schema_for(version: dict[str, Any], entity: str) -> dict[str, Any]:
        for schema in version["manifest"].get("entities", []):
            if schema.get("name") == entity:
                return schema
        raise NotFound("此版本未声明该数据实体")

    @staticmethod
    def validate(schema: dict[str, Any], data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or len(json.dumps(data, ensure_ascii=False)) > 16_000:
            raise ValueError("数据必须是小于 16 KB 的对象")
        fields = {field["name"]: field for field in schema["fields"]}
        if set(data) - set(fields):
            raise ValueError("包含未在计划中声明的字段")
        for name, field in fields.items():
            value = data.get(name)
            if field.get("required") and (value is None or value == ""):
                raise ValueError(f"缺少必填字段：{name}")
            if value is None:
                continue
            valid = (field["type"] == "text" and isinstance(value, str) and len(value) <= 2000) or (
                field["type"] == "number" and isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 1e12) or (
                field["type"] == "boolean" and isinstance(value, bool))
            if not valid:
                raise ValueError(f"字段类型或长度不符合计划：{name}")
        return data

    def list_records(self, project_id: str, entity: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute("SELECT * FROM app_records WHERE project_id=? AND entity=? ORDER BY created_at, id LIMIT 1000",
                              (project_id, entity)).fetchall()
        allowed = {field["name"] for field in schema["fields"]}
        return [{"id": row["id"], **{key: value for key, value in json.loads(row["data_json"]).items() if key in allowed},
                 "created_at": row["created_at"], "updated_at": row["updated_at"]} for row in rows]

    def create_record(self, project_id: str, entity: str, schema: dict[str, Any], data: Any, idempotency_key: str | None = None) -> dict[str, Any]:
        data = self.validate(schema, data)
        if idempotency_key is not None and (not 1 <= len(idempotency_key) <= 200 or not idempotency_key.isascii()):
            raise ValueError("无效的幂等键")
        request_hash = _hash(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        record_id, timestamp = str(uuid.uuid4()), now()
        with self.lock, self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                previous = db.execute("SELECT request_hash, record_id FROM app_data_ops WHERE project_id=? AND entity=? AND idempotency_key=?",
                                      (project_id, entity, idempotency_key)).fetchone()
                if previous:
                    if previous["request_hash"] != request_hash:
                        raise Conflict("相同幂等键不能用于不同数据")
                    row = db.execute("SELECT * FROM app_records WHERE project_id=? AND entity=? AND id=?",
                                     (project_id, entity, previous["record_id"])).fetchone()
                    if not row:
                        raise Conflict("原操作已完成，但记录已被删除")
                    return {"id": row["id"], **json.loads(row["data_json"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}
            count = db.execute("SELECT COUNT(*) FROM app_records WHERE project_id=? AND entity=?", (project_id, entity)).fetchone()[0]
            if count >= 1000:
                raise Conflict("该实体已达到 1000 条本地记录上限")
            db.execute("INSERT INTO app_records VALUES (?,?,?,?,?,?)", (project_id, entity, record_id, json.dumps(data, ensure_ascii=False), timestamp, timestamp))
            if idempotency_key:
                db.execute("INSERT INTO app_data_ops VALUES (?,?,?,?,?)", (project_id, entity, idempotency_key, request_hash, record_id))
        return {"id": record_id, **data, "created_at": timestamp, "updated_at": timestamp}

    def update_record(self, project_id: str, entity: str, record_id: str, schema: dict[str, Any], data: Any) -> dict[str, Any]:
        with self.lock, self._conn() as db:
            row = db.execute("SELECT * FROM app_records WHERE project_id=? AND entity=? AND id=?", (project_id, entity, record_id)).fetchone()
            if not row:
                raise NotFound("记录不存在")
            existing = json.loads(row["data_json"])
            allowed = {field["name"] for field in schema["fields"]}
            visible = {key: value for key, value in existing.items() if key in allowed}
            visible = self.validate(schema, {**visible, **data} if isinstance(data, dict) else data)
            merged = {**existing, **visible}
            timestamp = now()
            db.execute("UPDATE app_records SET data_json=?, updated_at=? WHERE project_id=? AND entity=? AND id=?",
                       (json.dumps(merged, ensure_ascii=False), timestamp, project_id, entity, record_id))
        return {"id": record_id, **visible, "created_at": row["created_at"], "updated_at": timestamp}

    def delete_record(self, project_id: str, entity: str, record_id: str) -> None:
        with self.lock, self._conn() as db:
            result = db.execute("DELETE FROM app_records WHERE project_id=? AND entity=? AND id=?", (project_id, entity, record_id))
            if result.rowcount == 0:
                raise NotFound("记录不存在")
