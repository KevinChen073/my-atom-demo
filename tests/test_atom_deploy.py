"""Atoms branch: token gate, one-process static generation, and preview routing."""

from __future__ import annotations

import time
import socket
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.atom_auth import valid_session
from backend.atom_serve import AtomHostDispatcher
from backend.atom_static import inspect_generated
from backend.api import create_app
from backend.settings import Settings


TOKEN = "test-token-with-at-least-32-characters-123456"
FILES = {
    "index.html": '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><div id="root"><button id="add">加一</button><output id="count">0</output></div><link rel="stylesheet" href="./style.css"><script src="./app.js"></script></html>',
    "style.css": "body { font-family: sans-serif; padding: 2rem; }",
    "app.js": "const count = document.getElementById('count'); let value = Number(localStorage.getItem('count') || '0'); count.textContent = String(value); document.getElementById('add').addEventListener('click', () => { value += 1; localStorage.setItem('count', String(value)); count.textContent = String(value); });",
    "readme.md": "# 计数器\n数据在项目预览域的 localStorage 中。",
}


class StaticModel:
    def check_limits(self, _: str) -> None:
        pass

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "clarify":
            return {"summary": "制作计数器", "questions": [{"text": "初始值是多少？", "default": "0", "required": True}]}
        if node == "clarity_gate":
            return {"complete": True, "missing": []}
        if node == "plan":
            return {"title": "计数器", "pages": [{"name": "首页", "purpose": "计数"}],
                    "features": ["点击加一"], "data_model": ["localStorage 保存当前计数"],
                    "acceptance": ["刷新后读回计数"], "tasks": ["生成静态页面"], "limitations": []}
        if node == "code_loop":
            assert "无构建步骤" in system
            return {"files": FILES}
        raise AssertionError(node)


def wait_for(client: TestClient, run_id: str, wanted: str) -> dict:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] == wanted:
            return run
        assert run["status"] not in {"failed", "cancelled", "budget_exceeded"}, run
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {wanted}")


def login(client: TestClient) -> None:
    assert client.get("/").status_code == 303
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", data={"token": "wrong"}).status_code == 401
    response = client.post("/api/auth/login", data={"token": TOKEN})
    assert response.status_code == 303
    assert client.get("/").status_code == 200


def generate(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/projects", json={"title": "Atom 计数器"}).json()
    response = client.post(f"/api/projects/{project['id']}/runs",
                           json={"request_text": "做一个点击加一并刷新后保留结果的计数器网页"})
    assert response.status_code == 201, response.text
    run_id = response.json()["run"]["id"]
    card = wait_for(client, run_id, "awaiting_clarification")
    response = client.post(f"/api/runs/{run_id}/decisions", json={
        "card_id": card["card_id"], "spec_version": card["spec_version"],
        "action": "confirm_clarification", "answers": {"q1": "0"}})
    assert response.status_code == 202, response.text
    card = wait_for(client, run_id, "awaiting_plan")
    assert card["plan"]["template"] == "Static HTML + CSS + JavaScript"
    response = client.post(f"/api/runs/{run_id}/decisions", json={
        "card_id": card["card_id"], "spec_version": card["spec_version"], "action": "approve_plan"})
    assert response.status_code == 202, response.text
    wait_for(client, run_id, "completed")
    version = client.get(f"/api/projects/{project['id']}").json()["versions"][0]
    assert version["manifest"]["build"]["level"] == "static_files_only"
    assert version["manifest"]["template"] == "static-html-css-js-v1"
    assert client.get(f"/api/versions/{version['id']}/files/app.js").text == FILES["app.js"]
    assert client.get(f"/api/runs/{run_id}/build-log").status_code == 200
    return project["id"], version["id"]


def test_atom_token_and_static_pipeline(tmp_path: Path, monkeypatch):
    settings = Settings(data_dir=tmp_path, app_env="atom", atom_access_token=TOKEN,
                        workbench_origin="https://testserver")
    app = create_app(settings, model=StaticModel())
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
        login(client)
        monkeypatch.setattr("backend.runner.subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess called")))
        _, version_id = generate(client)
        assert client.get(f"/api/versions/{version_id}/preview").status_code == 503
        assert client.get("/api/ops/exceptions").status_code == 200
        assert client.post("/api/auth/logout").status_code == 303
        assert client.get("/api/ops/exceptions").status_code == 401


def test_atom_isolated_preview_uses_same_process(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, app_env="atom", atom_access_token=TOKEN,
                        workbench_origin="https://app.example.test",
                        atom_preview_domain="preview.example.test")
    dispatcher = AtomHostDispatcher(settings)
    dispatcher.workbench.state.workflow.model = StaticModel()
    with TestClient(dispatcher, base_url="https://app.example.test", follow_redirects=False) as client:
        login(client)
        _, version_id = generate(client)
        issued = client.get(f"/api/versions/{version_id}/preview")
        assert issued.status_code == 200, issued.text
        url = issued.json()["url"]
        assert url.startswith("https://p-") and ".preview.example.test/open/" in url
        opened = client.get(url)
        assert opened.status_code == 303
        page = client.get(url.split("/open/")[0] + opened.headers["location"])
        assert page.status_code == 200 and "./app.js" in page.text
        assert "connect-src 'none'" in page.headers["content-security-policy"]


def test_static_source_rejects_network_and_inline_script():
    assert inspect_generated(FILES) == []
    assert any(item["code"] == "unsafe_capability" for item in inspect_generated({**FILES, "app.js": "fetch('/api/projects')"}))
    assert inspect_generated({**FILES, "index.html": FILES["index.html"].replace("<script src=\"./app.js\"></script>", "<script>alert(1)</script>")})
    assert not valid_session("0." + "x" * 64, TOKEN, now=100000)


def test_atom_browser_login_and_integrated_ops(tmp_path: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    executable = next((path for path in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ) if path.is_file()), None)
    if not executable:
        pytest.skip("Chromium browser unavailable")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    settings = Settings(data_dir=tmp_path, app_env="atom", atom_access_token=TOKEN,
                        workbench_origin=f"http://127.0.0.1:{port}")
    server = uvicorn.Server(uvicorn.Config(create_app(settings, model=StaticModel()),
                                           host="127.0.0.1", port=port, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with playwright.sync_playwright() as engine:
            browser = engine.chromium.launch(executable_path=str(executable), headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(f"http://127.0.0.1:{port}/")
                assert page.url.endswith("/login")
                page.get_by_label("访问 Token").fill(TOKEN)
                page.get_by_role("button", name="登录").click()
                page.wait_for_url(f"http://127.0.0.1:{port}/")
                page.goto(f"http://127.0.0.1:{port}/ops/")
                page.get_by_role("heading", name="异常中心").wait_for(state="visible")
                page.get_by_text("暂无异常记录").wait_for(state="visible")
                page.get_by_role("button", name="退出运维").click()
                page.wait_for_url(f"http://127.0.0.1:{port}/login")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
