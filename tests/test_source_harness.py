from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings
from backend.source_harness import repair_feedback, source_violation_code
from backend.runner import LocalRunner, UnsafeSource
from backend.store import Store
from backend.workflow import source_failure_summary
from tests.test_build_harness import failed_build
from tests.test_mvp1 import FakeModel, wait_status


def approved_run(client: TestClient, request_text: str) -> tuple[str, str]:
    project_id = client.post("/api/projects", json={"title": "源码反馈"}).json()["id"]
    run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": request_text}).json()["run"]["id"]
    clarify = wait_status(client, run_id, "awaiting_clarification")
    assert client.post(f"/api/runs/{run_id}/decisions", json={
        "card_id": clarify["card_id"], "spec_version": clarify["spec_version"],
        "action": "confirm_clarification", "answers": {"q1": "0"},
    }).status_code == 202
    plan = wait_status(client, run_id, "awaiting_plan")
    assert client.post(f"/api/runs/{run_id}/decisions", json={
        "card_id": plan["card_id"], "spec_version": plan["spec_version"], "action": "approve_plan",
    }).status_code == 202
    return project_id, run_id


class CaptureRepairModel(FakeModel):
    def __init__(self, first_failure: str):
        super().__init__()
        self.first_failure = first_failure
        self.code_requests: list[tuple[str, str, dict]] = []

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        result = super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)
        if node != "code_loop":
            return result
        if not self.code_requests:
            if self.first_failure == "hook":
                result["files"]["src/hooks/useAppState.ts"] = (
                    "export function useAppState() { setCount((prev) => {\n"
                    " persistTasks();\n return prev + 1;\n }); return { count: 0, increment: () => {} } }")
            elif self.first_failure == "layout":
                result["files"]["package.json"] = "{}"
        self.code_requests.append((system, user, result))
        return result


def test_source_validation_repairs_only_named_file(tmp_path: Path):
    model = CaptureRepairModel("hook")
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    with TestClient(app) as client:
        project_id, run_id = approved_run(client, "做一个可点击加一的计数器")
        completed = wait_status(client, run_id, "completed", timeout=90)
        assert completed["fix_rounds"] == 1
        assert len(model.code_requests) == 2
        system, prompt, response = model.code_requests[1]
        assert "路径必须且只能是 src/hooks/useAppState.ts" in system
        assert "原始需求：做一个可点击加一的计数器" in prompt
        assert "React 状态更新函数" in prompt
        assert set(response["files"]) == {"src/hooks/useAppState.ts"}
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        failure = next(event for event in events if event["type"] == "source_validation_failed")
        assert failure["payload"]["target_files"] == ["src/hooks/useAppState.ts"]
        assert "React 状态更新函数" in failure["payload"]["issues"][0]["feedback"]
        passed = [event for event in events if event["type"] == "source_validation_passed"][-1]
        assert passed["payload"]["mode"] == "partial"
        assert passed["payload"]["modified_files"] == ["src/hooks/useAppState.ts"]
        state = app.state.workflow.graph.get_state({"configurable": {"thread_id": run_id}}).values
        assert state["source_candidate_ref"] == "candidate-2"
        assert state["repair_failure_history"] == [["source:updater_side_effect:src/hooks/useAppState.ts"]]
        assert len(client.get(f"/api/projects/{project_id}").json()["versions"]) == 1


def test_source_feedback_keeps_concrete_validator_reason_and_classifies_capabilities():
    feedback = repair_feedback([{"code": "invalid_import", "file": "src/App.tsx",
                                 "detail": "导入未生成的项目文件：./missing"}], origin="source")
    assert feedback["target_files"] == ["src/App.tsx"]
    assert feedback["issues"][0]["feedback"] == "导入未生成的项目文件：./missing"
    assert source_violation_code(UnsafeSource("生成代码包含 MVP1 不允许的能力：fetch")) == "unsupported_capability"
    assert source_violation_code(UnsafeSource("生成代码包含 MVP1 不允许的能力：eval(")) == "unsafe_capability"


def test_manual_source_summary_names_the_file_and_problem():
    summary = source_failure_summary([{"type": "source_validation_failed", "payload": {
        "issues": [{"code": "invalid_import", "file": "src/App.tsx",
                    "feedback": "导入未生成的项目文件：./missing"}],
    }}], "源码仍未通过", 1)
    assert "src/App.tsx" in summary["latest_error"]
    assert "./missing" in summary["latest_error"]


def test_hook_count_feedback_includes_required_hook(tmp_path: Path):
    runner = LocalRunner(Settings(data_dir=tmp_path), Store(tmp_path / "app.sqlite3"))
    files = {
        "src/App.tsx": "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { useAppState(); return <main /> }",
        "src/app.css": "main { color: black }",
        "readme.md": "# 测试",
        **{f"src/hooks/{name}.ts": f"export function {name}() {{ return null }}" for name in
           ("useAppState", "useTimer", "useTasks", "useStorage", "useEffects")},
    }
    issues = runner.inspect_generated(files)
    assert any(issue["code"] == "invalid_layout" and issue["file"] is None and
               "hook 数量 5 个" in issue["detail"] and "最多 4 个" in issue["detail"] for issue in issues)


