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

    def _atomic_write_text(self, path: Path, text: str) -> None:
        """Write a file atomically to avoid readers seeing partial/empty JSON.

        We write to a temp file in the same directory then replace.
        """
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(text)
        os.replace(tmp, path)

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))

    def write_request(self, paths: JobPaths, request_obj: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write_json(paths.request_path, request_obj)

    def read_request(self, paths: JobPaths) -> dict[str, Any]:
        with self._lock:
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
            self._atomic_write_json(paths.status_path, payload)

    def read_status(self, paths: JobPaths) -> dict[str, Any]:
        # Polling can hit while a background thread updates status; keep reads consistent.
        with self._lock:
            raw = paths.status_path.read_text()
        if not raw.strip():
            # Extremely defensive: empty file should not happen with atomic writes, but
            # return a helpful error rather than a JSONDecodeError.
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


def default_job_store() -> JobStore:
    base = os.environ.get("POCKET_DRS_DATA_DIR")
    if base:
        data_dir = Path(base)
    else:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    return JobStore(data_dir=data_dir)
