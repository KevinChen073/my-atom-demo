"""Safe, bounded exception metadata shared by the workbench write paths."""

from __future__ import annotations

import logging
import re
from typing import Iterator

from .model import BudgetExceeded, ModelOutputError
from .runner import UnsafeSource


logger = logging.getLogger(__name__)

REASONS = {
    "model_output_invalid": "模型输出未通过结构校验，任务已停止。",
    "model_call_failed": "模型服务调用失败，任务已停止。",
    "build_failed": "生成应用的构建未通过，自动修复次数已用尽。",
    "budget_exceeded": "本次任务达到调用、用量或时间预算上限。",
    "unsafe_source": "生成源码未通过安全检查，任务已停止。",
    "agent_unhandled": "任务执行时发生未预期异常。",
    "api_unhandled": "服务端处理请求时发生未预期异常。",
}

PHASES = {
    "Clarify", "WaitClarification", "Plan", "WaitPlan", "Prepare",
    "CodeLoop", "BuildTest", "Diagnose", "Package", "NeedsUser", "Done",
}


def cause_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify(exc: BaseException) -> tuple[str, str]:
    chain = tuple(cause_chain(exc))
    if any(isinstance(item, ModelOutputError) for item in chain):
        code = "model_output_invalid"
        kind = "ModelOutputError"
    elif any(isinstance(item, BudgetExceeded) for item in chain):
        code = "budget_exceeded"
        kind = "BudgetExceeded"
    elif any(isinstance(item, UnsafeSource) for item in chain):
        code = "unsafe_source"
        kind = "UnsafeSource"
    elif any("模型" in str(item) and isinstance(item, RuntimeError) for item in chain):
        code = "model_call_failed"
        kind = "ModelCallError"
    else:
        code = "agent_unhandled"
        name = type(exc).__name__
        kind = name[:80] if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) else "Exception"
    return code, kind


def safe_phase(phase: str | None) -> str:
    return phase if phase in PHASES else "Unknown"

