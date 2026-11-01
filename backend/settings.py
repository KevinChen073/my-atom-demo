from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .budget import DEFAULT_LIMITS


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    data_dir: Path = Path(os.getenv("MYATOM_DATA_DIR", str(ROOT / "data"))).resolve()
    app_env: str = os.getenv("APP_ENV", "local")
    database_url: str = field(default_factory=lambda: os.getenv("MYATOM_DATABASE_URL", ""), repr=False)
    model_api_key: str = os.getenv("MODEL_API_KEY", "")
    model_name: str = os.getenv("MODEL_NAME", "deepseek-flash")
    model_base_url: str = os.getenv("MODEL_BASE_URL", "https://api.deepseek.com")
    model_reasoning_effort: str = os.getenv("MODEL_REASONING_EFFORT", "high")
    model_code_reasoning_effort: str = os.getenv("MODEL_CODE_REASONING_EFFORT", "none")
    max_model_calls: int = int(os.getenv("MAX_MODEL_CALLS", str(DEFAULT_LIMITS["model_calls"])))
    max_total_tokens: int = int(os.getenv("MAX_TOTAL_TOKENS", str(DEFAULT_LIMITS["total_tokens"])))
    max_run_seconds: int = int(os.getenv("MAX_RUN_SECONDS", str(DEFAULT_LIMITS["run_seconds"])))
    max_fix_rounds: int = int(os.getenv("MAX_FIX_ROUNDS", str(DEFAULT_LIMITS["fix_rounds"])))
    preview_port: int = int(os.getenv("PREVIEW_PORT", "8001"))
    workbench_origin: str = os.getenv("WORKBENCH_ORIGIN", "http://127.0.0.1:8000")
    preview_base_domain: str = os.getenv("PREVIEW_BASE_DOMAIN", "")
    trusted_demo: bool = os.getenv("MYATOM_TRUSTED_DEMO", "") == "1"

    def validate_azure_demo(self) -> None:
        """Fail closed before starting a container with persistent demo writes."""
        from urllib.parse import urlparse

        if self.app_env != "azure_demo":
            return
        origin = urlparse(self.workbench_origin)
        domain = self.preview_base_domain.lower().strip(".")
        if not self.trusted_demo or not self.database_url:
            raise RuntimeError("Azure 受信演示须显式启用并配置 PostgreSQL")
        if (origin.scheme != "https" or not origin.hostname or origin.netloc != origin.hostname
                or origin.path not in {"", "/"} or origin.query or origin.fragment):
            raise RuntimeError("Azure 工作台必须配置 HTTPS 单一 origin")
        if (not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", domain)
                or origin.hostname == domain or origin.hostname.endswith("." + domain)):
            raise RuntimeError("预览域须与工作台分离，且配置可用的独立域名")
        if not os.path.ismount(self.data_dir):
            raise RuntimeError("Azure data/ 必须是已挂载的持久 Azure Files 卷")

    @property
    def app_db(self) -> Path:
        return self.data_dir / "myatom.sqlite3"

    @property
    def checkpoint_db(self) -> Path:
        return self.data_dir / "checkpoints.sqlite3"

    @property
    def template_dir(self) -> Path:
        return self.root / "templates" / "react-vite"

