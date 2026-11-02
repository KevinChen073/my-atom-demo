from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.invite_auth import InviteAuth
from backend.model import ModelGateway
from backend.settings import Settings
import backend.model as model_module


CODE_A = "invite-test-a-very-long-random-code-2026"
CODE_B = "invite-test-b-another-long-random-code-2026"
SERVER_KEY = "server-key-never-return-this-value"


def _app(tmp_path: Path, monkeypatch, *, server_key: str = SERVER_KEY):
    monkeypatch.setattr(Settings, "validate_azure_demo", lambda self: None)
    settings = Settings(data_dir=tmp_path, app_env="azure_demo", model_api_key=server_key,
                        workbench_origin="https://app.example.com",
                        invite_code=CODE_A)
    app = create_app(settings)
    app.state.workflow.enqueue = lambda _run_id: None
    return app


def test_invitation_is_the_only_platform_key_grant_and_recovers_projects(tmp_path: Path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app, base_url="https://app.example.com") as visitor, \
         TestClient(app, base_url="https://app.example.com") as device_two, \
         TestClient(app, base_url="https://app.example.com") as other:
        assert visitor.get("/api/auth/session").json() == {"invited": False, "platform_model_available": False, "invite_required": True}
        assert visitor.get("/api/projects").json()["projects"] == []
        assert visitor.post("/api/projects", json={"title": "访客项目"}).status_code == 401
        assert visitor.get("/preview/open/unknown?ticket=fake").status_code == 401
        assert visitor.get("/api/versions/unknown").status_code == 401
        assert visitor.post("/api/auth/invite", json={"code": "incorrect-invitation-code-long-enough"}).status_code == 401
        assert visitor.post("/api/auth/invite", json={"code": "错误邀请码"}).status_code == 401
        assert visitor.post("/api/auth/invite", json={"code": "x" * 257}).status_code == 422
        login = visitor.post("/api/auth/invite", json={"code": CODE_A})
        assert login.status_code == 200
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "secure" in login.headers["set-cookie"].lower()
        assert CODE_A not in login.headers["set-cookie"]
        assert SERVER_KEY not in login.text
        assert visitor.get("/api/projects").json()["projects"] == []
        invited_project = visitor.post("/api/projects", json={"title": "测试项目"}).json()
        response = visitor.post(f"/api/projects/{invited_project['id']}/runs", json={"request_text": "Please create a tiny task application"})
        assert response.status_code == 201
        run_id = response.json()["run"]["id"]
        assert app.state.store.operation_get(run_id, "platform_model_access")["invite_hash"] == InviteAuth.digest(CODE_A)
        assert device_two.post("/api/auth/invite", json={"code": CODE_A}).status_code == 200
        assert [item["id"] for item in device_two.get("/api/projects").json()["projects"]] == [invited_project["id"]]
        assert device_two.get(f"/api/projects/{invited_project['id']}").status_code == 200
        assert other.post("/api/auth/invite", json={"code": CODE_B}).status_code == 401
        assert other.get(f"/api/projects/{invited_project['id']}").status_code == 401
        assert other.get(f"/api/runs/{run_id}").status_code == 401
        assert visitor.post("/api/auth/logout").status_code == 200
        assert visitor.get(f"/api/projects/{invited_project['id']}").status_code == 401
        assert visitor.get(f"/api/runs/{run_id}").status_code == 401
        assert visitor.get("/api/projects").json()["projects"] == []
    raw = (tmp_path / "myatom.sqlite3").read_bytes()
    assert CODE_A.encode() not in raw and SERVER_KEY.encode() not in raw


