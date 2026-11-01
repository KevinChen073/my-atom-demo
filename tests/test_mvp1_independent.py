"""Independent MVP1 contract checks. No test here calls the paid model API."""

from __future__ import annotations

import threading
import time
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError

from backend.api import create_app
from backend.model import BudgetExceeded, ModelGateway
from backend.settings import Settings
from backend.store import Store, dumps
from tests.test_mvp1 import FakeModel, wait_status


def new_store_run(tmp_path: Path) -> tuple[Store, str]:
    store = Store(tmp_path / "app.sqlite3")
    project = store.create_project("test-owner", "test")
    run, _ = store.create_run(project["id"], "Build a counter app", "run-key")
    return store, run["id"]


def test_model_hard_budget_stops_before_network(tmp_path: Path):
    store, run_id = new_store_run(tmp_path)
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", max_model_calls=0)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE runs SET max_model_calls=0 WHERE id=?", (run_id,))
    gateway = ModelGateway(settings, store)
    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_: pytest.fail("network call made after hard budget"))))
    with pytest.raises(BudgetExceeded):
        gateway.generate(run_id, "clarify", "first", "system", "user")
    assert store.get_run(run_id)["model_calls"] == 0


def test_long_human_wait_does_not_consume_execution_budget(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", max_run_seconds=30)
    app = create_app(settings, model=FakeModel())
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "等待确认"}).json()
        run_id = client.post(f"/api/projects/{project['id']}/runs",
                             json={"request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        deadline = time.monotonic() + 5
        while app.state.store.get_run(run_id)["execution_started_at"] is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        paused = app.state.store.get_run(run_id)
        assert paused["execution_started_at"] is None
        with sqlite3.connect(settings.app_db) as db:
            db.execute("UPDATE runs SET created_at=? WHERE id=?",
                       ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), run_id))
        response = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        })
        assert response.status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert plan["status"] == "awaiting_plan"
        assert plan["active_seconds"] < 30
        deadline = time.monotonic() + 5
        while app.state.store.get_run(run_id)["execution_started_at"] is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert app.state.store.get_run(run_id)["execution_started_at"] is None
        with sqlite3.connect(settings.app_db) as db:
            db.execute("UPDATE runs SET created_at=? WHERE id=?",
                       ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), run_id))
        revision = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"],
            "action": "revise_plan", "feedback": "将按钮文字改成增加",
        })
        assert revision.status_code == 202
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            revised = client.get(f"/api/runs/{run_id}").json()
            if revised["status"] == "awaiting_plan" and revised["spec_version"] > plan["spec_version"]:
                break
            time.sleep(0.05)
        assert revised["status"] == "awaiting_plan"
        assert revised["spec_version"] > plan["spec_version"]
        assert revised["active_seconds"] < 30


def test_active_segments_accumulate_and_restart_excludes_downtime(tmp_path: Path):
    store, run_id = new_store_run(tmp_path)
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", max_run_seconds=5)
    gateway = ModelGateway(settings, store)
    assert store.begin_execution(run_id)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE runs SET execution_started_at=? WHERE id=?",
                   ((datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat(), run_id))
    first_segment = store.finish_execution(run_id)
    assert 3 <= first_segment < 5
    gateway.check_limits(run_id)
    assert store.begin_execution(run_id)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE runs SET execution_started_at=? WHERE id=?",
                   ((datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat(), run_id))
    with pytest.raises(BudgetExceeded) as error:
        gateway.check_limits(run_id)
    assert error.value.kind == "run_seconds"
    accumulated = store.checkpoint_execution(run_id)
    assert accumulated >= 6
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE runs SET execution_started_at=? WHERE id=?",
                   ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), run_id))
    store.recover_execution_timers()
    assert store.get_run(run_id)["execution_started_at"] is None
    assert abs(store.active_elapsed_seconds(run_id) - accumulated) < 0.1


def test_model_retries_transient_timeout_and_tracks_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store, run_id = new_store_run(tmp_path)
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="test-only"), store)
    calls = 0

    def complete(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=42), choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"ok": true}'), finish_reason="stop")])

    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    monkeypatch.setattr("backend.model.time.sleep", lambda _: None)
    assert gateway.generate(run_id, "clarify", "retry", "system", "user") == {"ok": True}
    assert calls == 2
    assert store.get_run(run_id)["model_calls"] == 2
    assert store.get_run(run_id)["tokens_used"] == 42


