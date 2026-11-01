"""Explicit one-time PostgreSQL platform and LangGraph checkpoint migration."""

from __future__ import annotations

import os
from pathlib import Path


def migrate(database_url: str) -> None:
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("MYATOM_DATABASE_URL 必须是 PostgreSQL 连接地址")
    import psycopg
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver

    with psycopg.connect(database_url, connect_timeout=5) as connection:
        # A migration must be serialized even when two deploy jobs overlap.
        connection.execute("SELECT pg_advisory_xact_lock(75142017)")
        exists = connection.execute("SELECT to_regclass('public.myatom_schema_version')").fetchone()[0]
        version = connection.execute("SELECT max(version) FROM myatom_schema_version").fetchone()[0] if exists else 0
        if version not in (0, 1, 2):
            raise RuntimeError("不支持的 PostgreSQL schema 版本")
        for target in range(version + 1, 3):
            sql = (Path(__file__).parent / "sql" / f"postgres_v{target}.sql").read_text(encoding="utf-8")
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
    # LangGraph requires autocommit when creating checkpoint tables/indexes.
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row, connect_timeout=5) as connection:
        PostgresSaver(connection).setup()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate MYATOM PostgreSQL platform schema")
    parser.add_argument("--database-url", default=os.getenv("MYATOM_DATABASE_URL", ""))
    args = parser.parse_args()
    migrate(args.database_url)
    print("MYATOM PostgreSQL schema and checkpoint migration complete")
