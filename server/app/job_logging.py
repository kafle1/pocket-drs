from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .logging_setup import ensure_log_dirs


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
    artifact_log_path = artifacts_dir / "server.log"

    # Centralized job logs live in /logs/server/jobs/<job_id>.log
    dirs = ensure_log_dirs()
    central_log_path = dirs["server_jobs"] / f"{job_id}.log"

    logger = logging.getLogger("pocket_drs.job")
    logger.setLevel(logging.INFO)

    artifact_handler = logging.FileHandler(artifact_log_path, encoding="utf-8")
    artifact_handler.setLevel(logging.INFO)
    artifact_handler.setFormatter(_make_formatter(job_id))

    central_handler = logging.FileHandler(central_log_path, encoding="utf-8")
    central_handler.setLevel(logging.INFO)
    central_handler.setFormatter(_make_formatter(job_id))

    # Avoid double-handlers if something calls this twice for the same job.
    logger.addHandler(artifact_handler)
    logger.addHandler(central_handler)
    try:
        yield logger
    finally:
        logger.removeHandler(artifact_handler)
        logger.removeHandler(central_handler)
        artifact_handler.close()
        central_handler.close()
