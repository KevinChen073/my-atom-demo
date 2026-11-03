"""Source-level evidence that a generated app wires up its approved business data."""

from __future__ import annotations

import re
from typing import Any


READ = re.compile(r"\bgeneratedAppStorage\s*\.\s*getItem\s*\(")
WRITE = re.compile(r"\bgeneratedAppStorage\s*\.\s*setItem\s*\(")
NON_EXECUTABLE = re.compile(r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", re.DOTALL)
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
KEY_CONSTANT = re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*(['\"])([^'\"\n\\]*)\2")
KEY_ARGUMENT = re.compile(r"\bgeneratedAppStorage\s*\.\s*(?:getItem|setItem|removeItem)\s*\(\s*([^,)\n]+)")


def executable_text(content: str) -> str:
    return NON_EXECUTABLE.sub(lambda match: " " * len(match.group(0)), content)


def invalid_static_keys(content: str) -> bool:
    """Inspect simple literal and local-constant keys; dynamic expressions stay unproven."""
    source = COMMENTS.sub("", content)
    constants = {name: value for name, _, value in KEY_CONSTANT.findall(source)}
    for match in KEY_ARGUMENT.finditer(source):
        argument = match.group(1).strip()
        if len(argument) >= 2 and argument[0] in "\"'" and argument[-1] == argument[0] and "\\" not in argument:
            value = argument[1:-1]
        else:
            value = constants.get(argument)
        if value is not None and not KEY_PATTERN.fullmatch(value):
            return True
    return False


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
    for path, content in source.items():
        if invalid_static_keys(content):
            issues.append({"code": "invalid_business_data_key", "file": path,
                           "detail": "generatedAppStorage 的键名不符合模板规则：首字符须为英文字母，总长不超过 80 字符，其余只允许字母、数字、下划线、点、冒号和短横线"})
    return {"ok": not issues, "level": "source_contract_only", "required": True,
            "reason": "源码包含业务数据读写接线，已检查简单静态键名；浏览器实际读写尚未验证" if not issues else issues[0]["detail"],
            "read_files": reads, "write_files": writes, "issues": issues}
