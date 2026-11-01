"""Safe, structured descriptions of model and run budget stops."""

from __future__ import annotations


# New runs snapshot these limits. Rows created before this migration have NULL
# limits and continue using the previous defaults until their owner extends them.
DEFAULT_LIMITS = {"model_calls": 80, "total_tokens": 100_000, "run_seconds": 900, "fix_rounds": 60}
LEGACY_LIMITS = {"model_calls": 80, "total_tokens": 40_000, "run_seconds": 900, "fix_rounds": 60}
EXTENSION_STEPS = {"model_calls": 40, "total_tokens": 100_000, "run_seconds": 900, "fix_rounds": 30}
LIMIT_COLUMNS = {kind: f"max_{kind}" for kind in DEFAULT_LIMITS}


def effective_limits(run: dict) -> dict[str, int]:
    return {kind: int(run.get(column) if run.get(column) is not None else LEGACY_LIMITS[kind])
            for kind, column in LIMIT_COLUMNS.items()}


def budget_reason(kind: str, observed: int, limit: int) -> str:
    """Format trusted numeric budget metadata without persisting exception text."""
    if not isinstance(observed, int) or not isinstance(limit, int) or limit < 0:
        return "本次任务达到调用、用量或时间预算上限。"
    if kind == "model_calls":
        return f"模型调用次数达到上限：已调用 {observed} 次，上限 {limit} 次。"
    if kind == "total_tokens":
        return f"模型 Token 用量达到上限：已用 {observed}，上限 {limit}。"
    if kind == "run_seconds":
        return f"Agent 累计执行 {observed} 秒，达到 {limit} 秒上限（等待用户确认不计时）。"
    if kind == "output_reserve":
        return f"可用于模型输出的 Token 余量为 {observed}，低于最低所需的 {limit}。"
    return "本次任务达到调用、用量或时间预算上限。"
