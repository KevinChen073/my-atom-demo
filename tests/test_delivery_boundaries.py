"""The current clarification, diagnosis, and version contract."""

from __future__ import annotations

import time
import hashlib
import socket
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from backend.api import create_app, owner_hash
from backend.preview import create_preview_app
from backend.runner import LocalRunner, UnsafeSource
from backend.settings import Settings
from backend.store import Store
from backend.workflow import classify_build_failure, normalize_clarification
from tests.test_mvp1 import FakeModel, wait_status


APPROVED_PLAN = '{"title":"计数器","features":["点击加一"],"acceptance":["点击后数字增加"]}'


class ThreeCardModel(FakeModel):
    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "clarify":
            number = int(cache_key[4])
            return {"summary": "待确认", "questions": [{"text": f"第 {number} 个关键选择？", "default": "同意", "required": True}]}
        if node == "clarity_gate":
            return {"complete": False, "missing": ["仍缺关键约束"]}
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_clarification_requires_one_to_three_questions():
    for count in (0, 4):
        with pytest.raises(ValueError):
            normalize_clarification({"questions": [{"text": f"Choice {i}"} for i in range(count)]})


def test_clarification_stops_after_three_distinct_confirmed_cards(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=ThreeCardModel())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "澄清轮次"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击计分的小游戏"}).json()["run"]["id"]
        questions = []
        for number in range(1, 4):
            card = wait_status(client, run_id, "awaiting_clarification")
            assert len(card["card"]["payload"]["questions"]) == 1
            question = card["card"]["payload"]["questions"][0]["text"]
            assert question not in questions
            questions.append(question)
            answer = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": card["card_id"],
                "spec_version": card["spec_version"], "action": "confirm_clarification", "answers": {"q1": "同意"}})
            assert answer.status_code == 202
            if number < 3:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    current = client.get(f"/api/runs/{run_id}").json()
                    if current["status"] == "awaiting_clarification" and current["card_id"] != card["card_id"]:
                        break
                    time.sleep(0.1)
                assert current["card_id"] != card["card_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = client.get(f"/api/runs/{run_id}").json()
            if current["status"] == "failed":
                break
            time.sleep(0.1)
        assert current["status"] == "failed"
        assert "仍缺关键约束" in current["error"]
        assert client.get(f"/api/projects/{project_id}").json()["versions"] == []


def test_diagnosis_only_retries_source_errors():
    install = classify_build_failure({"ok": False, "steps": [{"command": "npm ci --ignore-scripts", "exit_code": 1}],
        "diagnostics": "network unavailable"}, "run-1")
    assert install["category"] == "dependency_install" and install["repairable"] is False
    assert install["command"].startswith("npm ci") and install["evidence_ref"].endswith("/build-log")
    source = classify_build_failure({"ok": False, "steps": [{"command": "npm run build", "exit_code": 2}],
        "diagnostics": "error TS1005: expected"}, "run-1")
    assert source["category"] == "source_compile" and source["repairable"] is True
    unknown = classify_build_failure({"ok": False, "steps": [{"command": "npm run build", "exit_code": 1}],
        "diagnostics": "permission denied"}, "run-1")
    assert unknown["category"] == "build_unknown" and unknown["repairable"] is False


def test_generated_layout_rejects_ui_storage_and_missing_hook(tmp_path: Path):
    runner = LocalRunner(Settings(data_dir=tmp_path), None)
    runner.prepare = lambda *_: (_ for _ in ()).throw(RuntimeError("validation passed"))
    files = {
        "src/App.tsx": "import './app.css'\nexport default function App() { return <main /> }",
        "src/app.css": "body { margin: 0 }",
        "src/hooks/useAppState.ts": "export function useAppState() { return null }",
        "readme.md": "# Test application",
    }
    with pytest.raises(UnsafeSource, match="useAppState"):
        runner.write_generated("project", "run", files, 0)
    files["src/App.tsx"] = "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { useAppState(); return <main>数据保存在 localStorage；刷新后恢复。</main> }"
    with pytest.raises(RuntimeError, match="validation passed"):
        runner.write_generated("project", "run", files, 0)
    files["src/App.tsx"] = "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { useAppState(); localStorage.setItem('x', 'y'); return <main /> }"
    with pytest.raises(UnsafeSource, match="src/hooks"):
        runner.write_generated("project", "run", files, 0)


def test_five_snapshots_and_persistent_pointer(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    store = Store(settings.app_db)
    project = store.create_project(owner_hash("owner"), "版本上限")
    ids = []
    for number in range(6):
        run, _ = store.create_run(project["id"], f"需求 {number}", f"run-{number}")
        store.update_run(run["id"], status="completed", phase="Done", plan_json=APPROVED_PLAN)
        version, _ = store.commit_version(project["id"], run["id"], {"files": [], "build": {"ok": True}})
        ids.append(version["id"])
    versions = store.get_project(project["id"], owner_hash("owner"))["versions"]
    assert len(versions) == 5
    assert ids[0] not in {version["id"] for version in versions}
    assert store.get_project(project["id"], owner_hash("owner"))["active_version_id"] == ids[-1]
    store.activate_version(project["id"], ids[2])
    assert Store(settings.app_db).get_project(project["id"], owner_hash("owner"))["active_version_id"] == ids[2]
    assert len(Store(settings.app_db).get_project(project["id"], owner_hash("owner"))["versions"]) == 5


def test_failed_preview_candidate_keeps_last_good_version(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=FakeModel())
    app.state.workflow.runner.probe_candidate = lambda *_: {"ok": False, "reason": "probe failed", "checked_assets": 0}
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "保留旧版"}).json()["id"]
        old_run, _ = app.state.store.create_run(project_id, "原有可用的计数器应用", "old-run")
        app.state.store.update_run(old_run["id"], status="completed", phase="Done", plan_json=APPROVED_PLAN)
        files = FakeModel().generate(old_run["id"], "code_loop", "seed", "", "")["files"]
        entries = []
        rows = []
        for name, content in {**files, "dist/index.html": "<main>old version</main>"}.items():
            data = content.encode("utf-8")
            entry = {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            rows.append({"path": name, "content": content, "utf8_bytes": len(data), "sha256": entry["sha256"],
                         "kind": "dist" if name.startswith("dist/") else "source", "mime_type": "text/plain"})
            entries.append(entry)
        old_version, _ = app.state.store.commit_version_with_files(project_id, old_run["id"],
            {"files": [e for e in entries if not e["path"].startswith("dist/")],
             "build_files": [e for e in entries if e["path"].startswith("dist/")], "build": {"ok": True}}, rows)
        response = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的新计数器应用"})
        assert response.status_code == 201
        run_id = response.json()["run"]["id"]
        clarify = wait_status(client, run_id, "awaiting_clarification")
        assert client.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarify["card_id"],
            "spec_version": clarify["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}}).status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert client.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
            "spec_version": plan["spec_version"], "action": "approve_plan"}).status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] == "failed":
                break
            time.sleep(0.15)
        assert run["status"] == "failed"
        assert "probe failed" in run["error"]
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["active_version_id"] == old_version["id"]
        assert [version["id"] for version in project["versions"]] == [old_version["id"]]
        assert not (tmp_path / "artifacts" / project_id / run_id).exists()


