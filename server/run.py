from __future__ import annotations

import os

import uvicorn

from app.logging_setup import build_uvicorn_log_config


def main() -> None:
    host = os.environ.get("POCKET_DRS_HOST", "0.0.0.0")
    port = int(os.environ.get("POCKET_DRS_PORT", "8000"))

    reload_raw = os.environ.get("POCKET_DRS_RELOAD", "0")
    reload = reload_raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    log_level = os.environ.get("POCKET_DRS_LOG_LEVEL", "info")

    log_config = build_uvicorn_log_config(log_level=log_level)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
