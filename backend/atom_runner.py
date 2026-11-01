"""Single-process static artifact runner for the Atoms deployment branch."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from . import atom_static
from .runner import LocalRunner, UnsafeSource


class AtomRunner(LocalRunner):
    generated_file = atom_static.GENERATED_FILE

    def prepare(self, project_id: str, run_id: str) -> Path:
        target = self.workspace(project_id, run_id)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def inspect_generated(self, files: Any) -> list[dict[str, str | None]]:
        return atom_static.inspect_generated(files)

    def build(self, project_id: str, run_id: str) -> dict[str, Any]:
        started = time.monotonic()
        root = self.prepare(project_id, run_id)
        issues = self.inspect_generated({name: (root / name).read_text(encoding="utf-8")
                                         for name in sorted(atom_static.REQUIRED_FILES) if (root / name).is_file()})
        log = root / "build.log"
        if issues:
            detail = "；".join(str(item["detail"]) for item in issues[:5])
            log.write_text(f"静态文件检查失败：{detail}\n", encoding="utf-8")
            return {"ok": False, "steps": [{"command": "static asset check", "exit_code": 1,
                                               "seconds": round(time.monotonic() - started, 3)}],
                    "diagnostics": detail, "log": str(log), "environment_failure": True}
        dist = root / "dist"
        if dist.resolve().parent != root.resolve() or dist.resolve() == root.resolve():
            raise RuntimeError("静态产物目录越界")
        if dist.is_dir():
            shutil.rmtree(dist)
        dist.mkdir()
        for name in ("index.html", "style.css", "app.js"):
            shutil.copyfile(root / name, dist / name)
        log.write_text("静态文件检查通过；未执行 Node 构建、JavaScript 语法解析或浏览器交互。\n", encoding="utf-8")
        return {"ok": True, "steps": [{"command": "static asset check", "exit_code": 0,
                                         "seconds": round(time.monotonic() - started, 3)}],
                "diagnostics": "", "log": str(log), "level": "static_files_only"}

    def package_candidate(self, project_id: str, run_id: str, build: dict[str, Any]) -> dict[str, Any]:
        result = super().package_candidate(project_id, run_id, build)
        result["manifest"]["template"] = "static-html-css-js-v1"
        result["manifest"]["build"]["level"] = "static_files_only"
        return result

    def probe_candidate(self, project_id: str, run_id: str, digest: str) -> dict[str, Any]:
        root = self.candidate(project_id, run_id, digest) / "dist"
        if not all((root / name).is_file() for name in ("index.html", "style.css", "app.js")):
            return {"ok": False, "reason": "静态预览文件缺失", "checked_assets": 0}
        issues = self.inspect_generated({name: (root / name).read_text(encoding="utf-8")
                                         for name in ("index.html", "style.css", "app.js")}
                                        | {"readme.md": "预览静态资源检查"})
        if issues:
            return {"ok": False, "reason": "静态预览文件校验失败", "checked_assets": 0}
        return {"ok": True, "reason": "静态入口和本地资源可读取；未执行浏览器交互", "checked_assets": 3,
                "level": "static_assets_only"}

    def read_artifact_file(self, project_id: str, run_id: str, name: str) -> str:
        if name not in atom_static.REQUIRED_FILES | {"build.log"}:
            raise UnsafeSource("不允许读取此文件")
        path = self.artifact(project_id, run_id) / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path.read_text(encoding="utf-8", errors="replace")
