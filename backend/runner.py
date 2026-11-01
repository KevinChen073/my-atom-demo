from __future__ import annotations

import hashlib
import math
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .model import BudgetExceeded, RunCancelled
from .budget import effective_limits
from .settings import Settings
from .source_harness import (GENERATED_FILE, MAX_COMPONENTS, MAX_FILE_BYTES, MAX_GENERATED_BYTES,
                             MAX_GENERATED_FILES, MAX_HOOKS, MAX_README_BYTES, REQUIRED_FILES, TEMPLATE_STORAGE_FILE,
                             source_violation_code)
from .store import Store


FORBIDDEN_SOURCE = re.compile(
    r"\b(?:eval|Function|require|XMLHttpRequest|WebSocket)\s*\(|"
    r"\b(?:fetch|sessionStorage|indexedDB|document\.cookie|import\.meta\.env|process\.env|window\.(?:parent|top|location)|document\.location|navigator\.serviceWorker|dangerouslySetInnerHTML|srcDoc)\b|"
    r"<\s*(?:script|iframe)\b|"
    r"https?://|@import|url\s*\(",
    re.IGNORECASE,
)
IMPORT_LINE = re.compile(r"^\s*import\s+(?:.*?\s+from\s+)?['\"]([^'\"]+)['\"]", re.MULTILINE)
STATE_UPDATER_BLOCK = re.compile(
    r"\bset[A-Z]\w*\s*\(\s*\(\s*\w+\s*\)\s*=>\s*\{(?P<body>.*?)\n\s*\}\s*\)",
    re.DOTALL,
)
UPDATER_SIDE_EFFECT = re.compile(
    r"\b(?:createRecord|updateRecord|deleteRecord|listRecords|persist\w*|save\w*|sync\w*|set[A-Z]\w*)\s*\("
)
STORAGE_ACCESS = re.compile(r"\blocalStorage\s*(?:\.|\[|[,;)])")
DIRECT_STORAGE_ACCESS = re.compile(r"\b(?:localStorage|sessionStorage)\s*(?:\.|\[|[,;)])|\b(?:window|globalThis)\s*\.\s*localStorage\b|\bStorage\s*\.\s*prototype\b")


