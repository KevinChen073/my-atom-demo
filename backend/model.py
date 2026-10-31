from __future__ import annotations

import json
import random
import time
from datetime import datetime
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from .settings import Settings
from .store import Store


class BudgetExceeded(Exception):
    pass


class RunCancelled(Exception):
    pass


class ModelOutputError(Exception):
    pass


class ModelGateway:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.client = OpenAI(api_key=settings.model_api_key or "not-configured", base_url=settings.model_base_url, timeout=120)

    def check_limits(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run["cancel_requested"]:
            raise RunCancelled("任务已取消")
        if run["model_calls"] >= self.settings.max_model_calls:
            raise BudgetExceeded("模型调用次数已达上限")
        if run["tokens_used"] >= self.settings.max_total_tokens:
            raise BudgetExceeded("模型 token 预算已达上限")
        elapsed = (datetime.now().astimezone() - datetime.fromisoformat(run["created_at"])).total_seconds()
        if elapsed > self.settings.max_run_seconds:
            raise BudgetExceeded("任务执行时间已达上限")

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000) -> dict[str, Any]:
        cached = self.store.cache_get(run_id, node, cache_key)
        if cached is not None:
            return cached
        if not self.settings.model_api_key:
            raise RuntimeError("MODEL_API_KEY 未配置，请在本地 .env 中设置")
        messages = [
            {"role": "system", "content": system + "\n请只输出一个合法的 JSON 对象，不要输出 Markdown。"},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None
        request_max_tokens = max_tokens
        reasoning_effort = self.settings.model_code_reasoning_effort if node == "code_loop" else self.settings.model_reasoning_effort
        thinking_type = "disabled" if reasoning_effort == "none" else "enabled"
        for attempt in range(4):
            self.check_limits(run_id)
            remaining = self.settings.max_total_tokens - self.store.get_run(run_id)["tokens_used"]
            input_reserve = sum(len(message["content"]) for message in messages)
            call_max_tokens = min(request_max_tokens, remaining - input_reserve)
            if call_max_tokens < 512:
                raise BudgetExceeded("剩余 token 预算不足以完成模型输出")
            self.store.record_model_attempt(run_id, node)
            try:
                response = self.client.chat.completions.create(
                    model=self.settings.model_name,
                    messages=messages,
                    stream=False,
                    reasoning_effort=reasoning_effort,
                    extra_body={"thinking": {"type": thinking_type}},
                    response_format={"type": "json_object"},
                    max_tokens=call_max_tokens,
                )
                choice = response.choices[0]
                content = choice.message.content or ""
                reported_tokens = response.usage.total_tokens if response.usage else 0
                # Some compatible providers omit usage. Reserve the full response
                # allowance plus a conservative input estimate in that case.
                usage = reported_tokens if reported_tokens > 0 else call_max_tokens + input_reserve
                run = self.store.add_usage(run_id, usage)
                self.store.record_model_response(run_id, {
                    "node": node,
                    "attempt": attempt + 1,
                    "finish_reason": choice.finish_reason,
                    "max_tokens": call_max_tokens,
                    "reasoning_effort": reasoning_effort,
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                    "completion_tokens": getattr(response.usage, "completion_tokens", None),
                    "content_chars": len(content),
                })
                if run["cancel_requested"]:
                    raise RunCancelled("任务已取消")
                if run["tokens_used"] > self.settings.max_total_tokens:
                    raise BudgetExceeded("模型 token 预算已达上限")
                if choice.finish_reason == "length":
                    request_max_tokens = min(call_max_tokens * 2, self.settings.max_total_tokens)
                    raise ModelOutputError("模型输出长度不足，JSON 未完成")
                if choice.finish_reason != "stop":
                    raise ModelOutputError(f"模型输出中断（{choice.finish_reason}）")
                try:
                    value = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise ModelOutputError("模型没有返回合法 JSON") from exc
                if not isinstance(value, dict):
                    raise ModelOutputError("模型输出必须是 JSON 对象")
                self.store.cache_set(run_id, node, cache_key, value)
                return value
            except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                last_error = exc
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise RuntimeError(f"模型服务拒绝请求（HTTP {exc.status_code}）") from exc
                last_error = exc
            except ModelOutputError as exc:
                last_error = exc
                if "长度不足" not in str(exc):
                    messages.append({"role": "user", "content": "上一个响应不符合要求。请重发完整、有效的 JSON 对象，字段和值必须齐全。"})
                if attempt >= 1:
                    break
            if attempt < 3:
                time.sleep(min(2 ** attempt, 4) + random.uniform(0, 0.25))
        if isinstance(last_error, ModelOutputError):
            raise RuntimeError(f"模型输出未完成：{last_error}") from last_error
        raise RuntimeError(f"模型调用失败：{type(last_error).__name__ if last_error else '未知错误'}")
