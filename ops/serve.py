"""Run the standalone operations server: python -m ops.serve."""

from __future__ import annotations

import uvicorn

from .config import OpsSettings


def main() -> None:
    settings = OpsSettings.from_env()
    uvicorn.run("ops.api:app", host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
