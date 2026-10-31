"""Local browser-test server with deterministic fake model; never calls the paid API."""

from pathlib import Path

import uvicorn

from backend.api import create_app
from backend.settings import Settings
from tests.test_mvp1 import FakeModel


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    settings = Settings(data_dir=root / "data" / "ui-tc", model_api_key="test-only")
    uvicorn.run(create_app(settings, model=FakeModel()), host="127.0.0.1", port=8765, log_level="warning")
