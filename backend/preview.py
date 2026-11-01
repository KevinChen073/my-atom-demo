from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from .preview_access import PreviewAccess, preview_host
from .settings import Settings
from .store import Conflict, NotFound, Store


VERSION_ID = re.compile(r"^[0-9a-f-]{36}$")


def create_preview_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.app_env not in {"local", "azure_demo"}:
        raise RuntimeError("当前环境不允许预览")
    settings.validate_azure_demo()
    domain = settings.preview_base_domain if settings.app_env == "azure_demo" else "localhost"
    if settings.database_url:
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
        if version["project_id"] != project_id or request.url.hostname != preview_host(project_id, domain):
            raise HTTPException(status_code=403, detail="预览无权访问此项目")
        return version, project_id

    @app.get("/open/{version_id}")
    def open_preview(version_id: str, ticket: str, request: Request):
        if not VERSION_ID.fullmatch(version_id):
            raise HTTPException(status_code=404, detail="版本不存在")
        version = store.get_version(version_id)
        if request.url.hostname != preview_host(version["project_id"], domain):
            raise HTTPException(status_code=403, detail="预览域与项目不匹配")
        session = access.consume_ticket(ticket, version_id)
        if not session:
            return expired_response()
        if session[1] != version["project_id"]:
            raise HTTPException(status_code=403, detail="预览域与项目不匹配")
        # A cross-site iframe cannot send a SameSite=Strict cookie. A scoped
        # session path also authorizes relative Vite assets on the same origin.
        response = RedirectResponse(f"/s/{session[0]}/v/{version_id}/", status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/s/{session_token}/v/{version_id}/{name:path}")
    def static_file(session_token: str, version_id: str, name: str, request: Request):
        try:
            version, _ = authorize(request, version_id, session_token)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            return expired_response()
        root = (settings.data_dir / "artifacts" / version["project_id"] / version["run_id"] / "dist").resolve()
        target = (root / (name or "index.html")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
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
        if target.name == "index.html":
            html = target.read_text(encoding="utf-8").replace('="/assets/', '="./assets/')
            return HTMLResponse(html, headers=headers)
        return FileResponse(target, headers=headers)

    return app


app = create_preview_app() if Settings().app_env != "azure_demo" else None
