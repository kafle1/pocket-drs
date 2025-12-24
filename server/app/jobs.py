from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ApiError, JobStatus, ProgressInfo


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

    def create_job(self) -> tuple[str, JobPaths]:
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
        return (self._data_dir / "jobs" / job_id).exists()

    def write_request(self, paths: JobPaths, request_obj: dict[str, Any]) -> None:
        with self._lock:
            paths.request_path.write_text(json.dumps(request_obj, indent=2, sort_keys=True))

    def read_request(self, paths: JobPaths) -> dict[str, Any]:
        return json.loads(paths.request_path.read_text())

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
            paths.status_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def read_status(self, paths: JobPaths) -> dict[str, Any]:
        return json.loads(paths.status_path.read_text())

    def write_result(self, paths: JobPaths, payload: dict[str, Any]) -> None:
        with self._lock:
            paths.result_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def read_result(self, paths: JobPaths) -> dict[str, Any]:
        return json.loads(paths.result_path.read_text())


def default_job_store() -> JobStore:
    base = os.environ.get("POCKET_DRS_DATA_DIR")
    if base:
        data_dir = Path(base)
    else:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    return JobStore(data_dir=data_dir)
