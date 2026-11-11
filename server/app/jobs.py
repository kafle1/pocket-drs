from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging_setup import configure_logging
from .models import ApiError, JobStatus, ProgressInfo

# jobs are cleaned up by age; job ids are unguessable, so no owner check on reads
MAX_JOB_AGE_S = 24 * 60 * 60


@dataclass(frozen=True)
class JobPaths:
    job_dir: Path
    video_path: Path
    request_path: Path
    status_path: Path
    result_path: Path
    artifacts_dir: Path


def data_dir() -> Path:
    # /data in the container; the repo's data/ when run straight from a checkout
    return Path(os.environ.get("POCKET_DRS_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")


def short_id(job_id: str) -> str:
    # enough to match log lines up, too little to fetch someone's result with
    return job_id[:8]


def _now_ms() -> int:
    return int(time.time() * 1000)


class JobStore:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def sweep(self) -> None:
        # a job dir's mtime moves whenever its status is rewritten
        jobs_root = self._data_dir / "jobs"
        if not jobs_root.exists():
            return
        cutoff = time.time() - MAX_JOB_AGE_S
        for job_dir in jobs_root.iterdir():
            try:
                if job_dir.is_dir() and job_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(job_dir, ignore_errors=True)
            except OSError:
                continue

    def create_job(self) -> tuple[str, JobPaths]:
        job_id = uuid.uuid4().hex
        paths = self.job_paths(job_id)
        paths.artifacts_dir.mkdir(parents=True)
        self.write_status(paths, status=JobStatus.queued, progress=ProgressInfo(pct=0, stage="queued"), error=None)
        return job_id, paths

    def job_paths(self, job_id: str) -> JobPaths:
        job_dir = self._data_dir / "jobs" / job_id
        return JobPaths(
            job_dir=job_dir,
            video_path=job_dir / "input.mp4",
            request_path=job_dir / "request.json",
            status_path=job_dir / "status.json",
            result_path=job_dir / "result.json",
            artifacts_dir=job_dir / "artifacts",
        )

    def exists(self, job_id: str) -> bool:
        # every route checks this first, so it also stops ids like ".." reaching the disk
        if re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
            return False
        try:
            mtime = (self._data_dir / "jobs" / job_id).stat().st_mtime
        except OSError:
            return False
        # the sweep runs hourly, so a result must stop being served the moment it is a day old
        return time.time() - mtime < MAX_JOB_AGE_S

    def remove(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            shutil.rmtree(self.job_paths(job_id).job_dir, ignore_errors=True)

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        # a poll must never read a half-written file
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, path)

    def write_request(self, paths: JobPaths, request_obj: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write_json(paths.request_path, request_obj)

    def write_status(
        self,
        paths: JobPaths,
        *,
        status: JobStatus,
        progress: ProgressInfo | None,
        error: ApiError | None,
    ) -> None:
        payload = {
            "job_id": paths.job_dir.name,
            "status": status.value,
            "updated_at_ms": _now_ms(),
            "progress": progress.model_dump() if progress else None,
            "error": error.model_dump() if error else None,
        }
        with self._lock:
            self._atomic_write_json(paths.status_path, payload)

    def read_status(self, paths: JobPaths) -> dict[str, Any]:
        with self._lock:
            raw = paths.status_path.read_text()
        if not raw.strip():
            raise RuntimeError("Job status unavailable (empty status file)")
        return json.loads(raw)

    def write_result(self, paths: JobPaths, payload: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write_json(paths.result_path, payload)

    def read_result(self, paths: JobPaths) -> dict[str, Any]:
        with self._lock:
            raw = paths.result_path.read_text()
        if not raw.strip():
            raise RuntimeError("Job result unavailable (empty result file)")
        return json.loads(raw)

    def drop_interrupted_jobs(self) -> list[str]:
        # the worker pool that owned these died with the last process, and a 404 makes the app send the clip again
        jobs_root = self._data_dir / "jobs"
        if not jobs_root.exists():
            return []
        dropped: list[str] = []
        for job_dir in sorted(jobs_root.iterdir()):
            if not job_dir.is_dir():
                continue
            try:
                status = self.read_status(self.job_paths(job_dir.name)).get("status")
            except Exception:  # noqa: BLE001 - missing/corrupt status.json -> skip
                continue
            if status in (JobStatus.queued.value, JobStatus.running.value):
                shutil.rmtree(job_dir, ignore_errors=True)
                dropped.append(job_dir.name)
        return dropped


def run_job(paths: JobPaths, request_json: dict[str, Any]) -> None:
    """The body of a job's own process, which can be killed when it hangs; it leaves its outcome in status.json."""
    from .pipeline.process_job import map_exception_to_api_error, run_pipeline

    configure_logging()
    log = logging.getLogger("pocket_drs")
    store = JobStore(paths.job_dir.parent.parent)
    last = None

    # the pipeline reports every decoded frame, so only a new percent or stage is written to disk
    def progress(pct: int, stage: str) -> None:
        nonlocal last
        if (pct, stage) != last:
            store.write_status(paths, status=JobStatus.running, progress=ProgressInfo(pct=pct, stage=stage), error=None)
            last = (pct, stage)

    try:
        progress(1, "starting")
        out = run_pipeline(video_path=paths.video_path, request_json=request_json, artifacts_dir=paths.artifacts_dir,
                           progress=progress)
        store.write_result(paths, out.result)
        store.write_status(paths, status=JobStatus.succeeded, progress=ProgressInfo(pct=100, stage="succeeded"),
                           error=None)
        log.info("job %s done with %d warnings", short_id(paths.job_dir.name), len(out.warnings))
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", short_id(paths.job_dir.name))
        store.write_status(paths, status=JobStatus.failed, progress=ProgressInfo(pct=100, stage="failed"),
                           error=map_exception_to_api_error(e))


def default_job_store() -> JobStore:
    return JobStore(data_dir())
