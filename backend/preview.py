from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .preview_access import PreviewAccess
from .settings import Settings
from .store import Conflict, NotFound, Store


VERSION_ID = re.compile(r"^[0-9a-f-]{36}$")


def create_preview_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.app_env not in {"local", "azure_demo"}:
        raise RuntimeError("当前环境不允许预览")
    settings.validate_azure_demo()
    if settings.azure_sql_connection_string:
        from .azure_sql import AzureSqlStore
        from .preview_access import AzureSqlPreviewAccess

        store = AzureSqlStore(settings.azure_sql_connection_string)
        access = AzureSqlPreviewAccess(settings.azure_sql_connection_string)
    elif settings.database_url:
        from .postgres_store import PostgresStore
        from .preview_access import PostgresPreviewAccess
        store = PostgresStore(settings.database_url)
        access = PostgresPreviewAccess(settings.database_url)
    else:
        store = Store(settings.app_db)
        access = PreviewAccess(settings.data_dir / "preview_access.sqlite3")
    app = FastAPI(title="MYATOM local preview", docs_url=None, redoc_url=None, openapi_url=None)

    def expired_response() -> HTMLResponse:
        return HTMLResponse(
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<title>预览已过期</title><body><main>"
            "<h1>预览已过期</h1><p>请点击工作台中的“重新载入”，获取新的预览访问权限。</p>"
            "</main></body></html>",
            status_code=401,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": f"default-src 'none'; frame-ancestors {settings.workbench_origin}",
            },
        )

    @app.exception_handler(NotFound)
    async def missing(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def authorize(request: Request, version_id: str, session_token: str) -> tuple[dict[str, Any], str]:
        if not VERSION_ID.fullmatch(version_id):
            raise HTTPException(status_code=404, detail="版本不存在")
        project_id = access.session_project(session_token, version_id)
        if not project_id:
            raise HTTPException(status_code=401, detail="预览访问已过期，请从工作台重新打开")
        version = store.get_version(version_id)
        if version.get("manifest", {}).get("template") != "react-vite-v4":
            raise HTTPException(status_code=409, detail="旧版应用不能在同源预览中打开")
        if version["project_id"] != project_id:
            raise HTTPException(status_code=403, detail="预览无权访问此项目")
        return version, project_id

    @app.get("/open/{version_id}")
    def open_preview(version_id: str, ticket: str, request: Request):
        if not VERSION_ID.fullmatch(version_id):
            raise HTTPException(status_code=404, detail="版本不存在")
        version = store.get_version(version_id)
        if version.get("manifest", {}).get("template") != "react-vite-v4":
            raise HTTPException(status_code=409, detail="旧版应用不能在同源预览中打开")
        session = access.consume_ticket(ticket, version_id)
        if not session:
            return expired_response()
        if session[1] != version["project_id"]:
            raise HTTPException(status_code=403, detail="预览项目不匹配")
        response = RedirectResponse(f"/preview/s/{session[0]}/v/{version_id}/", status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/s/{session_token}/v/{version_id}/{name:path}")
    def static_file(session_token: str, version_id: str, name: str, request: Request):
        try:
            version, project_id = authorize(request, version_id, session_token)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            return expired_response()
        try:
            content, mime = store.get_version_file(version_id, "dist/" + (name or "index.html"))
        except NotFound:
            raise HTTPException(status_code=404, detail="预览文件不存在")
        headers = {
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'none'; font-src 'self'; "
                f"base-uri 'none'; form-action 'none'; frame-ancestors {settings.workbench_origin}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Origin-Agent-Cluster": "?1",
        }
        if (name or "index.html") == "index.html":
            html = content.replace('="/assets/', '="./assets/')
            project_hex = UUID(project_id).hex
            html = html.replace("<head>", f'<head><meta name="myatom-project-id" content="{project_hex}">', 1)
            return HTMLResponse(html, headers=headers)
        return Response(content, media_type=mime, headers=headers)

    return app
