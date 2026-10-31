"""Local-only browser verification of one existing generated version.

Start with MYATOM_DATA_DIR and MYATOM_EXAMPLE_VERSION set, bind only to
127.0.0.1, then open /__tc_open. The route issues a test ticket for that
single version so automation never prints a ticket or session cookie.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from backend.app_data import AppDataService
from backend.preview import create_preview_app
from backend.settings import Settings
from backend.store import Store


settings = Settings()
version_id = os.environ.get("MYATOM_EXAMPLE_VERSION", "")
if not version_id or settings.app_env != "local":
    raise RuntimeError("Test-only preview requires MYATOM_EXAMPLE_VERSION and APP_ENV=local")

app = create_preview_app(settings)


@app.get("/__tc_open", include_in_schema=False)
def test_open():
    try:
        version = Store(settings.app_db).get_version(version_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Test version missing") from exc
    ticket, _ = AppDataService(settings.data_dir / "app_data.sqlite3").issue_ticket(version_id, version["project_id"])
    return RedirectResponse(f"/open/{version_id}?ticket={ticket}", status_code=303)
