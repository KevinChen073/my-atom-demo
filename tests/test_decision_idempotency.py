"""A retried clarification must use the original card even if the UI has advanced."""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings
from backend.store import dumps
from tests.test_mvp1 import FakeModel, wait_status


def test_repeated_clarification_returns_original_decision_after_card_changes(tmp_path, monkeypatch):
    app = create_app(Settings(data_dir=tmp_path, model_api_key="test-only"), model=FakeModel())
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "Idempotency"}).json()
        run_id = client.post(f"/api/projects/{project['id']}/runs",
                             json={"request_text": "Create a small task list application"},
                             headers={"Idempotency-Key": str(uuid4())}).json()["run"]["id"]
        run = wait_status(client, run_id, "awaiting_clarification")
        monkeypatch.setattr(app.state.workflow, "enqueue", lambda _run_id: None)
        body = {"card_id": run["card_id"], "spec_version": run["spec_version"],
                "action": "confirm_clarification", "answers": {run["card"]["payload"]["questions"][0]["id"]: "No login"}}
        first = client.post(f"/api/runs/{run_id}/decisions", json=body, headers={"Idempotency-Key": "same"})
        assert first.status_code == 202
        new_card = {"type": "clarification", "payload": {"questions": [{"id": "new", "text": "New?", "required": True}]},
                    "actions": ["confirm_clarification"]}
        app.state.store.update_run(run_id, status="awaiting_clarification", card_id=str(uuid4()),
                                   spec_version=run["spec_version"] + 1, card_json=dumps(new_card))
        repeated = client.post(f"/api/runs/{run_id}/decisions", json=body, headers={"Idempotency-Key": "same"})
        assert repeated.status_code == 202
        assert repeated.json()["decision_id"] == first.json()["decision_id"]
        assert repeated.json()["created"] is False
