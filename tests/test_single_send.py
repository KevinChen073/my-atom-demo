"""Single send: persistent messages, guarded decisions, and replay safety."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.messages import interpret_submission
from backend.settings import Settings
from tests.test_mvp1 import FakeModel, wait_status


def send(client: TestClient, run: dict, text: str = "", answers: dict[str, str] | None = None,
         *, submission_id: str | None = None, key: str | None = None,
         reply_to: str | None = None):
    submission_id = submission_id or str(uuid.uuid4())
    key = key or submission_id
    return client.post(f"/api/runs/{run['id']}/messages", headers={"Idempotency-Key": key}, json={
        "submission_id": submission_id, "card_ref": {"card_id": run["card_id"], "spec_version": run["spec_version"]},
        "text": text, "answers": answers or {}, "reply_to_interpretation_id": reply_to,
    })


def wait_message(client: TestClient, run_id: str, submission_id: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = client.get(f"/api/runs/{run_id}/messages/{submission_id}").json()
        if message["status"] != "interpreting":
            return message
        time.sleep(0.02)
    raise AssertionError("message remained interpreting")


def test_single_send_requires_explicit_plan_approval_and_persists_original_message(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as client, TestClient(app) as stranger:
        project = client.post("/api/projects", json={"title": "单一发送"}).json()
        run_id = client.post(f"/api/projects/{project['id']}/runs", json={"request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]["id"]
        clarify = wait_status(client, run_id, "awaiting_clarification")
        question = clarify["card"]["payload"]["questions"][0]
        missing = send(client, clarify, "", {})
        assert missing.status_code == 422
        submission_id = str(uuid.uuid4())
        answered = send(client, clarify, "", {question["id"]: question["default"]}, submission_id=submission_id)
        assert answered.status_code == 202
        assert wait_message(client, run_id, submission_id)["committed_action"] == "confirm_clarification"
        plan = wait_status(client, run_id, "awaiting_plan")
        replay = send(client, clarify, "", {question["id"]: question["default"]}, submission_id=submission_id)
        assert replay.status_code == 202 and replay.json()["created"] is False
        assert stranger.get(f"/api/runs/{run_id}/messages").status_code in {401, 404}

        vague_id = str(uuid.uuid4())
        vague = send(client, plan, "可以", submission_id=vague_id)
        assert vague.status_code == 202
        assert wait_message(client, run_id, vague_id)["status"] == "needs_clarification"
        assert client.get(f"/api/runs/{run_id}").json()["approved_spec_version"] is None
        assert not (tmp_path / "projects" / project["id"] / "runs" / run_id / "workspace").exists()
        duplicate = send(client, plan, "可以", submission_id=vague_id)
        assert duplicate.status_code == 202 and duplicate.json()["created"] is False
        assert send(client, plan, "确认", submission_id=vague_id).status_code == 409

        question_id = str(uuid.uuid4())
        assert send(client, plan, "如果能跨设备同步，就按这版计划开始生成", submission_id=question_id).status_code == 202
        question_result = wait_message(client, run_id, question_id)
        assert question_result["status"] == "needs_clarification"
        assert "不支持跨设备同步" in question_result["reply"]
        assert client.get(f"/api/runs/{run_id}").json()["approved_spec_version"] is None

        changed_id = str(uuid.uuid4())
        assert send(client, plan, "把首页改成绿色，然后按这版计划开始生成", submission_id=changed_id,
                    reply_to=vague_id).status_code == 202
        assert wait_message(client, run_id, changed_id)["committed_action"] == "revise_plan"
        revised = wait_status(client, run_id, "awaiting_plan")
        deadline = time.monotonic() + 5
        while revised["spec_version"] == plan["spec_version"] and time.monotonic() < deadline:
            time.sleep(0.05)
            revised = client.get(f"/api/runs/{run_id}").json()
        assert revised["spec_version"] > plan["spec_version"]
        assert send(client, plan, "按这版计划开始生成").status_code == 409
        assert send(client, revised, "按这版计划开始生成", reply_to=vague_id).status_code == 409
        assert revised["approved_spec_version"] is None

        approved_id = str(uuid.uuid4())
        assert send(client, revised, "按这版计划开始生成", submission_id=approved_id).status_code == 202
        approved = wait_message(client, run_id, approved_id)
        assert approved["status"] == "committed" and approved["committed_action"] == "approve_plan"
        assert wait_status(client, run_id, "completed", timeout=90)["version_id"]
        history = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
        assert [item["text"] for item in history] == ["", "可以", "如果能跨设备同步，就按这版计划开始生成", "把首页改成绿色，然后按这版计划开始生成", "按这版计划开始生成"]
        assert len([item for item in history if item["committed_action"] == "approve_plan"]) == 1


def test_stage_gate_rejects_vague_or_conflicting_requests():
    model = FakeModel()
    run = {"id": str(uuid.uuid4()), "request_text": "做一个中文计数器网页应用", "status": "awaiting_plan",
           "card": {"type": "build_plan", "actions": ["revise_plan", "approve_plan"]}}
    def result(text: str) -> str | None:
        return interpret_submission({"id": str(uuid.uuid4()), "text": text, "answers": {}}, run, model)[0]
    for vague in ("可以", "确认", "继续", "好"):
        assert result(vague) is None
    assert result("把首页改成绿色，然后按这版计划开始生成") == "revise_plan"
    assert result("如果支持跨设备同步，就按这版计划开始生成") is None
    assert result("按这版计划开始生成") == "approve_plan"
    run["status"] = "awaiting_repair"
    run["card"] = {"type": "test_result", "actions": ["rebuild"]}
    assert result("继续") is None
    assert result("再修复一次") is None  # environment failure cannot enter code repair
    assert result("用现有代码重新构建，不改文件") == "rebuild"
    assert result("再修复一次，并用现有代码重新构建，不改文件") is None
    run["status"] = "awaiting_clarification"
    run["card"] = {"type": "clarification", "payload": {"questions": [
        {"id": "required", "required": True}, {"id": "optional", "required": False}]}}
    assert interpret_submission({"id": str(uuid.uuid4()), "text": "", "answers": {"required": "1"}}, run, model)[0] == "confirm_clarification"
    assert interpret_submission({"id": str(uuid.uuid4()), "text": "", "answers": {"optional": "2"}}, run, model)[0] is None


def test_restart_recovers_persisted_uninterpreted_message(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=FakeModel())
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "恢复待解释消息"}).json()
        run_id = client.post(f"/api/projects/{project['id']}/runs", json={"request_text": "做一个中文计数器网页应用"}).json()["run"]["id"]
        clarify = wait_status(client, run_id, "awaiting_clarification")
        question = clarify["card"]["payload"]["questions"][0]
        submission_id = str(uuid.uuid4())
        app.state.store.create_submission(run_id, submission_id=submission_id, key=submission_id,
            card_id=clarify["card_id"], spec_version=clarify["spec_version"], text="",
            answers={question["id"]: question["default"]})
        assert app.state.store.get_submission(submission_id)["status"] == "interpreting"
    restarted = create_app(settings, model=FakeModel())
    with TestClient(restarted):
        # Recovery is a storage/workflow property; inspect it through the shared store.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = restarted.state.store.get_submission(submission_id)
            if result["status"] != "interpreting":
                break
            time.sleep(0.03)
        assert result["status"] == "committed"
        assert result["committed_action"] == "confirm_clarification"
        assert len([item for item in restarted.state.store.list_submissions(run_id) if item["committed_action"]]) == 1


def test_two_submissions_for_same_card_commit_only_one_decision(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "并发卡片"}).json()
        run_id = client.post(f"/api/projects/{project['id']}/runs", json={"request_text": "做一个中文计数器网页应用"}).json()["run"]["id"]
        run = wait_status(client, run_id, "awaiting_clarification")
        question = run["card"]["payload"]["questions"][0]
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        for submission_id in ids:
            app.state.store.create_submission(run_id, submission_id=submission_id, key=submission_id,
                card_id=run["card_id"], spec_version=run["spec_version"], text="",
                answers={question["id"]: question["default"]})
        for submission_id in ids:
            app.state.messages.enqueue(submission_id)
        results = [wait_message(client, run_id, submission_id) for submission_id in ids]
        assert sorted(item["status"] for item in results) == ["committed", "rejected"]
        assert len([item for item in results if item["decision_id"]]) == 1
