"""The container candidate must not expose the local build workflow online."""

from fastapi.testclient import TestClient
import pytest

from backend.api import create_app
from backend.settings import Settings


def test_container_smoke_exposes_only_health(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, app_env="container_smoke", model_api_key=""))
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"ok": True, "model_configured": False, "app_env": "container_smoke"}
        assert client.get("/").status_code == 503
        assert client.get("/api/projects").status_code == 503
        assert client.post("/api/projects", json={"title": "不可创建"}).status_code == 503


def test_production_mode_fails_closed_without_adapters(tmp_path):
    with pytest.raises(RuntimeError, match="不支持的运行环境"):
        create_app(Settings(data_dir=tmp_path, app_env="production", model_api_key=""))