def test_missing_usage_is_conservatively_counted(tmp_path: Path):
    store, run_id = new_store_run(tmp_path)
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="test-only"), store)
    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
        usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'), finish_reason="stop")]))))
    gateway.generate(run_id, "clarify", "no-usage", "system", "user")
    assert store.get_run(run_id)["tokens_used"] > 0, "missing provider usage must not disable token budget"


def test_truncated_thinking_response_increases_limit_and_records_safe_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store, run_id = new_store_run(tmp_path)
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="test-only"), store)
    limits: list[int] = []
    modes: list[tuple[str, str]] = []

    def complete(**kwargs):
        limits.append(kwargs["max_tokens"])
        modes.append((kwargs["reasoning_effort"], kwargs["extra_body"]["thinking"]["type"]))
        if len(limits) == 1:
            return SimpleNamespace(usage=SimpleNamespace(total_tokens=7815, prompt_tokens=1315, completion_tokens=6500),
                                   choices=[SimpleNamespace(message=SimpleNamespace(content=""), finish_reason="length")])
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=40, prompt_tokens=20, completion_tokens=20),
                               choices=[SimpleNamespace(message=SimpleNamespace(content='{"app_tsx":"ok","app_css":"ok"}'), finish_reason="stop")])

    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    monkeypatch.setattr("backend.model.time.sleep", lambda _: None)
    assert gateway.generate(run_id, "code_loop", "r0", "system", "user", max_tokens=6500)["app_tsx"] == "ok"
    assert limits == [6500, 13000]
    assert modes == [("none", "disabled"), ("none", "disabled")]
    responses = [event["payload"] for event in store.events(run_id) if event["type"] == "model_response"]
    assert [event["finish_reason"] for event in responses] == ["length", "stop"]
    assert [event["content_chars"] for event in responses] == [0, 31]
    assert all("app_tsx" not in str(event) for event in responses), "trace must not store generated source"


def test_model_caps_output_to_remaining_token_budget(tmp_path: Path):
    store, run_id = new_store_run(tmp_path)
    store.add_usage(run_id, 35_000)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE runs SET max_total_tokens=40000 WHERE id=?", (run_id,))
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="test-only", max_total_tokens=40_000), store)
    observed: list[int] = []

    def complete(**kwargs):
        observed.append(kwargs["max_tokens"])
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=10), choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop")])

    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    assert gateway.generate(run_id, "code_loop", "budget", "system", "user", max_tokens=12_000) == {"ok": True}
    assert 512 <= observed[0] < 5_000


def test_plan_retries_when_it_promises_unsupported_server_storage(tmp_path: Path):
    class StoragePlanModel(FakeModel):
        def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
            value = super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)
            if node == "plan" and cache_key.endswith("-c0"):
                value["features"].append("使用服务端数据库保存数据")
            return value

    model = StoragePlanModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "计划边界"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的计数器网页"}).json()["run"]["id"]
        run = wait_status(client, run_id, "awaiting_clarification")
        response = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": run["card_id"], "spec_version": run["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        })
        assert response.status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert "服务端数据库" not in json.dumps(plan["plan"], ensure_ascii=False)
        assert len([call for call in model.calls if call[0] == "plan"]) == 2
        assert not (tmp_path / "projects" / project_id / "runs" / run_id / "workspace").exists()


