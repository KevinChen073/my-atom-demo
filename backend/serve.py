"""Run the trusted local workbench with its same-origin preview."""

from __future__ import annotations

import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings()
    if settings.app_env != "local":
        raise RuntimeError("同宿主预览仅用于 APP_ENV=local")
    uvicorn.run("backend.api:app", host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
