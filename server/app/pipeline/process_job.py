"""One review job, end to end.

decode -> calibrate from the tapped marks -> detect and associate the ball -> reconstruct the
delivery in metres -> predict the stump-plane crossing with its uncertainty -> Law 36 verdict
-> overlay and metrics for the client.

The result dict is the client contract:

    video            {duration_ms, fps_est}
    image_size       {width, height}
    calibration      {mode, pose{K, R, t, cam_center_world_m, fx, fy, cx, cy, pitch_length_m, pitch_width_m, fov_deg},
                      quality{reproj_error_px, score, notes[]}}
    track            {image_points[{t_ms, u, v, radius_px, confidence}], candidates_total, inliers, rms_px}
    world_trajectory {points_m[{t_ms, x, y, z, confidence}], predicted_to_stumps_m[...],
                      fit{x0, y0, z0, vx, vy, vz, bounce_t_ms, rms_px, rms_m, notes[]}, model{...}}
    events           {bounce{t_ms, x_m, y_m, z_m, sigma_x_m, sigma_y_m}, impact{t_ms, x_m, y_m, z_m}}
    lbw              {decision, reason, checks{...}, prediction{y_at_stumps_m, z_at_stumps_m, stump_x_m,
                      u_y_m, u_z_m, U95_y_m, U95_z_m, sigma_fit_*, sigma_cal_*, calibrated}}
    overlay          pixel-space polylines and markers, see overlay.py
    metrics          {speed_kmh, speed_mph, swing_sf, spin_deg}
    diagnostics      {warnings[]}

world_trajectory, events, lbw, overlay and metrics are null when no verdict could be given;
diagnostics.warnings says why.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..models import ApiError, CreateJobRequest
from .calibration import CalibrationError, solve_camera_pose
from .decision import decide
from .overlay import build_overlay
from .reconstruction import BALL_RADIUS_M, reconstruct, sample_path
from .tracking import ColourMotionDetector, YoloDetector, build_pitch_roi_mask, drop_impossible
from .trajectory import find_ball_trajectory
from .uncertainty import GUARD_K, MAX_FIT_RMS_PX, calibrated, calibration_sigma, camera_end, measurands
from .video import VideoDecodeError, VideoReader

_log = logging.getLogger("pocket_drs.pipeline")

YOLO_WEIGHTS = Path(__file__).resolve().parents[2] / "models" / "cricket_ball.pt"
# a correct full-pitch tap calibration sits well under 10 px; the bound scales with frame width
CALIB_REJECT_PX, CALIB_REJECT_FRAC = 25.0, 0.03
# a track point this far off the fitted flight is an outlier by a 3-sigma rule, even at the
# largest residual the app accepts
FLIGHT_OUTLIER_PX = 3.0 * MAX_FIT_RMS_PX

ProgressFn = Callable[[int, str], None]


@dataclass(frozen=True)
class PipelineOutput:
    result: dict
    warnings: list[str]


def _finite(obj):
    """JSON-safe copy: NaN and Inf become None, numpy scalars become Python numbers."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, np.generic):
        return _finite(obj.item())
    if isinstance(obj, np.ndarray):
        return [_finite(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(x) for x in obj]
    return obj


def _points(cal, key: str, width: int, height: int) -> list[tuple[float, float]]:
    norm = getattr(cal, f"{key}_norm")
    if norm is not None:
        return [(p.x * width, p.y * height) for p in norm]
    return [(p.x, p.y) for p in getattr(cal, f"{key}_px")]


def _leg_sign(handedness: str) -> float:
    """+1 when world +y is the batter's leg side. The world frame is fixed to the pitch whichever
    end the phone is at, so only the batter's hand flips it."""
    return -1.0 if handedness == "left" else 1.0


def _resolve(image_size: tuple[int, int], cal, taps: np.ndarray):
    """The pose from 8 stump marks then 4 pitch corners, with the request's dimensions."""
    return solve_camera_pose(image_size=image_size, stump_quads_px=[tuple(p) for p in taps[:8]],
                             pitch_corners_px=[tuple(p) for p in taps[8:]],
                             pitch_width_m=cal.pitch_dimensions_m.width, fov_deg=cal.h_fov_deg,
                             pitch_length_m=cal.pitch_dimensions_m.length)


def detections(image_points: list[dict]) -> list[tuple]:
    """(t_s from the first point, u, v, radius_px, weight) for the fit."""
    return [((p["t_ms"] - image_points[0]["t_ms"]) / 1000.0, p["u"], p["v"], p["radius_px"], max(0.05, p["confidence"]))
            for p in image_points]


def _rotate(frame: np.ndarray, deg: int) -> np.ndarray:
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(deg)
    return frame if code is None else cv2.rotate(frame, code)


def _span(fit) -> float:
    xs = [p.x_px for p in fit.points]
    ys = [p.y_px for p in fit.points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _flight_fit(pose, points):
    """3-D flight through the track points and each point's pixel offset from it, or None."""
    if len(points) < 6:
        return None
    t0 = points[0].t_ms
    ts = np.array([(p.t_ms - t0) / 1000.0 for p in points])
    rec = reconstruct(pose, [(t, p.x_px, p.y_px, p.radius_px, max(0.05, p.confidence)) for t, p in zip(ts, points)])
    if rec is None:
        return None
    u, v, _ = pose.project(rec.trajectory.position(ts))
    return rec, np.hypot(u - np.array([p.x_px for p in points]), v - np.array([p.y_px for p in points]))


def _fits_flight(pose, fit):
    """The track less the points far off the 3-D flight through it, or None when no ball in
    flight explains it. Only the part before a bat or pad is judged, since the flight changes there."""
    cut = _impact_index(fit.points)
    live = fit.points if cut is None or cut + 1 < 6 else fit.points[:cut + 1]
    rest = fit.points[len(live):]
    got = _flight_fit(pose, live)
    if got is not None and (got[1] > FLIGHT_OUTLIER_PX).any():
        n = len(live)
        live = [p for p, off in zip(live, got[1]) if off <= FLIGHT_OUTLIER_PX]
        _log.info("flight gate: dropped %d of %d track points off the 3-D flight", n - len(live), n)
        got = _flight_fit(pose, live)
    if got is None or got[0].rms_px > MAX_FIT_RMS_PX:
        _log.info("flight gate: no ball flight explains a %d-point track (%s)", len(fit.points),
                  "no fit" if got is None else f"{got[0].rms_px:.1f} px residual")
        return None
    return replace(fit, points=live + rest, inliers=len(live) + len(rest))


def _track(frames, times_ms, detector, diag, pose, fps):
    dets, n_raw, n_kept = [], 0, 0
    for t, f in zip(times_ms, frames):
        raw = detector.detect(f)
        kept = drop_impossible(raw, pose, fps)
        n_raw, n_kept = n_raw + len(raw), n_kept + len(kept)
        dets.append((t, kept[:8]))
    if n_kept < n_raw:
        _log.info("%s: dropped %d of %d detections no ball could make", type(detector).__name__, n_raw - n_kept, n_raw)
    return dets, find_ball_trajectory(dets, image_diagonal_px=diag, min_inliers=6, accept=partial(_fits_flight, pose))


def _select_track(frames, times_ms, *, kind: str, ball_color: str, roi_mask, diag: float, pose, fps: float,
                  warnings: list[str]):
    """Returns (per-frame detections to walk past the arc, the chosen track).

    The learned detector is trusted when it produces a solid arc. A colour track wins only when
    it is both markedly longer and tight in an absolute sense, a fuller ball path rather than a
    bowler's run-up that merely out-spans a small, far ball. The learned detections are handed
    back whichever track won, because they are what the interception walk needs."""
    yolo = _track(frames, times_ms, YoloDetector(str(YOLO_WEIGHTS)), diag, pose, fps) if kind != "colour" else None
    if kind == "yolo":
        return yolo
    colours = [_track(frames, times_ms, ColourMotionDetector(c, roi_mask), diag, pose, fps)
               for c in dict.fromkeys([ball_color, "red", "pink"])]
    best_colour = max((c for c in colours if c[1] is not None), key=lambda c: _span(c[1]), default=None)
    dets = yolo[0] if yolo is not None else (best_colour[0] if best_colour else [])
    if yolo is not None and yolo[1] is not None and len(yolo[1].points) >= 8 and yolo[1].inliers >= 6:
        if best_colour is not None and _span(best_colour[1]) >= 1.5 * _span(yolo[1]) and best_colour[1].rms_px <= 0.007 * diag:
            warnings.append("used the colour track over a shorter learned-detector arc")
            return dets, best_colour[1]
        return dets, yolo[1]
    return dets, (best_colour[1] if best_colour else None)


def _impact_index(points) -> int | None:
    """Last point of the live delivery: a sustained reversal of horizontal image travel is a bat
    or pad interception. A bounce flips only vertical motion, so it never trips this."""
    n = len(points)
    if n < 8:
        return None
    t = np.array([p.t_ms for p in points], dtype=float)
    u = np.array([p.x_px for p in points], dtype=float)
    dt = np.diff(t)
    dt[dt == 0] = 1.0
    du = np.diff(u) / dt
    med, sgn = float(np.median(np.abs(du))), np.sign(np.median(du))
    if med < 0.02 or sgn == 0:
        return None
    for i in range(max(2, int(0.4 * n)), len(du) - 1):
        if np.sign(du[i]) == -sgn and abs(du[i]) > 0.5 * med and np.sign(du[i + 1]) == -sgn:
            return i
    return None


def _extend_to_reversal(dets_per_frame, points, *, min_conf=0.4, max_step_per_17ms=130.0) -> list[dict]:
    """Walk the detections forward past the fitted arc until the ball reverses."""
    tail = points[-min(4, len(points)):]
    ref = (tail[-1].x_px - tail[0].x_px, tail[-1].y_px - tail[0].y_px)
    if abs(ref[0]) + abs(ref[1]) < 1.0:
        return []
    prev_t, prev_u, prev_v = float(points[-1].t_ms), points[-1].x_px, points[-1].y_px
    out, reversed_run = [], 0
    for t_ms, cands in dets_per_frame:
        if t_ms <= prev_t:
            continue
        max_step = max_step_per_17ms * max(1.0, t_ms - prev_t) / 17.0
        ok = [c for c in cands if c["confidence"] >= min_conf
              and 5.0 <= math.hypot(c["x"] - prev_u, c["y"] - prev_v) <= max_step]
        if not ok:
            continue
        best = max(ok, key=lambda c: c["confidence"])
        if (best["x"] - prev_u) * ref[0] + (best["y"] - prev_v) * ref[1] < 0:
            reversed_run += 1
            if reversed_run >= 2:
                return out[:len(out) - reversed_run + 1]
        else:
            reversed_run = 0
        out.append({"t_ms": float(t_ms), "u": best["x"], "v": best["y"], "radius_px": best["radius_px"],
                    "confidence": best["confidence"]})
        prev_t, prev_u, prev_v = float(t_ms), best["x"], best["y"]
    return out


def run_pipeline(*, video_path: Path, request_json: dict, artifacts_dir: Path,
                 progress: ProgressFn | None = None) -> PipelineOutput:
    req = CreateJobRequest.model_validate(request_json)
    warnings: list[str] = []
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    def report(pct: int, stage: str) -> None:
        if progress is not None:
            progress(pct, stage)

    # ---- decode ------------------------------------------------------------
    report(5, "decode")
    with VideoReader(str(video_path)) as reader:
        meta = reader.meta
        if meta.duration_ms and req.segment.start_ms >= meta.duration_ms:
            raise ValueError("segment starts after the end of the video")
        # ask for a frame every 1000/sample_fps ms; each comes back labelled with its own timestamp
        step = 1000.0 / req.tracking.sample_fps
        end = min(req.segment.end_ms, meta.duration_ms) if meta.duration_ms > 0 else req.segment.end_ms
        n_req = min(req.tracking.max_frames, int((end - req.segment.start_ms) / step + 1e-9) + 1)
        picked, notes = reader.frames([req.segment.start_ms + k * step for k in range(n_req)],
                                      progress=lambda f: report(5 + int(20 * f), "decode"))
    for note in notes:
        _log.warning("decode: %s", note)
        warnings.append(note)
    times_ms = [t for t, _ in picked]
    frames = [f for _, f in picked]
    del picked
    for i, f in enumerate(frames):
        frames[i] = _rotate(f, req.video.rotation_deg)
    height, width = frames[0].shape[:2]
    cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])

    # ---- calibrate ----------------------------------------------------------
    report(30, "calibration")
    corners = _points(req.calibration, "pitch_corners", width, height)
    stumps = _points(req.calibration, "stump_quads", width, height)
    taps = np.array(list(stumps) + list(corners), dtype=float)
    pose = _resolve((width, height), req.calibration, taps)
    reject = max(CALIB_REJECT_PX, CALIB_REJECT_FRAC * width)
    if pose.reproj_error_px > reject:
        raise CalibrationError(
            f"Calibration rejected: reprojection error {pose.reproj_error_px:.0f} px exceeds {reject:.0f} px. "
            "Re-tap the four corners of each stump cluster more precisely.")
    cam_z = float(pose.centre_world[2])
    if not (0.10 <= cam_z <= 5.0):
        raise CalibrationError(
            f"Calibration rejected: recovered camera height {cam_z:.2f} m is not a hand-held phone. "
            "Re-mark the stumps in order: striker end then bowler end, top-left, top-right, bottom-right, bottom-left.")
    if not (2.0 <= pose.pitch_length_m <= 25.0):
        raise CalibrationError(f"Calibration rejected: derived pitch length {pose.pitch_length_m:.2f} m is implausible.")
    if not pose.used_corners:
        warnings.append("the pitch corners disagree with the stumps and were left out; "
                        "tap them clockwise, the two at the striker end first")
    if pose.reproj_error_px > 8.0:
        warnings.append(f"high calibration reprojection error ({pose.reproj_error_px:.1f} px); re-tap the stump corners")
    leg_sign = _leg_sign(req.batsman_handedness)
    _log.info("calibration ok: reproj=%.2fpx length=%.2fm cam=(%.2f,%.2f,%.2f) fx=%.0f",
              pose.reproj_error_px, pose.pitch_length_m, *pose.centre_world, pose.fx)

    result = {
        "video": {"duration_ms": int(meta.duration_ms), "fps_est": float(meta.fps)},
        "image_size": {"width": width, "height": height},
        "calibration": {
            "mode": "taps",
            "pose": {"K": pose.K.tolist(), "R": pose.R.tolist(), "t": pose.t.tolist(),
                     "cam_center_world_m": pose.centre_world.tolist(),
                     "fx": pose.fx, "fy": pose.fy, "cx": pose.cx, "cy": pose.cy,
                     "pitch_length_m": pose.pitch_length_m, "pitch_width_m": pose.pitch_width_m,
                     "fov_deg": pose.fov_deg},
            "quality": {"reproj_error_px": pose.reproj_error_px,
                        "score": max(0.05, min(0.99, 1.0 - pose.reproj_error_px / 20.0)),
                        "notes": pose.notes},
        },
        "track": None, "world_trajectory": None, "events": None, "lbw": None, "overlay": None, "metrics": None,
        "diagnostics": {"warnings": warnings},
    }

    def finish() -> PipelineOutput:
        clean = _finite(result)
        (artifacts_dir / "result_debug.json").write_text(json.dumps(clean, indent=2))
        return PipelineOutput(clean, warnings)

    # ---- detect and associate ------------------------------------------------
    report(40, "tracking")
    diag = math.hypot(width, height)
    dets_per_frame, fit = _select_track(frames, times_ms, kind=req.tracking.detector,
                                        ball_color=req.tracking.ball_color,
                                        roi_mask=build_pitch_roi_mask(frames[0].shape, corners),
                                        diag=diag, pose=pose, fps=meta.fps, warnings=warnings)
    report(55, "tracking")
    if fit is None:
        warnings.append("no consistent ball trajectory found")
        result["track"] = {"image_points": [], "candidates_total": sum(len(d) for _, d in dets_per_frame),
                           "inliers": 0, "rms_px": 0.0}
        return finish()

    cut = _impact_index(fit.points)
    live = fit.points if cut is None or cut + 1 < 6 else fit.points[:cut + 1]
    if live is not fit.points:
        warnings.append("ball intercepted; tracked the delivery to impact and predicted the rest")
    else:
        warnings.append("no interception seen; the last tracked point stands in for the impact")
    image_points = [{"t_ms": p.t_ms, "u": p.x_px, "v": p.y_px, "radius_px": p.radius_px, "confidence": p.confidence}
                    for p in live]
    image_points.extend(_extend_to_reversal(dets_per_frame, live))
    result["track"] = {"image_points": image_points, "candidates_total": fit.candidates_total,
                       "inliers": len(live), "rms_px": fit.rms_px}

    # ---- reconstruct ----------------------------------------------------------
    report(65, "reconstruction")
    t0_ms = image_points[0]["t_ms"]
    dets = detections(image_points)
    meas = measurands(pose, dets)
    n_walk = len(dets) - len(live)
    if meas is None and n_walk > 0:
        # the walk past the arc takes the most confident nearby detection, which may not be the
        # ball, so keep only the walk points the arc's own flight explains and fit again
        arc = reconstruct(pose, dets[:len(live)])
        if arc is not None:
            u, v, _ = pose.project(arc.trajectory.position(np.array([d[0] for d in dets])))
            off = np.hypot(u - np.array([d[1] for d in dets]), v - np.array([d[2] for d in dets]))
            keep = [i for i in range(len(live), len(dets)) if off[i] <= FLIGHT_OUTLIER_PX]
            if len(keep) < n_walk:
                warnings.append(f"dropped {n_walk - len(keep)} of {n_walk} points past the tracked arc "
                                "that its flight does not explain")
                image_points[len(live):] = [image_points[i] for i in keep]
                dets = dets[:len(live)] + [dets[i] for i in keep]
                meas = measurands(pose, dets)
    if meas is None:
        rec = reconstruct(pose, dets)
        why = "did not converge" if rec is None else f"{rec.rms_px:.1f} px residual"
        warnings.append(f"3-D reconstruction discarded ({why}); the track or the calibration is unreliable")
        return finish()
    rec, pred, tr, impact = meas.rec, meas.pred, meas.rec.trajectory, meas.impact
    if not tr.bounce_observed:
        warnings.append("no bounce in the tracked window; the flight was fitted as a single parabola, so the "
                        "pitching test is skipped, no bias correction is applied and the uncertainty takes "
                        "its widest factor and largest model term")

    # ---- uncertainty and decision -------------------------------------------------
    report(75, "uncertainty")
    sig_cal, n_failed = calibration_sigma(partial(_resolve, (width, height), req.calibration), taps, dets, meas,
                                          pose.tap_sigma_px)
    if n_failed:
        warnings.append(f"{n_failed} of {taps.size} perturbed calibration solves failed; what they lost "
                        "counts as unknown, so the verdict is at most umpire's call")
    cal = calibrated(camera_end(pose), leg_sign, meas.values, meas.sigma_fit, sig_cal, meas.x_b, tr.bounce_observed)

    def get(q, key):
        return cal[q][key] if q in cal else None

    report(85, "lbw")
    verdict = decide(leg_sign=leg_sign, pitch_y=get("pitch_y", "value"), pitch_sigma=get("pitch_y", "sigma"),
                     impact_y=get("impact_y", "value"), impact_sigma=get("impact_y", "sigma"),
                     stump_y=get("y", "value"), stump_z=get("z", "value"),
                     sigma_y=get("y", "sigma"), sigma_z=get("z", "sigma"), k=GUARD_K)
    predicted = sample_path(tr, meas.t_impact, pred.t, 24) if pred and pred.t > meas.t_impact else np.empty((0, 4))
    bounce_ms = round(t0_ms + tr.t_b * 1000.0) if tr.bounce_observed else None
    impact_ms = round(t0_ms + meas.t_impact * 1000.0)
    world_points = tr.position(np.array([d[0] for d in dets]))
    v0 = tr.velocity(0.0)

    result["world_trajectory"] = {
        "points_m": [{"t_ms": float(p["t_ms"]), "x": float(w[0]), "y": float(w[1]), "z": float(max(w[2], 0.0)),
                      "confidence": float(p["confidence"])} for p, w in zip(image_points, world_points)],
        "predicted_to_stumps_m": [{"t_ms": round(t0_ms + t * 1000.0), "x": float(x), "y": float(y), "z": float(z)}
                                  for t, x, y, z in predicted],
        "fit": {"x0": float(world_points[0][0]), "y0": float(world_points[0][1]), "z0": float(world_points[0][2]),
                "vx": float(v0[0]), "vy": float(v0[1]), "vz": float(v0[2]),
                "bounce_t_ms": tr.t_b * 1000.0 if tr.bounce_observed else None,
                "rms_px": rec.rms_px, "rms_m": rec.rms_px * float(np.mean(pose.project(world_points)[2])) / pose.fx,
                "notes": rec.notes},
        "model": tr.as_dict(),
    }
    result["events"] = {
        "bounce": {"t_ms": bounce_ms,
                   "x_m": float(tr.x_b) if tr.bounce_observed else None,
                   "y_m": float(tr.y_b) if tr.bounce_observed else None,
                   "z_m": BALL_RADIUS_M if tr.bounce_observed else None,
                   "sigma_x_m": math.sqrt(max(float(rec.covariance[1, 1]), 0.0)) if tr.bounce_observed else None,
                   "sigma_y_m": meas.sigma_fit["pitch_y"] if tr.bounce_observed else None},
        "impact": {"t_ms": impact_ms, "x_m": float(impact[0]), "y_m": float(impact[1]), "z_m": float(max(impact[2], 0.0))},
    }
    result["lbw"] = {
        "decision": verdict.decision, "reason": verdict.reason,
        "checks": {"pitching_in_line": verdict.pitching_in_line, "impact_in_line": verdict.impact_in_line,
                   "wickets_hitting": verdict.wickets_hitting},
        # y and z have the rule's bias removed where it has one; u and U95 are half-widths of the calibrated 68 and 95 % intervals
        "prediction": {"y_at_stumps_m": get("y", "value"), "z_at_stumps_m": get("z", "value"), "stump_x_m": 0.0,
                       "u_y_m": get("y", "u"), "u_z_m": get("z", "u"), "U95_y_m": get("y", "U95"), "U95_z_m": get("z", "U95"),
                       "sigma_fit_y_m": meas.sigma_fit["y"], "sigma_fit_z_m": meas.sigma_fit["z"],
                       "sigma_cal_y_m": sig_cal["y"] if pred else None, "sigma_cal_z_m": sig_cal["z"] if pred else None,
                       "calibrated": bool(tr.bounce_observed)},
    }
    result["overlay"] = build_overlay(pose=pose, trajectory=tr, t0_ms=int(t0_ms), image_points=image_points,
                                      predicted=predicted, bounce_ms=bounce_ms, impact_ms=impact_ms)
    speed = float(np.linalg.norm(v0))
    turn = math.degrees(math.atan2(float(tr.v_post[1] - tr.v_pre[1]), abs(float(tr.v_pre[0])))) if tr.bounce_observed else 0.0
    result["metrics"] = {
        "speed_kmh": round(speed * 3.6, 1), "speed_mph": round(speed * 2.2369362921, 1),
        "swing_sf": round(abs(float(tr.y_b - world_points[0][1])) * 100.0, 1) if tr.bounce_observed else 0.0,
        "spin_deg": round(abs(turn), 1),
    }
    return finish()


def map_exception_to_api_error(exc: Exception) -> ApiError:
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, VideoDecodeError):
        return ApiError(code="VIDEO_DECODE_FAILED", message=msg)
    if isinstance(exc, CalibrationError):
        return ApiError(code="CALIBRATION_DEGENERATE", message=msg)
    if isinstance(exc, ValueError):
        return ApiError(code="INVALID_REQUEST", message=msg)
    return ApiError(code="INTERNAL_ERROR", message=msg)