def test_unlocatable_layout_error_regenerates_full_map(tmp_path: Path):
    model = CaptureRepairModel("layout")
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    with TestClient(app) as client:
        _, run_id = approved_run(client, "做一个可点击加一的计数器")
        wait_status(client, run_id, "completed", timeout=90)
        assert len(model.code_requests) == 2
        assert "本次返回完整 files 路径映射" in model.code_requests[1][0]
        assert set(model.code_requests[1][2]["files"]) == {
            "src/App.tsx", "src/app.css", "src/hooks/useAppState.ts", "readme.md"}
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        failure = next(event for event in events if event["type"] == "source_validation_failed")
        assert failure["payload"]["target_files"] == []
        assert failure["payload"]["mode"] == "full"


def test_source_and_build_repairs_share_limit(tmp_path: Path):
    model = CaptureRepairModel("hook")
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=2), model=model)
    builds = 0

    def fail_build(_project_id: str, _run_id: str) -> dict:
        nonlocal builds
        builds += 1
        return failed_build("src/App.tsx(1,8): error TS2304: Cannot find name 'missing'.")

    app.state.workflow.runner.build = fail_build
    with TestClient(app) as client:
        _, run_id = approved_run(client, "做一个可点击加一的计数器")
        paused = wait_status(client, run_id, "awaiting_repair")
        assert paused["fix_rounds"] == 2
        assert builds == 2
        assert len(model.code_requests) == 3
        assert "路径必须且只能是 src/App.tsx" in model.code_requests[2][0]
        assert "error TS2304" in model.code_requests[2][1]
        assert paused["card"]["payload"]["stop_code"] == "repair_limit"
        state = app.state.workflow.graph.get_state({"configurable": {"thread_id": run_id}}).values
        assert len(state["repair_failure_history"]) == 3


class ThreeFailuresThenSuccess(FakeModel):
    def __init__(self):
        super().__init__()
        self.code_calls = 0

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        result = super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)
        if node == "code_loop":
            self.code_calls += 1
            if self.code_calls <= 3:
                result["files"]["src/hooks/useAppState.ts"] = (
                    "export function useAppState() { setCount((prev) => {\n"
                    " persistTasks();\n return prev + 1;\n }); return { count: 0, increment: () => {} } }")
        return result


def test_source_checkpoint_survives_restart_and_manual_repair(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    model = ThreeFailuresThenSuccess()
    first = create_app(settings, model=model)
    with TestClient(first) as client:
        project_id, run_id = approved_run(client, "做一个可点击加一的计数器")
        guest_cookie = client.cookies.get("myatom_guest")
        paused = wait_status(client, run_id, "awaiting_repair")
        assert model.code_calls == 3
        state = first.state.workflow.graph.get_state({"configurable": {"thread_id": run_id}}).values
        assert state["source_feedback"]["target_files"] == ["src/hooks/useAppState.ts"]
        assert state["candidate_number"] == 3
        assert state["source_candidate_ref"] == "candidate-3"
    second = create_app(settings, model=model)
    with TestClient(second) as client:
        client.cookies.set("myatom_guest", guest_cookie)
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "awaiting_repair"
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": run["card_id"], "spec_version": run["spec_version"],
            "action": "continue_repair",
        }).status_code == 202
        done = wait_status(client, run_id, "completed", timeout=90)
        assert done["version_id"]
        assert model.code_calls == 4
        assert len(client.get(f"/api/projects/{project_id}").json()["versions"]) == 1


class BadPartialShape(FakeModel):
    def __init__(self):
        super().__init__()
        self.code_requests: list[tuple[str, dict]] = []

    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        result = super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)
        if node == "code_loop":
            if not self.code_requests:
                result["files"]["src/hooks/useAppState.ts"] = (
                    "export function useAppState() { setCount((prev) => {\n"
                    " persistTasks();\n return prev + 1;\n }); return { count: 0, increment: () => {} } }")
            elif len(self.code_requests) == 1:
                # A full response cannot silently overwrite unaffected files.
                result["files"] = FakeModel().generate(run_id, node, cache_key, "", user)["files"]
            self.code_requests.append((system, result))
        return result


def test_partial_response_with_extra_files_falls_back_to_full_regeneration(tmp_path: Path):
    model = BadPartialShape()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=model)
    with TestClient(app) as client:
        _, run_id = approved_run(client, "做一个可点击加一的计数器")
        wait_status(client, run_id, "completed", timeout=90)
        assert len(model.code_requests) == 3
        assert "路径必须且只能是 src/hooks/useAppState.ts" in model.code_requests[1][0]
        assert "本次返回完整 files 路径映射" in model.code_requests[2][0]
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        failures = [event["payload"] for event in events if event["type"] == "source_validation_failed"]
        assert failures[1]["reason_code"] == "invalid_partial_files"
        assert failures[1]["target_files"] == []
        assert len([event for event in events if event["type"] == "files_written"]) == 1
