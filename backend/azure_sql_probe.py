"""Read-only Azure SQL connection check to run inside the Container App."""

from __future__ import annotations

import os

from .azure_sql import azure_sql_connection, validate_connection_string


def probe(connection_string: str) -> dict[str, str | int]:
    validate_connection_string(connection_string)
    with azure_sql_connection(connection_string) as db:
        row = db.execute("SELECT DB_NAME() AS database_name, USER_NAME() AS database_user, "
                         "OBJECT_ID(N'dbo.myatom_schema_version', N'U') AS schema_table").fetchone()
        result: dict[str, str | int] = {"database": row["database_name"], "user": row["database_user"]}
        result["schema_version"] = (db.execute("SELECT MAX(version) AS version FROM dbo.myatom_schema_version").fetchone()["version"]
                                    if row["schema_table"] is not None else 0)
        return result


if __name__ == "__main__":
    result = probe(os.getenv("MYATOM_AZURE_SQL_CONNECTION_STRING", ""))
    print(f"Azure SQL connected: database={result['database']} user={result['user']} schema_version={result['schema_version']}")
