from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .jobs import JobStore, default_job_store
from .job_logging import job_log_context
from .models import (
    ApiError,
    CreateJobRequest,
    CreateJobResponse,
    JobResultResponse,
    JobStatus,
    JobStatusResponse,
    ProgressInfo,
)
from .pipeline.process_job import map_exception_to_api_error, run_pipeline


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

app = FastAPI(title="PocketDRS Server", version="1.0")

# CORS is required for Flutter Web (browser) to call the API.
# Configure via POCKET_DRS_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
_cors_origins_raw = os.environ.get("POCKET_DRS_CORS_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

_store: JobStore = default_job_store()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job-worker")
_log = logging.getLogger("pocket_drs")


def _load_json(s: str) -> dict[str, Any]:
    try:
        v = json.loads(s)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request_json: {e}")
    if not isinstance(v, dict):
        raise HTTPException(status_code=400, detail="request_json must be a JSON object")
    return v


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _process_job(job_id: str, video_path: Path, request_json: dict[str, Any], artifacts_dir: Path) -> None:
    paths = _store.job_paths(job_id)

    last_stage: str | None = None
    last_pct: int | None = None

    with job_log_context(job_id=job_id, artifacts_dir=artifacts_dir) as job_log:
        job_log.info(
            "Processing job_id=%s video=%s size=%dMB",
            job_id,
            video_path.name,
            video_path.stat().st_size // (1024 * 1024) if video_path.exists() else 0,
        )

        def progress(pct: int, stage: str) -> None:
            nonlocal last_stage, last_pct
            _store.write_status(
                paths,
                status=JobStatus.running,
                progress=ProgressInfo(pct=pct, stage=stage),
                error=None,
            )

            # Keep logs readable: record stage changes and meaningful pct jumps.
            if stage != last_stage or last_pct is None or abs(pct - last_pct) >= 10:
                job_log.info("Progress: %d%% - %s", pct, stage)
                last_stage = stage
                last_pct = pct

        try:
            progress(1, "starting")
            out = run_pipeline(
                video_path=video_path,
                request_json=request_json,
                artifacts_dir=artifacts_dir,
                progress=progress,
            )
            _store.write_result(paths, out.result)
            _store.write_status(
                paths,
                status=JobStatus.succeeded,
                progress=ProgressInfo(pct=100, stage="succeeded"),
                error=None,
            )
            warnings = out.result.get("diagnostics", {}).get("warnings", [])
            n_points = len(out.result.get("track", {}).get("points", []))
            job_log.info("✓ Completed successfully: %d tracking points, %d warnings", n_points, len(warnings) if isinstance(warnings, list) else 0)
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            error_type = e.__class__.__name__
            error_msg = str(e) if str(e) else error_type
            job_log.error("✗ Failed with %s: %s\n%s", error_type, error_msg, tb)
            err = map_exception_to_api_error(e)
            _store.write_status(
                paths,
                status=JobStatus.failed,
                progress=ProgressInfo(pct=100, stage="failed"),
                error=err,
            )
            _log.error("Job failed: job_id=%s error_code=%s message=%s", job_id, err.code, err.message)


@app.post("/v1/jobs", response_model=CreateJobResponse)
async def create_job(
    video_file: UploadFile = File(...),
    request_json: str = Form(...),
) -> CreateJobResponse:
    req_dict = _load_json(request_json)

    # Validate contract early.
    try:
        CreateJobRequest.model_validate(req_dict)
    except Exception as e:  # noqa: BLE001
        _log.warning("Invalid job request: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))

    job_id, paths = _store.create_job()
    _log.info("Created job: job_id=%s filename=%s", job_id, video_file.filename)

    # Persist request + video.
    _store.write_request(paths, req_dict)
    try:
        bytes_written = 0
        with paths.video_path.open("wb") as f:
            while True:
                chunk = await video_file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)
                bytes_written += len(chunk)
        _log.debug("Video uploaded: job_id=%s size=%dMB", job_id, bytes_written // (1024 * 1024))
    except Exception as e:
        _log.error("Failed to save video: job_id=%s error=%s", job_id, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")
    finally:
        await video_file.close()

    _store.write_status(
        paths,
        status=JobStatus.queued,
        progress=ProgressInfo(pct=0, stage="queued"),
        error=None,
    )

    # Kick off analysis.
    _executor.submit(_process_job, job_id, paths.video_path, req_dict, paths.artifacts_dir)

    return CreateJobResponse(job_id=job_id, status=JobStatus.queued)


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    if not _store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    paths = _store.job_paths(job_id)
    raw = _store.read_status(paths)

    status = JobStatus(raw["status"])
    progress_raw = raw.get("progress")
    error_raw = raw.get("error")

    progress = ProgressInfo(**progress_raw) if isinstance(progress_raw, dict) else None
    error = ApiError(**error_raw) if isinstance(error_raw, dict) else None

    return JobStatusResponse(job_id=job_id, status=status, progress=progress, error=error)


@app.get("/v1/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str) -> JobResultResponse:
    if not _store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    paths = _store.job_paths(job_id)
    status_raw = _store.read_status(paths)
    status = JobStatus(status_raw["status"])
    error_raw = status_raw.get("error")
    error = ApiError(**error_raw) if isinstance(error_raw, dict) else None

    if status != JobStatus.succeeded:
        return JobResultResponse(job_id=job_id, status=status, result=None, error=error)

    result = _store.read_result(paths)
    return JobResultResponse(job_id=job_id, status=status, result=result, error=None)


@app.get("/v1/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: str, name: str):
    if not _store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    paths = _store.job_paths(job_id)
    file_path = (paths.artifacts_dir / name).resolve()
    if paths.artifacts_dir.resolve() not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(str(file_path))








