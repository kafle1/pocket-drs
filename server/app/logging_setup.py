from __future__ import annotations

import logging
import logging.config
from contextvars import ContextVar
from typing import Any


# Per-request correlation id. Set by RequestLoggingMiddleware; "-" outside
# a request scope so log lines stay aligned.
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="-")


class RequestIdFilter(logging.Filter):
    """Attach the current request id from the ContextVar onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if not hasattr(record, "req_id") or not getattr(record, "req_id", None):
            record.req_id = request_id_ctx.get()
        return True


def build_uvicorn_log_config(*, log_level: str = "info") -> dict[str, Any]:
    """Return a uvicorn-compatible logging config.

    Everything goes to stdout, and whatever runs the server decides where it
    ends up: the container log, or ~/.pocket-drs/server.log under make host.
    """
    level = (log_level or "info").upper()
    fmt = "%(asctime)s [%(levelname)s] %(name)s req=%(req_id)s: %(message)s"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "req_id": {"()": "app.logging_setup.RequestIdFilter"},
        },
        "formatters": {
            "default": {"format": fmt},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": level,
                "stream": "ext://sys.stdout",
                "filters": ["req_id"],
            },
        },
        "loggers": {
            "pocket_drs": {"level": level, "handlers": ["console"], "propagate": False},
            "pocket_drs.job": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
            # the middleware already logs each request, and uvicorn only writes its own line when this has a handler
            "uvicorn.access": {"level": level, "handlers": [], "propagate": False},
        },
        "root": {"level": level, "handlers": ["console"]},
    }


def configure_logging(*, log_level: str = "info") -> None:
    logging.config.dictConfig(build_uvicorn_log_config(log_level=log_level))
    logging.getLogger("pocket_drs")
    logging.getLogger("pocket_drs.job")