def test_only_invited_visitor_can_bring_own_key(tmp_path: Path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    config = {"provider": "deepseek", "api_key": "visitor-private-key", "base_url": "https://api.deepseek.com",
              "model_name": "deepseek-chat"}
    with TestClient(app, base_url="https://app.example.com") as visitor:
        assert visitor.post("/api/projects", json={"title": "个人项目"}).status_code == 401
        assert visitor.post("/api/model/test", headers={"X-Myatom-Model-Config": json.dumps(config)}).status_code == 401
        assert visitor.post("/api/auth/invite", json={"code": CODE_A}).status_code == 200
        project = visitor.post("/api/projects", json={"title": "个人项目"}).json()
        run = visitor.post(f"/api/projects/{project['id']}/runs", json={"request_text": "Please create a tiny task application"},
                           headers={"X-Myatom-Model-Config": json.dumps(config)})
        assert run.status_code == 201
        assert app.state.workflow.model.has_run_credentials(run.json()["run"]["id"])
    assert b"visitor-private-key" not in (tmp_path / "myatom.sqlite3").read_bytes()


def test_invited_run_requires_own_key_until_platform_secret_is_configured(tmp_path: Path, monkeypatch):
    app = _app(tmp_path, monkeypatch, server_key="")
    with TestClient(app, base_url="https://app.example.com") as client:
        assert client.post("/api/auth/invite", json={"code": CODE_A}).json()["platform_model_available"] is False
        project = client.post("/api/projects", json={"title": "测试项目"}).json()
        url = f"/api/projects/{project['id']}/runs"
        payload = {"request_text": "Please create a small application"}
        denied = client.post(url, json=payload)
        assert denied.status_code == 403 and "平台测试 Key 尚未配置" in denied.json()["detail"]
        credentials = {"provider": "deepseek", "api_key": "private-test-key", "base_url": "https://api.deepseek.com",
                       "model_name": "deepseek-chat"}
        assert client.post(url, json=payload, headers={"X-Myatom-Model-Config": json.dumps(credentials)}).status_code == 201


def test_preview_ticket_and_session_stay_with_invitation_space(tmp_path: Path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app, base_url="https://app.example.com") as alpha, \
         TestClient(app, base_url="https://app.example.com") as beta:
        assert alpha.post("/api/auth/invite", json={"code": CODE_A}).status_code == 200
        assert beta.post("/api/auth/invite", json={"code": CODE_B}).status_code == 401
        project = alpha.post("/api/projects", json={"title": "A project"}).json()
        run = alpha.post(f"/api/projects/{project['id']}/runs",
                         json={"request_text": "Please create a small application"}).json()["run"]
        content = "<html><head></head><body>ok</body></html>"
        data = content.encode()
        entry = {"path": "dist/index.html", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        version, _ = app.state.store.commit_version_with_files(project["id"], run["id"],
            {"template": "react-vite-v4", "files": [], "build_files": [entry], "build": {"ok": True}},
            [{**entry, "content": content, "utf8_bytes": len(data), "kind": "dist", "mime_type": "text/html"}])
        ticket_url = alpha.get(f"/api/versions/{version['id']}/preview").json()["url"]
        assert beta.get(ticket_url, follow_redirects=False).status_code == 401
        opened = alpha.get(ticket_url, follow_redirects=False)
        assert opened.status_code == 303
        assert beta.get(opened.headers["location"]).status_code == 401
        assert alpha.get(opened.headers["location"]).status_code == 200


def test_azure_model_gateway_never_falls_back_to_ungranted_server_key(tmp_path: Path):
    from backend.store import Store
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("owner", "test")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    settings = Settings(data_dir=tmp_path, app_env="azure_demo", model_api_key=SERVER_KEY,
                        invite_code=CODE_A)
    gateway = ModelGateway(settings, store)
    with pytest.raises(RuntimeError, match="邀请码"):
        gateway.generate(run["id"], "plan", "key", "system", "user")
    gateway.configure_platform_run(run["id"], InviteAuth.digest(CODE_A))
    assert store.operation_get(run["id"], "platform_model_access")
    store.cache_set(run["id"], "plan", "cached", {"ok": True})
    revoked = ModelGateway(Settings(data_dir=tmp_path, app_env="azure_demo", model_api_key=SERVER_KEY), store)
    with pytest.raises(RuntimeError, match="邀请码"):
        revoked.generate(run["id"], "plan", "cached", "system", "user")


def test_invitation_daily_call_quota_blocks_next_model_attempt(tmp_path: Path):
    from backend.store import Store
    store = Store(tmp_path / "myatom.sqlite3")
    code_hash = InviteAuth.digest(CODE_A)
    project = store.create_project(InviteAuth.owner(code_hash), "test")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    gateway = ModelGateway(Settings(data_dir=tmp_path, app_env="azure_demo", model_api_key=SERVER_KEY,
        invite_code=CODE_A,
        invite_daily_model_calls=1), store)
    gateway.configure_platform_run(run["id"], code_hash)
    gateway.check_platform_quota(code_hash)
    store.record_model_attempt(run["id"], "plan")
    with pytest.raises(RuntimeError, match="今日平台测试额度已用完"):
        gateway.check_platform_quota(code_hash)


def test_only_invited_run_reaches_server_model_key(tmp_path: Path, monkeypatch):
    from backend.store import Store
    seen_keys = []
    seen_calls = []

    class FakeClient:
        def __init__(self, *, api_key, base_url, timeout):
            seen_keys.append(api_key)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **_options):
            seen_calls.append(True)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop")],
                                   usage=SimpleNamespace(total_tokens=3, prompt_tokens=1, completion_tokens=2))

    monkeypatch.setattr(model_module, "OpenAI", FakeClient)
    store = Store(tmp_path / "myatom.sqlite3")
    code_hash = InviteAuth.digest(CODE_A)
    project = store.create_project(InviteAuth.owner(code_hash), "test")
    ungranted, _ = store.create_run(project["id"], "make a small app", "one")
    gateway = ModelGateway(Settings(data_dir=tmp_path, app_env="azure_demo", model_api_key=SERVER_KEY,
        invite_code=CODE_A), store)
    with pytest.raises(RuntimeError, match="邀请码"):
        gateway.generate(ungranted["id"], "plan", "one", "system", "user")
    assert seen_calls == []
    gateway.configure_platform_run(ungranted["id"], code_hash)
    assert gateway.generate(ungranted["id"], "plan", "one", "system", "user") == {"ok": True}
    assert seen_keys == [SERVER_KEY]
    assert seen_calls == [True]


def test_invalid_session_and_rate_limit():
    auth = InviteAuth(CODE_A)
    token = auth.issue(InviteAuth.digest(CODE_A))
    assert auth.verify(token) == InviteAuth.digest(CODE_A)
    assert InviteAuth(CODE_B).verify(token) is None
    assert auth.verify(token[:-1] + ("0" if token[-1] != "0" else "1")) is None
    for _ in range(5):
        assert auth.authenticate("incorrect-invitation-code-long-enough", "198.51.100.1") is None
    assert auth.authenticate(CODE_A, "198.51.100.1") is None
    assert auth.authenticate(CODE_A, "198.51.100.2") == InviteAuth.digest(CODE_A)


def test_short_single_invitation_code_is_accepted():
    auth = InviteAuth("demo1234")
    owner = auth.authenticate("demo1234", "198.51.100.3")
    assert owner == InviteAuth.digest("demo1234")
    assert auth.verify(auth.issue(owner)) == owner
    assert auth.authenticate("wrong", "198.51.100.4") is None
