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
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as FormFile
from starlette.middleware.base import BaseHTTPMiddleware

from . import accounts as acc

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
    refunded = _accounts.fail_unfinished()
    if refunded:
        _log.warning("Gave back the free use of %d unfinished job(s)", refunded)
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
    if request.method != "POST" or request.url.path != "/v1/jobs":
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

# auth rides in a bearer header, not cookies, so any origin may call it
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
_accounts = acc.default_accounts()
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


_WEB = Path(__file__).parent / "web"
app.mount("/web", StaticFiles(directory=_WEB), name="web")


# the website for phones without the Android app; /admin is the same page showing the admin panel
@app.get("/", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
def website() -> FileResponse:
    return FileResponse(_WEB / "index.html", headers={"Cache-Control": "no-cache"})


_FIREBASE_KEYS = ("apiKey", "authDomain", "projectId", "appId", "messagingSenderId", "storageBucket", "measurementId")


@app.get("/config.json", include_in_schema=False)
def web_config() -> JSONResponse:
    # the firebase web config is public by design but kept out of the repo
    try:
        raw = json.loads(Path(os.environ.get("FIREBASE_WEB_CONFIG", "/data/firebase-web.json")).read_text())
    except (OSError, ValueError):
        return JSONResponse({"error": "not_configured"}, status_code=503)
    cfg = {k: raw[k] for k in _FIREBASE_KEYS if isinstance(raw.get(k), str) and raw[k]}
    if os.environ.get("FIREBASE_MEASUREMENT_ID"):
        cfg["measurementId"] = os.environ["FIREBASE_MEASUREMENT_ID"]
    return JSONResponse(cfg, headers={"Cache-Control": "no-cache"})


def _err(status: int, error: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": error, **extra}, status_code=status)


def _identify(request: Request, need_device: bool) -> tuple[dict[str, Any], str | None] | JSONResponse:
    """The signed-in person and their device id, or the error response to send instead."""
    try:
        ident = acc.verify_token(request.headers.get("authorization"))
    except acc.AuthError as e:
        _log.info("sign-in refused: %s", str(e)[:200])
        return _err(401, "sign_in_required")
    device_id = request.headers.get("x-device-id", "").strip() or None
    if device_id is not None and not acc.valid_device(device_id):
        return _err(400, "device_id_required")
    if need_device and device_id is None:
        return _err(400, "device_id_required")
    return ident, device_id


def _used_up() -> JSONResponse:
    return _err(402, "trials_used_up",
                message=f"You've used your {acc.FREE_ANALYSES} free reviews. Contact the admin for premium access.",
                contact_email=acc.CONTACT_EMAIL)


@app.get("/v1/me")
def me(request: Request):
    who = _identify(request, need_device=True)
    if isinstance(who, JSONResponse):
        return who
    return _accounts.me(*who)


def _admin(request: Request) -> JSONResponse | None:
    who = _identify(request, need_device=False)
    if isinstance(who, JSONResponse):
        return who
    if who[0]["email"] not in acc.admin_emails():
        return _err(403, "admin_only")
    return None


@app.get("/v1/admin/users")
def admin_users(request: Request, q: str = ""):
    return _admin(request) or {"users": _accounts.list_users(q)}


@app.put("/v1/admin/users/{email}")
async def admin_update_user(email: str, request: Request):
    denied = await run_in_threadpool(_admin, request)
    if denied:
        return denied
    target = acc.clean_email(email)
    if target is None:
        return _err(400, "bad_email")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _err(400, "bad_request")
    plan, reset = body.get("plan"), body.get("reset_used", False)
    if plan not in (None, "free", "premium") or not isinstance(reset, bool):
        return _err(400, "bad_request")
    if plan is not None and target in acc.admin_emails():
        return _err(400, "admin_plan_locked")
    return await run_in_threadpool(_accounts.update_user, target, plan, reset)


@app.get("/v1/admin/devices")
def admin_devices(request: Request, q: str = ""):
    return _admin(request) or {"devices": _accounts.list_devices(q)}


@app.post("/v1/admin/devices/{device_id}/reset")
def admin_reset_device(device_id: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    if not acc.valid_device(device_id):
        return _err(400, "device_id_required")
    if not _accounts.reset_device(device_id):
        return _err(404, "not_found")
    return {"device_id": device_id, "used": 0}


@app.get("/v1/admin/stats")
def admin_stats(request: Request):
    return _admin(request) or _accounts.stats()


def _finish_safe(job_id: str, status: str) -> None:
    # a database hiccup must not stop the job's own status from being written
    try:
        _accounts.finish(job_id, status)
    except Exception:  # noqa: BLE001
        _log.exception("could not record how job %s ended", job_id)


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
        _finish_safe(job_id, "succeeded")
    except Exception as e:  # noqa: BLE001
        _log.exception("job %s failed", job_id)
        _write_failed_status_safe(paths, map_exception_to_api_error(e))
        _finish_safe(job_id, "failed")
    finally:
        _job_slots.release()
        # nothing serves the clip back, so it goes as soon as the analysis ends
        video_path.unlink(missing_ok=True)


def _earlier_job(job_id: str) -> CreateJobResponse:
    try:
        status = JobStatus(_store.read_status(_store.job_paths(job_id))["status"])
    except Exception:  # noqa: BLE001 - the poll that follows reports what happened
        status = JobStatus.queued
    return CreateJobResponse(job_id=job_id, status=status)


async def _drain(request: Request, response: JSONResponse) -> JSONResponse:
    # a refusal sent mid-upload resets the socket and the phone shows "can't connect", so read the clip out first
    try:
        async for _ in request.stream():
            pass
    except Exception:  # noqa: BLE001 - the phone gave up, nothing left to tell it
        pass
    return response


@app.post("/v1/jobs", response_model=CreateJobResponse)
async def create_job(request: Request):
    # who and how many uses are left is checked before the body is read, so a refused phone uploads nothing
    who = await run_in_threadpool(_identify, request, True)
    if isinstance(who, JSONResponse):
        return await _drain(request, who)
    ident, device_id = who
    key = request.headers.get("idempotency-key", "").strip() or None
    if key is not None and not acc.valid_device(key):
        return await _drain(request, _err(400, "bad_request"))
    # a retry of a clip that already went through gets that job back, before the used-up check can refuse it
    earlier = await run_in_threadpool(_accounts.find_keyed, ident["email"], key)
    if earlier and _store.exists(earlier):
        return await _drain(request, _earlier_job(earlier))
    if earlier:
        # a redeploy wiped that job's files, so the key would only ever answer "not found"
        await run_in_threadpool(_accounts.forget_key, ident["email"], key)
    if not await run_in_threadpool(_accounts.can_start, ident["email"], device_id):
        return await _drain(request, _used_up())

    form = await request.form()
    try:
        video_file, request_json = form.get("video_file"), form.get("request_json")
        if not isinstance(video_file, FormFile) or not isinstance(request_json, str):
            raise HTTPException(status_code=400, detail="The app sent an invalid request. Update the app and try again.")
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
            # the real check: one sqlite write lock, so two uploads at once can't both take the last use
            got = await run_in_threadpool(_accounts.take_use, ident, device_id, job_id, key)
            if got is None:
                return _used_up()
            if got != job_id:
                # the same clip raced in twice; the other upload already owns the job
                return _earlier_job(got)
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
                # no row (refused, or the other upload owns it) makes this a no-op; a cut-off
                # request may have taken the use without reaching the next line, so always give it back
                if paths is not None:
                    _finish_safe(job_id, "failed")
                # no worker will ever delete a half-saved clip
                if paths is not None:
                    shutil.rmtree(paths.job_dir, ignore_errors=True)
    finally:
        await form.close()

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
