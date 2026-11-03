"""Source-level evidence that a generated app wires up its approved business data."""

from __future__ import annotations

import re
from typing import Any


READ = re.compile(r"\bgeneratedAppStorage\s*\.\s*getItem\s*\(")
WRITE = re.compile(r"\bgeneratedAppStorage\s*\.\s*setItem\s*\(")
NON_EXECUTABLE = re.compile(r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", re.DOTALL)


def executable_text(content: str) -> str:
    return NON_EXECUTABLE.sub(lambda match: " " * len(match.group(0)), content)


def inspect_business_data(files: dict[str, str], plan: dict[str, Any]) -> dict[str, Any]:
    spec = plan.get("business_data") or {}
    required = bool(spec.get("required"))
    if not required:
        return {"ok": True, "level": "source_contract_only", "required": False,
                "reason": "已批准计划没有需要跨刷新保存的业务数据", "issues": []}

    source = {path: content for path, content in files.items() if path.endswith((".ts", ".tsx"))}
    reads = sorted(path for path, content in source.items() if READ.search(executable_text(content)))
    writes = sorted(path for path, content in source.items() if WRITE.search(executable_text(content)))
    targets = sorted(set(reads + writes)) or ["src/App.tsx"]
    issues = []
    if not reads:
        issues.append({"code": "missing_business_data_read", "file": targets[0],
                       "detail": "计划要求保存业务数据，但源码没有通过 generatedAppStorage.getItem 读回；刷新后无法恢复"})
    if not writes:
        issues.append({"code": "missing_business_data_write", "file": targets[0],
                       "detail": "计划要求保存业务数据，但源码没有通过 generatedAppStorage.setItem 写入"})
    return {"ok": not issues, "level": "source_contract_only", "required": True,
            "reason": "源码包含业务数据读写接线；浏览器实际读写尚未验证" if not issues else issues[0]["detail"],
            "read_files": reads, "write_files": writes, "issues": issues}
