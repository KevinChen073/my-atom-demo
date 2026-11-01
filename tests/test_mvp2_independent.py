"""Independent MVP2 API checks using local temporary data and no paid model calls."""

from __future__ import annotations

import json
import hashlib
import socket
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi.testclient import TestClient

from backend.api import create_app, owner_hash
from backend.settings import Settings
from backend.store import Store
from tests.test_shared_origin_preview import _version
from tests.test_mvp1 import FakeModel
from tests.test_mvp1 import wait_status


TODO_SCHEMA = {"name": "todos", "fields": [
    {"name": "title", "type": "text", "required": True},
    {"name": "completed", "type": "boolean", "required": True},
]}


class TodoFakeModel(FakeModel):
    """Deterministic localStorage app through the real build pipeline."""

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000):
        if node == "plan":
            return {"title": "待办应用", "pages": [{"name": "待办", "purpose": "管理待办任务"}],
                    "features": ["新增、完成和删除待办"], "data_model": ["localStorage 任务"],
                    "acceptance": ["刷新后待办仍存在"], "tasks": ["实现本地待办页面"], "limitations": []}
        if node == "code_loop":
            return {"files": {
                "src/App.tsx": "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { const { rows, title, setTitle, add, toggle, remove, error } = useAppState(); return <main><h1>待办应用</h1><input aria-label=\"任务名称\" value={title} onChange={e => setTitle(e.target.value)} /><button onClick={add}>新增</button><p role=\"alert\">{error}</p><ul>{rows.map(row => <li key={row.id}><span>{row.title} {row.completed ? '已完成' : '未完成'}</span><button onClick={() => toggle(row.id)}>切换完成</button><button onClick={() => remove(row.id)}>删除</button></li>)}</ul></main> }",
                "src/hooks/useAppState.ts": "import { useState } from 'react'\nimport { generatedAppStorage } from './generatedAppStorage'\ntype Row = { id: string; title: string; completed: boolean }\nexport function useAppState() { const [rows, setRows] = useState<Row[]>(() => { try { return JSON.parse(generatedAppStorage.getItem('todos') || '[]') as Row[] } catch { return [] } }); const [title, setTitle] = useState(''); const [error, setError] = useState(''); function save(next: Row[]) { try { generatedAppStorage.setItem('todos', JSON.stringify(next)); setRows(next); setError('') } catch { setError('本地保存失败') } } function add() { if (!title.trim()) return; save([...rows, { id: crypto.randomUUID(), title: title.trim(), completed: false }]); setTitle('') } function toggle(id: string) { save(rows.map(row => row.id === id ? { ...row, completed: !row.completed } : row)) } function remove(id: string) { save(rows.filter(row => row.id !== id)) } return { rows, title, setTitle, add, toggle, remove, error } }",
                "src/app.css": "body { font-family: sans-serif; } main { margin: 2rem auto; max-width: 40rem; }",
                "readme.md": "# 待办应用\n任务保存在项目预览域 localStorage。",
            }}
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def seed_version(store: Store, data_dir: Path, owner_token: str, title: str) -> tuple[str, str, str]:
    project = store.create_project(owner_hash(owner_token), title)
    run, _ = store.create_run(project["id"], "做一个可持久化的待办事项应用", f"run-{title}")
    store.update_run(run["id"], status="completed", phase="Done")
    version = store.save_version(project["id"], run["id"], {
        "template": "react-vite-v1", "build": {"ok": True, "steps": []},
        "files": [],
    })
    dist = data_dir / "artifacts" / project["id"] / run["id"] / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<html><script src="/assets/app.js"></script><h1>待办</h1></html>', encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('test preview')", encoding="utf-8")
    return project["id"], run["id"], version["id"]


def open_preview(main: TestClient, version_id: str) -> str:
    issued = main.get(f"/api/versions/{version_id}/preview")
    assert issued.status_code == 200, issued.text
    url = issued.json()["url"]
    assert urlsplit(url).hostname == main.base_url.host
    assert urlsplit(url).port == main.base_url.port
    assert urlsplit(url).path == f"/preview/open/{version_id}"
    first = main.get(urlsplit(url).path + "?" + urlsplit(url).query, follow_redirects=False)
    assert first.status_code == 303
    location = first.headers["location"]
    assert location.startswith("/preview/s/") and location.endswith(f"/v/{version_id}/")
    assert "set-cookie" not in first.headers
    assert main.get(urlsplit(url).path + "?" + urlsplit(url).query, follow_redirects=False).status_code == 401
    return location


