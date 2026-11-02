"""Opt-in real-model MVP1 smoke test. Uses an ignored local data directory."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings


def wait_for(client: TestClient, run_id: str, statuses: set[str], timeout: float = 480) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        response.raise_for_status()
        last = response.json()
        if last["status"] in statuses or last["status"] in {"failed", "cancelled", "budget_exceeded"}:
            return last
        time.sleep(0.5)
    raise TimeoutError(f"run remained in {last.get('status')}")


def main() -> None:
    settings = Settings(data_dir=Path("data/live-smoke").resolve())
    if not settings.model_api_key:
        raise RuntimeError("MODEL_API_KEY is missing from local .env")
    app = create_app(settings)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "真实模型计数器验收"})
        project.raise_for_status()
        project_id = project.json()["id"]
        created = client.post(
            f"/api/projects/{project_id}/runs",
            json={"request_text": "做一个中文计数器网页，有加一、减一和清零按钮，显示当前数字。"},
            headers={"Idempotency-Key": f"live-{project_id}", "X-Myatom-Model-Config": json.dumps({
                "provider": "deepseek" if "api.deepseek.com" in settings.model_base_url else "openai_compatible",
                "api_key": settings.model_api_key, "base_url": settings.model_base_url,
                "model_name": settings.model_name})},
        )
        created.raise_for_status()
        run_id = created.json()["run"]["id"]
        run = wait_for(client, run_id, {"awaiting_clarification"})
        assert run["status"] == "awaiting_clarification", run.get("error")
        answers = {q["id"]: q["default"] or "按需求实现" for q in run["card"]["payload"]["questions"]}
        clarified = client.post(
            f"/api/runs/{run_id}/decisions",
            json={"card_id": run["card_id"], "spec_version": run["spec_version"], "action": "confirm_clarification", "answers": answers},
            headers={"Idempotency-Key": f"clarify-{run_id}"},
        )
        clarified.raise_for_status()
        run = wait_for(client, run_id, {"awaiting_plan"})
        assert run["status"] == "awaiting_plan", run.get("error")
        approved = client.post(
            f"/api/runs/{run_id}/decisions",
            json={"card_id": run["card_id"], "spec_version": run["spec_version"], "action": "approve_plan"},
            headers={"Idempotency-Key": f"approve-{run_id}"},
        )
        approved.raise_for_status()
        run = wait_for(client, run_id, {"completed"})
        assert run["status"] == "completed", run.get("error")
        project = client.get(f"/api/projects/{project_id}").json()
        version = project["versions"][0]
        source = client.get(f"/api/versions/{version['id']}/files/src/App.tsx")
        source.raise_for_status()
        assert "计数" in source.text or "count" in source.text.lower()
        assert version["manifest"]["build"]["ok"]
        print(json.dumps({
            "status": run["status"], "project_id": project_id, "run_id": run_id,
            "version_id": version["id"], "model_calls": run["model_calls"],
            "tokens_used": run["tokens_used"], "fix_rounds": run["fix_rounds"],
            "build_steps": version["manifest"]["build"]["steps"],
            "source_bytes": len(source.content),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
