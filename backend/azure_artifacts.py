"""Bounded UTF-8 snapshots for database-backed delivered versions."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any


MAX_FILES = 64
MAX_FILE_BYTES = 512 * 1024
MAX_VERSION_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = {".tsx", ".ts", ".js", ".css", ".html", ".json", ".md", ".svg", ".txt"}


class VersionCommitError(RuntimeError):
    """A candidate passed checks, but its database snapshot could not be committed."""


def valid_snapshot_path(name: str) -> bool:
    if not isinstance(name, str) or not name or len(name) > 400 or "\\" in name or ":" in name or name.startswith("/"):
        return False
    parts = name.split("/")
    return (all(part and part not in {".", ".."} and not part.startswith(".") for part in parts)
            and "node_modules" not in parts and Path(name).suffix.lower() in TEXT_EXTENSIONS)


def collect_candidate_files(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify exact manifest bytes before opening the version transaction."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for kind, key in (("source", "files"), ("dist", "build_files")):
        entries = manifest.get(key)
        if not isinstance(entries, list):
            raise ValueError(f"候选产物缺少 {key} 清单")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("候选文件清单格式无效")
            name = entry.get("path")
            if not valid_snapshot_path(name) or name in seen or (name.startswith("dist/") != (kind == "dist")):
                raise ValueError(f"候选文件路径无效或重复：{name}")
            seen.add(name)
            path = root.joinpath(*name.split("/"))
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"候选文件缺失或越界：{name}")
            data = path.read_bytes()
            size = len(data)
            total += size
            if size > MAX_FILE_BYTES or total > MAX_VERSION_BYTES or len(seen) > MAX_FILES:
                raise ValueError("候选文件超过 64 个、单文件 512 KiB 或整版 2 MiB 上限")
            try:
                content = data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(f"候选文件不是 UTF-8 文本：{name}") from exc
            digest = hashlib.sha256(data).hexdigest()
            if entry.get("bytes") != size or entry.get("sha256") != digest:
                raise ValueError(f"候选文件与清单校验不一致：{name}")
            mime = mimetypes.guess_type(name)[0] or "text/plain"
            rows.append({"path": name, "content": content, "utf8_bytes": size,
                         "sha256": digest, "kind": kind, "mime_type": mime})
    if "dist/index.html" not in seen:
        raise ValueError("候选产物缺少 dist/index.html")
    return rows


def verify_stored_file(row: dict[str, Any]) -> str:
    content = row["text_content"]
    data = content.encode("utf-8")
    if len(data) != row["utf8_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("已保存的版本文件校验失败")
    return content


def validate_snapshot_files(manifest: dict[str, Any], files: list[dict[str, Any]]) -> None:
    entries = manifest["files"] + manifest["build_files"]
    expected = {entry["path"]: entry for entry in entries}
    if (len(expected) != len(entries) or len(expected) != len(files)
            or {row["path"] for row in files} != set(expected) or "dist/index.html" not in expected
            or len(files) > MAX_FILES or sum(row["utf8_bytes"] for row in files) > MAX_VERSION_BYTES):
        raise ValueError("版本文件与清单不一致")
    for row in files:
        if not valid_snapshot_path(row["path"]) or row["utf8_bytes"] > MAX_FILE_BYTES:
            raise ValueError("版本文件路径无效")
        entry = expected[row["path"]]
        data = row["content"].encode("utf-8")
        if (entry["bytes"] != len(data) or entry["sha256"] != row["sha256"]
                or row["utf8_bytes"] != len(data) or hashlib.sha256(data).hexdigest() != row["sha256"]):
            raise ValueError("版本文件内容与清单不一致")