def test_sse_replay_order_cursor_and_guest_authorization(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    store = Store(settings.app_db)
    project_id, run_id, _ = seed_version(store, tmp_path, "owner-a", "A")
    store.update_run(run_id, event_type="phase", event_payload={"phase": "BuildTest"})
    store.update_run(run_id, event_type="completed", event_payload={"ok": True})
    app = create_app(settings, model=FakeModel())
    with TestClient(app) as owner, TestClient(app) as other:
        owner.cookies.set("myatom_guest", "owner-a")
        other.cookies.set("myatom_guest", "owner-b")
        all_events = owner.get(f"/api/runs/{run_id}/events").json()["events"]
        assert [event["seq"] for event in all_events] == list(range(1, len(all_events) + 1))
        assert len({event["event_id"] for event in all_events}) == len(all_events)
        assert all(event["run_id"] == run_id and event["schema_version"] == 1 for event in all_events)
        response = owner.get(f"/api/runs/{run_id}/stream?after_seq=1")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        data_lines = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
        streamed = [json.loads(line) for line in data_lines]
        assert streamed == all_events[1:]
        assert [int(line.removeprefix("id: ")) for line in response.text.splitlines() if line.startswith("id: ")] == [e["seq"] for e in streamed]
        resumed = owner.get(f"/api/runs/{run_id}/stream?after_seq=0", headers={"Last-Event-ID": "2"})
        assert [json.loads(line.removeprefix("data: "))["seq"] for line in resumed.text.splitlines() if line.startswith("data: ")] == [e["seq"] for e in all_events if e["seq"] > 2]
        assert other.get(f"/api/runs/{run_id}/events").status_code == 404
        assert other.get(f"/api/runs/{run_id}/stream").status_code == 404


def test_sse_live_delivery_then_reconnect_without_duplicates(tmp_path: Path):
    """Exercise the streaming response over a socket while new events are written."""
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=FakeModel())
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()

    def next_event(lines):
        for line in lines:
            if line.startswith("data: "):
                return json.loads(line.removeprefix("data: "))
        raise AssertionError("SSE stream ended before the next event")

    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        store = app.state.store
        project = store.create_project(owner_hash("owner-a"), "流测试")
        run, _ = store.create_run(project["id"], "测试事件实时写入和恢复", "sse-live-test")
        run_id = run["id"]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", cookies={"myatom_guest": "owner-a"}, timeout=10) as client:
            with client.stream("GET", f"/api/runs/{run_id}/stream") as response:
                assert response.status_code == 200
                lines = response.iter_lines()
                first = next_event(lines)
                store.update_run(run_id, event_type="phase", event_payload={"phase": "Plan"})
                second = next_event(lines)
                store.update_run(run_id, event_type="phase", event_payload={"phase": "Build"})
                third = next_event(lines)
                assert [first["seq"], second["seq"], third["seq"]] == [1, 2, 3]
                assert [second["payload"]["phase"], third["payload"]["phase"]] == ["Plan", "Build"]
            store.update_run(run_id, event_type="phase", event_payload={"phase": "BuildTest"})
            store.update_run(run_id, status="completed", event_type="completed", event_payload={"ok": True})
            resumed = client.get(f"/api/runs/{run_id}/stream?after_seq={third['seq']}")
            assert resumed.status_code == 200
            replayed = [json.loads(line.removeprefix("data: ")) for line in resumed.text.splitlines() if line.startswith("data: ")]
            assert [event["seq"] for event in replayed] == [4, 5]
            assert [event["type"] for event in replayed] == ["phase", "completed"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def test_preview_single_use_ticket_static_scope_on_shared_origin(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", workbench_origin="http://127.0.0.1:8000")
    store = Store(settings.app_db)
    a_project, a_version = _version(store, "owner-a", "A", "react-vite-v4")
    b_project, b_version = _version(store, "owner-b", "B", "react-vite-v4")
    main_app = create_app(settings, model=FakeModel())
    with TestClient(main_app, base_url=settings.workbench_origin) as main_a, TestClient(main_app, base_url=settings.workbench_origin) as main_b:
        main_a.cookies.set("myatom_guest", "owner-a")
        main_b.cookies.set("myatom_guest", "owner-b")
        assert main_b.get(f"/api/versions/{a_version}/preview").status_code == 404
        assert main_a.get(f"/preview/s/no-ticket/v/{a_version}/").status_code == 401
        a_path = open_preview(main_a, a_version)
        b_path = open_preview(main_b, b_version)
        index = main_a.get(a_path)
        assert index.status_code == 200
        assert "./assets/app.js" in index.text
        assert "connect-src 'none'" in index.headers["content-security-policy"]
        assert main_a.get(a_path + "assets/app.js").status_code == 200
        assert main_a.get(b_path).status_code == 200  # Same-origin URLs are bearer sessions.
        assert main_b.get(a_path.replace(a_version, b_version)).status_code == 401
        session_token = a_path.split("/")[3]
        with sqlite3.connect(tmp_path / "preview_access.sqlite3") as db:
            db.execute("UPDATE preview_sessions SET expires_at=? WHERE token_hash=?",
                       ("2000-01-01T00:00:00+00:00", hashlib.sha256(session_token.encode()).hexdigest()))
        expired = main_a.get(a_path)
        assert expired.status_code == 401
        assert expired.headers["content-type"].startswith("text/html")
        assert "重新载入" in expired.text


def test_generated_todo_app_has_real_build_and_preview_manifest(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", preview_port=8001)
    app = create_app(settings, model=TodoFakeModel())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "待办生成测试"}).json()["id"]
        run_response = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个持久化待办应用，可以新增、完成、删除，刷新后保留任务"})
        assert run_response.status_code == 201
        run_id = run_response.json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        }).status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert plan["card"]["payload"]["entities"] == []
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan",
        }).status_code == 202
        complete = wait_status(client, run_id, "completed", timeout=90)
        assert complete["card"]["payload"]["browser_check"] == "not_run"
        versions = client.get(f"/api/projects/{project_id}").json()["versions"]
        assert len(versions) == 1
        version = versions[0]
        assert version["manifest"]["build"]["ok"] is True
        assert version["manifest"]["preview"]["ok"] is True
        source = client.get(f"/api/versions/{version['id']}/files/src/App.tsx")
        assert source.status_code == 200 and "useAppState" in source.text
        assert client.get(f"/api/versions/{version['id']}/preview").status_code == 200
