"""Explicit, repeatable migration of a dedicated empty Azure SQL database."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .azure_sql import validate_connection_string


def migrate(connection_string: str) -> None:
    validate_connection_string(connection_string)
    import mssql_python

    sql_dir = Path(__file__).parent / "sql"
    with mssql_python.connect(connection_string, autocommit=False, timeout=60) as db:
        cursor = db.cursor()
        cursor.execute("SELECT OBJECT_ID(N'dbo.myatom_schema_version', N'U')")
        if cursor.fetchone()[0] is None:
            cursor.execute("SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped=0")
            if cursor.fetchone()[0]:
                raise RuntimeError("Azure SQL 数据库不是空库，拒绝自动接管；请使用独立空库")
            version = 0
        else:
            cursor.execute("SELECT MAX(version) FROM dbo.myatom_schema_version")
            version = cursor.fetchone()[0]
            if version not in {1, 2}:
                raise RuntimeError("不支持的 Azure SQL schema 版本")
        if version == 1:
            cursor.execute("SELECT COUNT(*) FROM dbo.versions")
            if cursor.fetchone()[0]:
                raise RuntimeError("schema v1 已有版本记录，必须先受控导入文件，拒绝生成空文件的可用版本")
        for number in range(version + 1, 3):
            script = (sql_dir / f"azure_sql_v{number}.sql").read_text(encoding="utf-8")
            for batch in (part.strip() for part in re.split(r"(?im)^GO\s*$", script)):
                if batch:
                    cursor.execute(batch)
        cursor.execute("SELECT MAX(version) FROM dbo.myatom_schema_version")
        if cursor.fetchone()[0] != 2:
            raise RuntimeError("Azure SQL schema 迁移未完成")


if __name__ == "__main__":
    migrate(os.getenv("MYATOM_AZURE_SQL_CONNECTION_STRING", ""))
    print("MYATOM Azure SQL schema migration complete")
