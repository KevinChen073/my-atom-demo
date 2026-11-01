"""Read-only operations routes inside the authenticated Atoms API process."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ops.store import DatabaseUnavailable, InvalidCursor, ReadOnlyExceptionStore


def create_router(db_path) -> APIRouter:
    router = APIRouter()
    store = ReadOnlyExceptionStore(db_path)

    @router.get("/api/ops/exceptions")
    def list_exceptions(limit: int = Query(default=30, ge=1, le=100),
                        cursor: str | None = Query(default=None, max_length=500),
                        source: Literal["agent", "build", "api"] | None = None,
                        code: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$"),
                        project_id: UUID | None = None, trace_id: UUID | None = None):
        try:
            return store.list_records(limit=limit, cursor=cursor, source=source, code=code,
                                      project_id=str(project_id) if project_id else None,
                                      trace_id=str(trace_id) if trace_id else None)
        except DatabaseUnavailable:
            return JSONResponse({"detail": "异常数据库不可用或尚未迁移"}, status_code=503)
        except InvalidCursor:
            return JSONResponse({"detail": "分页游标无效"}, status_code=422)

    @router.get("/api/ops/exceptions/{record_id}")
    def get_exception(record_id: UUID):
        try:
            result = store.get_record(str(record_id))
        except DatabaseUnavailable:
            return JSONResponse({"detail": "异常数据库不可用或尚未迁移"}, status_code=503)
        if result is None:
            raise HTTPException(status_code=404, detail="异常记录不存在")
        return result

    return router