def test_two_guest_identities_cannot_read_or_change_each_other(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as a, TestClient(app) as b:
        a_project = a.post("/api/projects", json={"title": "A"}).json()["id"]
        b.post("/api/projects", json={"title": "B"})
        run = a.post(f"/api/projects/{a_project}/runs", json={"request_text": "做一个可点击的计数器网页应用"},
                     headers={"Idempotency-Key": "a-run"}).json()["run"]
        wait_status(a, run["id"], "awaiting_clarification")
        assert b.get(f"/api/projects/{a_project}").status_code == 404
        assert b.get(f"/api/runs/{run['id']}").status_code == 404
        assert b.get(f"/api/runs/{run['id']}/events").status_code == 404
        assert b.post(f"/api/runs/{run['id']}/cancel").status_code == 404
        assert b.post(f"/api/projects/{a_project}/runs", json={"request_text": "做一个可点击的计数器网页应用"}).status_code == 404


def test_restart_restores_waiting_plan_and_completes_once(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    model = FakeModel()
    app = create_app(settings, model=model)
    with TestClient(app) as first:
        project_id = first.post("/api/projects", json={"title": "重启恢复"}).json()["id"]
        cookie = first.cookies.get("myatom_guest")
        run_id = first.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可点击的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(first, run_id, "awaiting_clarification")
        answer = first.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        }, headers={"Idempotency-Key": "clarify-before-restart"})
        assert answer.status_code == 202
        plan = wait_status(first, run_id, "awaiting_plan")
        assert plan["approved_spec_version"] is None
    # A second application instance uses the same on-disk app DB and LangGraph checkpoint DB.
    restarted = create_app(settings, model=model)
    with TestClient(restarted) as second:
        second.cookies.set("myatom_guest", cookie)
        recovered = second.get(f"/api/runs/{run_id}").json()
        assert recovered["status"] == "awaiting_plan"
        assert recovered["card_id"] == plan["card_id"]
        approve = second.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": recovered["card_id"], "spec_version": recovered["spec_version"], "action": "approve_plan",
        }, headers={"Idempotency-Key": "approve-after-restart"})
        assert approve.status_code == 202
        completed = wait_status(second, run_id, "completed", timeout=90)
        assert completed["approved_spec_version"] == plan["spec_version"]
        versions = second.get(f"/api/projects/{project_id}").json()["versions"]
        assert len(versions) == 1
        assert versions[0]["manifest"]["build"]["ok"] is True
        duplicate = second.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": recovered["card_id"], "spec_version": recovered["spec_version"], "action": "approve_plan",
        }, headers={"Idempotency-Key": "approve-after-restart"})
        assert duplicate.status_code == 202
        assert len(second.get(f"/api/projects/{project_id}").json()["versions"]) == 1


def test_clarification_revision_and_plan_return_keep_write_gate(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "改需求"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可点击的计数器网页应用"}).json()["run"]["id"]
        first_card = wait_status(client, run_id, "awaiting_clarification")
        workspace = tmp_path / "projects" / project_id / "runs" / run_id / "workspace"
        missing_answer = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": first_card["card_id"], "spec_version": first_card["spec_version"],
            "action": "confirm_clarification",
        })
        assert missing_answer.status_code == 422
        revised_text = "做一个计数器网页，按钮可以加一、减一和清零"
        revise = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": first_card["card_id"], "spec_version": first_card["spec_version"],
            "action": "revise_clarification", "request_text": revised_text,
        }, headers={"Idempotency-Key": "revise-clarify"})
        assert revise.status_code == 202
        newer_card = wait_status(client, run_id, "awaiting_clarification")
        assert newer_card["spec_version"] > first_card["spec_version"]
        assert newer_card["request_text"] == revised_text
        assert not workspace.exists()
        stale_clarify = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": first_card["card_id"], "spec_version": first_card["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        })
        assert stale_clarify.status_code == 409
        accepted_default = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": newer_card["card_id"], "spec_version": newer_card["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        })
        assert accepted_default.status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        back = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "return_to_clarification",
        }, headers={"Idempotency-Key": "back-to-clarify"})
        assert back.status_code in {409, 422}
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "awaiting_plan"
        assert not workspace.exists()


