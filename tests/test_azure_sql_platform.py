"""Opt-in Azure SQL smoke against a dedicated disposable database.

Set TEST_AZURE_SQL_CONNECTION_STRING and TEST_AZURE_SQL_DISPOSABLE=1. The test
creates platform records; never point it at a shared or production database.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4
import hashlib

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.azure_sql import AzureSqlStore
from backend.azure_artifacts import collect_candidate_files
from backend.migrate_azure_sql import migrate
from backend.preview_access import AzureSqlPreviewAccess
from backend.settings import Settings
from tests.test_mvp1 import FakeModel, wait_status


@pytest.fixture
def sql_connection_string() -> str:
    value = os.getenv("TEST_AZURE_SQL_CONNECTION_STRING", "")
    if not value or os.getenv("TEST_AZURE_SQL_DISPOSABLE") != "1":
        pytest.skip("requires an explicitly disposable Azure SQL database; live Azure SQL not claimed")
    try:
        migrate(value)
    except Exception as exc:
        if "AADSTS500200" in str(exc):
            pytest.fail(
                "当前登录应用拒绝个人 Microsoft 账号（AADSTS500200），尚未连接 Azure SQL。"
                "请使用该租户的组织账号执行本机测试，或在 Azure Container App 内使用托管身份验证；"
                "不要继续重试个人账号的设备码登录。",
                pytrace=False,
            )
        if "FA004" in str(exc) and "ActiveDirectoryInteractive" in value:
            pytest.fail(
                "Azure SQL 的 Entra 交互认证失败（FA004），迁移 SQL 尚未执行。"
                "请核对所选账号和数据库身份；若该账号是个人 Microsoft 账号，"
                "不要继续重试设备码登录，改用租户组织账号或 Azure 容器托管身份。不要填写 PWD。",
                pytrace=False,
            )
        raise
    return value


def test_azure_sql_restart_checkpoint_events_versions_and_preview(
        sql_connection_string: str, tmp_path: Path):
    settings = Settings(data_dir=tmp_path, app_env="local", azure_sql_connection_string=sql_connection_string,
                        model_api_key="test-only")
    first = create_app(settings, model=FakeModel())
    with TestClient(first) as client:
        project_id = client.post("/api/projects", json={"title": "Azure SQL restart smoke"}).json()["id"]
        run_id = client.post(f"/api/projects/{project_id}/runs", json={
            "request_text": "Create a small task app with add and delete actions",
        }, headers={"Idempotency-Key": str(uuid4())}).json()["run"]["id"]
        waiting = wait_status(client, run_id, "awaiting_clarification")
        checkpoint = first.state.workflow.checkpointer.get_tuple({"configurable": {"thread_id": run_id}})
        assert checkpoint is not None and waiting["card_id"]
        cookie = client.cookies.get("myatom_guest")

    second = create_app(settings, model=FakeModel())
    with TestClient(second) as client:
        client.cookies.set("myatom_guest", cookie)
        current = client.get(f"/api/runs/{run_id}").json()
        assert current["card_id"] == waiting["card_id"]
        assert client.post(f"/api/runs/{run_id}/decisions", json={
            "card_id": current["card_id"], "spec_version": current["spec_version"],
            "action": "confirm_clarification", "answers": {"q1": "No login"},
        }).status_code == 202
        plan = wait_status(client, run_id, "awaiting_plan")
        assert plan["card_id"] != waiting["card_id"]
        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))

    store = AzureSqlStore(sql_connection_string)
    store.update_run(run_id, status="completed", phase="Done")
    root = tmp_path / "delivered"
    (root / "dist").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "App.tsx").write_text("export default function App() { return <p>SQL</p> }", encoding="utf-8")
    (root / "dist" / "index.html").write_text("<!doctype html><div id=\"root\">SQL</div>", encoding="utf-8")
    manifest = {"files": [], "build_files": []}
    for name, key in (("src/App.tsx", "files"), ("dist/index.html", "build_files")):
        data = (root / name).read_bytes()
        manifest[key].append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    version, removed = store.commit_version_with_files(project_id, run_id, manifest,
                                                       collect_candidate_files(root, manifest))
    assert removed == []
    assert AzureSqlStore(sql_connection_string).get_version(version["id"])["project_id"] == project_id
    assert AzureSqlStore(sql_connection_string).get_version_file(version["id"], "dist/index.html")[0].endswith("SQL</div>")
    access = AzureSqlPreviewAccess(sql_connection_string)
    ticket, _ = access.issue_ticket(version["id"], project_id)
    session, owner = access.consume_ticket(ticket, version["id"])
    assert owner == project_id
    assert access.consume_ticket(ticket, version["id"]) is None
    assert AzureSqlPreviewAccess(sql_connection_string).session_project(session, version["id"]) == project_id
