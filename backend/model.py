from __future__ import annotations

import json
import math
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from .budget import budget_reason, effective_limits
from .settings import Settings
from .store import Store
from .model_credentials import ModelCredentials


class BudgetExceeded(Exception):
    def __init__(self, kind: str, *, observed: int, limit: int):
        self.kind = kind
        self.observed = observed
        self.limit = limit
        super().__init__(budget_reason(kind, observed, limit))


class RunCancelled(Exception):
    pass


class ModelOutputError(Exception):
    def __init__(self, message: str, *, reason_code: str = "invalid_output"):
        self.reason_code = reason_code
        super().__init__(message)


class ModelGateway:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.client = OpenAI(api_key=settings.model_api_key or "not-configured", base_url=settings.model_base_url, timeout=120)
        self._run_credentials: dict[str, ModelCredentials] = {}
        self._credentials_lock = threading.Lock()
        from .invite_auth import InviteAuth
        self._invite_hashes = InviteAuth(settings.invite_code).allowed

    def configure_platform_run(self, run_id: str, invite_hash: str) -> None:
        if invite_hash not in self._invite_hashes or not self.settings.model_api_key:
            raise RuntimeError("测试模型暂不可用，请使用自己的 API Key")
        self.store.operation_set(run_id, "platform_model_access", {"invite_hash": invite_hash})

    def platform_quota_remaining(self, invite_hash: str) -> tuple[int, int]:
        from .invite_auth import InviteAuth
        if invite_hash not in self._invite_hashes:
            raise RuntimeError("测试身份已失效")
        today = datetime.now(timezone.utc).date().isoformat()
        calls = tokens = 0
        for project in self.store.list_projects(InviteAuth.owner(invite_hash)):
            for run in self.store.get_project(project["id"], InviteAuth.owner(invite_hash))["runs"]:
                access = self.store.operation_get(run["id"], "platform_model_access")
                if str(run["created_at"]).startswith(today) and isinstance(access, dict) and access.get("invite_hash") == invite_hash:
                    calls += run["model_calls"]
                    tokens += run["tokens_used"]
        return self.settings.invite_daily_model_calls - calls, self.settings.invite_daily_tokens - tokens

    def check_platform_quota(self, invite_hash: str) -> int:
        calls, tokens = self.platform_quota_remaining(invite_hash)
        if calls <= 0 or tokens < 512:
            raise RuntimeError("今日测试模型用量已达上限，请使用自己的 API Key")
        return tokens

    def configure_run(self, run_id: str, credentials: ModelCredentials) -> None:
        self.store.operation_set(run_id, "platform_model_access", {})
        self.store.operation_set(run_id, "user_model_config", {"provider": credentials.provider,
            "base_url": credentials.base_url, "model_name": credentials.model_name, "needs_key": True})
        with self._credentials_lock:
            self._run_credentials[run_id] = credentials

    def has_run_credentials(self, run_id: str) -> bool:
        with self._credentials_lock:
            return run_id in self._run_credentials

    def release_run_credentials(self, run_id: str) -> None:
        with self._credentials_lock:
            self._run_credentials.pop(run_id, None)

    def check_limits(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        limits = effective_limits(run)
        if run["cancel_requested"]:
            raise RunCancelled("任务已取消")
        if run["model_calls"] >= limits["model_calls"]:
            raise BudgetExceeded("model_calls", observed=run["model_calls"], limit=limits["model_calls"])
        if run["tokens_used"] >= limits["total_tokens"]:
            raise BudgetExceeded("total_tokens", observed=run["tokens_used"], limit=limits["total_tokens"])
        self.check_execution_time(run_id)

    def check_execution_time(self, run_id: str) -> None:
        elapsed = self.store.active_elapsed_seconds(run_id)
        limit = effective_limits(self.store.get_run(run_id))["run_seconds"]
        if elapsed >= limit:
            raise BudgetExceeded("run_seconds", observed=math.ceil(elapsed), limit=limit)

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000) -> dict[str, Any]:
        with self._credentials_lock:
            credentials = self._run_credentials.get(run_id)
        if credentials is None and self.store.operation_get(run_id, "user_model_config"):
            raise RuntimeError("模型 Key 需要重新提供，请打开模型设置并刷新任务")
        platform_access = self.store.operation_get(run_id, "platform_model_access") if credentials is None else None
        platform_allowed = (isinstance(platform_access, dict)
                            and platform_access.get("invite_hash") in self._invite_hashes
                            and bool(self.settings.model_api_key))
        if credentials is None and not platform_allowed:
            raise RuntimeError("请先填写自己的 API Key，或使用有效邀请码登录")
        if platform_allowed:
            self.check_platform_quota(platform_access["invite_hash"])
        if credentials is None and not self.settings.model_api_key:
            raise RuntimeError("请先在模型设置中填写 API Key")
        cached = self.store.cache_get(run_id, node, cache_key)
        if cached is not None:
            return cached
        client = (OpenAI(api_key=credentials.api_key, base_url=credentials.base_url, timeout=120)
                  if credentials else self.client)
        model_name = credentials.model_name if credentials else self.settings.model_name
        messages = [
            {"role": "system", "content": system + "\n请只输出一个合法的 JSON 对象，不要输出 Markdown。"},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None
        request_max_tokens = max_tokens
        # Plans have a strict JSON schema and a small output budget. Deep
        # reasoning can consume the entire allowance before JSON is emitted.
        reasoning_effort = self.settings.model_code_reasoning_effort if node in {"code_loop", "plan"} else self.settings.model_reasoning_effort
        provider = credentials.provider if credentials else "deepseek"
        thinking_type = "disabled" if reasoning_effort == "none" else "enabled"
        for attempt in range(4):
            self.check_limits(run_id)
            run_before_call = self.store.get_run(run_id)
            total_token_limit = effective_limits(run_before_call)["total_tokens"]
            run_seconds_limit = effective_limits(run_before_call)["run_seconds"]
            remaining = total_token_limit - run_before_call["tokens_used"]
            if platform_allowed:
                remaining = min(remaining, self.check_platform_quota(platform_access["invite_hash"]))
            input_reserve = sum(len(message["content"]) for message in messages)
            call_max_tokens = min(request_max_tokens, remaining - input_reserve)
            if call_max_tokens < 512:
                raise BudgetExceeded("output_reserve", observed=remaining - input_reserve, limit=512)
            self.store.record_model_attempt(run_id, node)
            try:
                remaining_seconds = max(0.1, run_seconds_limit - self.store.active_elapsed_seconds(run_id))
                options: dict[str, Any] = {"model": model_name, "messages": messages, "stream": False,
                    "response_format": {"type": "json_object"}, "max_tokens": call_max_tokens,
                    "timeout": min(120, remaining_seconds)}
                if provider == "deepseek":
                    options.update(reasoning_effort=reasoning_effort, extra_body={"thinking": {"type": thinking_type}})
                response = client.chat.completions.create(**options)
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
                self.check_execution_time(run_id)
                if run["cancel_requested"]:
                    raise RunCancelled("任务已取消")
                if run["tokens_used"] > total_token_limit:
                    raise BudgetExceeded("total_tokens", observed=run["tokens_used"], limit=total_token_limit)
                if choice.finish_reason == "length":
                    request_max_tokens = min(call_max_tokens * 2, total_token_limit)
                    raise ModelOutputError("模型输出长度不足，JSON 未完成", reason_code="length")
                if choice.finish_reason != "stop":
                    raise ModelOutputError("模型输出中断", reason_code="finish_reason")
                try:
                    value = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise ModelOutputError("模型没有返回合法 JSON", reason_code="invalid_json") from exc
                if not isinstance(value, dict):
                    raise ModelOutputError("模型输出必须是 JSON 对象", reason_code="not_object")
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
                self.store.record_model_output_issue(run_id, node=node, attempt=attempt + 1,
                                                     reason_code=exc.reason_code)
                if "长度不足" not in str(exc):
                    messages.append({"role": "user", "content": "上一个响应不符合要求。请重发完整、有效的 JSON 对象，字段和值必须齐全。"})
                if attempt >= 1:
                    break
            if attempt < 3:
                time.sleep(min(2 ** attempt, 4) + random.uniform(0, 0.25))
        if isinstance(last_error, ModelOutputError):
            raise RuntimeError(f"模型输出未完成：{last_error}") from last_error
        raise RuntimeError(f"模型调用失败：{type(last_error).__name__ if last_error else '未知错误'}")
