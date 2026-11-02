"""Shared-origin preview must still enforce version tickets and project ownership."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.api import create_app, owner_hash
from backend.settings import Settings


def _row(name: str, content: str) -> tuple[dict, dict]:
    data = content.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    entry = {"path": name, "bytes": len(data), "sha256": digest}
    row = {**entry, "content": content, "utf8_bytes": len(data),
           "kind": "dist" if name.startswith("dist/") else "source",
           "mime_type": "text/html" if name.endswith(".html") else "text/javascript"}
    return entry, row


def _version(store, owner: str, title: str, template: str) -> tuple[str, str]:
    project = store.create_project(owner_hash(owner), title)
    run, _ = store.create_run(project["id"], "做一个可点击的待办应用", title)
    src, src_row = _row("src/App.tsx", "export default function App(){ return null }")
    html, html_row = _row("dist/index.html", '<html><head></head><body><div id="root"></div><script src="/assets/app.js"></script></body></html>')
    js, js_row = _row("dist/assets/app.js", "document.body.dataset.loaded = 'yes'")
    version, _ = store.commit_version_with_files(project["id"], run["id"],
        {"template": template, "files": [src], "build_files": [html, js], "build": {"ok": True}},
        [src_row, html_row, js_row])
    return project["id"], version["id"]


def test_shared_origin_preview_redeems_ticket_and_injects_project_id(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, workbench_origin="http://127.0.0.1:8000")
    app = create_app(settings)
    project_a, version_a = _version(app.state.store, "owner-a", "A", "react-vite-v4")
    _, version_b = _version(app.state.store, "owner-a", "B", "react-vite-v4")
    with TestClient(app, base_url=settings.workbench_origin) as client:
        client.cookies.set("myatom_guest", "owner-a")
        issued = client.get(f"/api/versions/{version_a}/preview")
        assert issued.status_code == 200
        url = issued.json()["url"]
        assert urlsplit(url).netloc == urlsplit(settings.workbench_origin).netloc
        assert urlsplit(url).path == f"/preview/open/{version_a}"
        first = client.get(url, follow_redirects=False)
        assert first.status_code == 303
        location = first.headers["location"]
        assert location.startswith("/preview/s/") and location.endswith(f"/v/{version_a}/")
        assert client.get(url, follow_redirects=False).status_code == 401
        html = client.get(location)
        assert html.status_code == 200
        assert f'content="{project_a.replace("-", "")}"' in html.text
        assert 'src="./assets/app.js"' in html.text
        asset = client.get(location + "assets/app.js")
        assert asset.status_code == 200 and "dataset.loaded" in asset.text
        assert client.get(location.replace(version_a, version_b)).status_code == 401


def test_legacy_version_can_preview_with_project_access_and_ticket(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path))
    _, version = _version(app.state.store, "owner-a", "legacy", "react-vite-v3")
    with TestClient(app) as client:
        client.cookies.set("myatom_guest", "owner-a")
        response = client.get(f"/api/versions/{version}/preview")
        assert response.status_code == 200
        opened = client.get(response.json()["url"], follow_redirects=False)
        assert opened.status_code == 303
        assert client.get(opened.headers["location"]).status_code == 200
        assert client.get(response.json()["url"], follow_redirects=False).status_code == 401
