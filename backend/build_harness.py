"""Bounded automatic repair decisions based on stable build error fingerprints."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from .source_harness import GENERATED_FILE, repair_feedback


ERROR_LINE = re.compile(r"error TS\d+|Could not resolve|Failed to resolve import|Transform failed|Unexpected token", re.I)
POSITION = re.compile(r"\(\d+,\d+\)|:\d+:\d+")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def error_fingerprints(result: dict[str, Any], category: str) -> list[str]:
    """Keep diagnostic identity stable across line shifts and log ordering."""
    command = str(((result.get("steps") or [{}])[-1]).get("command", ""))
    output = ANSI.sub("", str(result.get("diagnostics", "")))
    lines = output.splitlines()
    errors = [POSITION.sub("", line).strip().casefold() for line in lines if ERROR_LINE.search(line)]
    # Generic Vite wrapper text adds no identity. Its next line carries the
    # actual failure when Vite does not use one of the recognized error labels.
    specific = [line for line in errors if line != "error during build:"]
    if specific:
        errors = specific
    elif errors == ["error during build:"]:
        wrapper = next(index for index, line in enumerate(lines) if "error during build:" in line.casefold())
        detail = next((line.strip() for line in lines[wrapper + 1:] if line.strip()), "")
        errors = [POSITION.sub("", detail).casefold() or "error during build"]
    if not errors:
        errors = [POSITION.sub("", output).strip().casefold()[:500] or "unknown build failure"]
    normalized = sorted(set(re.sub(r"\s+", " ", line)[:500] for line in errors))
    return [hashlib.sha256(f"{category}|{command}|{line}".encode()).hexdigest()[:20] for line in normalized]


def repair_stop_reason(history: list[list[str]], fix_rounds: int, max_fix_rounds: int,
                       *, stage: str = "构建") -> tuple[str, str]:
    """Return a user-facing stop reason and a stable code, or empty strings."""
    if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
        return f"连续 3 次{stage}仍出现同一组错误，自动修复没有进展。请查看检查记录并指定修复方向。", "no_progress"
    counts = Counter(signature for attempt in history for signature in set(attempt))
    if any(count > 4 for count in counts.values()):
        return f"同一种{stage}错误累计出现第 5 次，已停止自动修复，避免重复循环。请查看检查记录并指定修复方向。", "recurring_error"
    if fix_rounds >= max_fix_rounds:
        return f"已完成最多 {max_fix_rounds} 轮自动源码修复，{stage}仍未通过。请查看检查记录并选择下一步。", "repair_limit"
    return "", ""


SOURCE_PATH = re.compile(r"\b(?:src[/\\](?:App\.tsx|app\.css|hooks[/\\][A-Za-z][A-Za-z0-9]*\.ts|components[/\\][A-Za-z][A-Za-z0-9]*\.tsx)|readme\.md)\b")
TS_DETAIL = re.compile(r"^(?:Property |Type |Did you mean|No overload matches|Object literal may only specify|The expected type)", re.I)


def build_error_blocks(output: str, *, limit: int = 6) -> list[str]:
    """Keep the decisive continuation line of a multiline TypeScript error."""
    lines = ANSI.sub("", output).splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if not ERROR_LINE.search(line):
            continue
        details: list[str] = []
        for follow in lines[index + 1:index + 5]:
            detail = follow.strip()
            if not detail or ERROR_LINE.search(detail) or SOURCE_PATH.search(detail):
                break
            if TS_DETAIL.search(detail):
                details.append(detail[:180])
            if len(details) >= 2:
                break
        blocks.append((line.strip() + (" | " + " | ".join(details) if details else ""))[:600])
        if len(blocks) >= limit:
            break
    return blocks


def build_repair_feedback(result: dict[str, Any], candidate_files: set[str]) -> dict[str, Any]:
    """A partial repair is allowed only when compiler evidence names generated files."""
    errors = build_error_blocks(str(result.get("diagnostics", "")))
    paths = sorted({path for line in errors for found in SOURCE_PATH.findall(line)
                    if (path := found.replace("\\", "/")) in candidate_files and GENERATED_FILE.fullmatch(path)})
    issues = [{"code": "source_compile", "file": path, "feedback": "; ".join(line for line in errors if path in line.replace("\\", "/"))[:400] or "修复该文件的编译或类型错误"}
              for path in paths]
    if not issues:
        issues = [{"code": "source_compile", "file": None,
                   "feedback": "; ".join(errors[:2])[:400] or "编译或类型错误，无法确定具体文件"}]
    return repair_feedback(issues, origin="build")
