from __future__ import annotations

import os
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
    atom_access_token: str = field(default_factory=lambda: os.getenv("ATOM_ACCESS_TOKEN", ""), repr=False)
    atom_preview_domain: str = os.getenv("ATOM_PREVIEW_DOMAIN", "").strip().lower()
    atom_preview_scheme: str = os.getenv("ATOM_PREVIEW_SCHEME", "https").strip().lower()

    @property
    def app_db(self) -> Path:
        return self.data_dir / "myatom.sqlite3"

    @property
    def checkpoint_db(self) -> Path:
        return self.data_dir / "checkpoints.sqlite3"

    @property
    def template_dir(self) -> Path:
        return self.root / "templates" / "react-vite"

