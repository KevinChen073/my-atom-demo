"""Isolated local V3 browser fixture; deterministic model, no paid calls."""

from pathlib import Path
import threading
import time

import uvicorn

from backend.api import create_app
from backend.preview import create_preview_app
from backend.settings import Settings
from tests.test_mvp2_independent import TodoFakeModel


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    settings = Settings(
        data_dir=root / "data" / "ui-v3-tc-20261031",
        model_api_key="test-only",
        preview_port=8786,
        workbench_origin="http://127.0.0.1:8785",
    )
    preview = uvicorn.Server(uvicorn.Config(
        create_preview_app(settings), host="127.0.0.1", port=8786,
        access_log=False, log_level="warning",
    ))
    preview_thread = threading.Thread(target=preview.run, name="myatom-v3-preview", daemon=True)
    preview_thread.start()
    deadline = time.monotonic() + 10
    while not preview.started and preview_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not preview.started:
        raise RuntimeError("V3 preview test server did not start")
    try:
        uvicorn.run(create_app(settings, model=TodoFakeModel()), host="127.0.0.1", port=8785,
                    access_log=False, log_level="warning")
    finally:
        preview.should_exit = True
        preview_thread.join(timeout=5)
