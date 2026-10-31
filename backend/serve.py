"""Run the trusted local workbench and its separate-origin preview together."""

from __future__ import annotations

import threading
import time

import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings()
    if settings.app_env != "local":
        raise RuntimeError("同宿主预览仅用于 APP_ENV=local")
    preview = uvicorn.Server(uvicorn.Config("backend.preview:app", host="127.0.0.1", port=settings.preview_port, access_log=False, log_level="warning"))
    thread = threading.Thread(target=preview.run, name="myatom-preview", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not preview.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not preview.started:
        raise RuntimeError("本地预览服务未启动，请检查端口")
    try:
        uvicorn.run("backend.api:app", host="127.0.0.1", port=8000, access_log=False)
    finally:
        preview.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
