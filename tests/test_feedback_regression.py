"""Regression for the conversation timeline and compact model planning budget.

All API tests use a fake model and an isolated database; no paid calls occur.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import shutil
import socket
import threading
import time

import uvicorn

from fastapi.testclient import TestClient
import pytest

from backend.api import create_app
from backend.model import ModelGateway
from backend.settings import Settings
from backend.store import Store
from backend.workflow import normalize_plan
from tests.test_mvp1 import FakeModel, wait_status


class PlanBudgetModel(FakeModel):
    def __init__(self) -> None:
        super().__init__()
        self.plan_limits: list[int] = []

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "plan":
            self.plan_limits.append(max_tokens)
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_project_decision_timeline_is_persistent_ordered_and_private(tmp_path: Path):
    model = PlanBudgetModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    with TestClient(app) as owner, TestClient(app) as outsider:
        project_id = owner.post("/api/projects", json={"title": "时间线项目"}).json()["id"]
        other_project_id = outsider.post("/api/projects", json={"title": "其他访客项目"}).json()["id"]
        created = owner.post(
            f"/api/projects/{project_id}/runs",
            json={"request_text": "做一个可以点击按钮递增的中文计数器网页"},
        )
        assert created.status_code == 201
        run_id = created.json()["run"]["id"]
        clarification = wait_status(owner, run_id, "awaiting_clarification")
        question = clarification["card"]["payload"]["questions"][0]
        first_body = {
            "card_id": clarification["card_id"],
            "spec_version": clarification["spec_version"],
            "action": "confirm_clarification",
            "answers": {question["id"]: "从 3 开始"},
        }
        first = owner.post(
            f"/api/runs/{run_id}/decisions", json=first_body,
            headers={"Idempotency-Key": "timeline-confirm"},
        )
        assert first.status_code == 202
        replay = owner.post(
            f"/api/runs/{run_id}/decisions", json=first_body,
            headers={"Idempotency-Key": "timeline-confirm"},
        )
        assert replay.status_code == 202
        assert replay.json()["decision_id"] == first.json()["decision_id"]

        plan = wait_status(owner, run_id, "awaiting_plan")
        second = owner.post(
            f"/api/runs/{run_id}/decisions",
            json={"card_id": plan["card_id"], "spec_version": plan["spec_version"],
                  "action": "revise_plan", "feedback": "把按钮放在数字下面"},
            headers={"Idempotency-Key": "timeline-revise"},
        )
        assert second.status_code == 202
        snapshot = owner.get(f"/api/projects/{project_id}")
        assert snapshot.status_code == 200
        decisions = snapshot.json()["decisions"]
        assert [item["id"] for item in decisions] == [first.json()["decision_id"], second.json()["decision_id"]]
        assert [item["action"] for item in decisions] == ["confirm_clarification", "revise_plan"]
        assert all(item["run_id"] == run_id and item["created_at"] for item in decisions)
        assert decisions[0]["payload"] == {"answers": {question["id"]: "从 3 开始"}}
        assert decisions[1]["payload"] == {"feedback": "把按钮放在数字下面"}
        assert all(set(item) == {"id", "run_id", "card_id", "spec_version", "action", "payload", "created_at"}
                   for item in decisions), "project snapshot must not expose internal decision bookkeeping"
        assert model.plan_limits and all(limit == 4000 for limit in model.plan_limits)

        assert owner.get(f"/api/projects/{other_project_id}").status_code == 404
        assert outsider.get(f"/api/projects/{project_id}").status_code == 404
        assert outsider.get(f"/api/runs/{run_id}").status_code == 404
        assert outsider.get(f"/api/runs/{run_id}/events").status_code == 404
        assert outsider.get(f"/api/projects/{other_project_id}").json()["decisions"] == []
        assert owner.get(f"/api/projects/{project_id}").json()["decisions"] == decisions


def test_plan_gateway_disables_deep_thinking_but_keeps_json_budget(tmp_path: Path):
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("isolated-owner", "计划预算")
    run, _ = store.create_run(project["id"], "制作一个带筛选的待办网页", "plan-budget")
    gateway = ModelGateway(Settings(
        data_dir=tmp_path, model_api_key="test-only",
        model_reasoning_effort="high", model_code_reasoning_effort="none",
    ), store)
    observed: list[dict] = []

    def complete(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(total_tokens=15, prompt_tokens=5, completion_tokens=10),
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"待办"}'), finish_reason="stop")],
        )

    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    assert gateway.generate(run["id"], "plan", "first-plan", "system", "user", max_tokens=4000) == {"title": "待办"}
    assert len(observed) == 1
    assert observed[0]["reasoning_effort"] == "none"
    assert observed[0]["extra_body"]["thinking"] == {"type": "disabled"}
    assert observed[0]["max_tokens"] == 4000
    assert observed[0]["response_format"] == {"type": "json_object"}
    response_events = [event for event in store.events(run["id"]) if event["type"] == "model_response"]
    assert len(response_events) == 1
    assert response_events[0]["payload"]["reasoning_effort"] == "none"


@pytest.mark.parametrize("constraint", ["禁止使用 localStorage", "不使用 localStorage 保存任务"])
def test_plan_storage_negation_does_not_trigger_old_template_guard(constraint: str):
    raw = {
        "title": "待办应用", "pages": [{"name": "首页", "purpose": "管理任务"}],
        "features": ["新增和完成任务"], "data_model": ["任务有标题与完成状态"],
        "acceptance": ["刷新后任务仍可读取"], "tasks": [constraint],
    }
    assert normalize_plan(raw)["tasks"] == [constraint]


def test_plan_local_storage_is_allowed_and_server_storage_is_rejected():
    raw = {
        "title": "待办应用", "pages": [{"name": "首页", "purpose": "管理任务"}],
        "features": ["使用 localStorage 保存数据"], "data_model": ["任务有标题与完成状态"],
        "acceptance": ["刷新后任务仍可读取"], "tasks": ["实现任务列表"],
    }
    assert normalize_plan(raw)["features"] == ["使用 localStorage 保存数据"]
    raw["features"] = ["使用服务端数据库保存数据"]
    with pytest.raises(ValueError, match="localStorage"):
        normalize_plan(raw)


def test_built_workbench_focuses_conversation_until_a_version_exists(tmp_path: Path):
    playwright = pytest.importorskip("playwright.sync_api", reason="browser regression requires Playwright")
    dist = Path(__file__).resolve().parents[1] / "web" / "dist" / "index.html"
    if not dist.is_file():
        pytest.skip("run npm run build in web/ before the built-browser regression")
    executable = next((path for path in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ) if path.is_file()), None)
    if executable is None:
        found = shutil.which("chromium") or shutil.which("google-chrome")
        if found is None:
            pytest.skip("a local Chromium-family browser is required")
        executable = Path(found)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "isolated workbench did not start"
        base = f"http://127.0.0.1:{port}"
        with playwright.sync_playwright() as engine:
            browser = engine.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={"width": 1280, "height": 720})
                project_response = context.request.post(f"{base}/api/projects", data={"title": "对话回归"})
                assert project_response.status == 201
                project_id = project_response.json()["id"]
                run_response = context.request.post(
                    f"{base}/api/projects/{project_id}/runs",
                    data={"request_text": "做一个可以点击按钮递增的中文计数器网页"},
                )
                assert run_response.status == 201
                run_id = run_response.json()["run"]["id"]
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    run = context.request.get(f"{base}/api/runs/{run_id}").json()
                    if run["status"] == "awaiting_clarification":
                        break
                    time.sleep(0.1)
                assert run["status"] == "awaiting_clarification"

                page = context.new_page()
                page.goto(f"{base}/projects/{project_id}")
                page.locator(".decision-card").wait_for(state="visible")
                composer = page.locator("#new-run-request")
                assert composer.is_visible(), "the message input stays available within the active decision"
                assert page.locator(".decision-turn .decision-composer #new-run-request").count() == 1
                assert page.locator("#conversation-pane > .new-run-card").count() == 0
                assert page.locator(".decision-card textarea").count() == 0
                assert page.locator(".decision-card .card-summary").count() == 0
                assert "先把关键问题说清楚" not in page.locator(".decision-card").inner_text()
                assert "建议答案需要明确点击" not in page.locator(".decision-card").inner_text()
                assert composer.input_value() == "", "the card must not turn the default composer into an editor"
                assert page.get_by_role("button", name="发送", exact=True).is_disabled()
                page.get_by_role("button", name="修改原需求").click()
                assert composer.input_value() == run["request_text"]
                assert page.get_by_role("button", name="取消编辑").is_visible()
                edited = "做一个可以点击按钮递增的中文计数器网页，并加入重置按钮"
                composer.fill(edited)
                page.reload()
                page.get_by_role("button", name="修改原需求").click()
                composer = page.locator("#new-run-request")
                page.wait_for_function("value => document.querySelector('#new-run-request')?.value === value", arg=edited)
                assert composer.input_value() == edited, "an unsent edit survives refresh"
                assert page.get_by_role("button", name="发送", exact=True).is_enabled()
                page.get_by_role("button", name="发送", exact=True).click()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    revised = context.request.get(f"{base}/api/runs/{run_id}").json()
                    if revised["status"] == "awaiting_clarification" and revised["card_id"] != run["card_id"]:
                        break
                    time.sleep(0.1)
                assert revised["status"] == "awaiting_clarification" and revised["card_id"] != run["card_id"]
                assert revised["request_text"] == edited
                page.reload()
                page.locator(".decision-card").wait_for(state="visible")
                assert page.locator(".workspace").evaluate("element => element.classList.contains('right-collapsed')")
                assert not page.locator("#results-pane").is_visible()
                assert page.locator("#conversation-pane").bounding_box()["width"] > 900
                conversation = page.locator("#conversation-pane").inner_text()
                assert "过程记录" not in conversation and "运行详情" not in conversation
                assert "Token" not in conversation and "模型调用" not in conversation
                assert "做一个可以点击按钮递增的中文计数器网页" in conversation

                assert composer.input_value() == ""
                composer.fill("还需要一个减一按钮")
                page.get_by_role("button", name="发送", exact=True).click()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    supplemented = context.request.get(f"{base}/api/runs/{run_id}").json()
                    if supplemented["status"] == "awaiting_clarification" and supplemented["card_id"] != revised["card_id"]:
                        break
                    time.sleep(0.1)
                assert supplemented["request_text"] == edited + "\n补充要求：还需要一个减一按钮"
                page.reload()
                question = supplemented["card"]["payload"]["questions"][0]
                page.locator(f"#answer-{question['id']}").fill("从 3 开始")
                page.get_by_role("button", name="发送", exact=True).click()
                page.get_by_text("已提交澄清卡答案", exact=False).wait_for(state="visible")
                page.get_by_text("从 3 开始", exact=False).wait_for(state="visible")
                page.locator(".plan-approval-choice").wait_for(state="visible")
                assert composer.is_visible() and page.locator(".decision-turn .decision-composer textarea").count() == 1
                assert composer.input_value() == ""
                composer.fill("把按钮放在数字下面")
                page.reload()
                page.wait_for_function("value => document.querySelector('#new-run-request')?.value === value", arg="把按钮放在数字下面")
                assert page.locator("#new-run-request").input_value() == "把按钮放在数字下面"
                page.get_by_text("已提交澄清卡答案", exact=False).wait_for(state="visible")
                assert not page.locator("#results-pane").is_visible()
                assert page.locator(".conversation-turn").count() >= 2
                assert "过程记录" not in page.locator("#conversation-pane").inner_text()
                page.get_by_role("button", name="发送", exact=True).click()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    planned = context.request.get(f"{base}/api/runs/{run_id}").json()
                    if planned["status"] == "awaiting_plan" and planned["spec_version"] > supplemented["spec_version"] + 1:
                        break
                    time.sleep(0.1)
                assert planned["status"] == "awaiting_plan"
                assert planned["spec_version"] > supplemented["spec_version"] + 1
                page.evaluate("id => sessionStorage.setItem('myatom.request-drafts.v1', JSON.stringify({[id]: {bad: true}}))", project_id)
                page.reload()
                page.locator(".decision-card").wait_for(state="visible")
                assert page.locator("#new-run-request").is_visible(), "invalid local draft data must not break the workbench"
                assert page.locator(".decision-turn .decision-composer #new-run-request").count() == 1
                assert page.locator("#conversation-pane > .new-run-card").count() == 0
                assert not page.locator(".decision-details .plan-view").is_visible(), "full technical plan starts collapsed"
                assert "关联当前计划卡" not in page.locator("#conversation-pane").inner_text()
                page.locator(".plan-approval-choice").click()
                assert page.locator("#new-run-request").input_value() == "按这版计划开始生成"
                assert context.request.get(f"{base}/api/runs/{run_id}").json()["approved_spec_version"] is None
                for width, height in ((1280, 720), (1366, 768), (1440, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.locator(".decision-card").scroll_into_view_if_needed()
                    assert page.locator(".decision-card").is_visible()
                    assert page.get_by_role("button", name="发送", exact=True).is_visible()
                    page.locator("#new-run-request").fill("按这版计划开始生成")
                    assert page.locator(".decision-composer .form-bottom span").inner_text() == f"{len('按这版计划开始生成')}/2000"
                    assert page.get_by_role("button", name="发送", exact=True).is_enabled()
                    page.locator("#new-run-request").focus()
                    page.keyboard.press("Tab")
                    assert page.get_by_role("button", name="发送", exact=True).evaluate(
                        "element => element === document.activeElement"
                    ), f"send button not next in keyboard order at {width}x{height}"
                composer.fill("请把按钮放到页面顶部")
                composer.press("Shift+Enter")
                assert composer.input_value() == "请把按钮放到页面顶部\n"
                before = context.request.get(f"{base}/api/runs/{run_id}/messages").json()["messages"]
                composer.press("Enter")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    after = context.request.get(f"{base}/api/runs/{run_id}/messages").json()["messages"]
                    if len(after) > len(before):
                        break
                    time.sleep(0.1)
                assert len(after) == len(before) + 1, "Enter submits one message"
                assert after[-1]["text"] == "请把按钮放到页面顶部"
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
