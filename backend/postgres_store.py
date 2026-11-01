"""PostgreSQL platform state behind the existing Store contract.

Only APP_ENV=local may use this adapter until the isolated Runner and HTTPS
preview are ready. Schema creation is an explicit deployment step.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .store import NotFound, Store


class _Row(dict):
    """Preserve SQLite Row's positional and named access for Store methods."""

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _Cursor:
    def __init__(self, cursor: Any):
        self.cursor = cursor

    @staticmethod
    def _row(row: dict[str, Any] | None) -> _Row | None:
        if row is None:
            return None
        return _Row((key, value) for key, value in row.items() if key != "ordinal")

    def fetchone(self) -> _Row | None:
        return self._row(self.cursor.fetchone())

    def fetchall(self) -> list[_Row]:
        return [self._row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        for row in self.cursor:
            yield self._row(row)


class PostgresConnection:
    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, query: str, parameters: Any = ()) -> _Cursor | None:
        statement = query.strip()
        if statement.upper() == "BEGIN IMMEDIATE":
            # Psycopg starts a transaction on the next statement. The caller's
            # project row lock below provides the required serialization.
            return None
        ignored = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", statement, re.I))
        if ignored:
            statement = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", statement, count=1, flags=re.I)
            statement = statement.rstrip("; ") + " ON CONFLICT DO NOTHING"
        statement = re.sub(r"\browid\b", "ordinal", statement, flags=re.I).replace("?", "%s")
        return _Cursor(self.connection.execute(statement, parameters))


@contextmanager
def postgres_connection(database_url: str) -> Iterator[PostgresConnection]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=5) as connection:
        yield PostgresConnection(connection)


class PostgresStore(Store):
    def __init__(self, database_url: str):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("PostgreSQL 连接地址无效")
        self.database_url = database_url
        self.lock = threading.RLock()
        with self._conn() as db:
            version = db.execute("SELECT version FROM myatom_schema_version").fetchone()
            if version is None or version[0] != 1:
                raise RuntimeError("PostgreSQL schema 尚未迁移，请先执行 backend.migrate_postgres")

    def _conn(self):
        return postgres_connection(self.database_url)

    @staticmethod
    def _lock_project(db: PostgresConnection, project_id: str) -> None:
        if db.execute("SELECT id FROM projects WHERE id=? FOR UPDATE", (project_id,)).fetchone() is None:
            raise NotFound("项目不存在")

    @staticmethod
    def _append_event(db: PostgresConnection, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        # MAX(seq)+1 is safe only while a per-run row lock is held.
        db.execute("SELECT id FROM runs WHERE id=? FOR UPDATE", (run_id,))
        return Store._append_event(db, run_id, event_type, payload)
