from __future__ import annotations

import logging
import logging.config
import os
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Any


# Per-request correlation id. Set by RequestLoggingMiddleware; "-" outside
# a request scope so file columns stay aligned.
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="-")


# Matches a `token` query parameter and captures its `?token=` / `&token=`
# prefix; the value runs until the next `&`, whitespace, or quote (the access
# log wraps the request line in quotes and the URL is space-delimited from the
# HTTP version). Case-insensitive so `Token=` is covered too.
_TOKEN_QUERY_RE = re.compile(r"""(?i)([?&]token=)[^&\s"']*""")


class RequestIdFilter(logging.Filter):
    """Attach the current request id from the ContextVar onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if not hasattr(record, "req_id") or not getattr(record, "req_id", None):
            record.req_id = request_id_ctx.get()
        return True


class RedactTokenFilter(logging.Filter):
    """Redact the value of a `token` query parameter from a log line.

    The `/three-d` route accepts the Firebase ID token as `?token=...` so it can
    be opened in a new browser tab, and uvicorn's access logger writes the full
    request line (path + query) to access.log on disk. Replace the token value
    with ``REDACTED`` so the secret never lands on disk, keeping the rest of the
    line intact. Applied in the logging layer so it covers any route.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging break a request
            return True
        if "token=" in msg.lower():
            # Collapse args into the redacted, already-rendered message so the
            # handler's formatter re-renders nothing (empty args is falsy, so no
            # further %-interpolation of any literal % in the URL).
            record.msg = _TOKEN_QUERY_RE.sub(r"\1REDACTED", msg)
            record.args = ()
        return True


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
    errors_log = str(server_dir / "errors.log")

    level = (log_level or "info").upper()

    # Includes req_id when set via RequestLoggingMiddleware; falls back to "-"
    # so the column stays aligned for records emitted outside a request.
    server_fmt = (
        "%(asctime)s [%(levelname)s] %(name)s req=%(req_id)s: %(message)s"
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "req_id": {
                "()": "app.logging_setup.RequestIdFilter",
            },
            "redact_token": {
                "()": "app.logging_setup.RedactTokenFilter",
            },
        },
        "formatters": {
            "default": {
                "format": server_fmt,
            },
            "access": {
                # Uvicorn renders the full "GET /path HTTP/1.1 200" string into
                # %(message)s for us; we just prefix our own req_id so a single
                # `grep req=<id> logs/server/*.log` surfaces every line for that
                # request, including the access entry.
                "format": "%(asctime)s [%(levelname)s] %(name)s req=%(req_id)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": "WARNING",
                "stream": "ext://sys.stdout",
                "filters": ["req_id"],
            },
            "server_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": level,
                "filename": server_log,
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
                "filters": ["req_id"],
            },
            "errors_file": {
                # Fast-triage: every ERROR+ across all loggers, one file.
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": "ERROR",
                "filename": errors_log,
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
                "filters": ["req_id"],
            },
            "access_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "access",
                "level": level,
                "filename": access_log,
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
                "filters": ["redact_token", "req_id"],
            },
        },
        "loggers": {
            # App code: everything to file, only warnings/errors to console
            "pocket_drs": {"level": level, "handlers": ["console", "server_file", "errors_file"], "propagate": False},
            "pocket_drs.job": {"level": level, "handlers": ["server_file", "errors_file"], "propagate": False},

            # uvicorn: file-only for access logs, minimal console for errors
            "uvicorn": {"level": level, "handlers": ["server_file", "errors_file"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console", "server_file", "errors_file"], "propagate": False},
            "uvicorn.access": {"level": level, "handlers": ["access_file"], "propagate": False},
        },
        "root": {"level": level, "handlers": ["console", "server_file", "errors_file"]},
    }


def configure_logging(*, log_level: str = "info") -> None:
    logging.config.dictConfig(build_uvicorn_log_config(log_level=log_level))

    # Ensure our named loggers exist (helps mypy/linters and avoids typos).
    logging.getLogger("pocket_drs")
    logging.getLogger("pocket_drs.job")
