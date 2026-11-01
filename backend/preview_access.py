"""Short-lived access tickets for the local preview gateway; no app business data."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from .store import now


def preview_host(project_id: str, domain: str = "localhost") -> str:
    return f"p-{UUID(project_id).hex}.{domain}"


def preview_origin(project_id: str, port: int | None, domain: str = "localhost", scheme: str = "http") -> str:
    return f"{scheme}://{preview_host(project_id, domain)}" + (f":{port}" if port is not None else "")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class PreviewAccess:
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
            """)

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def issue_ticket(self, version_id: str, project_id: str) -> tuple[str, str]:
        ticket, expires = secrets.token_urlsafe(32), _expiry(2)
        with self.lock, self._conn() as db:
            db.execute("DELETE FROM preview_tickets WHERE expires_at<? OR used=1", (now(),))
            db.execute("DELETE FROM preview_sessions WHERE expires_at<?", (now(),))
            db.execute("INSERT INTO preview_tickets VALUES (?,?,?,?,0)", (_hash(ticket), version_id, project_id, expires))
        return ticket, expires

    def consume_ticket(self, ticket: str, version_id: str) -> tuple[str, str] | None:
        session, expires = secrets.token_urlsafe(32), _expiry(60)
        with self.lock, self._conn() as db:
            row = db.execute("SELECT project_id FROM preview_tickets WHERE token_hash=? AND version_id=? AND used=0 AND expires_at>?",
                             (_hash(ticket), version_id, now())).fetchone()
            if not row:
                return None
            db.execute("UPDATE preview_tickets SET used=1 WHERE token_hash=?", (_hash(ticket),))
            db.execute("INSERT INTO preview_sessions VALUES (?,?,?,?)", (_hash(session), version_id, row["project_id"], expires))
        return session, row["project_id"]

    def session_project(self, token: str | None, version_id: str) -> str | None:
        if not token:
            return None
        with self._conn() as db:
            row = db.execute("SELECT project_id FROM preview_sessions WHERE token_hash=? AND version_id=? AND expires_at>?",
                             (_hash(token), version_id, now())).fetchone()
            return row[0] if row else None


class PostgresPreviewAccess(PreviewAccess):
    """Same ticket API on the shared platform database; schema is migrated separately."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.lock = threading.RLock()

    def _conn(self):
        from .postgres_store import postgres_connection
        return postgres_connection(self.database_url)

    def consume_ticket(self, ticket: str, version_id: str) -> tuple[str, str] | None:
        session, expires = secrets.token_urlsafe(32), _expiry(60)
        with self.lock, self._conn() as db:
            row = db.execute("""UPDATE preview_tickets SET used=1
                WHERE token_hash=? AND version_id=? AND used=0 AND expires_at>?
                RETURNING project_id""", (_hash(ticket), version_id, now())).fetchone()
            if not row:
                return None
            db.execute("INSERT INTO preview_sessions VALUES (?,?,?,?)",
                       (_hash(session), version_id, row["project_id"], expires))
        return session, row["project_id"]
