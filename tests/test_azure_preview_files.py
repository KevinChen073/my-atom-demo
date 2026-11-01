"""Preview must serve SQL text even when the container artifact directory is empty."""

from uuid import uuid4

from fastapi.testclient import TestClient

import backend.azure_sql as sql_module
import backend.preview_access as access_module
from backend.preview import create_preview_app
from backend.settings import Settings


def test_sql_preview_serves_snapshot_without_container_files(monkeypatch, tmp_path):
    project_id, version_id, run_id = (str(uuid4()) for _ in range(3))

    class FakeStore:
        def __init__(self, _connection_string):
            pass

        def get_version(self, requested):
            assert requested == version_id
            return {"id": version_id, "project_id": project_id, "run_id": run_id,
                    "manifest": {"template": "react-vite-v4"}}

        def get_version_file(self, requested, name):
            assert requested == version_id
            files = {"dist/index.html": ("<html><head></head><body><div id='root'></div><script src='./assets/app.js'></script></body></html>", "text/html"),
                     "dist/assets/app.js": ("document.body.dataset.loaded='yes'", "text/javascript")}
            return files[name]

    class FakeAccess:
        def __init__(self, _connection_string):
            pass

        def session_project(self, session, requested):
            return project_id if session == "session" and requested == version_id else None

    monkeypatch.setattr(sql_module, "AzureSqlStore", FakeStore)
    monkeypatch.setattr(access_module, "AzureSqlPreviewAccess", FakeAccess)
    settings = Settings(data_dir=tmp_path, app_env="local", azure_sql_connection_string="test")
    app = create_preview_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        html = client.get(f"/s/session/v/{version_id}/")
        assert html.status_code == 200 and "id='root'" in html.text
        assert f'content="{project_id.replace("-", "")}"' in html.text
        script = client.get(f"/s/session/v/{version_id}/assets/app.js")
        assert script.status_code == 200 and "text/javascript" in script.headers["content-type"]
        assert "dataset.loaded" in script.text
