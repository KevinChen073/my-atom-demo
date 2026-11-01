"""Azure SQL platform adapter for the existing Store contract.

Only fixed, repository-owned SQL is translated here. Values remain bound
parameters. A separate connection is opened per transaction so worker threads
never share a mssql-python connection.
"""

from __future__ import annotations

import re
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from .azure_artifacts import VersionCommitError, valid_snapshot_path, validate_snapshot_files, verify_stored_file
from .store import Conflict, NotFound, Store, dumps, now


def validate_connection_string(connection_string: str) -> None:
    sql = connection_string.lower()
    if (not re.search(r"(?:^|;)\s*server\s*=", sql)
            or not re.search(r"(?:^|;)\s*database\s*=", sql)
            or not re.search(r"(?:^|;)\s*encrypt\s*=\s*(?:yes|true|mandatory)(?:;|$)", sql)
            or not re.search(r"(?:^|;)\s*trustservercertificate\s*=\s*(?:no|false)(?:;|$)", sql)):
        raise ValueError("Azure SQL 连接须配置 Server、Database、Encrypt=yes、TrustServerCertificate=no")


class _Row(dict):
    def __getitem__(self, key: str | int) -> Any:
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class _Cursor:
    def __init__(self, cursor: Any):
        self.cursor = cursor

    def _row(self, value: Any) -> _Row | None:
        if value is None:
            return None
        return _Row((column[0], item) for column, item in zip(self.cursor.description, value)
                    if str(column[0]).lower() != "ordinal")

    def fetchone(self) -> _Row | None:
        return self._row(self.cursor.fetchone())

    def fetchall(self) -> list[_Row]:
        return [self._row(value) for value in self.cursor.fetchall()]

    def __iter__(self):
        for value in self.cursor:
            yield self._row(value)


def _top(query: str) -> str:
    """Translate the Store's terminal literal LIMIT; nested limits are explicit below."""
    match = re.search(r"\s+LIMIT\s+(\d+)\s*$", query, re.I)
    if not match:
        return query
    statement = query[:match.start()]
    if not re.match(r"\s*SELECT\b", statement, re.I):
        raise ValueError("unsupported Azure SQL limit query")
    return re.sub(r"\bSELECT\b", f"SELECT TOP ({match.group(1)})", statement, count=1, flags=re.I)


# Primary keys of the fixed INSERT OR IGNORE statements in Store.
_IGNORE_KEYS = {
    "artifact_cleanup": (0, 1),
    "build_check_attempts": (0, 1),
    "node_outputs": (0, 1, 2),
    "operations": (0, 1),
}
_KEY_COLUMNS = {
    "artifact_cleanup": ("project_id", "run_id"),
    "build_check_attempts": ("run_id", "attempt"),
    "node_outputs": ("run_id", "node", "cache_key"),
    "operations": ("run_id", "operation_key"),
}


def _insert_if_absent(query: str, parameters: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    match = re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)", query, re.I)
    if not match:
        return query, parameters
    table = match.group(1).lower()
    insert = query[:match.start()] + re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", query[match.start():], count=1, flags=re.I)
    if table == "exception_records":
        # The deterministic build-check warning uses its id; terminal records
        # also have a one-per-run filtered unique index.
        condition = "id=?"
        keys: tuple[Any, ...] = (parameters[0],)
        if len(parameters) > 6 and parameters[3] is not None and parameters[6] not in {"budget_exceeded", "build_check_failed"}:
            condition += " OR (run_id=? AND source IN ('agent','build') AND code NOT IN ('budget_exceeded','build_check_failed'))"
            keys += (parameters[3],)
    elif table in _IGNORE_KEYS:
        condition = " AND ".join(f"{column}=?" for column in _KEY_COLUMNS[table])
        keys = tuple(parameters[index] for index in _IGNORE_KEYS[table])
    else:
        raise ValueError(f"unsupported Azure SQL insert-if-absent table: {table}")
    return (f"IF NOT EXISTS (SELECT 1 FROM {table} WITH (UPDLOCK, HOLDLOCK) WHERE {condition}) {insert}",
            keys + parameters)


class AzureSqlConnection:
    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, query: str, parameters: Any = ()) -> _Cursor | None:
        statement = query.strip()
        if statement.upper() == "BEGIN IMMEDIATE":
            return None  # The driver's non-autocommit connection owns the transaction.
        values = tuple(parameters)
        statement, values = _insert_if_absent(statement, values)
        statement = re.sub(r"\browid\b", "ordinal", statement, flags=re.I)
        statement = _top(statement)
        cursor = self.connection.cursor()
        cursor.execute(statement, values)
        return _Cursor(cursor)