def test_direct_project_url_reload_serves_spa(tmp_path: Path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<html><div id="root">MYATOM SPA</div></html>', encoding="utf-8")
    app = create_app(Settings(root=tmp_path, data_dir=tmp_path / "data", model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "直接打开"}).json()["id"]
        response = client.get(f"/projects/{project_id}")
        assert response.status_code == 200
        assert "MYATOM SPA" in response.text
        assert "text/html" in response.headers["content-type"]


class BrokenBuildModel(FakeModel):
    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "code_loop":
            self.calls.append((node, cache_key))
            return {"files": {
                "src/App.tsx": "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { useAppState(); return <main>broken",
                "src/app.css": "body { margin: 0; }",
                "src/hooks/useAppState.ts": "export function useAppState() { return { count: 0, increment: () => {} } }",
                "readme.md": "# Broken build",
            }}
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


class CapturedRepairModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.code_prompt = ""

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "code_loop":
            self.code_prompt = user
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_build_failure_has_test_card_authorized_log_and_no_version(tmp_path: Path):
    broken_model = BrokenBuildModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=0), model=broken_model)
    with TestClient(app) as owner, TestClient(app) as other:
        project_id = owner.post("/api/projects", json={"title": "失败构建"}).json()["id"]
        other.post("/api/projects", json={"title": "其他访客"})
        run_id = owner.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可点击的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(owner, run_id, "awaiting_clarification")
        confirmed = owner.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": clarification["card_id"], "spec_version": clarification["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "0"},
        })
        assert confirmed.status_code == 202
        plan = wait_status(owner, run_id, "awaiting_plan")
        approved = owner.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan",
        })
        assert approved.status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            run = owner.get(f"/api/runs/{run_id}").json()
            if run["status"] in {"awaiting_repair", "failed", "completed", "budget_exceeded", "cancelled"}:
                break
            time.sleep(0.15)
        assert run["status"] == "awaiting_repair"
        assert run["card"]["type"] == "test_result"
        assert run["card"]["status"] == "pending"
        assert run["card"]["payload"]["build"]["ok"] is False
        assert run["card"]["payload"]["diagnostics_ref"] == f"/api/runs/{run_id}/build-log"
        assert run["card"]["payload"]["failure_summary"]["latest_error"]
        assert set(run["card"]["actions"]) == {"continue_repair", "guided_repair", "rebuild", "extend_auto_repair"}
        assert run["version_id"] is None
        assert owner.get(f"/api/projects/{project_id}").json()["versions"] == []
        log = owner.get(f"/api/runs/{run_id}/build-log")
        assert log.status_code == 200
        assert "error TS" in log.text and "npm run build" in log.text
        assert other.get(f"/api/runs/{run_id}/build-log").status_code == 404
        card = {"card_id": run["card_id"], "spec_version": run["spec_version"]}
        code_calls = len([call for call in broken_model.calls if call[0] == "code_loop"])
        assert other.post(f"/api/runs/{run_id}/decisions", json={**card, "action": "rebuild"}).status_code == 404
        first = owner.post(f"/api/runs/{run_id}/decisions", json={**card, "action": "rebuild"}, headers={"Idempotency-Key": "rebuild-once"})
        assert first.status_code == 202
        repeated = owner.post(f"/api/runs/{run_id}/decisions", json={**card, "action": "rebuild"}, headers={"Idempotency-Key": "rebuild-once"})
        assert repeated.json()["decision_id"] == first.json()["decision_id"]
        retry = wait_status(owner, run_id, "awaiting_repair", timeout=60)
        assert retry["spec_version"] > run["spec_version"]
        assert retry["card"]["payload"]["manual_rounds"] == 1
        assert len(retry["card"]["payload"]["failure_summary"]["attempts"]) == 2
        assert len([call for call in broken_model.calls if call[0] == "code_loop"]) == code_calls
        assert owner.post(f"/api/runs/{run_id}/decisions", json={**card, "action": "continue_repair"}).status_code == 409
        assert owner.post(f"/api/runs/{run_id}/decisions", json={"card_id": retry["card_id"], "spec_version": retry["spec_version"],
            "action": "guided_repair", "feedback": " "}).status_code == 422
        repair_model = CapturedRepairModel()
        app.state.workflow.model = repair_model
        guided = owner.post(f"/api/runs/{run_id}/decisions", json={"card_id": retry["card_id"], "spec_version": retry["spec_version"],
            "action": "guided_repair", "feedback": "修复 TypeScript 语法错误"})
        assert guided.status_code == 202
        done = wait_status(owner, run_id, "completed", timeout=90)
        assert done["version_id"]
        assert "修复 TypeScript 语法错误" in repair_model.code_prompt


def test_terminal_build_checkpoint_can_be_reopened_only_by_explicit_owner_action(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=0), model=BrokenBuildModel())
    with TestClient(app) as owner, TestClient(app) as other:
        project_id = owner.post("/api/projects", json={"title": "旧构建失败"}).json()["id"]
        other.post("/api/projects", json={"title": "其他项目"})
        run_id = owner.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可点击的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(owner, run_id, "awaiting_clarification")
        owner.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarification["card_id"],
            "spec_version": clarification["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}})
        plan = wait_status(owner, run_id, "awaiting_plan")
        owner.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
            "spec_version": plan["spec_version"], "action": "approve_plan"})
        pending = wait_status(owner, run_id, "awaiting_repair", timeout=60)
        config = {"configurable": {"thread_id": run_id}}
        app.state.workflow.graph.update_state(config, {}, as_node="commit_version")
        assert app.state.workflow.graph.get_state(config).next == ()
        old_card = {**pending["card"], "status": "failed", "actions": []}
        app.state.store.update_run(run_id, status="failed", phase="NeedsUser", card_json=dumps(old_card))
        observed = owner.get(f"/api/runs/{run_id}").json()
        assert observed["status"] == "failed"
        assert observed["card"]["actions"] == ["open_repair"]
        assert observed["card"]["payload"]["failure_summary"]["attempts"]
        assert app.state.store.get_run(run_id)["status"] == "failed", "read must not resume the graph"
        assert other.post(f"/api/runs/{run_id}/offer-repair").status_code == 404
        reopened = owner.post(f"/api/runs/{run_id}/offer-repair")
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "awaiting_repair"
        assert app.state.workflow.graph.get_state(config).next == ("wait_repair",)
        assert owner.post(f"/api/runs/{run_id}/offer-repair").json()["card_id"] == reopened.json()["card_id"]
        app.state.workflow.model = FakeModel()
        card = reopened.json()
        resumed = owner.post(f"/api/runs/{run_id}/decisions", json={"card_id": card["card_id"],
            "spec_version": card["spec_version"], "action": "continue_repair"})
        assert resumed.status_code == 202
        assert wait_status(owner, run_id, "completed", timeout=90)["version_id"]


