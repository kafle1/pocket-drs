from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _make_formatter(job_id: str) -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)s job=%(job_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        defaults={"job_id": job_id},
    )


@contextmanager
def job_log_context(*, job_id: str, artifacts_dir: Path) -> Iterator[logging.Logger]:
    """Attach a per-job file handler to a dedicated logger.

    - Writes to `<artifacts_dir>/server.log`.
    - Does not touch global/root logging configuration.
    - Always closes the handler.

    The returned logger is safe to use in background threads.
    """

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_dir / "server.log"

    logger = logging.getLogger("pocket_drs.job")
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(_make_formatter(job_id))

    # Avoid double-handlers if something calls this twice for the same job.
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        handler.close()
