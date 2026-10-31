"""Independent MVP1 contract checks. No test here calls the paid model API."""

from __future__ import annotations

import threading
import time
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError

from backend.api import create_app
from backend.model import BudgetExceeded, ModelGateway
from backend.settings import Settings
from backend.store import Store
from tests.test_mvp1 import FakeModel, wait_status


def new_store_run(tmp_path: Path) -> tuple[Store, str]:
    store = Store(tmp_path / "app.sqlite3")
    project = store.create_project("test-owner", "test")
    run, _ = store.create_run(project["id"], "Build a counter app", "run-key")
    return store, run["id"]


def test_model_hard_budget_stops_before_network(tmp_path: Path):
    store, run_id = new_store_run(tmp_path)
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", max_model_calls=0)
    gateway = ModelGateway(settings, store)
    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_: pytest.fail("network call made after hard budget"))))
    with pytest.raises(BudgetExceeded):
        gateway.generate(run_id, "clarify", "first", "system", "user")
    assert store.get_run(run_id)["model_calls"] == 0


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
    gateway = ModelGateway(Settings(data_dir=tmp_path, model_api_key="test-only", max_total_tokens=40_000), store)
    observed: list[int] = []

    def complete(**kwargs):
        observed.append(kwargs["max_tokens"])
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=10), choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop")])

    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    assert gateway.generate(run_id, "code_loop", "budget", "system", "user", max_tokens=12_000) == {"ok": True}
    assert 512 <= observed[0] < 5_000


def test_plan_retries_when_it_promises_unsupported_browser_storage(tmp_path: Path):
    class StoragePlanModel(FakeModel):
        def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
            value = super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)
            if node == "plan" and cache_key.endswith("-c0"):
                value["features"].append("使用 localStorage 保存数据")
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
        assert "localStorage" not in json.dumps(plan["plan"], ensure_ascii=False)
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
        assert back.status_code == 202
        returned = wait_status(client, run_id, "awaiting_clarification")
        assert returned["spec_version"] > plan["spec_version"]
        assert returned["approved_spec_version"] is None
        assert not workspace.exists()
        stale_plan = client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan",
        })
        assert stale_plan.status_code == 409


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
            return {"app_tsx": "export default function App() { return <main>broken", "app_css": "body { margin: 0; }"}
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_build_failure_has_test_card_authorized_log_and_no_version(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=0), model=BrokenBuildModel())
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
            if run["status"] in {"failed", "completed", "budget_exceeded", "cancelled"}:
                break
            time.sleep(0.15)
        assert run["status"] == "failed"
        assert run["card"]["type"] == "test_result"
        assert run["card"]["status"] == "failed"
        assert run["card"]["payload"]["build"]["ok"] is False
        assert run["card"]["payload"]["diagnostics_ref"] == f"/api/runs/{run_id}/build-log"
        assert run["version_id"] is None
        assert owner.get(f"/api/projects/{project_id}").json()["versions"] == []
        log = owner.get(f"/api/runs/{run_id}/build-log")
        assert log.status_code == 200
        assert "error TS" in log.text and "npm run build" in log.text
        assert other.get(f"/api/runs/{run_id}/build-log").status_code == 404


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
