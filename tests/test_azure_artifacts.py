"""Offline checks for immutable Azure SQL text snapshots."""

import hashlib
import threading
from contextlib import contextmanager

import pytest

from backend.azure_artifacts import collect_candidate_files, valid_snapshot_path, verify_stored_file
from backend.azure_sql import AzureSqlStore


def _candidate(tmp_path, content="<main>中文</main>"):
    root = tmp_path / "candidate"
    (root / "dist").mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    (root / "dist" / "index.html").write_bytes(data)
    manifest = {"files": [], "build_files": [{"path": "dist/index.html", "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}]}
    return root, manifest


def test_candidate_text_is_bounded_and_hash_verified(tmp_path):
    root, manifest = _candidate(tmp_path)
    rows = collect_candidate_files(root, manifest)
    assert rows[0]["content"] == "<main>中文</main>"
    assert rows[0]["utf8_bytes"] == len("<main>中文</main>".encode("utf-8"))
    assert verify_stored_file({"text_content": rows[0]["content"], "utf8_bytes": rows[0]["utf8_bytes"],
                               "sha256": rows[0]["sha256"]}) == rows[0]["content"]
    (root / "dist" / "index.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="校验不一致"):
        collect_candidate_files(root, manifest)


def test_candidate_rejects_invalid_path_binary_and_oversize(tmp_path):
    root, manifest = _candidate(tmp_path)
    for bad in ("../secret.txt", "dist/../index.html", "dist\\index.html", "/dist/index.html", "dist/a.png", "C:/file.ts"):
        assert not valid_snapshot_path(bad)
    (root / "dist" / "index.html").write_bytes(b"\xff")
    manifest["build_files"][0].update(bytes=1, sha256=hashlib.sha256(b"\xff").hexdigest())
    with pytest.raises(ValueError, match="UTF-8"):
        collect_candidate_files(root, manifest)
    root, manifest = _candidate(tmp_path, "x" * (512 * 1024 + 1))
    with pytest.raises(ValueError, match="512 KiB"):
        collect_candidate_files(root, manifest)


def test_saved_file_corruption_is_never_served():
    with pytest.raises(ValueError, match="校验失败"):
        verify_stored_file({"text_content": "corrupted", "utf8_bytes": 5, "sha256": "0" * 64})


def test_second_file_insert_failure_does_not_publish_version():
    committed = {"active": None, "versions": [], "files": []}
    rolled_back = []

    class Result:
        def __init__(self, value=None):
            self.value = value

        def fetchone(self):
            return self.value

    class FakeDb:
        def __init__(self):
            self.staged = {"active": committed["active"], "versions": [], "files": []}

        def execute(self, sql, params=()):
            if sql.startswith("SELECT id FROM projects WITH"):
                return Result({"id": "project"})
            if sql.startswith("SELECT * FROM versions WHERE run_id"):
                return Result()
            if sql.startswith("SELECT base_version_id FROM runs"):
                return Result({"base_version_id": None})
            if sql.startswith("SELECT active_version_id FROM projects"):
                return Result({"active_version_id": None})
            if sql.startswith("INSERT INTO versions"):
                self.staged["versions"].append(params[0])
            if sql.startswith("INSERT INTO version_files"):
                self.staged["files"].append(params[1])
                if len(self.staged["files"]) == 2:
                    raise RuntimeError("injected second file insert failure")
            return Result()

    @contextmanager
    def fake_connection():
        db = FakeDb()
        try:
            yield db
        except Exception:
            rolled_back.append(True)
            raise
        else:
            committed.update(db.staged)

    store = object.__new__(AzureSqlStore)
    store.lock = threading.RLock()
    store._conn = fake_connection
    source = b"export default 1"
    html = b"<div></div>"
    files = [{"path": path, "content": data.decode(), "utf8_bytes": len(data),
              "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "mime_type": mime}
             for path, data, kind, mime in (("src/App.tsx", source, "source", "text/plain"),
                                           ("dist/index.html", html, "dist", "text/html"))]
    manifest = {"files": [{"path": files[0]["path"], "bytes": len(source), "sha256": files[0]["sha256"]}],
                "build_files": [{"path": files[1]["path"], "bytes": len(html), "sha256": files[1]["sha256"]}]}
    with pytest.raises(RuntimeError, match="injected"):
        store.commit_version_with_files("project", "run", manifest, files)
    assert rolled_back == [True]
    assert committed == {"active": None, "versions": [], "files": []}
