from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .jobs import JobPaths, JobStore, default_job_store
from .logging_setup import configure_logging, request_id_ctx
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
from .three_d_viewer import render_html


configure_logging(log_level=os.environ.get("POCKET_DRS_LOG_LEVEL", "info"))
_log = logging.getLogger("pocket_drs")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # jobs still queued or running belong to a previous process whose worker pool is gone
    dropped = _store.drop_interrupted_jobs()
    if dropped:
        _log.warning("Dropped %d interrupted job(s) on startup: %s", len(dropped), ", ".join(dropped))
    yield


app = FastAPI(title="PocketDRS Server", version="1.0", lifespan=_lifespan)
# the 3D page's three.js, served from here so no outside site sees who opens it
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# one log line per request, under an id the client also gets back in X-Request-Id
class RequestLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        incoming = request.headers.get("x-request-id", "").strip()
        req_id = incoming if incoming else uuid.uuid4().hex[:12]
        token = request_id_ctx.set(req_id)

        start = time.perf_counter()
        status_code = 500
        try:
            try:
                response: Response = await call_next(request)
            except Exception:
                _log.exception("Unhandled exception in %s %s", request.method, request.url.path)
                response = PlainTextResponse("Internal Server Error", status_code=500)
            status_code = response.status_code
            response.headers["X-Request-Id"] = req_id
            return response
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            # no client address: the log is never rotated, so it must not hold anything personal
            _log.info("%s %s -> %d %.1fms", request.method, request.url.path, status_code, dur_ms)
            request_id_ctx.reset(token)


_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
_UPLOAD_DEADLINE_S = 600    # the app gives up on an upload after 10 minutes too


@app.middleware("http")
async def _cap_upload(request: Request, call_next):
    # starlette spools the whole multipart body to disk before create_job runs, so cap it by header
    if request.method != "POST":
        return await call_next(request)
    size = request.headers.get("content-length", "")
    if not size.isdigit():
        return JSONResponse({"detail": "Content-Length header required"}, status_code=411)
    if int(size) > _MAX_UPLOAD_BYTES:
        return JSONResponse({"detail": f"Video exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"},
                            status_code=413)
    # the job queue only says busy after the body is on disk, so parallel uploads could still fill it
    if _uploads.locked():
        return JSONResponse({"detail": "Server busy: too many uploads at once, try again shortly"}, status_code=503)
    async with _uploads:
        # a phone that drops off the network mid-upload leaves a half-open socket that would hold its slot forever
        try:
            async with asyncio.timeout(_UPLOAD_DEADLINE_S):
                return await call_next(request)
        except TimeoutError:
            return JSONResponse({"detail": "The upload took too long. Try again on a better connection."}, status_code=408)


app.add_middleware(RequestLoggingMiddleware)

# public, anonymous API: any origin may call it, and there are no cookies to guard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# the 3D page pulls about 730 KB of three.js, often over mobile data
app.add_middleware(GZipMiddleware, minimum_size=1024)

_store: JobStore = default_job_store()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-worker")

# the ball detector pins every CPU, so one job runs at a time and a burst past the cap gets a 503
_MAX_JOBS = 10
_job_slots = threading.Semaphore(_MAX_JOBS)
_uploads = asyncio.Semaphore(_MAX_JOBS)


