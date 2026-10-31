from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from .app_data import AppDataService
from .settings import Settings
from .store import Conflict, NotFound, Store


VERSION_ID = re.compile(r"^[0-9a-f-]{36}$")


class RecordInput(BaseModel):
    data: dict[str, Any]


def cookie_name(version_id: str) -> str:
    return "myatom_preview_" + version_id.replace("-", "")


def create_preview_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.app_env != "local":
        raise RuntimeError("同宿主预览仅允许 APP_ENV=local")
    store = Store(settings.app_db)
    app_data = AppDataService(settings.data_dir / "app_data.sqlite3")
    app = FastAPI(title="MYATOM local preview", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(NotFound)
    async def missing(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def authorize(request: Request, version_id: str) -> tuple[dict[str, Any], str]:
        if not VERSION_ID.fullmatch(version_id):
            raise HTTPException(status_code=404, detail="版本不存在")
        project_id = app_data.session_project(request.cookies.get(cookie_name(version_id)), version_id)
        if not project_id:
            raise HTTPException(status_code=401, detail="预览访问已过期，请从工作台重新打开")
        version = store.get_version(version_id)
        if version["project_id"] != project_id:
            raise HTTPException(status_code=403, detail="预览无权访问此项目")
        return version, project_id

    def check_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        expected = f"http://127.0.0.1:{settings.preview_port}"
        if origin and origin != expected:
            raise HTTPException(status_code=403, detail="预览请求来源不受信任")

    @app.get("/open/{version_id}")
    def open_preview(version_id: str, ticket: str):
        if not VERSION_ID.fullmatch(version_id):
            raise HTTPException(status_code=404, detail="版本不存在")
        session = app_data.consume_ticket(ticket, version_id)
        if not session:
            raise HTTPException(status_code=401, detail="预览票据无效或已使用")
        response = RedirectResponse(f"/v/{version_id}/", status_code=303)
        response.set_cookie(cookie_name(version_id), session[0], httponly=True, samesite="strict", max_age=3600, secure=False)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/v/{version_id}/{name:path}")
    def static_file(version_id: str, name: str, request: Request):
        version, _ = authorize(request, version_id)
        root = (settings.data_dir / "artifacts" / version["project_id"] / version["run_id"] / "dist").resolve()
        target = (root / (name or "index.html")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="预览文件不存在")
        headers = {
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                f"base-uri 'none'; form-action 'none'; frame-ancestors {settings.workbench_origin}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        }
        if target.name == "index.html":
            html = target.read_text(encoding="utf-8").replace('="/assets/', '="./assets/')
            return HTMLResponse(html, headers=headers)
        return FileResponse(target, headers=headers)

    @app.get("/data/{version_id}/{entity}")
    def list_data(version_id: str, entity: str, request: Request):
        version, project_id = authorize(request, version_id)
        schema = app_data.schema_for(version, entity)
        return app_data.list_records(project_id, entity, schema)

    @app.post("/data/{version_id}/{entity}", status_code=201)
    def create_data(version_id: str, entity: str, body: RecordInput, request: Request):
        check_origin(request)
        version, project_id = authorize(request, version_id)
        return app_data.create_record(project_id, entity, app_data.schema_for(version, entity), body.data,
                                      request.headers.get("idempotency-key"))

    @app.patch("/data/{version_id}/{entity}/{record_id}")
    @app.put("/data/{version_id}/{entity}/{record_id}")
    def update_data(version_id: str, entity: str, record_id: str, body: RecordInput, request: Request):
        check_origin(request)
        version, project_id = authorize(request, version_id)
        return app_data.update_record(project_id, entity, record_id, app_data.schema_for(version, entity), body.data)

    @app.delete("/data/{version_id}/{entity}/{record_id}", status_code=204)
    def delete_data(version_id: str, entity: str, record_id: str, request: Request):
        check_origin(request)
        version, project_id = authorize(request, version_id)
        app_data.schema_for(version, entity)
        app_data.delete_record(project_id, entity, record_id)
        return Response(status_code=204)

    return app


app = create_preview_app()