def test_browser_preview_origin_is_stable_within_project_and_isolated_across_projects(tmp_path: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    executable = next((p for p in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ) if p.is_file()), None)
    if not executable:
        pytest.skip("Chromium browser unavailable")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    parent_listener = socket.socket()
    parent_listener.bind(("127.0.0.1", 0))
    parent_listener.listen(128)
    parent_port = parent_listener.getsockname()[1]
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", preview_port=port,
                        workbench_origin=f"http://127.0.0.1:{parent_port}")
    store = Store(settings.app_db)
    project_a = store.create_project(owner_hash("browser"), "A")
    project_b = store.create_project(owner_hash("browser"), "B")

    def seed(project_id: str, number: int) -> str:
        run, _ = store.create_run(project_id, f"版本 {number} 的预览应用", f"{project_id}-{number}")
        store.update_run(run["id"], status="completed", phase="Done", plan_json=APPROVED_PLAN)
        contents = {"src/App.tsx": "export default function App(){return null}",
                    "dist/index.html": '<div id="root"></div><script src="./assets/app.js"></script>',
                    "dist/assets/app.js": "document.getElementById('root').textContent = localStorage.getItem('demo') || 'empty'"}
        rows, source_entries, build_entries = [], [], []
        for name, content in contents.items():
            data = content.encode("utf-8")
            entry = {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            rows.append({"path": name, "content": content, "utf8_bytes": len(data), "sha256": entry["sha256"],
                         "kind": "dist" if name.startswith("dist/") else "source", "mime_type": "text/html" if name.endswith(".html") else "application/javascript" if name.endswith(".js") else "text/plain"})
            (build_entries if name.startswith("dist/") else source_entries).append(entry)
        version, _ = store.commit_version_with_files(project_id, run["id"],
            {"files": source_entries, "build_files": build_entries, "build": {"ok": True}}, rows)
        return version["id"]

    first, second, other = seed(project_a["id"], 1), seed(project_a["id"], 2), seed(project_b["id"], 1)
    server = uvicorn.Server(uvicorn.Config(create_preview_app(settings), host="127.0.0.1", port=port, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    parent_app = FastAPI()
    parent_app.add_api_route("/iframe-fixture", lambda: HTMLResponse("<main>workbench</main>"))
    parent_server = uvicorn.Server(uvicorn.Config(parent_app, host="127.0.0.1", port=parent_port, log_level="error", lifespan="on"))
    parent_thread = threading.Thread(target=parent_server.run, kwargs={"sockets": [parent_listener]}, daemon=True)
    thread.start()
    parent_thread.start()
    try:
        deadline = time.monotonic() + 10
        while (not server.started or not parent_server.started) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started and parent_server.started
        with TestClient(create_app(settings, model=FakeModel())) as main:
            main.cookies.set("myatom_guest", "browser")

            def ticket(version_id: str) -> str:
                response = main.get(f"/api/versions/{version_id}/preview")
                assert response.status_code == 200
                return response.json()["url"]

            with playwright.sync_playwright() as engine:
                browser = engine.chromium.launch(executable_path=str(executable), headless=True, args=["--no-proxy-server"])
                try:
                    page = browser.new_page()
                    page.goto(ticket(first))
                    assert page.locator("#root").inner_text() == "empty"
                    page.evaluate("localStorage.setItem('demo', 'kept')")
                    page.reload()
                    assert page.locator("#root").inner_text() == "kept"
                    page.goto(ticket(second))
                    assert page.locator("#root").inner_text() == "kept"
                    page.goto(ticket(other))
                    assert page.locator("#root").inner_text() == "empty"
                    # The workbench embeds the preview across sites. A
                    # top-level navigation alone misses SameSite cookie bugs.
                    iframe_context = browser.new_context()
                    try:
                        embedded = iframe_context.new_page()
                        embedded.goto(f"http://127.0.0.1:{parent_port}/iframe-fixture")
                        embedded.evaluate("url => { const frame = document.createElement('iframe'); frame.src = url; document.body.appendChild(frame) }", ticket(first))
                        frame = embedded.frame_locator("iframe")
                        assert frame.locator("#root").inner_text(timeout=5000) == "empty"
                        frame.locator("#root").evaluate("node => { localStorage.setItem('demo', 'embedded'); location.reload() }")
                        assert frame.locator("#root").inner_text(timeout=5000) == "embedded"
                    finally:
                        iframe_context.close()
                finally:
                    browser.close()
    finally:
        server.should_exit = True
        parent_server.should_exit = True
        thread.join(timeout=5)
        parent_thread.join(timeout=5)
        listener.close()
        parent_listener.close()


def test_browser_rollback_button_persists_current_version(tmp_path: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    executable = next((p for p in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ) if p.is_file()), None)
    if not executable:
        pytest.skip("Chromium browser unavailable")
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=FakeModel())
    project = app.state.store.create_project(owner_hash("browser"), "Rollback demo")
    ids = []
    for number in range(2):
        run, _ = app.state.store.create_run(project["id"], f"Version {number} counter application", f"version-{number}")
        app.state.store.update_run(run["id"], status="completed", phase="Done", plan_json=APPROVED_PLAN)
        version, _ = app.state.store.commit_version(project["id"], run["id"],
            {"files": [], "build": {"ok": True, "steps": []}, "template": "react-vite-v3", "preview": {"status": "checked"}})
        ids.append(version["id"])
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on"))
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
                context = browser.new_context(viewport={"width": 1280, "height": 720})
                base = f"http://127.0.0.1:{port}"
                context.add_cookies([{"name": "myatom_guest", "value": "browser", "url": base}])
                page = context.new_page()
                page.goto(f"{base}/projects/{project['id']}")
                picker = page.get_by_label("选择生成版本")
                picker.wait_for(state="visible")
                assert picker.input_value() == ids[1]
                picker.select_option(ids[0])
                page.get_by_role("button", name="设为当前版本").click()
                page.get_by_role("button", name="设为当前版本").wait_for(state="hidden")
                assert "当前" in picker.locator("option:checked").text_content()
                assert app.state.store.get_project(project["id"], owner_hash("browser"))["active_version_id"] == ids[0]
                page.reload()
                assert page.get_by_label("选择生成版本").input_value() == ids[0]
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
