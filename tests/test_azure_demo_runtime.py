from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import azure_demo
from backend.api import create_app
from backend.runner import LocalRunner
from backend.settings import Settings


def _settings(tmp_path: Path, **changes) -> Settings:
    values = dict(data_dir=tmp_path, app_env="azure_demo",
                  azure_sql_connection_string="Server=tcp:my-atom.database.windows.net,1433;Database=my-atom;Encrypt=yes;TrustServerCertificate=no",
                  workbench_origin="https://app.example.com",
                  trusted_demo=True)
    values.update(changes)
    return Settings(**values)


def test_azure_demo_accepts_local_container_data_without_mount(tmp_path: Path):
    _settings(tmp_path).validate_azure_demo()
    assert tmp_path.is_dir()


def test_container_smoke_ignores_staged_azure_sql_connection(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, app_env="container_smoke",
                        azure_sql_connection_string="Server=unreachable;Database=staged")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["app_env"] == "container_smoke"
        assert client.get("/").status_code == 503


def test_azure_demo_rejects_invalid_config(tmp_path: Path):
    with pytest.raises(RuntimeError, match="Azure SQL"):
        _settings(tmp_path, azure_sql_connection_string="").validate_azure_demo()
    with pytest.raises(RuntimeError, match="加密连接"):
        _settings(tmp_path, azure_sql_connection_string="Server=x;Database=y;Encrypt=no").validate_azure_demo()
    with pytest.raises(RuntimeError, match="仅配置 Azure SQL"):
        _settings(tmp_path, database_url="postgresql://test.invalid/myatom").validate_azure_demo()
    with pytest.raises(RuntimeError, match="HTTPS"):
        _settings(tmp_path, workbench_origin="http://app.example.com").validate_azure_demo()
    _settings(tmp_path, preview_base_domain="").validate_azure_demo()


def test_azure_host_dispatch_uses_workbench_origin_for_preview(tmp_path: Path, monkeypatch):
    api = FastAPI()

    @api.get("/probe")
    def api_probe():
        return {"surface": "api"}

    @api.get("/preview/probe")
    def preview_probe():
        return {"surface": "preview"}

    monkeypatch.setattr(azure_demo, "create_app", lambda settings, model=None: api)
    app = azure_demo.create_azure_demo_app(_settings(tmp_path))
    with TestClient(app, base_url="https://app.example.com") as client:
        assert client.get("/probe").json() == {"surface": "api"}
        assert client.get("/preview/probe").json() == {"surface": "preview"}
        assert client.get("/probe", headers={"Host": "unknown.example.net"}).status_code == 421


def test_trusted_demo_runner_uses_container_data_path(tmp_path: Path):
    settings = _settings(tmp_path)
    runner = LocalRunner(settings, None)
    target = runner.prepare(str(uuid4()), str(uuid4()))
    assert target.is_relative_to(tmp_path)
    assert (target / "package.json").is_file()
