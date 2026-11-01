"""Offline contract tests for immutable Azure Blob artifact publishing."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from backend.blob_artifacts import ArtifactConflict, ArtifactMissing, BlobArtifactStore


class FakeBlob:
    def __init__(self, objects: dict[str, bytes], key: str):
        self.objects, self.key = objects, key

    def upload_blob(self, data: bytes, *, overwrite: bool):
        assert not overwrite
        if self.key in self.objects:
            raise FileExistsError(self.key)
        self.objects[self.key] = data

    def exists(self) -> bool:
        return self.key in self.objects

    def download_blob(self):
        if self.key not in self.objects:
            raise FileNotFoundError(self.key)
        return self

    def readall(self) -> bytes:
        return self.objects[self.key]


class FakeContainer:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get_blob_client(self, name: str) -> FakeBlob:
        return FakeBlob(self.objects, name)

    def list_blob_names(self, *, name_starts_with: str):
        return (name for name in self.objects if name.startswith(name_starts_with))

    def delete_blob(self, name: str):
        del self.objects[name]


def candidate(tmp_path):
    root = tmp_path / "candidate"
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "index.html").write_text("<main>ok</main>", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "App.tsx").write_text("export default function App() {}", encoding="utf-8")
    return root


def test_publish_read_retry_and_delete(tmp_path):
    container = FakeContainer()
    store = BlobArtifactStore(container)
    project_id, run_id = str(uuid4()), str(uuid4())
    root = candidate(tmp_path)
    digest = hashlib.sha256(b"candidate").hexdigest()
    first = store.publish(project_id, run_id, digest, root)
    assert store.publish(project_id, run_id, digest, root) == first
    assert first["blob_prefix"].startswith(f"projects/{project_id}/runs/{run_id}/")
    assert store.list(project_id, run_id, digest, first["manifest_sha256"]) == first["files"]
    assert store.read(project_id, run_id, digest, "dist/index.html", first["manifest_sha256"]) == b"<main>ok</main>"
    assert store.delete(project_id, run_id, digest) == 3
    with pytest.raises(ArtifactMissing):
        store.read(project_id, run_id, digest, "dist/index.html", first["manifest_sha256"])


def test_partial_upload_has_no_completion_marker(tmp_path):
    class FailingBlob(FakeBlob):
        def upload_blob(self, data: bytes, *, overwrite: bool):
            if self.key.endswith("src/App.tsx") and self.key not in container.failed:
                container.failed.add(self.key)
                raise ConnectionError("network interruption")
            return super().upload_blob(data, overwrite=overwrite)

    class FailingContainer(FakeContainer):
        def __init__(self):
            super().__init__()
            self.failed: set[str] = set()

        def get_blob_client(self, name: str):
            return FailingBlob(self.objects, name)

    container = FailingContainer()
    store = BlobArtifactStore(container)
    project_id, run_id, digest = str(uuid4()), str(uuid4()), "a" * 64
    root = candidate(tmp_path)
    with pytest.raises(ConnectionError):
        store.publish(project_id, run_id, digest, root)
    assert not any(name.endswith("_complete.json") for name in container.objects)
    published = store.publish(project_id, run_id, digest, root)
    assert store.read(project_id, run_id, digest, "src/App.tsx", published["manifest_sha256"])


def test_conflicting_retry_and_path_escape_fail_closed(tmp_path):
    container = FakeContainer()
    store = BlobArtifactStore(container)
    project_id, run_id, digest = str(uuid4()), str(uuid4()), "b" * 64
    root = candidate(tmp_path)
    published = store.publish(project_id, run_id, digest, root)
    (root / "src" / "App.tsx").write_text("changed", encoding="utf-8")
    with pytest.raises(ArtifactConflict):
        store.publish(project_id, run_id, digest, root)
    with pytest.raises(ValueError):
        store.read(project_id, run_id, digest, "../secret", published["manifest_sha256"])
    with pytest.raises(ArtifactConflict):
        store.read(project_id, run_id, digest, "dist/index.html", "c" * 64)
    with pytest.raises(ValueError):
        store.delete("bad-id", run_id, digest)
