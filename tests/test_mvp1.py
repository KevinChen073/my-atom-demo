from __future__ import annotations

import time
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.runner import LocalRunner, UnsafeSource
from backend.settings import Settings


class FakeModel:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def check_limits(self, run_id: str) -> None:
        return None

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000):
        self.calls.append((node, cache_key))
        if node == "clarify":
            question = "初始值是多少？" if cache_key.startswith("card1") else "按钮放在什么位置？" if cache_key.startswith("card2") else "是否保留计数？"
            return {"summary": "制作一个计数器", "assumptions": ["单页"], "questions": [{"text": question, "default": "0", "required": True}]}
        if node == "clarity_gate":
            return {"complete": True, "missing": []}
        if node == "plan":
            return {"title": "计数器", "pages": [{"name": "首页", "purpose": "计数"}], "features": ["点击加一"], "data_model": ["仅页面状态"], "acceptance": ["点击后数字增加"], "tasks": ["生成组件"], "limitations": ["预览在 MVP2"]}
        if node == "code_loop":
            files = {
                "src/App.tsx": "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { const { count, increment } = useAppState(); return <main><h1>计数器</h1><button onClick={increment}>加一 {count}</button></main> }",
                "src/hooks/useAppState.ts": "import { useState } from 'react'\nexport function useAppState() { const [count, setCount] = useState(0); return { count, increment: () => setCount(value => value + 1) } }",
                "src/app.css": "body { margin: 0; font-family: sans-serif; } main { padding: 2rem; }",
                "readme.md": "# 计数器\n点击加一；页面状态不持久化。",
            }
            partial = re.search(r"路径必须且只能是 (.*?)；", system)
            if partial:
                targets = [part.strip() for part in partial.group(1).split(",")]
                return {"files": {name: files[name] for name in targets}}
            return {"files": files}
        raise AssertionError(node)


def wait_status(client: TestClient, run_id: str, expected: str, timeout: float = 25) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == expected:
            return last
        if last["status"] in {"failed", "budget_exceeded", "cancelled"}:
            pytest.fail(f"run stopped in {last['status']}: {last['error']}")
        time.sleep(0.15)
    pytest.fail(f"timed out waiting for {expected}; last={last.get('status')}")


def test_real_files_gate_revision_persistence_and_isolation(tmp_path: Path):
    model = FakeModel()
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=model)
    with TestClient(app) as client:
        project_response = client.post("/api/projects", json={"title": "测试项目"})
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]
        run_response = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的计数器网页"}, headers={"Idempotency-Key": "run-1"})
        assert run_response.status_code == 201
        run_id = run_response.json()["run"]["id"]
        duplicate = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的计数器网页"}, headers={"Idempotency-Key": "run-1"})
        assert duplicate.json()["run"]["id"] == run_id
        run = wait_status(client, run_id, "awaiting_clarification")
        assert len(run["card"]["payload"]["questions"]) == 1
        workspace = tmp_path / "projects" / project_id / "runs" / run_id / "workspace"
        assert not workspace.exists(), "Plan approval must gate file writes"
        wrong_action = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": run["card_id"], "spec_version": run["spec_version"], "action": "approve_plan"})
        assert wrong_action.status_code == 409
        decision = {"card_id": run["card_id"], "spec_version": run["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}}
        first = client.post(f"/api/runs/{run_id}/decisions", json=decision, headers={"Idempotency-Key": "clarify-1"})
        assert first.status_code == 202
        repeat = client.post(f"/api/runs/{run_id}/decisions", json=decision, headers={"Idempotency-Key": "clarify-1"})
        assert repeat.json()["decision_id"] == first.json()["decision_id"]
        plan = wait_status(client, run_id, "awaiting_plan")
        assert not workspace.exists()
        old_card, old_spec = plan["card_id"], plan["spec_version"]
        revise = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": old_card, "spec_version": old_spec, "action": "revise_plan", "feedback": "按钮放在页面中央"}, headers={"Idempotency-Key": "revise-1"})
        assert revise.status_code == 202
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            plan = client.get(f"/api/runs/{run_id}").json()
            if plan["status"] == "awaiting_plan" and plan["spec_version"] > old_spec:
                break
            time.sleep(0.15)
        assert plan["spec_version"] > old_spec
        stale = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": old_card, "spec_version": old_spec, "action": "approve_plan"})
        assert stale.status_code == 409
        approve = client.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan"}, headers={"Idempotency-Key": "approve-1"})
        assert approve.status_code == 202
        completed = wait_status(client, run_id, "completed", timeout=90)
        assert completed["approved_spec_version"] == plan["spec_version"]
        project = client.get(f"/api/projects/{project_id}").json()
        assert len(project["versions"]) == 1
        version = project["versions"][0]
        assert version["manifest"]["build"]["ok"] is True
        assert all(step["exit_code"] == 0 for step in version["manifest"]["build"]["steps"])
        source = client.get(f"/api/versions/{version['id']}/files/src/App.tsx")
        assert source.status_code == 200 and "useAppState" in source.text
        assert "test-only" not in source.text
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
        outsider = TestClient(app)
        assert outsider.get(f"/api/projects/{project_id}").status_code == 401
        assert outsider.get(f"/api/versions/{version['id']}").status_code == 401
        assert not any("test-only" in str(event) for event in events)
    assert workspace.exists()


def test_runner_rejects_source_with_external_access(tmp_path: Path):
    runner = LocalRunner(Settings(data_dir=tmp_path), None)  # validation does not use the store
    with pytest.raises(UnsafeSource):
        runner.validate_source("src/App.tsx", "export default function App(){ fetch('https://evil.example'); return <div/> }")
    with pytest.raises(UnsafeSource):
        runner.validate_source("../secrets.txt", "leak")
    with pytest.raises(UnsafeSource, match="状态更新函数"):
        runner.validate_source("src/App.tsx", """export default function App() {
          setScore((prev) => {
            const next = prev + 1;
            void persistHighScore(next);
            return next;
          });
          return <div />;
        }""")
    runner.validate_source("src/App.tsx", """export default function App() {
      setScore((prev) => prev + 1);
      return <div />;
    }""")
