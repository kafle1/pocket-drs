from __future__ import annotations

import logging
import logging.config
from contextvars import ContextVar
from typing import Any


# set by RequestLoggingMiddleware; "-" outside a request so log lines stay aligned
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.req_id = request_id_ctx.get()
        return True


def build_uvicorn_log_config(*, log_level: str = "info") -> dict[str, Any]:
    # everything goes to stdout, which in production is the docker container log
    level = log_level.upper()
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
            "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
            # the middleware already logs each request, and uvicorn only writes its own line when this has a handler
            "uvicorn.access": {"level": level, "handlers": [], "propagate": False},
        },
        "root": {"level": level, "handlers": ["console"]},
    }


def configure_logging(*, log_level: str = "info") -> None:
    logging.config.dictConfig(build_uvicorn_log_config(log_level=log_level))
