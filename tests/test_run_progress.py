"""User-visible progress uses persisted clarification and execution facts."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings
from tests.test_mvp1 import FakeModel, wait_status


def test_clarity_result_and_waiting_time_are_persisted(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "进展测试"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的计数器网页"}).json()["run"]["id"]
        clarify = wait_status(client, run_id, "awaiting_clarification")
        assert "active_elapsed_seconds" in clarify
        assert clarify["execution_running"] is False
        time.sleep(0.2)
        stopped = client.get(f"/api/runs/{run_id}").json()
        assert stopped["active_elapsed_seconds"] - clarify["active_elapsed_seconds"] < 0.1

        response = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarify["card_id"], "spec_version": clarify["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "从零开始"},
        })
        assert response.status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        result = [event for event in events if event["type"] == "clarity_result"]
        assert len(result) == 1
        assert result[0]["payload"]["round"] == 1
        assert result[0]["payload"]["confirmed"] == [{"question": "初始值是多少？", "answer": "从零开始"}]
        assert result[0]["payload"]["complete"] is True
        assert plan["plan"]["tasks"] == ["生成组件"]
        assert plan["execution_running"] is False
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["runs"][0]["active_elapsed_seconds"] >= stopped["active_elapsed_seconds"]
