from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .model import RunCancelled
from .settings import Settings
from .store import Store


ALLOWED_FILES = {"src/App.tsx", "src/App.css"}
FORBIDDEN_SOURCE = re.compile(
    r"\b(?:eval|Function|require|XMLHttpRequest|WebSocket)\s*\(|"
    r"\b(?:fetch|localStorage|sessionStorage|document\.cookie|import\.meta\.env|process\.env|window\.(?:parent|top|location)|document\.location|navigator\.serviceWorker|dangerouslySetInnerHTML|srcDoc)\b|"
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


class UnsafeSource(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalRunner:
    """Trusted local MVP1 build only. This is not a public code sandbox."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def workspace(self, project_id: str, run_id: str) -> Path:
        return self.settings.data_dir / "projects" / project_id / "runs" / run_id / "workspace"

    def artifact(self, project_id: str, run_id: str) -> Path:
        return self.settings.data_dir / "artifacts" / project_id / run_id

    def prepare(self, project_id: str, run_id: str) -> Path:
        if self.settings.app_env != "local":
            raise RuntimeError("MVP1 同宿主构建仅允许 APP_ENV=local")
        target = self.workspace(project_id, run_id)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.settings.template_dir, target, ignore=shutil.ignore_patterns("node_modules", "dist"))
        return target

    def validate_source(self, name: str, content: str) -> None:
        if name not in ALLOWED_FILES or not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 60_000:
            raise UnsafeSource("生成文件不在允许范围内或内容无效")
        forbidden = FORBIDDEN_SOURCE.search(content)
        if forbidden:
            raise UnsafeSource(f"生成代码包含 MVP1 不允许的能力：{forbidden.group(0)}")
        if name.endswith(".tsx"):
            imports = IMPORT_LINE.findall(content)
            if any(module not in {"react", "./App.css", "./appData"} for module in imports):
                raise UnsafeSource("生成代码只能导入 React、模板样式和受控数据接口")
            if "export default" not in content:
                raise UnsafeSource("缺少默认导出的 React 组件")
            for update in STATE_UPDATER_BLOCK.finditer(content):
                if UPDATER_SIDE_EFFECT.search(update.group("body")):
                    raise UnsafeSource("React 状态更新函数中不能保存数据或调用其他 setState；请在事件处理函数中完成副作用")

    def write_generated(self, project_id: str, run_id: str, files: dict[str, str], round_number: int) -> list[dict[str, Any]]:
        if set(files) != ALLOWED_FILES:
            raise UnsafeSource("必须生成 App.tsx 和 App.css 两个文件")
        for name, content in files.items():
            self.validate_source(name, content)
        root = self.prepare(project_id, run_id).resolve()
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
            return_code, output = self._run_command(command, root, run_id, timeout)
            steps.append({"command": " ".join(command), "exit_code": return_code, "seconds": round(time.monotonic() - started, 1)})
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"\n$ {' '.join(command)}\n{output}\n")
            if return_code != 0:
                return {"ok": False, "steps": steps, "diagnostics": output[-6000:], "log": str(log)}
        return {"ok": True, "steps": steps, "diagnostics": "", "log": str(log)}

    def package(self, project_id: str, run_id: str, build: dict[str, Any]) -> dict[str, Any]:
        source = self.workspace(project_id, run_id)
        target = self.artifact(project_id, run_id)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=target.parent, prefix="package-") as staging:
                temp = Path(staging) / "artifact"
                shutil.copytree(source, temp, ignore=shutil.ignore_patterns("node_modules", ".vite"))
                os.replace(temp, target)
        files = []
        for name in sorted(ALLOWED_FILES | {"src/appData.ts", "package.json", "package-lock.json", "index.html"}):
            path = target / name
            if path.exists():
                files.append({"path": name, "sha256": sha256(path.read_bytes()), "bytes": path.stat().st_size})
        return {"files": files, "build": {"ok": build["ok"], "steps": build["steps"]}, "template": "react-vite-v2", "preview": {"status": "local"}}

    def read_artifact_file(self, project_id: str, run_id: str, name: str) -> str:
        if name not in ALLOWED_FILES | {"src/appData.ts", "package.json", "index.html", "build.log"}:
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
