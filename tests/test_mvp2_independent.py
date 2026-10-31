"""Independent MVP2 API checks using local temporary data and no paid model calls."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi.testclient import TestClient

from backend.api import create_app, owner_hash
from backend.preview import create_preview_app
from backend.settings import Settings
from backend.store import Store
from tests.test_mvp1 import FakeModel
from tests.test_mvp1 import wait_status


TODO_SCHEMA = {"name": "todos", "fields": [
    {"name": "title", "type": "text", "required": True},
    {"name": "completed", "type": "boolean", "required": True},
]}


class TodoFakeModel:
    """Deterministic model output; the workflow still writes and builds real files."""

    def check_limits(self, run_id: str) -> None:
        return None

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000):
        if node == "clarify":
            return {"summary": "持久化待办应用", "assumptions": ["单页"], "questions": []}
        if node == "plan":
            return {"title": "待办应用", "pages": [{"name": "待办", "purpose": "管理待办任务"}],
                    "features": ["新增、完成和删除待办"], "data_model": ["服务端 todos 实体"],
                    "acceptance": ["刷新后待办仍存在"], "tasks": ["实现待办页面与受控数据 API"],
                    "limitations": [], "entities": [TODO_SCHEMA]}
        if node == "code_loop":
            return {"app_tsx": """import { useEffect, useState } from 'react'
