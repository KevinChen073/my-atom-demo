"""Behavioral checks for bounded automatic build repair and human handoff."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.build_harness import build_repair_feedback, error_fingerprints, repair_stop_reason
from backend.settings import Settings
from tests.test_mvp1 import FakeModel, wait_status


def failed_build(message: str) -> dict:
    return {"ok": False, "diagnostics": message,
            "steps": [{"command": "npm run build", "exit_code": 2, "seconds": 0.1}]}


def wait_exception_code(db_path: Path, run_id: str) -> str:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path) as db:
            row = db.execute("SELECT code FROM exception_records WHERE run_id=? AND code!='build_check_failed'", (run_id,)).fetchone()
        if row:
            return row[0]
        time.sleep(0.02)
    raise AssertionError("build stop was not captured in the administrator exception table")


def test_same_error_after_line_shifts_stops_on_third_build():
    history = [error_fingerprints(failed_build(
        f"src/App.tsx({line},8): error TS2304: Cannot find name 'missing'."), "source_compile")
        for line in (2, 9, 15)]
    assert history[0] == history[1] == history[2]
    assert repair_stop_reason(history[:2], 1, 60) == ("", "")
    assert repair_stop_reason(history, 2, 60)[1] == "no_progress"


def test_recurring_error_stops_at_fifth_nonconsecutive_occurrence():
    a = error_fingerprints(failed_build("src/App.tsx(1,1): error TS2304: Cannot find name 'a'."), "source_compile")
    b = error_fingerprints(failed_build("src/App.tsx(1,1): error TS2304: Cannot find name 'b'."), "source_compile")
    history = [a, b, a, b, a, b, a, b, a]
    assert repair_stop_reason(history[:-1], 7, 60) == ("", "")
    assert repair_stop_reason(history, 8, 60)[1] == "recurring_error"


def test_ts2322_feedback_includes_missing_prop_detail():
    result = failed_build(
        "src/App.tsx(50,13): error TS2322: Type '{ skinId: SkinId; emojis: string[]; "
        "label: string; roundActive: boolean; pulseKey: number; onHit: () => void; }' "
        "is not assignable to type 'IntrinsicAttributes & CharacterProps'.\n"
        "  Property 'pulseKey' does not exist on type 'IntrinsicAttributes & CharacterProps'.\n"
    )
    feedback = build_repair_feedback(result, {"src/App.tsx", "src/components/Character.tsx"})
    assert feedback["mode"] == "partial"
    assert feedback["target_files"] == ["src/App.tsx"]
    assert "Property 'pulseKey' does not exist" in feedback["issues"][0]["feedback"]


def test_vite_wrapper_uses_failure_detail_not_only_generic_heading():
    a = error_fingerprints(failed_build("error during build:\n[vite] Cannot load one.ts"), "source_compile")
    b = error_fingerprints(failed_build("error during build:\n[vite] Cannot load two.ts"), "source_compile")
    assert a != b


def test_sixtieth_repair_is_allowed_and_sixty_first_is_not():
    history = [[f"distinct-{number}"] for number in range(61)]
    assert repair_stop_reason(history[:60], 59, 60) == ("", "")
    assert repair_stop_reason(history, 60, 60)[1] == "repair_limit"


def test_graph_checkpoints_error_history_and_manual_rebuild_stays_manual(tmp_path: Path):
    model = FakeModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=60), model=model)
    calls = 0

    def build(_project_id: str, _run_id: str) -> dict:
        nonlocal calls
        calls += 1
        return failed_build(f"src/App.tsx({calls},8): error TS2304: Cannot find name 'missing'.")

    app.state.workflow.runner.build = build
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "修复循环"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        assert client.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarification["card_id"],
            "spec_version": clarification["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}}).status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert client.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
            "spec_version": plan["spec_version"], "action": "approve_plan"}).status_code == 202
        stopped = wait_status(client, run_id, "awaiting_repair")
        assert calls == 3
        assert stopped["fix_rounds"] == 2
        assert stopped["card"]["payload"]["stop_code"] == "no_progress"
        assert "连续 3 次" in stopped["card"]["payload"]["failure_summary"]["cause"]
        assert stopped["card"]["payload"]["failure_summary"]["total_attempts"] == 3
        assert len(app.state.workflow.graph.get_state({"configurable": {"thread_id": run_id}}).values["build_failure_history"]) == 3
        assert client.get(f"/api/projects/{project_id}").json()["versions"] == []
        assert wait_exception_code(app.state.store.path, run_id) == "build_no_progress"
        code_calls = sum(node == "code_loop" for node, _ in model.calls)
        assert client.post(f"/api/runs/{run_id}/decisions", json={"card_id": stopped["card_id"],
            "spec_version": stopped["spec_version"], "action": "rebuild"}).status_code == 202
        again = wait_status(client, run_id, "awaiting_repair")
        assert again["spec_version"] > stopped["spec_version"]
        assert calls == 4
        assert sum(node == "code_loop" for node, _ in model.calls) == code_calls


def test_graph_allows_sixty_distinct_automatic_repairs(tmp_path: Path):
    model = FakeModel()
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only", max_fix_rounds=60), model=model)
    calls = 0

    def build(_project_id: str, _run_id: str) -> dict:
        nonlocal calls
        calls += 1
        return failed_build(f"src/App.tsx(2,8): error TS2304: Cannot find name 'missing{calls}'.")

    app.state.workflow.runner.build = build
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "上限校验"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一的计数器网页应用"}).json()["run"]["id"]
        clarification = wait_status(client, run_id, "awaiting_clarification")
        client.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarification["card_id"],
            "spec_version": clarification["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}})
        plan = wait_status(client, run_id, "awaiting_plan")
        client.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
            "spec_version": plan["spec_version"], "action": "approve_plan"})
        stopped = wait_status(client, run_id, "awaiting_repair", timeout=45)
        assert calls == 61  # initial build followed by exactly 60 automatic repairs
        assert stopped["fix_rounds"] == 60
        assert stopped["card"]["payload"]["stop_code"] == "repair_limit"
        assert stopped["card"]["payload"]["failure_summary"]["total_attempts"] == 61
        assert sum(node == "code_loop" for node, _ in model.calls) == 61
        assert wait_exception_code(app.state.store.path, run_id) == "build_repair_limit"
