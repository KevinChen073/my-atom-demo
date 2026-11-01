"""Offline contract checks for the Azure SQL translation boundary."""

from __future__ import annotations

import pytest
from contextlib import contextmanager

from langgraph.checkpoint.base import empty_checkpoint

from backend.azure_sql import AzureSqlConnection, validate_connection_string
import backend.azure_sql_checkpoint as checkpoint_module
import backend.azure_sql_probe as probe_module
from backend.azure_sql_checkpoint import AzureSqlSaver
from ops.store import AzureSqlReadOnlyExceptionStore, _AzureSqlOpsConnection


class _Cursor:
    description = [("id",), ("ordinal",)]

    def __init__(self, calls):
        self.calls = calls

    def execute(self, query, parameters):
        self.calls.append((query, tuple(parameters)))

    def fetchone(self):
        return ("run-1", 7)

    def fetchall(self):
        return [("run-1", 7)]


class _Connection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return _Cursor(self.calls)


def test_store_adapter_translates_ordered_limit_and_hides_sort_column():
    raw = _Connection()
    db = AzureSqlConnection(raw)
    row = db.execute("SELECT * FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row["id"] == row[0] == "run-1"
    assert dict(row) == {"id": "run-1"}
    assert raw.calls[-1] == ("SELECT TOP (1) * FROM runs ORDER BY ordinal DESC", ())
    assert db.execute("BEGIN IMMEDIATE") is None


def test_store_adapter_keeps_insert_if_absent_atomic_and_parameterized():
    raw = _Connection()
    db = AzureSqlConnection(raw)
    db.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?)", ("run-1", "prepare", "{}"))
    query, params = raw.calls[-1]
    assert "WITH (UPDLOCK, HOLDLOCK)" in query
    assert "WHERE run_id=? AND operation_key=?" in query
    assert "INSERT INTO operations VALUES (?,?,?)" in query
    assert params == ("run-1", "prepare", "run-1", "prepare", "{}")


def test_exception_insert_preserves_one_terminal_failure_per_run():
    raw = _Connection()
    db = AzureSqlConnection(raw)
    db.execute("INSERT OR IGNORE INTO exception_records (id, trace_id, project_id, run_id, source, phase, code) "
               "VALUES (?,?,?,?,?,?,?)", ("id", "trace", "project", "run", "agent", "Plan", "model_output_invalid"))
    query, params = raw.calls[-1]
    assert "source IN ('agent','build')" in query
    assert params[:2] == ("id", "run")


def test_ops_queries_use_only_safe_views_and_bounded_top():
    raw = _Connection()
    db = _AzureSqlOpsConnection(raw)
    db.execute("SELECT id FROM exception_records WHERE project_id=? ORDER BY occurred_at DESC LIMIT ?", ("project", 21))
    query, params = raw.calls[-1]
    assert query == "SELECT TOP (?) id FROM ops_exception_records WHERE project_id=? ORDER BY occurred_at DESC"
    assert params == (21, "project")
    db.execute("SELECT seq FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 30", ("run",))
    assert raw.calls[-1][1] == (30, "run")
    assert "ops_event_timeline" in raw.calls[-1][0]


def test_checkpoint_list_zero_limit_does_not_open_database():
    saver = AzureSqlSaver("unconnected-test")
    assert list(saver.list(None, limit=0)) == []


def test_ops_azure_sql_requires_encryption_and_certificate_validation():
    with pytest.raises(ValueError, match="验证证书"):
        AzureSqlReadOnlyExceptionStore("Server=host;Database=myatom;Encrypt=no")
    with pytest.raises(ValueError, match="验证证书"):
        AzureSqlReadOnlyExceptionStore("Server=host;Database=myatom;Encrypt=yes;TrustServerCertificate=yes")
    with pytest.raises(ValueError, match="TrustServerCertificate=no"):
        validate_connection_string("Server=host;Database=myatom;Encrypt=yes")


def test_checkpoint_saver_upserts_and_keeps_mixed_writes_idempotent(monkeypatch):
    calls = []

    class FakeDb:
        def execute(self, query, params):
            assert query.count("?") == len(params)
            calls.append(query)

    @contextmanager
    def fake_connection(_):
        yield FakeDb()

    monkeypatch.setattr(checkpoint_module, "azure_sql_connection", fake_connection)
    saver = AzureSqlSaver("test")
    config = {"configurable": {"thread_id": "run", "checkpoint_ns": ""}}
    saved = saver.put(config, empty_checkpoint(), {"source": "input", "step": 1, "writes": {}}, {})
    assert "IF EXISTS" in calls[-1] and "UPDATE myatom_checkpoints" in calls[-1]
    saver.put_writes(saved, [("__error__", "failed"), ("normal", 1)], "task")
    assert all("IF NOT EXISTS" in query for query in calls[-2:])


def test_read_only_probe_reports_managed_identity_and_schema(monkeypatch):
    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class FakeDb:
        def execute(self, sql):
            if "OBJECT_ID" in sql:
                return Result({"database_name": "my-atom-dev", "database_user": "myatom-azure-check", "schema_table": 1})
            return Result({"version": 2})

    @contextmanager
    def fake_connection(_):
        yield FakeDb()

    monkeypatch.setattr(probe_module, "azure_sql_connection", fake_connection)
    result = probe_module.probe("Server=host;Database=my-atom-dev;Authentication=ActiveDirectoryMSI;Encrypt=yes;TrustServerCertificate=no")
    assert result == {"database": "my-atom-dev", "user": "myatom-azure-check", "schema_version": 2}
