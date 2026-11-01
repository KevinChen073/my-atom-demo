"""Validated, short-lived user model configuration; never persist the API key."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ModelCredentials:
    provider: str
    api_key: str
    base_url: str
    model_name: str


def validate_model_credentials(value: dict[str, str]) -> ModelCredentials:
    if not isinstance(value, dict) or any(not isinstance(value.get(name, ""), str)
                                          for name in ("provider", "api_key", "base_url", "model_name")):
        raise ValueError("模型配置格式无效")
    provider = value.get("provider", "")
    key = value.get("api_key", "").strip()
    base_url = value.get("base_url", "").strip().rstrip("/")
    model_name = value.get("model_name", "").strip()
    if provider not in {"deepseek", "openai_compatible"}:
        raise ValueError("请选择 DeepSeek 或 OpenAI 兼容服务")
    if not key or len(key) > 512 or "\n" in key or "\r" in key:
        raise ValueError("请填写有效的 API Key")
    if not model_name or len(model_name) > 100 or any(c in model_name for c in "\r\n\t"):
        raise ValueError("请填写有效的模型名称")
    parsed = urlparse(base_url)
    if (len(base_url) > 512 or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/", "/v1"}):
        raise ValueError("接口地址必须是 HTTPS 服务根地址或 /v1 地址")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname in {"localhost", "localhost.localdomain"} or parsed.hostname.endswith(".localhost"):
            raise ValueError("接口地址不能指向本机")
    else:
        raise ValueError("接口地址不能使用 IP 地址")
    return ModelCredentials(provider, key, base_url, model_name)
