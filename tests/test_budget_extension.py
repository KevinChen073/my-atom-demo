from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.budget import effective_limits
from backend.model import BudgetExceeded, ModelGateway
from backend.settings import Settings
from backend.store import Store
from tests.test_mvp1 import FakeModel, wait_status
from tests.test_build_harness import failed_build


class BudgetOnceDuringPlan(FakeModel):
    def __init__(self):
        super().__init__()
        self.stopped = False

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "plan" and not self.stopped:
            self.stopped = True
            raise BudgetExceeded("output_reserve", observed=259, limit=512)
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_output_reserve_uses_persisted_100k_run_limit_without_model_call(tmp_path: Path):
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("owner", "额度")
    run, _ = store.create_run(project["id"], "做一个计数器网页应用", "one")
    store.add_usage(run["id"], 99_000)
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="test-only"), store)
    with pytest.raises(BudgetExceeded) as stopped:
        gateway.generate(run["id"], "plan", "one", "system", "a" * 700, max_tokens=1000)
    assert stopped.value.kind == "output_reserve"
    assert 0 < stopped.value.observed < 512
    assert store.get_run(run["id"])["model_calls"] == 0


def test_budget_pause_requires_explicit_idempotent_extension_then_resumes_plan(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=BudgetOnceDuringPlan())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "额度测试"}).json()["id"]
        run = client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]
        run_id = run["id"]
        assert effective_limits(run)["total_tokens"] == 100_000
        clarification = wait_status(client, run_id, "awaiting_clarification")
        response = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"}})
        assert response.status_code == 202
        paused = wait_status(client, run_id, "awaiting_budget")
        assert paused["card"]["type"] == "budget_extension"
        assert paused["card"]["payload"]["budget_kind"] == "output_reserve"
        assert paused["card"]["payload"]["reason"] == "可用于模型输出的 Token 余量为 259，低于最低所需的 512。"
        assert paused["execution_running"] is False
        assert client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "再做一个可以点击加一的计数器网页应用"}).status_code == 409
        body = {"card_id": paused["card_id"], "spec_version": paused["spec_version"],
                "model_calls": False, "total_tokens": True, "run_seconds": False, "fix_rounds": False}
        assert client.post(f"/api/runs/{run_id}/budgets/extend", json={**body, "total_tokens": False}).status_code == 422
        other_client = TestClient(app)
        other_client.post("/api/projects", json={"title": "其他访客"})
        assert other_client.post(f"/api/runs/{run_id}/budgets/extend", json=body).status_code == 404
        other_client.close()
        first = client.post(f"/api/runs/{run_id}/budgets/extend", json=body,
                            headers={"Idempotency-Key": "increase-once"})
        assert first.status_code == 202
        second = client.post(f"/api/runs/{run_id}/budgets/extend", json=body,
                             headers={"Idempotency-Key": "increase-once"})
        assert second.status_code == 202
        assert first.json()["decision_id"] == second.json()["decision_id"]
        assert second.json()["created"] is False
        planned = wait_status(client, run_id, "awaiting_plan")
        assert planned["id"] == run_id
        assert effective_limits(planned)["total_tokens"] == 200_000
        assert client.post(f"/api/runs/{run_id}/budgets/extend", json=body,
                           headers={"Idempotency-Key": "different-key"}).status_code == 409
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        assert len([event for event in events if event["type"] == "budget_extended"]) == 1


def test_older_budget_stop_can_open_extension_card(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=BudgetOnceDuringPlan())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "旧额度"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"}})
        paused = wait_status(client, run_id, "awaiting_budget")
        app.state.store.update_run(run_id, status="budget_exceeded", phase="NeedsUser",
                                   event_type="legacy_test", event_payload={})
        offered = client.post(f"/api/runs/{run_id}/offer-budget")
        assert offered.status_code == 200
        card = offered.json()["card"]
        assert offered.json()["status"] == "awaiting_budget"
        assert card["payload"]["resume_phase"] == "Plan"
        assert card["card_id"] != paused["card_id"]


def test_repair_round_limit_can_be_explicitly_extended_with_single_message(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=0)
    app = create_app(settings, model=FakeModel())
    original_build = app.state.workflow.runner.build
    calls = 0

    def first_build_fails(project_id: str, run_id: str):
        nonlocal calls
        calls += 1
        return failed_build("src/App.tsx(1,1): error TS2304: Cannot find name 'missing'.") if calls == 1 else original_build(project_id, run_id)

    app.state.workflow.runner.build = first_build_fails
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "轮次扩展"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"}})
        plan = wait_status(client, run_id, "awaiting_plan")
        client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan"})
        paused = wait_status(client, run_id, "awaiting_repair")
        assert paused["card"]["payload"]["stop_code"] == "repair_limit"
        assert "extend_auto_repair" in paused["card"]["actions"]
        message_id = str(uuid4())
        sent = client.post(f"/api/runs/{run_id}/messages", json={
            "submission_id": message_id,
            "card_ref": {"card_id": paused["card_id"], "spec_version": paused["spec_version"]},
            "text": "增加30轮自动修复并继续"})
        assert sent.status_code == 202
        completed = wait_status(client, run_id, "completed", timeout=40)
        assert effective_limits(completed)["fix_rounds"] == 30
        assert calls == 2
        assert any(decision["action"] == "extend_auto_repair" for decision in
                   client.get(f"/api/projects/{project_id}").json()["decisions"])
