"""Safe, bounded exception metadata shared by the workbench write paths."""

from __future__ import annotations

import logging
import re
from typing import Iterator

from .model import BudgetExceeded, ModelOutputError
from .runner import UnsafeSource
from .azure_artifacts import VersionCommitError
from .source_harness import source_validation_reason


logger = logging.getLogger(__name__)

REASONS = {
    "model_output_invalid": "模型输出未通过结构校验，任务已停止。",
    "model_call_failed": "模型服务调用失败，任务已停止。",
    "plan_validation_failed": "构建计划未通过产品边界校验，当前任务已停止。",
    "build_failed": "生成应用的构建未通过。",
    "build_no_progress": "连续 3 次构建出现同一组错误，自动源码修复已停止。",
    "build_recurring_error": "同一种构建错误累计出现第 5 次，自动源码修复已停止。",
    "build_repair_limit": "已达到 60 轮自动源码修复上限，构建仍未通过。",
    "preview_failed": "生成应用的预览检查未通过。",
    "version_commit_failed": "版本保存失败：数据库约束拒绝候选文件，写入已回滚。",
    "budget_exceeded": "本次任务达到调用、用量或时间预算上限。",
    "unsafe_source": "生成源码未通过安全检查，任务已停止。",
    "agent_unhandled": "任务执行时发生未预期异常。",
    "api_unhandled": "服务端处理请求时发生未预期异常。",
}

PLAN_VALIDATION_REASONS = {
    "incompatible_request": "当前需求要求服务端业务存储或排除 localStorage，与生成应用的存储边界冲突。请调整需求后开始新一轮。",
    "missing_features": "模型生成的计划缺少功能或验收点，自动修正后仍未补齐。",
    "unsupported_storage": "模型生成的计划包含不支持的存储方案；生成应用的业务数据只能保存在项目预览域 localStorage。",
    "missing_storage_model": "计划要求持久化数据，但数据模型没有写明使用项目预览域 localStorage。",
    "missing_refresh_check": "计划要求持久化数据，但没有验收刷新或重新进入后的数据读回。",
    "storage_limitation_conflict": "计划的限制说明与 localStorage 持久化要求冲突。",
    "invalid_plan": "模型生成的计划未通过结构或产品边界校验，自动修正后仍未解决。",
}

MODEL_OUTPUT_REASONS = {
    "length": "模型输出被长度限制截断，未形成完整 JSON。",
    "finish_reason": "模型响应未正常结束，未形成完整 JSON。",
    "invalid_json": "模型重试后仍未返回合法 JSON，当前步骤已停止。",
    "not_object": "模型重试后返回的 JSON 不是对象，当前步骤已停止。",
}

PLAN_VALIDATION_ERROR_CODES = {
    "模型计划缺少功能或验收点": "missing_features",
    "生成应用只能在独立预览 origin 使用 localStorage 保存业务数据": "unsupported_storage",
    "需要持久化的计划必须在数据模型中明确使用项目预览域 localStorage": "missing_storage_model",
    "需要持久化的计划必须验收刷新或重进后的数据读回": "missing_refresh_check",
    "计划限制与 localStorage 持久化边界冲突": "storage_limitation_conflict",
}


def plan_validation_error_code(exc: ValueError) -> str:
    return PLAN_VALIDATION_ERROR_CODES.get(str(exc), "invalid_plan")


class SourceValidationError(UnsafeSource):
    def __init__(self, codes: tuple[str, ...]):
        self.codes = codes
        super().__init__(source_validation_reason(codes))


class PlanValidationError(RuntimeError):
    """A plan violates a fixed, user-visible product rule after bounded correction."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code if reason_code in PLAN_VALIDATION_REASONS else "invalid_plan"
        super().__init__(PLAN_VALIDATION_REASONS[self.reason_code])


PHASES = {
    "Clarify", "ClarityGate", "WaitClarification", "Plan", "WaitPlan", "Prepare", "ValidateSource",
    "CodeLoop", "BusinessDataCheck", "BuildTest", "Diagnose", "PackageCandidate", "PreviewCheck", "CommitVersion", "NeedsUser", "Done",
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
    if any(isinstance(item, PlanValidationError) for item in chain):
        code = "plan_validation_failed"
        kind = "PlanValidationError"
    elif any(isinstance(item, VersionCommitError) for item in chain):
        code = "version_commit_failed"
        kind = "VersionCommitError"
    elif any(isinstance(item, ModelOutputError) for item in chain):
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

