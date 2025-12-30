from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
from typing import Any


def default_logs_root() -> Path:
    override = (os.environ.get("POCKET_DRS_LOG_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    # server/app/logging_setup.py -> server/app -> server -> repo root
    return Path(__file__).resolve().parents[2] / "logs"


def ensure_log_dirs() -> dict[str, Path]:
    root = default_logs_root()
    server_dir = root / "server"
    jobs_dir = server_dir / "jobs"

    server_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": root,
        "server": server_dir,
        "server_jobs": jobs_dir,
    }


def build_uvicorn_log_config(*, log_level: str = "info") -> dict[str, Any]:
    """Return a uvicorn-compatible logging config.

    Goals:
    - Keep full logs on disk under /logs
    - Minimal console output (errors + critical startup/shutdown only)
    - All details captured to files for debugging
    """

    dirs = ensure_log_dirs()
    server_dir = dirs["server"]

    server_log = str(server_dir / "server.log")
    access_log = str(server_dir / "access.log")

    level = (log_level or "info").upper()

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
            "access": {
                # Uvicorn access logs already render a complete message; avoid
                # relying on non-standard LogRecord fields.
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": "WARNING",
                "stream": "ext://sys.stdout",
            },
            "server_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": level,
                "filename": server_log,
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
            "access_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "access",
                "level": level,
                "filename": access_log,
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            # App code: everything to file, only warnings/errors to console
            "pocket_drs": {"level": level, "handlers": ["console", "server_file"], "propagate": False},
            "pocket_drs.job": {"level": level, "handlers": ["server_file"], "propagate": False},

            # uvicorn: file-only for access logs, minimal console for errors
            "uvicorn": {"level": level, "handlers": ["server_file"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console", "server_file"], "propagate": False},
            "uvicorn.access": {"level": level, "handlers": ["access_file"], "propagate": False},
        },
        "root": {"level": level, "handlers": ["console", "server_file"]},
    }


def configure_logging(*, log_level: str = "info") -> None:
    logging.config.dictConfig(build_uvicorn_log_config(log_level=log_level))

    # Ensure our named loggers exist (helps mypy/linters and avoids typos).
    logging.getLogger("pocket_drs")
    logging.getLogger("pocket_drs.job")
