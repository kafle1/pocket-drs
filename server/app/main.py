from __future__ import annotations

import json
import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Header
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import firestore as fb_firestore

from .jobs import JobStore, default_job_store
from .job_logging import job_log_context
from .logging_setup import configure_logging
from .firebase_config import initialize_firebase, verify_user_token, get_firestore
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


configure_logging(log_level=os.environ.get("POCKET_DRS_LOG_LEVEL", "info"))
_log = logging.getLogger("pocket_drs")


def _require_user_id(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    uid = verify_user_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return uid

app = FastAPI(title="PocketDRS Server", version="1.0")


@app.on_event("startup")
def _startup() -> None:
    # Fail fast: if Firebase isn't configured, the system can't meet its contract.
    db = initialize_firebase()
    try:
        # A simple read forces credentials + Firestore availability checks.
        db.collection("_health").document("startup").get()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Firestore is not reachable: {e}")
    _log.info("Firebase initialized and Firestore reachable")

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


def _process_job(job_id: str, video_path: Path, request_json: dict[str, Any], artifacts_dir: Path, user_id: str | None = None) -> None:
    paths = _store.job_paths(job_id)

    last_stage: str | None = None
    last_pct: int | None = None

    with job_log_context(job_id=job_id, artifacts_dir=artifacts_dir) as job_log:
        job_log.info(
            "Processing job_id=%s user_id=%s video=%s size=%dMB",
            job_id,
            user_id or "anonymous",
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
            job_log.info("✓ Completed: %d tracking points, %d warnings", n_points, len(warnings) if isinstance(warnings, list) else 0)
            
            # Store in Firestore if user is authenticated
            if user_id:
                try:
                    db = get_firestore()
                    pitch_id = request_json.get("calibration", {}).get("pitch_id")
                    db.collection('users').document(user_id).collection('analyses').add({
                        'jobId': job_id,
                        'pitchId': pitch_id,
                        'result': out.result,
                        'createdAt': fb_firestore.SERVER_TIMESTAMP,
                    })
                    job_log.info("✓ Saved to Firestore for user %s", user_id)
                except Exception as e:
                    job_log.warning("Failed to save to Firestore: %s", str(e))
                    
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


@app.post("/v1/jobs", response_model=CreateJobResponse)
async def create_job(
    video_file: UploadFile = File(...),
    request_json: str = Form(...),
    authorization: str | None = Header(None),
) -> CreateJobResponse:
    req_dict = _load_json(request_json)

    user_id = _require_user_id(authorization)

    try:
        CreateJobRequest.model_validate(req_dict)
    except Exception as e:  # noqa: BLE001
        _log.warning("Invalid job request: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))

    job_id, paths = _store.create_job()
    _log.debug("Created job: job_id=%s user_id=%s filename=%s", job_id, user_id or "anonymous", video_file.filename)

    _store.write_request(paths, req_dict)
    _store.write_meta(paths, {"user_id": user_id})
    try:
        bytes_written = 0
        with paths.video_path.open("wb") as f:
            while True:
                chunk = await video_file.read(1024 * 1024)
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

    _executor.submit(_process_job, job_id, paths.video_path, req_dict, paths.artifacts_dir, user_id)

    return CreateJobResponse(job_id=job_id, status=JobStatus.queued)


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, authorization: str | None = Header(None)) -> JobStatusResponse:
    user_id = _require_user_id(authorization)
    if not _store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    paths = _store.job_paths(job_id)
    owner_id = _store.read_owner_user_id(paths)
    if owner_id != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    raw = _store.read_status(paths)

    status = JobStatus(raw["status"])
    progress_raw = raw.get("progress")
    error_raw = raw.get("error")

    progress = ProgressInfo(**progress_raw) if isinstance(progress_raw, dict) else None
    error = ApiError(**error_raw) if isinstance(error_raw, dict) else None

    return JobStatusResponse(job_id=job_id, status=status, progress=progress, error=error)


@app.get("/v1/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, authorization: str | None = Header(None)) -> JobResultResponse:
    user_id = _require_user_id(authorization)
    if not _store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    paths = _store.job_paths(job_id)
    owner_id = _store.read_owner_user_id(paths)
    if owner_id != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    status_raw = _store.read_status(paths)
    status = JobStatus(status_raw["status"])
    error_raw = status_raw.get("error")
    error = ApiError(**error_raw) if isinstance(error_raw, dict) else None

    if status != JobStatus.succeeded:
        return JobResultResponse(job_id=job_id, status=status, result=None, error=error)

    result = _store.read_result(paths)
    return JobResultResponse(job_id=job_id, status=status, result=result, error=None)


@app.get("/v1/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: str, name: str, authorization: str | None = Header(None)):
    user_id = _require_user_id(authorization)
    if not _store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    paths = _store.job_paths(job_id)
    owner_id = _store.read_owner_user_id(paths)
    if owner_id != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    file_path = (paths.artifacts_dir / name).resolve()
    if paths.artifacts_dir.resolve() not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(str(file_path))








