"""Configuration isolated from the workbench's model-key environment file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "ops" / ".env", override=False)


@dataclass(frozen=True)
class OpsSettings:
    db_path: Path | None
    admin_key: str
    static_dir: Path
    database_url: str = field(default="", repr=False)
    host: str = "127.0.0.1"
    port: int = 8002

    @classmethod
    def from_env(cls) -> "OpsSettings":
        raw_path = os.getenv("OPS_DB_PATH", "").strip()
        return cls(
            db_path=Path(raw_path).resolve() if raw_path else None,
            admin_key=os.getenv("OPS_ADMIN_KEY", ""),
            static_dir=ROOT / "ops-web" / "dist",
            database_url=os.getenv("OPS_DATABASE_URL", ""),
            host=os.getenv("OPS_HOST", "127.0.0.1"),
            port=int(os.getenv("OPS_PORT", "8002")),
        )