def test_environment_failure_offers_rebuild_without_source_repair(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    project = app.state.store.create_project("owner", "环境故障")
    run, _ = app.state.store.create_run(project["id"], "做一个可点击的计数器网页应用", "one")
    result = {"ok": False, "environment_failure": True, "diagnostics": "npm could not start",
              "steps": [{"command": "npm run build", "exit_code": -1, "seconds": 0.1}]}
    from backend.workflow import classify_build_failure
    diagnosis = classify_build_failure(result, run["id"])
    app.state.store.update_run(run["id"], event_type="build_result", event_payload={"ok": False,
        "steps": result["steps"], "diagnostics": result["diagnostics"]})
    app.state.workflow.needs_user({"run_id": run["id"], "build_result": result, "diagnosis": diagnosis, "fix_rounds": 0})
    card = app.state.store.get_run(run["id"])["card"]
    assert diagnosis["repairable"] is False
    assert card["actions"] == ["rebuild"]
    assert "构建环境" in card["payload"]["failure_summary"]["cause"]
    app.state.workflow.executor.shutdown(wait=False, cancel_futures=True)
    app.state.workflow.checkpoint_connection.close()


def test_legacy_server_storage_plan_cannot_be_silently_repaired(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    project = app.state.store.create_project("owner", "旧计划")
    run, _ = app.state.store.create_run(project["id"], "做一个可点击的计数器网页应用", "one")
    config = {"configurable": {"thread_id": run["id"]}}
    plan = {"title": "旧计数器", "pages": [], "features": ["从服务端数据接口读取计数"],
            "data_model": ["通过 appData 保存计数"], "acceptance": ["刷新后从服务器读回计数"],
            "tasks": ["生成源码"], "limitations": []}
    build = {"ok": False, "diagnostics": "src/App.tsx(1,1): error TS2307: Cannot find module './appData'",
             "steps": [{"command": "npm run build", "exit_code": 1, "seconds": 0.1}]}
    app.state.workflow.graph.update_state(config, {"run_id": run["id"], "project_id": project["id"],
        "request_text": run["request_text"], "plan": plan, "build_result": build}, as_node="commit_version")
    card = app.state.workflow._failure_card(run["id"], "构建失败", build["steps"])
    app.state.store.update_run(run["id"], status="failed", phase="NeedsUser", card_json=dumps(card))
    presented = app.state.workflow.present_run(app.state.store.get_run(run["id"]))
    assert "localStorage" in presented["card"]["payload"]["recovery_blocker"]
    assert "open_repair" not in presented["card"]["actions"]
    with pytest.raises(ValueError, match="localStorage"):
        app.state.workflow.offer_repair(run["id"])
    app.state.workflow.executor.shutdown(wait=False, cancel_futures=True)
    app.state.workflow.checkpoint_connection.close()


class BlockingClarifyModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "clarify":
            self.entered.set()
            if not self.release.wait(10):
                raise TimeoutError("test failed to release blocking model")
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_cancel_during_model_call_remains_cancelled(tmp_path: Path):
    model = BlockingClarifyModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    try:
        with TestClient(app) as client:
            project_id = client.post("/api/projects", json={"title": "取消测试"}).json()["id"]
            run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可点击的计数器网页应用"}).json()["run"]["id"]
            assert model.entered.wait(5)
            assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
            model.release.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and run_id in app.state.workflow.queued:
                time.sleep(0.05)
            run = client.get(f"/api/runs/{run_id}").json()
            assert run["status"] == "cancelled"
            assert run["version_id"] is None
    finally:
        model.release.set()
