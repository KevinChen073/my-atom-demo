"""User model credentials stay in memory; Azure never returns the env key."""

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.model import ModelGateway
from backend.model_credentials import validate_model_credentials
from backend.settings import Settings
from backend.store import Store
import backend.model as model_module


def test_run_model_key_is_not_written_to_sqlite(tmp_path: Path):
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("owner", "key check")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    credentials = validate_model_credentials({"provider": "deepseek", "api_key": "test-secret-should-not-persist",
        "base_url": "https://api.deepseek.com", "model_name": "deepseek-chat"})
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key=""), store)
    gateway.configure_run(run["id"], credentials)
    assert gateway.has_run_credentials(run["id"])
    assert store.operation_get(run["id"], "user_model_config")["needs_key"] is True
    assert b"test-secret-should-not-persist" not in (tmp_path / "myatom.sqlite3").read_bytes()
    assert not ModelGateway(Settings(data_dir=tmp_path, model_api_key=""), Store(tmp_path / "myatom.sqlite3")).has_run_credentials(run["id"])


def test_model_defaults_never_expose_environment_key(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="local-env-secret"))
    with TestClient(app, client=("127.0.0.1", 10001), base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/model/defaults").json()["api_key"] == ""
    with TestClient(app, client=("127.0.0.1", 10001), base_url="http://localhost:8000") as client:
        assert client.get("/api/model/defaults").json()["api_key"] == ""
    with TestClient(app, client=("192.0.2.10", 10001), base_url="http://myatom.example") as client:
        assert client.get("/api/model/defaults").json()["api_key"] == ""


def test_local_run_requires_user_key_even_when_environment_key_exists(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="local-env-secret"))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "key check"}).json()
        response = client.post(f"/api/projects/{project['id']}/runs", json={"request_text": "Please make a small task app"})
        assert response.status_code == 403
        assert "自己的 API Key" in response.json()["detail"]
        assert client.get(f"/api/projects/{project['id']}").json()["runs"] == []


def test_local_gateway_does_not_fall_back_to_environment_key(tmp_path: Path):
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("owner", "key check")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="local-env-secret"), store)
    with pytest.raises(RuntimeError, match="自己的 API Key"):
        gateway.generate(run["id"], "plan", "one", "system", "user")


def test_user_key_follows_run_request_without_entering_platform_records(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key=""))
    app.state.workflow.enqueue = lambda _run_id: None
    config = {"provider": "deepseek", "api_key": "test-user-key-private", "base_url": "https://api.deepseek.com",
              "model_name": "deepseek-chat"}
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "user key"}).json()
        response = client.post(f"/api/projects/{project['id']}/runs", json={"request_text": "Please make a small task app"},
                               headers={"X-Myatom-Model-Config": json.dumps(config)})
        assert response.status_code == 201
        run_id = response.json()["run"]["id"]
        assert app.state.workflow.model.has_run_credentials(run_id)
        assert client.get(f"/api/runs/{run_id}").json()["needs_model_key"] is False
    assert b"test-user-key-private" not in (tmp_path / "myatom.sqlite3").read_bytes()


def test_openai_compatible_run_uses_user_config_without_deepseek_options(tmp_path: Path, monkeypatch):
    calls = []

    class Client:
        def __init__(self, *, api_key, base_url, timeout):
            self.api_key = api_key
            self.base_url = base_url
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **options):
            calls.append((self.api_key, self.base_url, options))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop")],
                                   usage=SimpleNamespace(total_tokens=2, prompt_tokens=1, completion_tokens=1))

    monkeypatch.setattr(model_module, "OpenAI", Client)
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("owner", "model")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key=""), store)
    gateway.configure_run(run["id"], validate_model_credentials({"provider": "openai_compatible",
        "api_key": "test-openai-key", "base_url": "https://api.openai.com/v1", "model_name": "gpt-4.1-mini"}))
    assert gateway.generate(run["id"], "plan", "one", "system", "user") == {"ok": True}
    key, url, options = calls[-1]
    assert (key, url, options["model"]) == ("test-openai-key", "https://api.openai.com/v1", "gpt-4.1-mini")
    assert "extra_body" not in options and "reasoning_effort" not in options
