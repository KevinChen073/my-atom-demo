"""Two local-origin browser-test servers with a deterministic fake model."""

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
    settings = Settings(data_dir=root / "data" / "ui-mvp2-tc", model_api_key="test-only", preview_port=8766,
                        workbench_origin="http://127.0.0.1:8765")
    preview = uvicorn.Server(uvicorn.Config(create_preview_app(settings), host="127.0.0.1", port=8766, access_log=False, log_level="warning"))
    preview_thread = threading.Thread(target=preview.run, name="myatom-test-preview", daemon=True)
    preview_thread.start()
    deadline = time.monotonic() + 10
    while not preview.started and preview_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not preview.started:
        raise RuntimeError("test preview server did not start")
    try:
        uvicorn.run(create_app(settings, model=TodoFakeModel()), host="127.0.0.1", port=8765, access_log=False, log_level="warning")
    finally:
        preview.should_exit = True
        preview_thread.join(timeout=5)
