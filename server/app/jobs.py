from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ApiError, JobStatus, ProgressInfo

# public API with no accounts: jobs are cleaned up by age instead of by owner
_MAX_JOB_AGE_S = 24 * 60 * 60


@dataclass(frozen=True)
class JobPaths:
    job_dir: Path
    video_path: Path
    request_path: Path
    status_path: Path
    result_path: Path
    artifacts_dir: Path


def _now_ms() -> int:
    return int(time.time() * 1000)


class JobStore:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def _sweep_old_jobs(self) -> None:
        # runs on job creation; a job dir's mtime moves whenever its status is rewritten
        jobs_root = self._data_dir / "jobs"
        if not jobs_root.exists():
            return
        cutoff = time.time() - _MAX_JOB_AGE_S
        for job_dir in jobs_root.iterdir():
            try:
                if job_dir.is_dir() and job_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(job_dir, ignore_errors=True)
            except OSError:
                continue

    def create_job(self) -> tuple[str, JobPaths]:
        self._sweep_old_jobs()
        job_id = uuid.uuid4().hex
        job_dir = self._data_dir / "jobs" / job_id
        artifacts_dir = job_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        paths = JobPaths(
            job_dir=job_dir,
            video_path=job_dir / "input.mp4",
            request_path=job_dir / "request.json",
            status_path=job_dir / "status.json",
            result_path=job_dir / "result.json",
            artifacts_dir=artifacts_dir,
        )

        self.write_status(
            paths,
            status=JobStatus.queued,
            progress=ProgressInfo(pct=0, stage="queued"),
            error=None,
        )
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
        # the sweep only runs when a job is created, so a quiet server must still stop serving old results
        return time.time() - mtime < _MAX_JOB_AGE_S

    def _atomic_write_text(self, path: Path, text: str) -> None:
        # a poll must never read a half-written file
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(text)
        os.replace(tmp, path)

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))

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

    def recover_interrupted_jobs(self) -> list[str]:
        # the worker pool that owned these died with the last process, so they'd poll as running forever
        jobs_root = self._data_dir / "jobs"
        if not jobs_root.exists():
            return []
        recovered: list[str] = []
        for job_dir in sorted(jobs_root.iterdir()):
            if not job_dir.is_dir():
                continue
            paths = self.job_paths(job_dir.name)
            try:
                status = self.read_status(paths).get("status")
            except Exception:  # noqa: BLE001 - missing/corrupt status.json -> skip
                continue
            if status not in (JobStatus.queued.value, JobStatus.running.value):
                continue
            try:
                # the worker that would have deleted the clip is gone
                paths.video_path.unlink(missing_ok=True)
                self.write_status(
                    paths,
                    status=JobStatus.failed,
                    progress=ProgressInfo(pct=100, stage="failed"),
                    error=ApiError(
                        code="INTERNAL_ERROR",
                        message="The server restarted while checking this ball, so it was lost.",
                        details=None,
                    ),
                )
                recovered.append(job_dir.name)
            except Exception:  # noqa: BLE001 - unwritable job dir -> skip
                continue
        return recovered


def default_job_store() -> JobStore:
    base = os.environ.get("POCKET_DRS_DATA_DIR")
    if base:
        data_dir = Path(base)
    else:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    return JobStore(data_dir=data_dir)
