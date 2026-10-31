from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app as create_workbench
from backend.model import ModelOutputError
from backend.settings import Settings
from ops.api import create_app as create_ops
from ops.config import OpsSettings
from ops.store import DatabaseUnavailable, ReadOnlyExceptionStore


SECRET = "PRIVATE_MODEL_OUTPUT_DO_NOT_RECORD"


class BrokenModel:
    def check_limits(self, run_id: str) -> None:
        pass

    def generate(self, *args, **kwargs):
        try:
            raise ModelOutputError(SECRET)
        except ModelOutputError as exc:
            raise RuntimeError(SECRET) from exc


def ops_app(db_path: Path | None, key: str = "test-ops-key", static_dir: Path | None = None):
    return create_ops(OpsSettings(db_path=db_path, admin_key=key,
                                  static_dir=static_dir or Path("missing-ops-dist")))


def wait_for_failure(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] == "failed":
            return run
        time.sleep(0.05)
    pytest.fail("fault model did not produce a terminal run")


def test_terminal_model_failure_is_safe_and_visible_across_projects(tmp_path: Path):
    settings = Settings(root=tmp_path, data_dir=tmp_path, model_api_key="test-only")
    app = create_workbench(settings, model=BrokenModel())
    run_ids = []
    with TestClient(app) as client:
        for title in ("项目甲", "项目乙"):
            project = client.post("/api/projects", json={"title": title}).json()
            response = client.post(f"/api/projects/{project['id']}/runs",
                                   json={"request_text": "做一个可以编辑并保存记录的应用"})
            assert response.status_code == 201
            run_id = response.json()["run"]["id"]
            run = wait_for_failure(client, run_id)
            assert SECRET not in str(run)
            run_ids.append(run_id)
        assert client.get("/api/ops/exceptions").status_code == 404

    ops = ops_app(settings.app_db)
    with TestClient(ops) as client:
        assert client.get("/api/ops/exceptions").status_code == 401
        assert client.get("/api/ops/exceptions", headers={"X-Operations-Key": "wrong"}).status_code == 401
        first = client.get("/api/ops/exceptions?limit=1", headers={"X-Operations-Key": "test-ops-key"})
        assert first.status_code == 200
        assert first.headers["Cache-Control"] == "no-store"
        assert len(first.json()["items"]) == 1
        cursor = first.json()["next_cursor"]
        assert cursor
        second = client.get("/api/ops/exceptions", params={"limit": 1, "cursor": cursor},
                            headers={"X-Operations-Key": "test-ops-key"})
        assert second.status_code == 200
        records = first.json()["items"] + second.json()["items"]
        assert {item["run_id"] for item in records} == set(run_ids)
        assert all(item["code"] == "model_output_invalid" for item in records)
        assert all(item["exception_type"] == "ModelOutputError" for item in records)
        assert SECRET not in str(records)
        detail = client.get(f"/api/ops/exceptions/{records[0]['id']}",
                            headers={"X-Operations-Key": "test-ops-key"})
        assert detail.status_code == 200
        assert detail.json()["exception"]["trace_id"] == records[0]["trace_id"]
        assert all(set(item) == {"seq", "type", "at"} for item in detail.json()["timeline"])
        assert SECRET not in detail.text
        assert client.get(f"/api/ops/exceptions/{records[0]['id']}").status_code == 401
        assert client.get("/api/ops/exceptions", params={"cursor": "garbage"},
                          headers={"X-Operations-Key": "test-ops-key"}).status_code == 422
        assert client.get("/api/ops/exceptions", params={"limit": 101},
                          headers={"X-Operations-Key": "test-ops-key"}).status_code == 422
        assert client.get("/api/ops/exceptions", params={"project_id": records[0]["project_id"]},
                          headers={"X-Operations-Key": "test-ops-key"}).json()["items"][0]["id"] == records[0]["id"]
    with sqlite3.connect(settings.app_db) as db:
        raw = str(db.execute("SELECT * FROM exception_records").fetchall())
    assert SECRET not in raw


