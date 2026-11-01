"""Immutable artifact snapshots in a private Azure Blob container.

This adapter deliberately does not create cloud resources or expose blob URLs.
The platform database owns version pointers; callers publish and verify first.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_FILES = 100
_MAX_TOTAL_BYTES = 50 * 1024 * 1024
_MARKER = "_complete.json"


class ArtifactConflict(RuntimeError):
    """An existing blob differs from the content addressed candidate."""


class ArtifactMissing(RuntimeError):
    """The immutable snapshot is incomplete or unavailable."""


def _prefix(project_id: str, run_id: str, digest: str) -> str:
    try:
        project, run = UUID(project_id), UUID(run_id)
    except ValueError as exc:
        raise ValueError("invalid artifact identity") from exc
    if not _DIGEST.fullmatch(digest):
        raise ValueError("invalid artifact digest")
    return f"projects/{project}/runs/{run}/snapshots/{digest}/"


def _file_name(name: str) -> str:
    candidate = Path(name)
    if (not name or candidate.is_absolute() or name.startswith(("/", "\\"))
            or "\\" in name or ":" in name or "\x00" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or candidate.as_posix() != name or name == _MARKER):
        raise ValueError("invalid artifact file name")
    return name


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobArtifactStore:
    """Publish candidate files before a separate database version transaction.

    `container` is an Azure ContainerClient-compatible object, injected for
    local tests. The configured container must already exist and stay private.
    """

    def __init__(self, container: Any):
        self.container = container

    @classmethod
    def from_managed_identity(cls, account_url: str, container_name: str) -> "BlobArtifactStore":
        if not account_url.startswith("https://") or not container_name:
            raise ValueError("Azure Blob HTTPS account URL and container are required")
        from azure.identity import ManagedIdentityCredential
        from azure.storage.blob import BlobServiceClient

        client = BlobServiceClient(account_url=account_url, credential=ManagedIdentityCredential())
        return cls(client.get_container_client(container_name))

    def _read_blob(self, key: str) -> bytes:
        try:
            return self.container.get_blob_client(key).download_blob().readall()
        except Exception as exc:
            raise ArtifactMissing("artifact blob unavailable") from exc

    def _put_immutable(self, key: str, data: bytes) -> None:
        blob = self.container.get_blob_client(key)
        try:
            blob.upload_blob(data, overwrite=False)
        except Exception:
            # A retry may race an earlier successful upload. Only identical
            # content can be accepted as an idempotent result.
            if not blob.exists():
                raise
            if self._read_blob(key) != data:
                raise ArtifactConflict("artifact key already has different content")
        if self._read_blob(key) != data:
            raise ArtifactConflict("artifact readback differs from upload")

    def publish(self, project_id: str, run_id: str, digest: str, source: Path) -> dict[str, Any]:
        """Upload complete candidate, then write the immutable completion marker."""
        prefix = _prefix(project_id, run_id, digest)
        root = source.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("candidate root is not a directory")
        entries: list[dict[str, Any]] = []
        payloads: list[tuple[str, bytes]] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("symlink is not allowed in artifact")
            if not path.is_file():
                continue
            name = _file_name(path.relative_to(root).as_posix())
            data = path.read_bytes()
            total += len(data)
            if len(payloads) >= _MAX_FILES or total > _MAX_TOTAL_BYTES:
                raise ValueError("artifact exceeds file or byte limit")
            entries.append({"path": name, "sha256": _sha256(data), "bytes": len(data)})
            payloads.append((name, data))
        if not entries or not any(item["path"] == "dist/index.html" for item in entries):
            raise ValueError("artifact has no preview entry")
        marker = json.dumps({"schema_version": 1, "files": entries}, sort_keys=True,
                            separators=(",", ":")).encode("utf-8")
        for name, data in payloads:
            self._put_immutable(prefix + name, data)
        self._put_immutable(prefix + _MARKER, marker)
        return {"blob_prefix": prefix, "manifest_sha256": _sha256(marker), "files": entries}

    def list(self, project_id: str, run_id: str, digest: str,
             expected_manifest_sha256: str) -> list[dict[str, Any]]:
        prefix = _prefix(project_id, run_id, digest)
        marker = self._read_blob(prefix + _MARKER)
        if not _DIGEST.fullmatch(expected_manifest_sha256) or _sha256(marker) != expected_manifest_sha256:
            raise ArtifactConflict("artifact manifest differs from database reference")
        try:
            entries = json.loads(marker)["files"]
            if not isinstance(entries, list) or any(
                not isinstance(item, dict) or _file_name(item["path"]) != item["path"]
                or not _DIGEST.fullmatch(item["sha256"])
                or not isinstance(item["bytes"], int) or item["bytes"] < 0
                for item in entries
            ):
                raise ValueError("invalid manifest entries")
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactMissing("artifact has invalid completion marker") from exc
        return entries

    def read(self, project_id: str, run_id: str, digest: str, name: str,
             expected_manifest_sha256: str) -> bytes:
        prefix = _prefix(project_id, run_id, digest)
        name = _file_name(name)
        entries = self.list(project_id, run_id, digest, expected_manifest_sha256)
        try:
            entry = next(item for item in entries if item["path"] == name)
        except StopIteration as exc:
            raise ArtifactMissing("artifact is not in completed snapshot") from exc
        data = self._read_blob(prefix + name)
        if len(data) != entry["bytes"] or _sha256(data) != entry["sha256"]:
            raise ArtifactConflict("artifact file failed checksum")
        return data

    def delete(self, project_id: str, run_id: str, digest: str) -> int:
        """Call only after DB metadata has been removed and cleanup is queued."""
        prefix = _prefix(project_id, run_id, digest)
        names = list(self.container.list_blob_names(name_starts_with=prefix))
        for name in names:
            if not name.startswith(prefix):
                raise ArtifactConflict("storage returned a blob outside cleanup prefix")
            self.container.delete_blob(name)
        return len(names)
