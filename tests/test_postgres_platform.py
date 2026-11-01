"""Disposable PostgreSQL smoke; set TEST_POSTGRES_URL for real database tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.migrate_postgres import migrate
from backend.postgres_store import PostgresConnection, PostgresStore
from backend.preview_access import PostgresPreviewAccess
from backend.settings import Settings
from backend.api import create_app
from ops.store import PostgresReadOnlyExceptionStore
from tests.test_mvp1 import FakeModel, wait_status


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, query, parameters):
        self.calls.append((query, parameters))
        return _Cursor({"id": "run-1", "ordinal": 5})


def test_postgres_sql_adapter_preserves_store_contract():
    raw = _Connection()
    db = PostgresConnection(raw)
    assert db.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?)", ("a", "b", "c")).fetchone()[0] == "run-1"
    assert raw.calls[-1][0] == "INSERT INTO operations VALUES (%s,%s,%s) ON CONFLICT DO NOTHING"
    assert db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()["id"] == "run-1"
    assert "ORDER BY ordinal DESC" in raw.calls[-1][0]
    assert db.execute("BEGIN IMMEDIATE") is None


@pytest.fixture
def pg_url():
    url = os.getenv("TEST_POSTGRES_URL", "")
    if not url:
        pytest.skip("TEST_POSTGRES_URL not configured; real PostgreSQL not claimed")
    migrate(url)
    return url


def test_postgres_restart_events_versions_preview_and_ops(pg_url: str):
    first = PostgresStore(pg_url)
    project = first.create_project("test-owner", "PostgreSQL restart smoke")
    run, created = first.create_run(project["id"], "Generate a localStorage todo app", "pg-first")
    assert created
    run_id = run["id"]
    first.update_run(run_id, phase="Plan", status="awaiting_plan", event_type="phase", event_payload={"phase": "Plan"})
    assert [event["seq"] for event in first.events(run_id)] == [1, 2]
    first.cache_set(run_id, "plan", "key", {"ok": True})
    first.operation_set(run_id, "prepare", {"done": True})
    first.record_exception(trace_id=run["trace_id"], source="agent", phase="Plan",
                           code="plan_validation_failed", exception_type="PlanValidationError",
                           run_id=run_id, project_id=project["id"])
    restarted = PostgresStore(pg_url)
    assert restarted.cache_get(run_id, "plan", "key") == {"ok": True}
    assert restarted.operation_get(run_id, "prepare") == {"done": True}
    assert restarted.get_run(run_id)["phase"] == "Plan"
    restarted.update_run(run_id, phase="Done", status="completed", event_type="done")
    assert [event["seq"] for event in restarted.events(run_id)] == [1, 2, 3]
    version, removed = restarted.commit_version(project["id"], run_id, {"files": ["src/App.tsx"]})
    assert removed == []
    assert PostgresStore(pg_url).get_project(project["id"], "test-owner")["active_version_id"] == version["id"]
    assert restarted.activate_version(project["id"], version["id"])["id"] == version["id"]
    access = PostgresPreviewAccess(pg_url)
    ticket, _ = access.issue_ticket(version["id"], project["id"])
    session, session_project = PostgresPreviewAccess(pg_url).consume_ticket(ticket, version["id"])
    assert session_project == project["id"]
    assert PostgresPreviewAccess(pg_url).consume_ticket(ticket, version["id"]) is None
    assert PostgresPreviewAccess(pg_url).session_project(session, version["id"]) == project["id"]
    records = PostgresReadOnlyExceptionStore(pg_url).list_records(
        limit=10, cursor=None, source=None, code=None, project_id=project["id"], trace_id=None)
    assert any(item["run_id"] == run_id for item in records["items"])
    assert "request_text" not in str(records)


def test_postgres_checkpoint_and_waiting_card_resume(pg_url: str, tmp_path: Path):
    settings = Settings(data_dir=tmp_path, app_env="local", database_url=pg_url, model_api_key="test-only")
    app = create_app(settings, model=FakeModel())
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "PG checkpoint smoke"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "Create a small task app with localStorage persistence and a refresh check"
        }).json()["run"]["id"]
        waiting = wait_status(client, run_id, "awaiting_clarification")
        assert waiting["card_id"]
        cookie = client.cookies.get("myatom_guest")
        checkpoint = app.state.workflow.checkpointer.get_tuple({"configurable": {"thread_id": run_id}})
        assert checkpoint is not None
    restarted = create_app(settings, model=FakeModel())
    with TestClient(restarted) as client:
        client.cookies.set("myatom_guest", cookie)
        current = client.get(f"/api/runs/{run_id}").json()
        assert current["card_id"] == waiting["card_id"]
        assert current["status"] == "awaiting_clarification"
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": current["card_id"], "spec_version": current["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "No login"},
        }).status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert plan["card_id"] != waiting["card_id"]
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))


def test_ops_role_can_read_only_safe_views(pg_url: str):
    if os.getenv("TEST_POSTGRES_ADMIN") != "1":
        pytest.skip("requires a disposable PostgreSQL database with role-admin rights")
    import psycopg
    from psycopg.errors import InsufficientPrivilege
    from urllib.parse import quote, urlsplit, urlunsplit

    with psycopg.connect(pg_url) as db:
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname='myatom_ops_smoke'").fetchone():
            db.execute("CREATE ROLE myatom_ops_smoke LOGIN PASSWORD 'ephemeral-smoke-only'")
        db.execute("GRANT USAGE ON SCHEMA public TO myatom_ops_smoke")
        db.execute("GRANT SELECT ON ops_exception_records, ops_run_metrics, ops_event_timeline, ops_build_checks TO myatom_ops_smoke")
    parts = urlsplit(pg_url)
    read_url = urlunsplit((parts.scheme,
                           f"myatom_ops_smoke:{quote('ephemeral-smoke-only')}@{parts.hostname}:{parts.port or 5432}",
                           parts.path, parts.query, parts.fragment))
    assert PostgresReadOnlyExceptionStore(read_url).list_records(
        limit=1, cursor=None, source=None, code=None, project_id=None, trace_id=None)["items"] is not None
    with pytest.raises(InsufficientPrivilege), psycopg.connect(read_url) as db:
        db.execute("SELECT id FROM projects LIMIT 1")
