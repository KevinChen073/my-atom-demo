"""Opt-in paid-model check for a localStorage to-do app and project preview."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.preview import create_preview_app
from backend.settings import Settings


def wait_for(client: TestClient, run_id: str, expected: str, timeout: int = 480, *, after_spec: int = -1) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] == expected and run["spec_version"] > after_spec:
            return run
        if expected == "awaiting_plan" and run["status"] == "awaiting_clarification" and run["spec_version"] > after_spec:
            return run
        if run["status"] in {"failed", "cancelled", "budget_exceeded"}:
            return run
        time.sleep(0.5)
    raise TimeoutError(f"任务未到达 {expected}")


def main() -> None:
    settings = Settings(data_dir=Path("data/live-mvp2-smoke").resolve())
    if not settings.model_api_key:
        raise RuntimeError("本地 .env 缺少 MODEL_API_KEY")
    with TestClient(create_app(settings)) as main_client:
        project = main_client.post("/api/projects", json={"title": "MVP2 真实待办验收"}).json()
        created = main_client.post(f"/api/projects/{project['id']}/runs", json={"request_text": "做一个中文待办事项应用，可以新增、编辑、完成和删除待办；每次操作保存到项目预览域的 localStorage，刷新页面后记录仍在。"}, headers={"X-Myatom-Model-Config": json.dumps({
            "provider": "deepseek" if "api.deepseek.com" in settings.model_base_url else "openai_compatible",
            "api_key": settings.model_api_key, "base_url": settings.model_base_url,
            "model_name": settings.model_name})})
        assert created.status_code == 201, created.text
        run_id = created.json()["run"]["id"]
        run = wait_for(main_client, run_id, "awaiting_clarification")
        assert run["status"] == "awaiting_clarification", run.get("error")
        while run["status"] == "awaiting_clarification":
            answers = {q["id"]: q["default"] or "按需求实现" for q in run["card"]["payload"]["questions"]}
            response = main_client.post(f"/api/runs/{run_id}/decisions", json={"card_id": run["card_id"], "spec_version": run["spec_version"], "action": "confirm_clarification", "answers": answers})
            response.raise_for_status()
            run = wait_for(main_client, run_id, "awaiting_plan", after_spec=run["spec_version"])
        assert run["status"] == "awaiting_plan", run.get("error")
        assert "localStorage" in json.dumps(run["plan"], ensure_ascii=False), "计划未说明本地持久化"
        response = main_client.post(f"/api/runs/{run_id}/decisions", json={"card_id": run["card_id"], "spec_version": run["spec_version"], "action": "approve_plan"})
        response.raise_for_status()
        run = wait_for(main_client, run_id, "completed")
        assert run["status"] == "completed", run.get("error")
        version = main_client.get(f"/api/projects/{project['id']}").json()["versions"][0]
        source = main_client.get(f"/api/versions/{version['id']}/files/src/hooks/useAppState.ts").text
        assert "localStorage" in source, "生成应用未接入项目本地存储"
        assert version["manifest"]["build"]["ok"]
        issued = main_client.get(f"/api/versions/{version['id']}/preview")
        issued.raise_for_status()
        path = urlsplit(issued.json()["url"])
        with TestClient(create_preview_app(settings), base_url=f"{path.scheme}://{path.netloc}") as preview:
            opened = preview.get(path.path + "?" + path.query)
            assert opened.status_code == 200, opened.text[:500]
            assert "assets" in opened.text
            assert preview.get(f"/data/{version['id']}/todos").status_code == 404
        print(json.dumps({"status": run["status"], "project_id": project["id"], "run_id": run_id,
                          "version_id": version["id"], "preview_origin": path.netloc, "model_calls": run["model_calls"],
                          "tokens_used": run["tokens_used"], "fix_rounds": run["fix_rounds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
