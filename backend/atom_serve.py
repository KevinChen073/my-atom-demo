"""One foreground Python process for the Atoms branch."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import uvicorn

from .settings import Settings


class AtomHostDispatcher:
    def __init__(self, settings: Settings):
        from .api import create_app

        self.workbench = create_app(settings)
        self.preview = None
        self.preview_host_pattern = None
        if settings.atom_preview_domain:
            if not re.fullmatch(r"[a-z0-9.-]+", settings.atom_preview_domain):
                raise RuntimeError("ATOM_PREVIEW_DOMAIN 格式无效")
            from .preview import create_preview_app

            self.preview = create_preview_app(settings)
            self.preview_host_pattern = re.compile(
                rf"p-[0-9a-f]{{32}}\.{re.escape(settings.atom_preview_domain)}\Z"
            )
        origin_host = urlparse(settings.workbench_origin).hostname
        if not origin_host:
            raise RuntimeError("WORKBENCH_ORIGIN 必须是完整 URL")
        if urlparse(settings.workbench_origin).scheme != "https" and origin_host not in {"localhost", "127.0.0.1"}:
            raise RuntimeError("公开 Atoms 工作台必须使用 HTTPS")
        if settings.atom_preview_domain and settings.atom_preview_scheme != "https":
            raise RuntimeError("Atoms 项目预览必须使用 HTTPS")
        if self.preview_host_pattern and self.preview_host_pattern.fullmatch(origin_host):
            raise RuntimeError("工作台与项目预览不能使用同一 origin")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.workbench(scope, receive, send)
            return
        host = next((value.decode("latin-1").split(":", 1)[0].lower()
                     for name, value in scope.get("headers", []) if name == b"host"), "")
        target = self.preview if self.preview_host_pattern and self.preview_host_pattern.fullmatch(host) else self.workbench
        await target(scope, receive, send)


def main() -> None:
    settings = Settings()
    if settings.app_env != "atom":
        raise RuntimeError("请设置 APP_ENV=atom")
    app = AtomHostDispatcher(settings)
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")),
                access_log=False)


if __name__ == "__main__":
    main()