def _load_json(s: str) -> dict[str, Any]:
    try:
        v = json.loads(s)
    except (ValueError, RecursionError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid request_json: {e}")
    if not isinstance(v, dict):
        raise HTTPException(status_code=400, detail="request_json must be a JSON object")
    return v


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# what people see when they open the hosted server's page
@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "Pocket DRS analysis server is running. Get the app at https://github.com/kafle1/pocket-drs"


# the worker's future is never awaited, so a failure here would otherwise leave the job running forever
def _write_failed_status_safe(paths: JobPaths, error: ApiError) -> None:
    try:
        _store.write_status(paths, status=JobStatus.failed, progress=ProgressInfo(pct=100, stage="failed"), error=error)
    except Exception:  # noqa: BLE001
        _log.exception("could not mark job %s failed", paths.job_dir.name)


def _process_job(job_id: str, video_path: Path, request_json: dict[str, Any], artifacts_dir: Path) -> None:
    paths = _store.job_paths(job_id)
    last = None

    # the pipeline reports every decoded frame, so only a new percent or stage is written to disk
    def progress(pct: int, stage: str) -> None:
        nonlocal last
        if (pct, stage) != last:
            _store.write_status(paths, status=JobStatus.running, progress=ProgressInfo(pct=pct, stage=stage), error=None)
            last = (pct, stage)

    try:
        progress(1, "starting")
        out = run_pipeline(video_path=video_path, request_json=request_json, artifacts_dir=artifacts_dir,
                           progress=progress)
        _store.write_result(paths, out.result)
        _store.write_status(paths, status=JobStatus.succeeded, progress=ProgressInfo(pct=100, stage="succeeded"),
                            error=None)
        _log.info("job %s done with %d warnings", job_id, len(out.warnings))
    except Exception as e:  # noqa: BLE001
        _log.exception("job %s failed", job_id)
        _write_failed_status_safe(paths, map_exception_to_api_error(e))
    finally:
        _job_slots.release()
        # nothing serves the clip back, so it goes as soon as the analysis ends
        video_path.unlink(missing_ok=True)


@app.post("/v1/jobs", response_model=CreateJobResponse)
async def create_job(
    video_file: UploadFile = File(...),
    request_json: str = Form(...),
) -> CreateJobResponse:
    req_dict = _load_json(request_json)

    try:
        CreateJobRequest.model_validate(req_dict)
    except Exception as e:  # noqa: BLE001
        # full validation detail goes to the log only; the client gets one plain sentence
        _log.warning("Invalid job request: %s", str(e))
        raise HTTPException(status_code=400, detail="The app sent an invalid request. Update the app and try again.")

    if not _job_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail=f"Server busy: {_MAX_JOBS} jobs already queued or running, try again shortly",
        )

    submitted, paths = False, None
    try:
        job_id, paths = _store.create_job()
        _store.write_request(paths, req_dict)
        with paths.video_path.open("wb") as f:
            await run_in_threadpool(shutil.copyfileobj, video_file.file, f, 1 << 20)

        _executor.submit(_process_job, job_id, paths.video_path, req_dict, paths.artifacts_dir)
        submitted = True
    except Exception:
        _log.exception("Failed to save the uploaded video")
        raise HTTPException(status_code=500, detail="The server couldn't save the video. Try again.")
    finally:
        if not submitted:
            _job_slots.release()
            # no worker will ever delete a half-saved clip
            if paths is not None:
                shutil.rmtree(paths.job_dir, ignore_errors=True)
        await video_file.close()

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


@app.get("/v1/jobs/{job_id}/three-d", response_class=Response)
def get_job_three_d(job_id: str):
    """Render the Three.js 3D ball path viewer; its three.js comes from /static."""
    # this page opens in the phone's browser, so errors get a sentence, not JSON
    if not _store.exists(job_id):
        return PlainTextResponse("This ball is no longer on the server. Results are kept for a day. "
                                 "Send the ball again to see it in 3D.", status_code=404)
    paths = _store.job_paths(job_id)
    status_raw = _store.read_status(paths)
    if JobStatus(status_raw["status"]) != JobStatus.succeeded:
        return PlainTextResponse("This ball is still being checked, or the check failed. Open it again from the app "
                                 "once it shows a verdict.", status_code=409)
    result = _store.read_result(paths)
    if not (result.get("world_trajectory") or {}).get("points_m"):
        return PlainTextResponse("No ball path was found for this delivery, so there is nothing to show in 3D.",
                                 status_code=409)
    return Response(content=render_html(result), media_type="text/html")
