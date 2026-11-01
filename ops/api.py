"""Standalone authenticated operations API and static UI."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import OpsSettings
from .store import (AzureSqlReadOnlyExceptionStore, DatabaseUnavailable, InvalidCursor,
                    ReadOnlyExceptionStore, PostgresReadOnlyExceptionStore)


def create_app(settings: OpsSettings | None = None) -> FastAPI:
    settings = settings or OpsSettings.from_env()
    if settings.azure_sql_connection_string and settings.database_url:
        raise ValueError("异常后台只能配置一个远程数据库")
    store = (AzureSqlReadOnlyExceptionStore(settings.azure_sql_connection_string)
             if settings.azure_sql_connection_string else
             PostgresReadOnlyExceptionStore(settings.database_url) if settings.database_url else
             ReadOnlyExceptionStore(settings.db_path))
    app = FastAPI(title="MYATOM Operations")
    app.state.store = store

    @app.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DatabaseUnavailable)
    async def database_unavailable(_, __):
        return JSONResponse({"detail": "异常数据库不可用或尚未迁移"}, status_code=503)

    @app.exception_handler(InvalidCursor)
    async def invalid_cursor(_, __):
        return JSONResponse({"detail": "分页游标无效"}, status_code=422)

    def require_admin(x_operations_key: str | None = Header(default=None)) -> None:
        if not settings.admin_key:
            raise HTTPException(status_code=503, detail="运维身份尚未配置")
        if not x_operations_key or not hmac.compare_digest(x_operations_key, settings.admin_key):
            raise HTTPException(status_code=401, detail="运维身份验证失败")

    @app.get("/api/ops/exceptions", dependencies=[Depends(require_admin)])
    def list_exceptions(
        limit: int = Query(default=30, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=500),
        source: Literal["agent", "build", "api"] | None = None,
        code: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$"),
        project_id: UUID | None = None,
        trace_id: UUID | None = None,
    ):
        return store.list_records(limit=limit, cursor=cursor, source=source,
                                  code=code, project_id=str(project_id) if project_id else None,
                                  trace_id=str(trace_id) if trace_id else None)

    @app.get("/api/ops/exceptions/{record_id}", dependencies=[Depends(require_admin)])
    def get_exception(record_id: UUID):
        result = store.get_record(str(record_id))
        if result is None:
            raise HTTPException(status_code=404, detail="异常记录不存在")
        return result

    static_dir: Path = settings.static_dir
    if static_dir.is_dir():
        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(static_dir / "index.html")

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ops-web")
    else:
        @app.get("/", include_in_schema=False)
        def missing_ui():
            return JSONResponse({"detail": "运维前端尚未构建"}, status_code=503)
    return app


app = create_app()
