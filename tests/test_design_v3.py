"""V3 shell contracts that can be checked without a model call."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_project_views_support_direct_open_and_reject_unknown_view(tmp_path: Path):
    class NoCallModel:
        def generate(self, *args, **kwargs):
            raise AssertionError("Opening a route must not call the model")

    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    with TestClient(create_app(settings, model=NoCallModel())) as client:
        home = client.get("/")
        assert home.status_code == 200
        for suffix in ("", "/overview", "/docs", "/tests", "/publish"):
            page = client.get(f"/projects/not-a-real-project{suffix}")
            assert page.status_code == 200
            assert page.text == home.text
        assert client.get("/projects/not-a-real-project/unknown").status_code == 404


def test_v3_color_and_layout_tokens_match_design_source():
    source = json.loads((ROOT / "design/v3/tokens.json").read_text(encoding="utf-8"))
    css = (ROOT / "web/src/design-tokens.css").read_text(encoding="utf-8")
    declarations = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", css))
    for name, value in source["color"].items():
        token = "--color-" + re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
        assert declarations[token].upper() == value.upper()
    for name, value in source["layoutPx"].items():
        token = {"chatWithPreview": "--layout-chat", "previewMin": "--layout-preview-min", "contentMax": "--layout-content-max"}.get(name, f"--layout-{name}")
        assert declarations[token] == f"{value}px"