@contextmanager
def azure_sql_connection(connection_string: str) -> Iterator[AzureSqlConnection]:
    import mssql_python

    with mssql_python.connect(connection_string, autocommit=False, timeout=30) as connection:
        yield AzureSqlConnection(connection)


class AzureSqlStore(Store):
    def __init__(self, connection_string: str):
        validate_connection_string(connection_string)
        self.connection_string = connection_string
        self.lock = threading.RLock()
        with self._conn() as db:
            version = db.execute("SELECT MAX(version) FROM myatom_schema_version").fetchone()
            if version is None or version[0] != 3:
                raise RuntimeError("Azure SQL schema 尚未迁移，请先执行 backend.migrate_azure_sql")
            collation = db.execute("SELECT collation_name FROM sys.columns "
                                   "WHERE object_id=OBJECT_ID(N'dbo.version_files') AND name=N'relative_path'").fetchone()
            if collation is None or collation[0] != "Latin1_General_100_BIN2":
                raise RuntimeError("Azure SQL 版本文件路径排序规则未迁移")

    def _conn(self):
        return azure_sql_connection(self.connection_string)

    def commit_version(self, project_id: str, run_id: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        raise RuntimeError("Azure SQL 可用版本必须连同文本文件一起提交")

    @staticmethod
    def _lock_project(db: AzureSqlConnection, project_id: str) -> None:
        if db.execute("SELECT id FROM projects WITH (UPDLOCK, HOLDLOCK) WHERE id=?", (project_id,)).fetchone() is None:
            raise NotFound("项目不存在")

    @staticmethod
    def _append_event(db: AzureSqlConnection, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        db.execute("SELECT id FROM runs WITH (UPDLOCK, HOLDLOCK) WHERE id=?", (run_id,))
        return Store._append_event(db, run_id, event_type, payload)

    def list_projects(self, owner_hash: str) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute("""
                SELECT p.*,
                  (SELECT TOP (1) status FROM runs WHERE project_id=p.id ORDER BY created_at DESC, ordinal DESC) AS latest_status,
                  (SELECT TOP (1) phase FROM runs WHERE project_id=p.id ORDER BY created_at DESC, ordinal DESC) AS latest_phase,
                  (SELECT TOP (1) id FROM versions WHERE project_id=p.id ORDER BY ordinal DESC) AS latest_version_id
                FROM projects p WHERE p.owner_hash=? ORDER BY p.updated_at DESC
            """, (owner_hash,)).fetchall()
            return [dict(row) for row in rows]

    def commit_version_with_files(self, project_id: str, run_id: str, manifest: dict[str, Any],
                                  files: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
        """Publish version metadata, file text, pointer, and five-version trim atomically."""
        from mssql_python.exceptions import IntegrityError

        validate_snapshot_files(manifest, files)
        removed_runs: list[str] = []
        try:
            with self.lock, self._conn() as db:
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
                for row in files:
                    db.execute("INSERT INTO version_files (version_id, relative_path, text_content, utf8_bytes, sha256, kind, mime_type) "
                               "VALUES (?,?,?,?,?,?,?)", (version_id, row["path"], row["content"], row["utf8_bytes"],
                                                           row["sha256"], row["kind"], row["mime_type"]))
                db.execute("UPDATE runs SET version_id=?, updated_at=? WHERE id=?", (version_id, now(), run_id))
                db.execute("UPDATE projects SET active_version_id=?, updated_at=? WHERE id=?", (version_id, now(), project_id))
                versions = db.execute("SELECT id, run_id FROM versions WHERE project_id=? ORDER BY ordinal", (project_id,)).fetchall()
                for old in versions[:max(0, len(versions) - 5)]:
                    if old["id"] == version_id:
                        continue
                    db.execute("DELETE FROM versions WHERE id=?", (old["id"],))
                    removed_runs.append(old["run_id"])
                self._append_event(db, run_id, "version_saved", {"version_id": version_id, "files": manifest["files"]})
        except IntegrityError as exc:
            raise VersionCommitError("版本保存失败：数据库约束拒绝候选文件，写入已回滚。") from exc
        return self.get_version(version_id), removed_runs

    def get_version_file(self, version_id: str, name: str) -> tuple[str, str]:
        if not valid_snapshot_path(name):
            raise NotFound("版本文件不存在")
        with self._conn() as db:
            row = db.execute("SELECT text_content, utf8_bytes, sha256, mime_type FROM version_files "
                             "WHERE version_id=? AND relative_path=?", (version_id, name)).fetchone()
        if row is None:
            raise NotFound("版本文件不存在")
        return verify_stored_file(row), row["mime_type"]
