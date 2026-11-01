"""The schema migration must refuse metadata-only upgrades of existing versions."""

import sys
from types import SimpleNamespace

import pytest

from backend.migrate_azure_sql import migrate
from pathlib import Path


def test_v1_with_versions_refuses_v2_before_any_ddl(monkeypatch):
    executed = []

    class Cursor:
        def execute(self, sql):
            executed.append(sql)

        def fetchone(self):
            sql = executed[-1]
            if sql.startswith("SELECT OBJECT_ID"):
                return (1,)
            if sql.startswith("SELECT MAX(version)"):
                return (1,)
            if sql.startswith("SELECT COUNT(*) FROM dbo.versions"):
                return (1,)
            raise AssertionError(sql)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(sys.modules, "mssql_python", SimpleNamespace(connect=lambda *_args, **_kwargs: Connection()))
    with pytest.raises(RuntimeError, match="受控导入"):
        migrate("Server=test;Database=test;Encrypt=yes;TrustServerCertificate=no")
    assert len(executed) == 3


def test_checkpoint_column_is_delimited_in_schema_and_saver():
    root = Path(__file__).resolve().parents[1]
    schema = (root / "backend/sql/azure_sql_v1.sql").read_text(encoding="utf-8")
    saver = (root / "backend/azure_sql_checkpoint.py").read_text(encoding="utf-8")
    assert "[checkpoint] VARBINARY(MAX)" in schema
    assert "[checkpoint]=?" in saver
    assert "data_type, [checkpoint], metadata" in saver