class UnsafeSource(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalRunner:
    """Trusted same-container build. This is not a public code sandbox."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def workspace(self, project_id: str, run_id: str) -> Path:
        return self.settings.data_dir / "projects" / project_id / "runs" / run_id / "workspace"

    def artifact(self, project_id: str, run_id: str) -> Path:
        return self.settings.data_dir / "artifacts" / project_id / run_id

    def candidate(self, project_id: str, run_id: str, digest: str) -> Path:
        # Keep staging paths short enough for Windows' legacy 260-character limit.
        return self.settings.data_dir / "candidates" / run_id / digest[:24]

    def prepare(self, project_id: str, run_id: str) -> Path:
        if self.settings.app_env not in {"local", "azure_demo"} or (self.settings.app_env == "azure_demo" and not self.settings.trusted_demo):
            raise RuntimeError("同宿主构建仅允许本地或显式启用的 Azure 受信演示环境")
        target = self.workspace(project_id, run_id)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.settings.template_dir, target, ignore=shutil.ignore_patterns("node_modules", "dist", "*.tsbuildinfo"))
        template_storage = self.settings.template_dir / TEMPLATE_STORAGE_FILE
        workspace_storage = target / TEMPLATE_STORAGE_FILE
        storage_bytes = template_storage.read_bytes()
        if not workspace_storage.exists() or workspace_storage.read_bytes() != storage_bytes:
            workspace_storage.parent.mkdir(parents=True, exist_ok=True)
            workspace_storage.write_bytes(storage_bytes)
        return target

    def validate_source(self, name: str, content: str, names: set[str] | None = None) -> None:
        names = names or REQUIRED_FILES
        if name == TEMPLATE_STORAGE_FILE or not GENERATED_FILE.fullmatch(name) or not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise UnsafeSource("生成文件不在允许范围内或内容无效")
        if name == "readme.md":
            if len(content.encode("utf-8")) > MAX_README_BYTES:
                raise UnsafeSource("项目说明超过长度限制")
            return
        forbidden = FORBIDDEN_SOURCE.search(content)
        if forbidden:
            raise UnsafeSource(f"生成代码包含 MVP1 不允许的能力：{forbidden.group(0)}")
        if name.endswith((".tsx", ".ts")):
            if DIRECT_STORAGE_ACCESS.search(content):
                raise UnsafeSource("生成源码必须通过项目存储适配器读写，不得直接访问浏览器存储")
            imports = IMPORT_LINE.findall(content)
            for module in imports:
                if module == "react":
                    continue
                if not module.startswith("."):
                    raise UnsafeSource("生成代码只能导入 React 和已生成的项目文件")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), module))
                if target not in names and not any(target + ext in names | {TEMPLATE_STORAGE_FILE} for ext in (".ts", ".tsx", ".css")):
                    raise UnsafeSource(f"导入未生成的项目文件：{module}")
            if name == "src/App.tsx" and "export default" not in content:
                raise UnsafeSource("缺少默认导出的 React 组件")
            if name.startswith(("src/components/", "src/App.")) and re.search(r"\b(?:useState|useEffect|useReducer|useRef)\s*\(", content):
                raise UnsafeSource("状态与业务逻辑须放在 src/hooks/ 中")
            for update in STATE_UPDATER_BLOCK.finditer(content):
                if UPDATER_SIDE_EFFECT.search(update.group("body")):
                    raise UnsafeSource("React 状态更新函数中不能保存数据或调用其他 setState；请在事件处理函数中完成副作用")

    def inspect_generated(self, files: Any) -> list[dict[str, str | None]]:
        """Validate a complete candidate without writing it; report bounded file targets."""
        if not isinstance(files, dict):
            return [{"code": "missing_files_mapping", "file": None, "detail": "模型必须返回 files 路径映射"}]
        names = set(files)
        issues: list[dict[str, str | None]] = []

        def add(code: str, path: str | None, detail: str) -> None:
            issues.append({"code": code, "file": path, "detail": detail})

        for name in sorted(REQUIRED_FILES - names):
            add("invalid_layout", name, f"生成文件缺少必需的 {name}")
        if (TEMPLATE_STORAGE_FILE in names or len(names) > MAX_GENERATED_FILES or
            sum(len(content.encode("utf-8")) for content in files.values() if isinstance(content, str)) > MAX_GENERATED_BYTES or
            any(not isinstance(name, str) or not GENERATED_FILE.fullmatch(name) for name in names)):
            add("invalid_layout", None, "生成文件不在允许范围内或数量/大小超过上限")
        component_count = sum(isinstance(name, str) and name.startswith("src/components/") for name in names)
        hook_count = sum(isinstance(name, str) and name.startswith("src/hooks/") for name in names)
        if component_count > MAX_COMPONENTS:
            add("invalid_layout", None, f"组件数量 {component_count} 个，最多 {MAX_COMPONENTS} 个；请合并组件并重新生成完整文件映射")
        if hook_count > MAX_HOOKS:
            add("invalid_layout", None, f"hook 数量 {hook_count} 个，包含必需的 useAppState.ts，最多 {MAX_HOOKS} 个；请合并逻辑并重新生成完整文件映射")
        app_source = files.get("src/App.tsx")
        if isinstance(app_source, str) and (not re.search(r"import\s+['\"]\./app\.css['\"]", app_source) or
                                            not re.search(r"from\s+['\"]\./hooks/useAppState['\"]", app_source)):
            add("invalid_layout", "src/App.tsx", "App.tsx 必须导入 app.css 与 useAppState hook")
        for name, content in files.items():
            if not isinstance(name, str):
                continue
            if (name == "src/App.tsx" or name.startswith("src/components/")) and isinstance(content, str) and STORAGE_ACCESS.search(content):
                add("ui_storage_access", name, "业务持久化逻辑只能写在 src/hooks/ 中")
            try:
                self.validate_source(name, content, names)
            except UnsafeSource as exc:
                add(source_violation_code(exc), name if GENERATED_FILE.fullmatch(name) else None, str(exc))
        return issues[:12]

    def write_generated(self, project_id: str, run_id: str, files: dict[str, str], round_number: int) -> list[dict[str, Any]]:
        issues = self.inspect_generated(files)
        if issues:
            raise UnsafeSource(str(issues[0]["detail"]))
        names = set(files)
        root = self.prepare(project_id, run_id).resolve()
        for folder in (root / "src" / "hooks", root / "src" / "components"):
            if folder.exists():
                for previous_file in folder.iterdir():
                    if previous_file.is_file() and previous_file.relative_to(root).as_posix() not in names | {TEMPLATE_STORAGE_FILE}:
                        previous_file.unlink()
        written: list[dict[str, Any]] = []
        for name in sorted(files):
            data = files[name].encode("utf-8")
            digest = sha256(data)
            operation_key = f"write:{round_number}:{name}:{digest}"
            target = (root / name).resolve()
            if not target.is_relative_to(root):
                raise UnsafeSource("文件路径越界")
            previous = self.store.operation_get(run_id, operation_key)
            if previous and target.exists() and sha256(target.read_bytes()) == digest:
                written.append(previous)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".tmp")
            temp.write_bytes(data)
            os.replace(temp, target)
            result = {"path": name, "sha256": digest, "bytes": len(data)}
            self.store.operation_set(run_id, operation_key, result)
            written.append(result)
        self.store.update_run(run_id, event_type="files_written", event_payload={"files": written, "round": round_number})
        return written

    def _clean_env(self) -> dict[str, str]:
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME", "TMPDIR"}
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env["npm_config_cache"] = str(self.settings.data_dir / "npm-cache")
        env["CI"] = "1"
        return env

    def _run_command(self, command: list[str], cwd: Path, run_id: str, timeout: int) -> tuple[int, str]:
        executable = shutil.which(command[0])
        if not executable:
            raise RuntimeError(f"未找到构建工具 {command[0]}")
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as output_file:
            process = subprocess.Popen([executable, *command[1:]], cwd=cwd, env=self._clean_env(), stdout=output_file,
                                       stderr=subprocess.STDOUT)
            started = time.monotonic()
            while process.poll() is None:
                if self.store.get_run(run_id)["cancel_requested"]:
                    process.kill()
                    process.wait()
                    raise RunCancelled("构建已取消")
                active_seconds = self.store.active_elapsed_seconds(run_id)
                run_seconds_limit = effective_limits(self.store.get_run(run_id))["run_seconds"]
                if active_seconds >= run_seconds_limit:
                    process.kill()
                    process.wait()
                    raise BudgetExceeded("run_seconds", observed=math.ceil(active_seconds),
                                         limit=run_seconds_limit)
                if time.monotonic() - started > timeout:
                    process.kill()
                    process.wait()
                    raise RuntimeError("构建超时")
                time.sleep(0.2)
            output_file.seek(0)
            output = output_file.read()
            return process.returncode, output[-20_000:]

    def build(self, project_id: str, run_id: str) -> dict[str, Any]:
        root = self.prepare(project_id, run_id)
        log = root / "build.log"
        steps = []
        for command, timeout in [(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], 180), (["npm", "run", "build"], 120)]:
            started = time.monotonic()
            try:
                return_code, output = self._run_command(command, root, run_id, timeout)
            except (RuntimeError, OSError) as exc:
                output = f"构建环境执行失败：{type(exc).__name__}: {exc}"
                steps.append({"command": " ".join(command), "exit_code": None, "seconds": round(time.monotonic() - started, 1)})
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n$ {' '.join(command)}\n{output}\n")
                return {"ok": False, "steps": steps, "diagnostics": output, "log": str(log),
                        "environment_failure": True}
            steps.append({"command": " ".join(command), "exit_code": return_code, "seconds": round(time.monotonic() - started, 1)})
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"\n$ {' '.join(command)}\n{output}\n")
            if return_code != 0:
                return {"ok": False, "steps": steps, "diagnostics": output[-6000:], "log": str(log)}
        return {"ok": True, "steps": steps, "diagnostics": "", "log": str(log)}

    def package_candidate(self, project_id: str, run_id: str, build: dict[str, Any]) -> dict[str, Any]:
        source = self.workspace(project_id, run_id)
        generated = sorted(path for path in source.rglob("*") if path.is_file() and "node_modules" not in path.parts
                           and ".vite" not in path.parts and path.name != "build.log" and not path.name.endswith(".tsbuildinfo"))
        digest_input = "\n".join(f"{path.relative_to(source).as_posix()}:{sha256(path.read_bytes())}" for path in generated)
        digest = sha256(digest_input.encode("utf-8"))
        target = self.candidate(project_id, run_id, digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=target.parent, prefix="package-") as staging:
                temp = Path(staging) / "artifact"
                shutil.copytree(source, temp, ignore=shutil.ignore_patterns("node_modules", ".vite", "*.tsbuildinfo"))
                os.replace(temp, target)
        files = []
        built = []
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(target).as_posix()
            entry = {"path": name, "sha256": sha256(path.read_bytes()), "bytes": path.stat().st_size}
            if name.startswith("dist/"):
                built.append(entry)
            elif name != "build.log":
                files.append(entry)
        return {"digest": digest, "manifest": {"files": files, "build_files": built,
                "build": {"ok": build["ok"], "steps": build["steps"]}, "template": "react-vite-v4",
                "preview": {"status": "candidate"}}}

    def probe_candidate(self, project_id: str, run_id: str, digest: str) -> dict[str, Any]:
        root = (self.candidate(project_id, run_id, digest) / "dist").resolve()
        index = root / "index.html"
        if not index.is_file():
            return {"ok": False, "reason": "预览入口文件不存在", "checked_assets": 0}
        html = index.read_text(encoding="utf-8", errors="replace")
        if 'id="root"' not in html or "<script" not in html:
            return {"ok": False, "reason": "预览入口缺少应用挂载点或脚本", "checked_assets": 0}
        references = re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", html)
        if not references:
            return {"ok": False, "reason": "预览入口没有静态资源引用", "checked_assets": 0}
        checked = 0
        for reference in references:
            if not reference.startswith("./assets/"):
                return {"ok": False, "reason": "预览入口引用了未隔离的资源", "checked_assets": checked}
            asset = (root / reference).resolve()
            if not asset.is_relative_to(root) or not asset.is_file():
                return {"ok": False, "reason": "预览静态资源缺失", "checked_assets": checked}
            checked += 1
        return {"ok": True, "reason": "入口与静态资源可读取", "checked_assets": checked,
                "level": "static_assets_only"}

    def commit_candidate(self, project_id: str, run_id: str, digest: str) -> None:
        source = self.candidate(project_id, run_id, digest)
        if not source.is_dir():
            raise FileNotFoundError("候选产物不存在")
        target = self.artifact(project_id, run_id)
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent, prefix="commit-") as staging:
            temp = Path(staging) / "artifact"
            shutil.copytree(source, temp)
            os.replace(temp, target)

    def remove_artifact(self, project_id: str, run_id: str) -> None:
        root = (self.settings.data_dir / "artifacts").resolve()
        target = self.artifact(project_id, run_id).resolve()
        if not target.is_relative_to(root) or target == root or target.parent.parent != root:
            raise ValueError("产物清理路径越界")
        if target.is_dir():
            shutil.rmtree(target)

    def read_artifact_file(self, project_id: str, run_id: str, name: str) -> str:
        if not GENERATED_FILE.fullmatch(name) and name not in {"package.json", "package-lock.json", "index.html", "tsconfig.json", "src/main.tsx", "build.log"}:
            raise UnsafeSource("不允许读取此文件")
        path = self.artifact(project_id, run_id) / name
        if not path.exists():
            raise FileNotFoundError(name)
        return path.read_text(encoding="utf-8", errors="replace")

    def read_build_log(self, project_id: str, run_id: str) -> str:
        path = self.workspace(project_id, run_id) / "build.log"
        if not path.exists():
            raise FileNotFoundError("build.log")
        return path.read_text(encoding="utf-8", errors="replace")[-20_000:]