import { listRecords, createRecord, updateRecord, deleteRecord, type AppRecord } from './appData'
import './App.css'
export default function App() {
  const [rows, setRows] = useState<AppRecord[]>([])
  const [title, setTitle] = useState('')
  const [error, setError] = useState('')
  async function load() { try { setRows(await listRecords('todos')) } catch (e) { setError(String(e)) } }
  useEffect(() => { void load() }, [])
  async function add() { if (!title.trim()) return; try { await createRecord('todos', { title: title.trim(), completed: false }); setTitle(''); await load() } catch (e) { setError(String(e)) } }
  async function toggle(row: AppRecord) { try { await updateRecord('todos', row.id, { completed: !row.completed }); await load() } catch (e) { setError(String(e)) } }
  async function remove(row: AppRecord) { try { await deleteRecord('todos', row.id); await load() } catch (e) { setError(String(e)) } }
  return <main><h1>待办应用</h1><input aria-label="任务名称" value={title} onChange={e => setTitle(e.target.value)} /><button onClick={add}>新增</button><p role="alert">{error}</p><ul>{rows.map(row => <li key={row.id}><span>{String(row.title)} {row.completed ? '已完成' : '未完成'}</span><button onClick={() => toggle(row)}>切换完成</button><button onClick={() => remove(row)}>删除</button></li>)}</ul></main>
}
""", "app_css": "body { font-family: sans-serif; } main { margin: 2rem auto; max-width: 40rem; }"}
        raise AssertionError(node)


def seed_version(store: Store, data_dir: Path, owner_token: str, title: str) -> tuple[str, str, str]:
    project = store.create_project(owner_hash(owner_token), title)
    run, _ = store.create_run(project["id"], "做一个可持久化的待办事项应用", f"run-{title}")
    store.update_run(run["id"], status="completed", phase="Done")
    version = store.save_version(project["id"], run["id"], {
        "template": "react-vite-v1", "build": {"ok": True, "steps": []},
        "files": [], "entities": [TODO_SCHEMA],
    })
    dist = data_dir / "artifacts" / project["id"] / run["id"] / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<html><script src="/assets/app.js"></script><h1>待办</h1></html>', encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('test preview')", encoding="utf-8")
    return project["id"], run["id"], version["id"]


def open_preview(main: TestClient, preview: TestClient, version_id: str) -> None:
    issued = main.get(f"/api/versions/{version_id}/preview")
    assert issued.status_code == 200, issued.text
    url = issued.json()["url"]
    assert urlsplit(url).hostname == "127.0.0.1"
    assert urlsplit(url).port == 8001
    assert urlsplit(url).path == f"/open/{version_id}"
    first = preview.get(urlsplit(url).path + "?" + urlsplit(url).query, follow_redirects=False)
    assert first.status_code == 303
    assert first.headers["location"] == f"/v/{version_id}/"
    assert "myatom_preview_" in first.headers["set-cookie"]
    assert "httponly" in first.headers["set-cookie"].lower()
    assert "samesite=strict" in first.headers["set-cookie"].lower()
    assert preview.get(urlsplit(url).path + "?" + urlsplit(url).query, follow_redirects=False).status_code == 401


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


def test_preview_single_use_ticket_static_scope_and_crud_persistence(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", preview_port=8001)
    store = Store(settings.app_db)
    a_project, _, a_version = seed_version(store, tmp_path, "owner-a", "A")
    b_project, _, b_version = seed_version(store, tmp_path, "owner-b", "B")
    main_app, preview_app = create_app(settings, model=FakeModel()), create_preview_app(settings)
    with TestClient(main_app) as main_a, TestClient(main_app) as main_b, TestClient(preview_app, base_url="http://127.0.0.1:8001") as preview_a, TestClient(preview_app, base_url="http://127.0.0.1:8001") as preview_b:
        main_a.cookies.set("myatom_guest", "owner-a")
        main_b.cookies.set("myatom_guest", "owner-b")
        assert main_b.get(f"/api/versions/{a_version}/preview").status_code == 404
        assert preview_a.get(f"/v/{a_version}/").status_code == 401
        open_preview(main_a, preview_a, a_version)
        open_preview(main_b, preview_b, b_version)
        index = preview_a.get(f"/v/{a_version}/")
        assert index.status_code == 200
        assert "./assets/app.js" in index.text
        assert "default-src 'none'" in index.headers["content-security-policy"]
        assert preview_a.get(f"/v/{a_version}/assets/app.js").status_code == 200
        assert preview_a.get("/api/projects").status_code == 404
        assert preview_a.get(f"/v/{b_version}/").status_code == 401
        route_a = f"/data/{a_version}/todos"
        route_b = f"/data/{b_version}/todos"
        origin = {"Origin": "http://127.0.0.1:8001"}
        create_body = {"data": {"title": "验收任务 A", "completed": False}}
        create_headers = {**origin, "Idempotency-Key": "test-create-a-1"}
        created = preview_a.post(route_a, json=create_body, headers=create_headers)
        assert created.status_code == 201, created.text
        record_id = created.json()["id"]
        replay = preview_a.post(route_a, json=create_body, headers=create_headers)
        assert replay.status_code == 201 and replay.json()["id"] == record_id
        assert len(preview_a.get(route_a).json()) == 1
        conflict = preview_a.post(route_a, json={"data": {"title": "另一任务", "completed": False}}, headers=create_headers)
        assert conflict.status_code == 409
        assert preview_a.get(route_a).json()[0]["title"] == "验收任务 A"
        updated = preview_a.put(f"{route_a}/{record_id}", json={"data": {"completed": True}}, headers=origin)
        assert updated.status_code == 200 and updated.json()["completed"] is True
        patched = preview_a.patch(f"{route_a}/{record_id}", json={"data": {"title": "PATCH 后的任务"}}, headers=origin)
        assert patched.status_code == 200 and patched.json()["title"] == "PATCH 后的任务"
        assert patched.json()["completed"] is True
        assert preview_b.get(route_b).json() == []
        assert preview_b.get(route_a).status_code == 401
        assert preview_a.get(route_b).status_code == 401
        assert preview_a.post(route_a, json={"data": {"title": "evil", "completed": False}}, headers={"Origin": "https://evil.invalid"}).status_code == 403
        assert preview_a.post(route_a, json={"data": {"title": "missing completed"}}, headers=origin).status_code == 422
        assert preview_a.post(route_a, json={"data": {"title": "wrong type", "completed": "yes"}}, headers=origin).status_code == 422
        assert preview_a.post(route_a, json={"data": {"title": "extra", "completed": False, "secret": "x"}}, headers=origin).status_code == 422
        assert preview_a.get(f"/data/{a_version}/unknown").status_code == 404
        preview_cookie = preview_a.cookies.get("myatom_preview_" + a_version.replace("-", ""))
        with TestClient(create_preview_app(settings), base_url="http://127.0.0.1:8001") as reopened:
            reopened.cookies.set("myatom_preview_" + a_version.replace("-", ""), preview_cookie)
            rows = reopened.get(route_a)
            assert rows.status_code == 200 and rows.json()[0]["completed"] is True
            assert rows.json()[0]["title"] == "PATCH 后的任务"
            assert reopened.delete(f"{route_a}/{record_id}", headers=origin).status_code == 204
            assert reopened.get(route_a).json() == []
        assert a_project != b_project


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
            "action": "confirm_clarification", "answers": {},
        }).status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert plan["card"]["payload"]["entities"] == [TODO_SCHEMA]
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan",
        }).status_code == 202
        complete = wait_status(client, run_id, "completed", timeout=90)
        assert complete["card"]["payload"]["browser_check"] == "not_run"
        versions = client.get(f"/api/projects/{project_id}").json()["versions"]
        assert len(versions) == 1
        version = versions[0]
        assert version["manifest"]["build"]["ok"] is True
        assert version["manifest"]["entities"] == [TODO_SCHEMA]
        source = client.get(f"/api/versions/{version['id']}/files/src/App.tsx")
        assert source.status_code == 200 and "createRecord('todos'" in source.text
        assert client.get(f"/api/versions/{version['id']}/preview").status_code == 200
