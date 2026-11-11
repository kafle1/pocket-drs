from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from multiprocessing.connection import wait as wait_for_exit
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from google.auth.exceptions import TransportError
from python_multipart import MultipartParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect

from . import accounts as acc
from .jobs import MAX_JOB_AGE_S, JobPaths, JobStore, data_dir, default_job_store, run_job, short_id
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
from .three_d_viewer import render_html


configure_logging()
_log = logging.getLogger("pocket_drs")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # jobs still queued or running belong to a previous process whose worker pool is gone
    dropped = _store.drop_interrupted_jobs()
    if dropped:
        _log.warning("Dropped %d interrupted job(s) on startup: %s", len(dropped), ", ".join(map(short_id, dropped)))
    refunded = _accounts.fail_unfinished()
    if refunded:
        _log.warning("Gave back the free use of %d unfinished job(s)", refunded)
    housekeeping = asyncio.create_task(_housekeeping())
    yield
    housekeeping.cancel()


# no /docs: it would hand strangers a map of the admin routes
app = FastAPI(title="PocketDRS Server", version="1.0", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
# the 3D page's three.js, served from here so no outside site sees who opens it
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# one log line per request, under an id the client also gets back in X-Request-Id
class RequestLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        incoming = request.headers.get("x-request-id", "")
        req_id = incoming if re.fullmatch(r"[A-Za-z0-9-]{1,64}", incoming) else uuid.uuid4().hex[:12]
        token = request_id_ctx.set(req_id)

        start = time.perf_counter()
        status_code = 500
        try:
            try:
                response: Response = await call_next(request)
            except Exception:
                _log.exception("Unhandled exception in %s %s", request.method, _route(request))
                response = _err(500, "internal_error")
            status_code = response.status_code
            response.headers["X-Request-Id"] = req_id
            return response
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            # no client address and no job id, so the log holds nothing personal and no key to a result
            _log.info("%s %s -> %d %.1fms", request.method, _route(request), status_code, dur_ms)
            request_id_ctx.reset(token)


def _route(request: Request) -> str:
    route = getattr(request.scope.get("route"), "path", None)
    return route or re.sub(r"[0-9a-f]{32}", "{job_id}", request.url.path)


_MAX_UPLOAD_BYTES = 201 * 1024 * 1024    # a 200 MB clip plus the form around it
_BAD_REQUEST = "The clip couldn't be sent. Pick it again and retry."
# a minute plus 25 KB a second, so a big clip on a slow phone still gets in; the apps wait 30 s longer
_UPLOAD_MIN_BPS, _UPLOAD_MAX_S = 25_000, 1800


@app.middleware("http")
async def _cap_upload(request: Request, call_next):
    # starlette would read the whole body before create_job runs, so every check that can refuse an upload runs
    # here first, and a queue slot is held from the first byte, so a full queue says busy before the upload
    if request.method != "POST" or request.url.path != "/v1/jobs":
        return await call_next(request)
    size = request.headers.get("content-length", "")
    if not size.isdigit():
        return _err(411, "length_required")
    if int(size) > _MAX_UPLOAD_BYTES:
        return _err(413, "too_large")
    who = await run_in_threadpool(_identify, request, True)
    if isinstance(who, JSONResponse):
        return await _drain(request, who)
    email = who[0]["email"]
    key = request.headers.get("idempotency-key", "").strip() or None
    if key is not None and not acc.valid_device(key):
        return await _drain(request, _err(400, "bad_request"))
    # one upload per account, so one person can't hold every slot
    if email in _uploading:
        return await _drain(request, _err(409, "upload_in_progress"))
    _uploading.add(email)
    slot = False
    try:
        live = await run_in_threadpool(_accounts.live_job, email)
        # a retry of the clip that's already queued gets that job back from create_job
        if live is not None and (key is None or live[1] != key):
            return await _drain(request, _err(409, "job_in_progress", acc.JOB_IN_PROGRESS, job_id=live[0]))
        slot = _job_slots.acquire(blocking=False)
        if not slot:
            return await _drain(request, _err(503, "server_busy"))
        request.state.who, request.state.key, request.state.slot_held = who, key, True
        # a phone that drops off the network mid-upload leaves a half-open socket that would hold its slot forever
        try:
            async with asyncio.timeout(min(_UPLOAD_MAX_S, 60 + int(size) / _UPLOAD_MIN_BPS)):
                return await call_next(request)
        except TimeoutError:
            return _err(408, "upload_timeout")
    finally:
        _uploading.discard(email)
        # create_job hands the slot to the worker once the job is queued
        if slot and request.state.slot_held:
            _job_slots.release()


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

# the ball detector pins every CPU, so one job runs at a time and a burst past the cap gets a 503;
# a job takes about 10 s, so a full queue is a few minutes' wait
_MAX_JOBS = 25
_job_slots = threading.Semaphore(_MAX_JOBS)
# accounts with an upload under way; only the event loop touches it
_uploading: set[str] = set()
# each job runs in its own process so a hung decode can be killed; the forkserver imports the pipeline once
_JOB_TIMEOUT_S = 180
_procs = multiprocessing.get_context("forkserver")
_procs.set_forkserver_preload(["app.pipeline.process_job"])
# jobs waiting for the worker, in order, and the process of the one running; an account deletion reads both
_queue: list[str] = []
_live: dict[str, Any] = {}
_live_lock = threading.Lock()
_TIMED_OUT = ApiError(code="TIMED_OUT", message="This clip took too long to check. Trim it to just the delivery "
                      "and send it again.")
_CRASHED = ApiError(code="INTERNAL_ERROR", message="Something went wrong checking this ball. Try again, or try "
                    "another clip.")


async def _housekeeping() -> None:
    # at every start and then hourly, so a restart in the middle of a cleanup just runs it again
    while True:
        try:
            await run_in_threadpool(_tidy)
        except Exception:  # noqa: BLE001
            _log.exception("housekeeping failed")
        await asyncio.sleep(3600)


def _tidy() -> None:
    _store.sweep()
    # ten minutes' slack, so a job row always outlives the folder it was last written with
    _accounts.purge_jobs(int(time.time()) - MAX_JOB_AGE_S - 600)
    _accounts.backup()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


_WEB = Path(__file__).parent / "web"
app.mount("/web", StaticFiles(directory=_WEB), name="web")


@app.middleware("http")
async def _revalidate_web(request: Request, call_next):
    # phones must not keep an old app.js next to a new index.html after a deploy; etags keep it a cheap 304
    response = await call_next(request)
    if request.url.path.startswith("/web/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# the website for phones without the Android app; /admin and /delete-account are the same page showing another panel
@app.get("/", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/delete-account", include_in_schema=False)
def website() -> FileResponse:
    return FileResponse(_WEB / "index.html", headers={"Cache-Control": "no-cache"})


_FIREBASE_KEYS = ("apiKey", "authDomain", "projectId", "appId", "messagingSenderId", "storageBucket", "measurementId")


@app.get("/config.json", include_in_schema=False)
def web_config() -> JSONResponse:
    # the firebase web config is public by design but kept out of the repo
    try:
        raw = json.loads(Path(os.environ.get("FIREBASE_WEB_CONFIG") or data_dir() / "firebase-web.json").read_text())
    except (OSError, ValueError):
        return _err(503, "not_configured")
    cfg = {k: raw[k] for k in _FIREBASE_KEYS if isinstance(raw.get(k), str) and raw[k]}
    return JSONResponse(cfg, headers={"Cache-Control": "no-cache"})


_MESSAGES = {
    "bad_request": _BAD_REQUEST,
    "sign_in_required": "Sign in again to carry on.",
    "device_id_required": "Update the app and try again.",
    "admin_only": "Only an admin can do that.",
    "bad_email": "That email address doesn't look right.",
    "admin_plan_locked": "An admin's plan can't be changed.",
    "job_not_found": "This ball is no longer on the server. Results are kept for a day.",
    "not_found": "There is nothing at this address.",
    "method_not_allowed": "This address doesn't take that kind of request.",
    "length_required": "The clip couldn't be sent because its size was missing. Update the app and try again.",
    "too_large": "The clip is over 200 MB. Trim it to just the delivery and send it again.",
    "upload_timeout": "The upload took too long. Try again on a better connection.",
    "upload_in_progress": "Another clip from this account is still uploading. Wait for it to finish.",
    "server_busy": "The server is busy. Try again in a few minutes.",
    "not_configured": "This server isn't set up for the website yet.",
    "save_failed": "The server couldn't save the video. Try again.",
    "internal_error": "Something went wrong on the server. Try again.",
    "app_outdated": "Update Pocket DRS to keep reviewing.",
}


def _err(status: int, code: str, message: str | None = None, headers: dict[str, str] | None = None,
         **extra: Any) -> JSONResponse:
    # every error has this one shape: {"error": {"code", "message", ...anything the client acts on}}
    return JSONResponse({"error": {"code": code, "message": message or _MESSAGES[code], **extra}},
                        status_code=status, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code)
    if code is None:
        code = "bad_request" if exc.status_code < 500 else "internal_error"
    return _err(exc.status_code, code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _err(400, "bad_request")


def _identify(request: Request, need_device: bool) -> tuple[dict[str, Any], str | None] | JSONResponse:
    """The signed-in person and their device id, or the error response to send instead."""
    try:
        ident = acc.verify_token(request.headers.get("authorization"))
    except acc.AuthError as e:
        _log.info("sign-in refused: %s", str(e)[:200])
        return _err(401, "sign_in_required")
    except TransportError as e:
        # google's signing keys couldn't be fetched; a 401 here would sign everyone out in a loop
        _log.warning("sign-in check unavailable: %s", str(e)[:200])
        return _err(503, "server_busy")
    device_id = request.headers.get("x-device-id", "").strip() or None
    if (device_id is None and need_device) or (device_id is not None and not acc.valid_device(device_id)):
        return _err(400, "device_id_required")
    return ident, device_id


@app.get("/v1/me")
def me(request: Request):
    who = _identify(request, need_device=True)
    if isinstance(who, JSONResponse):
        return who
    return _accounts.me(*who)


@app.delete("/v1/me")
def delete_me(request: Request):
    who = _identify(request, need_device=False)
    if isinstance(who, JSONResponse):
        return who
    job_ids = _accounts.delete_user(who[0]["email"])
    with _live_lock:
        for job_id in job_ids:
            if child := _live.get(job_id):
                # gone before its folder is, so it can't write into it after the delete
                child.kill()
                wait_for_exit([child.sentinel], 10)
        _store.remove(job_ids)
    _log.info("deleted an account and its %d job(s)", len(job_ids))
    return Response(status_code=204)


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
    plan = body.get("plan")
    if plan not in ("free", "premium"):
        return _err(400, "bad_request")
    if target in acc.admin_emails():
        return _err(400, "admin_plan_locked")
    return await run_in_threadpool(_accounts.update_user, target, plan)


@app.get("/v1/admin/stats")
def admin_stats(request: Request):
    return _admin(request) or _accounts.stats()


@app.get("/v1/admin/jobs")
def admin_jobs(request: Request, email: str = ""):
    return _admin(request) or {"jobs": _accounts.list_jobs(email.strip().lower())}


def _record_safe(job_id: str, status: str, decision: str | None = None) -> None:
    # a database hiccup must not stop the job's own status from being written
    try:
        _accounts.record(job_id, status, decision)
    except Exception:  # noqa: BLE001
        _log.exception("could not record how job %s ended", short_id(job_id))


# the worker's future is never awaited, so a failure here would otherwise leave the job running forever
def _write_failed_status_safe(paths: JobPaths, error: ApiError) -> None:
    try:
        _store.write_status(paths, status=JobStatus.failed, progress=ProgressInfo(pct=100, stage="failed"), error=error)
    except Exception:  # noqa: BLE001
        _log.exception("could not mark job %s failed", short_id(paths.job_dir.name))


def _process_job(job_id: str, paths: JobPaths, request_json: dict[str, Any]) -> None:
    try:
        with _live_lock:
            _queue.remove(job_id)
            # the account was deleted while this job waited
            if not paths.job_dir.exists():
                return
            child = _procs.Process(target=run_job, args=(paths, request_json), daemon=True)
            child.start()
            _live[job_id] = child
        _record_safe(job_id, "running")
        child.join(_JOB_TIMEOUT_S)
        timed_out = child.is_alive()
        if timed_out:
            child.kill()
            child.join()
        with _live_lock:
            del _live[job_id]
            if not paths.job_dir.exists():
                return
            status = _store.read_status(paths)["status"]
            if status not in ("succeeded", "failed"):
                _log.error("job %s %s", short_id(job_id),
                           "timed out" if timed_out else f"died with exit code {child.exitcode}")
                _write_failed_status_safe(paths, _TIMED_OUT if timed_out else _CRASHED)
                status = "failed"
            decision = None
            if status == "succeeded":
                decision = (_store.read_result(paths).get("lbw") or {}).get("decision") or "none"
            _record_safe(job_id, status, decision)
    except Exception:  # noqa: BLE001
        _log.exception("job %s could not run", short_id(job_id))
        _write_failed_status_safe(paths, _CRASHED)
        _record_safe(job_id, "failed")
    finally:
        _job_slots.release()
        # nothing serves the clip back, so it goes as soon as the analysis ends
        paths.video_path.unlink(missing_ok=True)


def _earlier_job(job_id: str) -> CreateJobResponse:
    try:
        status = JobStatus(_store.read_status(_store.job_paths(job_id))["status"])
    except Exception:  # noqa: BLE001 - the poll that follows reports what happened
        status = JobStatus.queued
    return CreateJobResponse(job_id=job_id, status=status)


async def _drain(request: Request, response: JSONResponse) -> JSONResponse:
    # a refusal sent mid-upload resets the socket and the phone shows "can't connect", so read the clip out first,
    # but only briefly, or a stranger trickling bytes would hold an upload slot for the whole deadline
    async def read_out() -> None:
        async for _ in request.stream():
            pass
    try:
        await asyncio.wait_for(read_out(), 15)
    except Exception:  # noqa: BLE001 - the phone gave up or was too slow, nothing left to tell it
        pass
    return response


_MAX_REQUEST_JSON = 64 * 1024
_FLUSH_BYTES = 1 << 20


class _BadUpload(Exception):
    pass


async def _receive_upload(request: Request, video_path: Path) -> dict[str, Any]:
    """Stream the multipart body: the clip straight into the job folder, the request json into memory."""
    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if ctype != b"multipart/form-data" or not boundary:
        raise _BadUpload
    head_field, head_value, seen = bytearray(), bytearray(), set()
    part: list[str | None] = [None]
    chunks: list[tuple[str | None, bytes]] = []
    ended = [False]

    def on_header_end() -> None:
        if bytes(head_field).lower() == b"content-disposition":
            name = parse_options_header(bytes(head_value))[1].get(b"name", b"").decode("latin-1")
            if name in seen:
                raise _BadUpload
            seen.add(name)
            part[0] = name
        head_field.clear()
        head_value.clear()

    parser = MultipartParser(boundary, {
        "on_part_begin": lambda: part.__setitem__(0, None),
        "on_header_field": lambda d, s, e: head_field.extend(d[s:e]),
        "on_header_value": lambda d, s, e: head_value.extend(d[s:e]),
        "on_header_end": on_header_end,
        "on_part_data": lambda d, s, e: chunks.append((part[0], d[s:e])),
        "on_end": lambda: ended.__setitem__(0, True),
    })
    request_json, pending, written = bytearray(), bytearray(), 0
    with video_path.open("wb") as f:
        try:
            async for body in request.stream():
                parser.write(body)
                for name, data in chunks:
                    if name == "video_file":
                        pending += data
                    elif name == "request_json":
                        request_json += data
                chunks.clear()
                if len(request_json) > _MAX_REQUEST_JSON:
                    raise _BadUpload
                if len(pending) >= _FLUSH_BYTES:
                    written += await run_in_threadpool(f.write, bytes(pending))
                    pending.clear()
            parser.finalize()
        except FormParserError as e:
            raise _BadUpload from e
        if pending:
            written += await run_in_threadpool(f.write, bytes(pending))
    if not ended[0] or not written or "request_json" not in seen:
        raise _BadUpload
    try:
        req = json.loads(request_json.decode("utf-8"))
    except (ValueError, RecursionError) as e:
        raise _BadUpload from e
    if not isinstance(req, dict):
        raise _BadUpload
    return req


def _outdated(req: dict[str, Any]) -> bool:
    # fields only apps from before the request rewrite send
    tracking, cal = req.get("tracking"), req.get("calibration")
    return ((isinstance(tracking, dict) and bool({"sample_fps", "max_frames"} & tracking.keys()))
            or (isinstance(cal, dict) and bool({"stump_quads_px", "crease_marks_px"} & cal.keys())))


@app.post("/v1/jobs", response_model=CreateJobResponse)
async def create_job(request: Request):
    # _cap_upload has checked the sign-in and holds a queue slot for this upload
    (ident, device_id), key = request.state.who, request.state.key
    job_id, paths = _store.create_job()
    took, submitted = False, False
    try:
        req_dict = await _receive_upload(request, paths.video_path)
        if _outdated(req_dict):
            return _err(426, "app_outdated")
        try:
            CreateJobRequest.model_validate(req_dict)
        except ValueError as e:
            # full validation detail goes to the log only; the client gets one plain sentence
            _log.warning("Invalid job request: %s", e)
            return _err(400, "bad_request")
        # shielded, so an upload timeout can't leave a row behind that nothing will ever finish
        with anyio.CancelScope(shield=True):
            try:
                # one sqlite write lock, so two uploads at once can't both take the last use
                got = await run_in_threadpool(_accounts.take_use, ident, device_id, job_id, key, _store.exists)
            except acc.Refused as e:
                return _err(e.status, e.code, e.message, **e.extra)
        if got != job_id:
            # a retry of a clip that already went through gets that job back
            return _earlier_job(got)
        took = True
        _store.write_request(paths, req_dict)
        _queue.append(job_id)
        _executor.submit(_process_job, job_id, paths, req_dict)
        request.state.slot_held = False
        submitted = True
    except (_BadUpload, ClientDisconnect):
        return _err(400, "bad_request")
    except Exception:
        _log.exception("Failed to save the uploaded video")
        return _err(500, "save_failed")
    finally:
        if not submitted:
            if took:
                # the use was taken but the job never queued, so give it back
                _record_safe(job_id, "failed")
            shutil.rmtree(paths.job_dir, ignore_errors=True)
    return CreateJobResponse(job_id=job_id, status=JobStatus.queued)


def _read_job(job_id: str, result: bool = False) -> tuple[JobStatus, dict[str, Any], dict[str, Any] | None] | None:
    """The job's status, its status file and, if asked and it succeeded, its result; None once it's gone.
    The hourly sweep and account deletes can remove a folder mid-read, which is a 404, never a 500."""
    if not _store.exists(job_id):
        return None
    paths = _store.job_paths(job_id)
    try:
        raw = _store.read_status(paths)
        status = JobStatus(raw["status"])
        out = _store.read_result(paths) if result and status == JobStatus.succeeded else None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None
    return status, raw, out


def _api_error(raw: dict[str, Any]) -> ApiError | None:
    e = raw.get("error")
    return ApiError(**e) if isinstance(e, dict) else None


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    job = _read_job(job_id)
    if job is None:
        return _err(404, "job_not_found")
    status, raw, _ = job
    progress_raw = raw.get("progress")
    progress = ProgressInfo(**progress_raw) if isinstance(progress_raw, dict) else None
    position = None
    if status == JobStatus.queued:
        try:
            position = _queue.index(job_id) + 1
        except ValueError:  # the worker took it between the status read and here
            pass
    return JobStatusResponse(job_id=job_id, status=status, queue_position=position, progress=progress,
                             error=_api_error(raw))


@app.get("/v1/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str):
    job = _read_job(job_id, result=True)
    if job is None:
        return _err(404, "job_not_found")
    status, raw, result = job
    return JobResultResponse(job_id=job_id, status=status, result=result,
                             error=None if status == JobStatus.succeeded else _api_error(raw))


@app.get("/v1/jobs/{job_id}/three-d", response_class=Response)
def get_job_three_d(job_id: str):
    """Render the Three.js 3D ball path viewer; its three.js comes from /static."""
    # this page opens in the phone's browser, so errors get a sentence, not JSON
    job = _read_job(job_id, result=True)
    if job is None:
        return PlainTextResponse("This ball is no longer on the server. Results are kept for a day. "
                                 "Send the ball again to see it in 3D.", status_code=404)
    status, _, result = job
    if status != JobStatus.succeeded or result is None:
        return PlainTextResponse("This ball is still being checked, or the check failed. Open it again from the app "
                                 "once it shows a verdict.", status_code=409)
    if not (result.get("world_trajectory") or {}).get("points_m"):
        return PlainTextResponse("No ball path was found for this delivery, so there is nothing to show in 3D.",
                                 status_code=409)
    return Response(content=render_html(result), media_type="text/html")
