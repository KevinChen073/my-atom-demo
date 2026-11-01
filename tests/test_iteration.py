from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings
from backend.store import Conflict, Store
from backend.workflow import merge_iteration_plan
from tests.test_mvp1 import FakeModel, wait_status


class IterationModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.second_code_prompt = ""

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "plan" and "上一可用版本" in user:
            return {"title": "计数器", "pages": [], "features": ["标题使用蓝色"],
                    "data_model": [], "acceptance": ["标题为蓝色"], "tasks": ["修改样式"],
                    "limitations": [], "changed_files": ["src/app.css"], "new_files": [],
                    "removed_features": [], "modified_features": {}}
        if node == "code_loop" and "这是已保存版本的迭代" in user:
            self.second_code_prompt = user
            return {"files": {"src/app.css": "body { margin: 0; font-family: sans-serif; } main { padding: 2rem; } h1 { color: blue; }"}}
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def approve_to_completion(client: TestClient, project_id: str, request: str, key: str) -> dict:
    response = client.post(f"/api/projects/{project_id}/runs", json={"request_text": request},
                           headers={"Idempotency-Key": key})
    assert response.status_code == 201, response.text
    run_id = response.json()["run"]["id"]
    clarification = wait_status(client, run_id, "awaiting_clarification")
    response = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarification["card_id"],
        "spec_version": clarification["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}})
    assert response.status_code == 202, response.text
    plan = wait_status(client, run_id, "awaiting_plan")
    response = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
        "spec_version": plan["spec_version"], "action": "approve_plan"})
    assert response.status_code == 202, response.text
    return wait_status(client, run_id, "completed", timeout=90)


def test_iteration_keeps_approved_plan_and_untouched_source(tmp_path: Path):
    model = IterationModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "计数器"}).json()["id"]
        first = approve_to_completion(client, project_id, "做一个可以点击加一的计数器网页", "first")
        first_version = client.get(f"/api/projects/{project_id}").json()["active_version_id"]
        first_source = client.get(f"/api/versions/{first_version}/files/src/App.tsx").text
        second = approve_to_completion(client, project_id, "保持计数功能，把标题改成蓝色", "second")
        second_run = client.get(f"/api/runs/{second['id']}").json()
        assert second_run["base_version_id"] == first_version
        assert second_run["run_mode"] == "iterate"
        assert "点击加一" in second_run["plan"]["features"]
        assert "标题使用蓝色" in second_run["plan"]["features"]
        assert "body { margin: 0" in model.second_code_prompt
        project = client.get(f"/api/projects/{project_id}").json()
        latest = project["active_version_id"]
        assert latest != first_version
        assert client.get(f"/api/versions/{latest}/files/src/App.tsx").text == first_source
        assert "color: blue" in client.get(f"/api/versions/{latest}/files/src/app.css").text
        assert "点击加一" in project["versions"][0]["manifest"]["effective_spec"]["plan"]["features"]


def test_merge_iteration_plan_preserves_baseline_and_requires_exact_deletion():
    base = {"plan": {"title": "计数器", "pages": [], "features": ["点击加一"], "data_model": ["localStorage 记录计数"],
                     "acceptance": ["刷新后读回计数"], "tasks": ["计数"], "limitations": []}}
    merged = merge_iteration_plan({"title": "计数器", "features": ["重置计数"], "acceptance": ["可以重置"],
                                   "changed_files": ["src/App.tsx"]}, base)
    assert merged["features"] == ["点击加一", "重置计数"]
    assert merged["data_model"] == ["localStorage 记录计数"]
    assert merged["acceptance"] == ["刷新后读回计数", "可以重置"]
    import pytest
    with pytest.raises(ValueError):
        merge_iteration_plan({"title": "计数器", "features": ["重置计数"], "acceptance": ["可以重置"],
                              "removed_features": ["别的功能"]}, base)


def test_run_pins_base_and_rejects_stale_commit(tmp_path: Path):
    store = Store(tmp_path / "state.sqlite3")
    project = store.create_project("owner", "计数器")
    first, _ = store.create_run(project["id"], "做一个计数器应用", "first")
    store.update_run(first["id"], status="completed", plan_json='{"title":"计数器","features":["点击加一"],"acceptance":["点击增加"]}')
    version, _ = store.commit_version(project["id"], first["id"], {"files": []})
    second, _ = store.create_run(project["id"], "把标题改成蓝色", "second")
    assert second["base_version_id"] == version["id"]
    assert second["base_spec"]["plan"]["features"] == ["点击加一"]
    store.update_run(second["id"], status="completed")
    second_version, _ = store.commit_version(project["id"], second["id"], {"files": []})
    store.activate_version(project["id"], version["id"])
    third, _ = store.create_run(project["id"], "把背景改成绿色", "third")
    store.update_run(third["id"], status="completed")
    store.activate_version(project["id"], second_version["id"])
    import pytest
    with pytest.raises(Conflict):
        store.commit_version(project["id"], third["id"], {"files": []})


def test_existing_sqlite_schema_adds_iteration_columns(tmp_path: Path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE runs (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            request_text TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
            card_json TEXT, card_id TEXT, spec_version INTEGER NOT NULL DEFAULT 0,
            approved_spec_version INTEGER, answers_json TEXT, plan_json TEXT,
            model_calls INTEGER NOT NULL DEFAULT 0, tokens_used INTEGER NOT NULL DEFAULT 0,
            max_model_calls INTEGER, max_total_tokens INTEGER, max_run_seconds INTEGER,
            max_fix_rounds INTEGER, active_seconds REAL, execution_started_at TEXT,
            fix_rounds INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
            error TEXT, version_id TEXT, trace_id TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(project_id, idempotency_key))""")
    Store(path)
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
    assert {"run_mode", "base_version_id", "base_spec_json"} <= columns
