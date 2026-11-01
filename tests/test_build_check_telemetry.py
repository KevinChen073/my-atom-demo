from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.model import ModelOutputError
from backend.settings import Settings
from backend.store import Store
from backend.source_harness import repair_interface_context
from ops.api import create_app as create_ops
from ops.config import OpsSettings
from tests.test_mvp1 import FakeModel, wait_status


class BrokenRepairModel(FakeModel):
    def generate(self, run_id, node, cache_key, system, user, *, max_tokens=4000):
        if node == "code_loop" and cache_key == "candidate-2":
            try:
                raise ModelOutputError("PRIVATE_MODEL_OUTPUT_DO_NOT_RECORD", reason_code="invalid_json")
            except ModelOutputError as exc:
                raise RuntimeError("PRIVATE_MODEL_OUTPUT_DO_NOT_RECORD") from exc
        return super().generate(run_id, node, cache_key, system, user, max_tokens=max_tokens)


def test_build_attempts_are_safe_idempotent_and_visible_in_ops(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite3")
    project = store.create_project("owner", "demo")
    run, _ = store.create_run(project["id"], "demo", "one")
    args = dict(attempt=1, outcome="failed", category="source_compile", command="npm run build",
                exit_code=1, duration_seconds=2.5, fix_round=0,
                fingerprints=["a" * 20], target_files=["src/App.tsx"], error_codes=["TS2339"], stop_code="")
    store.record_build_check(run["id"], **args)
    store.record_build_check(run["id"], **args)
    store.record_build_check(run["id"], **{**args, "attempt": 2, "outcome": "passed", "category": "passed",
                                              "fingerprints": [], "target_files": [], "error_codes": []})
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM build_check_attempts").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM exception_records WHERE code='build_check_failed'").fetchone()[0] == 1
    ops = create_ops(OpsSettings(db_path=store.path, admin_key="test-ops-key", static_dir=tmp_path / "missing"))
    with TestClient(ops) as client:
        records = client.get("/api/ops/exceptions", params={"trace_id": run["trace_id"]},
                             headers={"X-Operations-Key": "test-ops-key"}).json()["items"]
        assert len(records) == 1 and records[0]["severity"] == "warning"
        detail = client.get(f"/api/ops/exceptions/{records[0]['id']}",
                            headers={"X-Operations-Key": "test-ops-key"}).json()
        assert detail["build_checks"][0]["error_codes"] == ["TS2339"]
        assert detail["build_checks"][0]["target_files"] == ["src/App.tsx"]
        assert set(detail["build_checks"][0]["fingerprints"]) == {"a" * 20}
        assert detail["build_checks"][1]["outcome"] == "passed"


def test_partial_repair_sees_existing_imports_only(tmp_path: Path):
    files = {
        "src/App.tsx": "import { useAppState } from './hooks/useAppState';\nimport './app.css';",
        "src/hooks/useAppState.ts": "export function useAppState() { return { highScore: 1 } }",
        "src/app.css": "body { color: red; }",
    }
    assert repair_interface_context(files, ["src/App.tsx"]) == {
        "src/hooks/useAppState.ts": files["src/hooks/useAppState.ts"]}


def test_failed_code_output_after_build_can_open_manual_repair(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    app = create_app(settings, model=BrokenRepairModel())
    app.state.workflow.runner.build = lambda *_: {"ok": False,
        "diagnostics": "src/App.tsx(2,8): error TS2339: Property 'bad' does not exist.",
        "steps": [{"command": "npm run build", "exit_code": 1, "seconds": 0.1}]}
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "recover"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={"request_text": "做一个可以点击加一并保存分数的网页应用"}).json()["run"]["id"]
        clarify = wait_status(client, run_id, "awaiting_clarification")
        client.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarify["card_id"],
            "spec_version": clarify["spec_version"], "action": "confirm_clarification", "answers": {"q1": "0"}})
        plan = wait_status(client, run_id, "awaiting_plan")
        client.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
            "spec_version": plan["spec_version"], "action": "approve_plan"})
        failed = wait_status(client, run_id, "failed")
        assert failed["card"]["actions"] == ["open_repair"]
        assert failed["card"]["payload"]["failure_summary"]["total_attempts"] == 1
        opened = client.post(f"/api/runs/{run_id}/offer-repair")
        assert opened.status_code == 200
        assert opened.json()["status"] == "awaiting_repair"
        checks = app.state.store._conn()
        try:
            assert checks.execute("SELECT COUNT(*) FROM build_check_attempts WHERE run_id=?", (run_id,)).fetchone()[0] == 1
        finally:
            checks.close()
