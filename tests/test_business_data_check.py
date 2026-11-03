from __future__ import annotations

from backend.business_data_check import inspect_business_data
from backend.api import create_app
from backend.settings import Settings
from backend.store import Store
from backend.workflow import Workflow, normalize_plan
from fastapi.testclient import TestClient
from tests.test_mvp1 import wait_status
from tests.test_mvp2_independent import TodoFakeModel


def plan(required: bool = True) -> dict:
    return normalize_plan({
        "title": "待办", "pages": [], "features": ["新增待办"],
        "data_model": ["localStorage 保存任务标题和完成状态"] if required else [],
        "acceptance": ["刷新读回任务"] if required else ["页面显示静态信息"],
        "tasks": [], "limitations": [],
        "business_data": {"required": required, "fields": ["任务标题", "完成状态"] if required else []},
    })


def test_requirement_document_has_explicit_storage_scope_and_acceptance():
    spec = plan()["business_data"]
    assert spec["required"] is True
    assert spec["fields"] == ["任务标题", "完成状态"]
    assert "localStorage" in spec["storage"]
    assert "刷新" in spec["verification"]
    assert "换浏览器" in spec["limitations"]


def test_business_data_contract_rejects_old_counter_and_read_only_candidate():
    old_counter = {"src/App.tsx": "import { useState } from 'react'; export default function App(){const [count,setCount]=useState(0);return <button onClick={()=>setCount(count+1)}>{count}</button>}"}
    missing = inspect_business_data(old_counter, plan())
    assert not missing["ok"]
    assert {item["code"] for item in missing["issues"]} == {"missing_business_data_read", "missing_business_data_write"}
    assert {item["file"] for item in missing["issues"]} == {"src/App.tsx"}

    read_only = {"src/hooks/useTodos.ts": "generatedAppStorage.getItem('todos')"}
    missing_write = inspect_business_data(read_only, plan())
    assert [item["code"] for item in missing_write["issues"]] == ["missing_business_data_write"]
    assert missing_write["issues"][0]["file"] == "src/hooks/useTodos.ts"
    comments_only = {"src/App.tsx": "// generatedAppStorage.getItem('todos')\n/* generatedAppStorage.setItem('todos', '[]') */\nexport default function App(){return null}"}
    assert len(inspect_business_data(comments_only, plan())["issues"]) == 2


def test_business_data_contract_records_source_evidence_not_browser_pass():
    files = {"src/hooks/useTodos.ts": "generatedAppStorage.getItem('todos'); generatedAppStorage.setItem('todos', '[]')"}
    checked = inspect_business_data(files, plan())
    assert checked["ok"] and checked["level"] == "source_contract_only"
    assert checked["read_files"] == checked["write_files"] == ["src/hooks/useTodos.ts"]
    assert inspect_business_data({}, plan(False))["ok"] is True


def test_workflow_storage_node_routes_missing_writes_to_targeted_repair(tmp_path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    store = Store(settings.app_db)
    project = store.create_project("test-owner", "待办")
    run, _ = store.create_run(project["id"], "做一个待办", "storage-check")
    workflow = Workflow(settings, store, model=object())
    store.cache_set(run["id"], "source_candidate", "candidate-1", {"files": {
        "src/App.tsx": "generatedAppStorage.getItem('todos')",
    }})
    state = {"run_id": run["id"], "project_id": project["id"], "source_candidate_ref": "candidate-1",
             "plan": plan(), "candidate_number": 1, "fix_rounds": 0}
    result = workflow.business_data_check(state)
    assert result["business_data_ok"] is False
    assert result["code_feedback"]["target_files"] == ["src/App.tsx"]
    assert workflow.route_business_data(result) == "code_loop"
    assert store.events(run["id"])[-1]["type"] == "business_data_check_failed"


def test_missing_write_is_repaired_before_build_and_saved_with_source_level_result(tmp_path):
    class RepairModel(TodoFakeModel):
        def __init__(self):
            super().__init__()
            self.code_calls = 0

        def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
            if node == "code_loop":
                self.code_calls += 1
                complete = super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)
                if self.code_calls == 1:
                    hook = complete["files"]["src/hooks/useAppState.ts"]
                    complete["files"]["src/hooks/useAppState.ts"] = hook.replace(
                        "generatedAppStorage.setItem('todos', JSON.stringify(next)); ", "")
                    return complete
                assert "src/hooks/useAppState.ts" in user
                return {"files": {"src/hooks/useAppState.ts": complete["files"]["src/hooks/useAppState.ts"]}}
            return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)

    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    model = RepairModel()
    with TestClient(create_app(settings, model=model)) as client:
        project_id = client.post("/api/projects", json={"title": "待办"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "做一个待办应用，新增和完成任务后保存到 localStorage，刷新后读回"}).json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "不需要登录"},
        }).status_code == 202
        plan_card = wait_status(client, run_id, "awaiting_plan")
        assert plan_card["plan"]["business_data"]["required"] is True
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan_card["card_id"], "spec_version": plan_card["spec_version"],
            "action": "approve_plan",
        }).status_code == 202
        completed = wait_status(client, run_id, "completed", timeout=90)
        assert model.code_calls == 2
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        failure = next(event for event in events if event["type"] == "business_data_check_failed")
        assert failure["payload"]["target_files"] == ["src/hooks/useAppState.ts"]
        assert events.index(failure) < next(i for i, event in enumerate(events) if event["type"] == "build_result")
        check = completed["card"]["payload"]["business_data_check"]
        assert check["ok"] and check["level"] == "source_contract_only"
        assert completed["card"]["payload"]["browser_check"] == "not_run"
