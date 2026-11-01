"""Local delivered versions must survive without the artifact directory."""

import hashlib
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.preview import create_preview_app
from backend.preview_access import PreviewAccess, preview_host
from backend.settings import Settings
from backend.store import Store


def _item(path: str, content: str, kind: str) -> tuple[dict, dict]:
    data = content.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    return ({"path": path, "bytes": len(data), "sha256": digest},
            {"path": path, "content": content, "utf8_bytes": len(data),
             "sha256": digest, "kind": kind, "mime_type": "text/html" if path.endswith(".html") else "text/plain"})


def test_sqlite_version_preview_and_source_survive_restart_without_artifacts(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", preview_port=8001)
    store = Store(settings.app_db)
    project = store.create_project("owner", "snapshot")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    source, source_row = _item("src/App.tsx", "export default function App(){return <p>OK</p>}", "source")
    html, html_row = _item("dist/index.html", "<main>snapshot survives</main>", "dist")
    manifest = {"files": [source], "build_files": [html], "build": {"ok": True}}
    version, _ = store.commit_version_with_files(project["id"], run["id"], manifest, [source_row, html_row])
    shutil.rmtree(tmp_path / "artifacts", ignore_errors=True)
    restored = Store(settings.app_db)
    assert restored.get_version_file(version["id"], "src/App.tsx")[0] == source_row["content"]
    assert restored.get_project(project["id"], "owner")["active_version_id"] == version["id"]
    access = PreviewAccess(tmp_path / "preview_access.sqlite3")
    ticket, _ = access.issue_ticket(version["id"], project["id"])
    with TestClient(create_preview_app(settings), base_url=f"http://{preview_host(project['id'])}:8001") as client:
        response = client.get(f"/open/{version['id']}?ticket={ticket}")
        assert response.status_code == 200
        assert "snapshot survives" in response.text


def test_sqlite_snapshot_rejects_partial_files_without_moving_pointer(tmp_path: Path):
    store = Store(tmp_path / "myatom.sqlite3")
    project = store.create_project("owner", "snapshot")
    run, _ = store.create_run(project["id"], "make a small app", "one")
    source, source_row = _item("src/App.tsx", "export default 1", "source")
    html, _ = _item("dist/index.html", "<main>OK</main>", "dist")
    with pytest.raises(ValueError, match="清单"):
        store.commit_version_with_files(project["id"], run["id"],
                                        {"files": [source], "build_files": [html]}, [source_row])
    assert store.get_project(project["id"], "owner")["active_version_id"] is None
    with store._conn() as db:
        assert db.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM version_files").fetchone()[0] == 0
