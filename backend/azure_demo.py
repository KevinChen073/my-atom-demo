"""Single-origin host router for the explicitly trusted Azure demo."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .api import create_app
from .settings import Settings


def create_azure_demo_app(settings: Settings | None = None, model: Any = None):
    settings = settings or Settings()
    if settings.app_env != "azure_demo":
        raise RuntimeError("此入口仅用于 APP_ENV=azure_demo")
    settings.validate_azure_demo()
    api = create_app(settings, model=model)
    workbench_host = urlparse(settings.workbench_origin).hostname

    async def dispatch(scope, receive, send):
        if scope["type"] == "lifespan":
            await api(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        host = next((value.decode("ascii", "ignore") for key, value in scope.get("headers", []) if key.lower() == b"host"), "")
        host = host.lower().split(":", 1)[0]
        if host == workbench_host or (host in {"127.0.0.1", "localhost"} and scope["path"] == "/api/health"):
            await api(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 421, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
            await send({"type": "http.response.body", "body": "域名未配置".encode("utf-8")})

    return dispatch


app = create_azure_demo_app() if Settings().app_env == "azure_demo" else None