def test_final_build_failure_is_recorded_once(tmp_path: Path):
    settings = Settings(root=tmp_path, data_dir=tmp_path, model_api_key="test-only")
    app = create_workbench(settings, model=BrokenModel())
    store = app.state.store
    project = store.create_project("test-owner", "test")
    run, _ = store.create_run(project["id"], "build", "one")
    state = {"run_id": run["id"], "build_result": {"diagnostics": SECRET, "steps": []}, "fix_rounds": 2}
    app.state.workflow.needs_user(state)
    app.state.workflow.needs_user(state)
    with sqlite3.connect(settings.app_db) as db:
        rows = db.execute("SELECT source, code, reason, trace_id FROM exception_records").fetchall()
    assert len(rows) == 1
    assert rows[0][0:2] == ("build", "build_failed")
    assert SECRET not in rows[0][2]
    assert rows[0][3] == run["trace_id"]
    app.state.workflow.executor.shutdown(wait=False, cancel_futures=True)
    app.state.workflow.checkpoint_connection.close()


def test_unhandled_api_500_has_trace_without_leaking_payload(tmp_path: Path):
    settings = Settings(root=tmp_path, data_dir=tmp_path, model_api_key="test-only")
    app = create_workbench(settings, model=BrokenModel())

    @app.get("/api/test-throw")
    def fail():
        raise RuntimeError(SECRET)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/test-throw")
        assert response.status_code == 500
        assert response.json()["trace_id"] == response.headers["X-Trace-ID"]
        assert SECRET not in response.text
    with TestClient(ops_app(settings.app_db)) as client:
        records = client.get("/api/ops/exceptions", headers={"X-Operations-Key": "test-ops-key"}).json()["items"]
        assert len(records) == 1
        assert records[0]["trace_id"] == response.headers["X-Trace-ID"]
        assert records[0]["source"] == "api"
        assert records[0]["project_id"] is None
        assert SECRET not in str(records)


def test_ops_database_is_read_only_and_unconfigured_state_is_private(tmp_path: Path):
    settings = Settings(root=tmp_path, data_dir=tmp_path)
    create_workbench(settings, model=BrokenModel())
    with TestClient(ops_app(settings.app_db, key="")) as client:
        response = client.get("/api/ops/exceptions")
        assert response.status_code == 503
        assert "items" not in response.text
    with TestClient(ops_app(tmp_path / "no-database.sqlite3")) as client:
        assert client.get("/api/ops/exceptions", headers={"X-Operations-Key": "test-ops-key"}).status_code == 503
    store = ReadOnlyExceptionStore(settings.app_db)
    with pytest.raises(DatabaseUnavailable):
        with store.connection() as db:
            db.execute("DELETE FROM projects")


def test_capture_store_failure_preserves_terminal_result(tmp_path: Path, monkeypatch):
    settings = Settings(root=tmp_path, data_dir=tmp_path, model_api_key="test-only")
    app = create_workbench(settings, model=BrokenModel())
    store = app.state.store
    project = store.create_project("test-owner", "test")
    run, _ = store.create_run(project["id"], "build", "one")

    def capture_unavailable(**_):
        raise sqlite3.OperationalError("synthetic telemetry failure")

    monkeypatch.setattr(store, "record_exception", capture_unavailable)
    app.state.workflow.needs_user({
        "run_id": run["id"],
        "build_result": {"diagnostics": "build error", "steps": []},
        "fix_rounds": 2,
    })
    assert store.get_run(run["id"])["status"] == "failed"
    with sqlite3.connect(settings.app_db) as db:
        assert db.execute("SELECT COUNT(*) FROM exception_records").fetchone()[0] == 0
    app.state.workflow.executor.shutdown(wait=False, cancel_futures=True)
    app.state.workflow.checkpoint_connection.close()
