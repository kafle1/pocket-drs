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
                      confidence, sigma_y_m, sigma_z_m, uncertainty_k}}
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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..models import ApiError, CreateJobRequest
from .calibration import CalibrationError, solve_camera_pose
from .decision import decide
from .overlay import build_overlay
from .reconstruction import BALL_RADIUS_M, bounce_sigma, position_sigma, predict_stump_plane, reconstruct, sample_path
from .tracking import ColourMotionDetector, YoloDetector, build_pitch_roi_mask
from .trajectory import find_ball_trajectory
from .video import VideoDecodeError, VideoReader

_log = logging.getLogger("pocket_drs.pipeline")

YOLO_WEIGHTS = Path(__file__).resolve().parents[2] / "models" / "cricket_ball.pt"
# a correct full-pitch tap calibration sits well under 10 px; the bound scales with frame width
CALIB_REJECT_PX, CALIB_REJECT_FRAC = 25.0, 0.03
# above this pixel residual the 3-D model does not explain the track and no verdict is given
MAX_FIT_RMS_PX = 12.0
UNCERTAINTY_K = 1.0

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


def _quad_area(pts) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2.0


def _leg_sign(stumps: list[tuple[float, float]], handedness: str) -> float:
    """+1 when world +y is the batter's leg side. The nearer (larger) stump rectangle marks the
    camera's end; a left-hander and a bowler's-end view each flip the sign."""
    end = 1.0 if _quad_area(stumps[0:4]) >= _quad_area(stumps[4:8]) else -1.0
    return end * (-1.0 if handedness == "left" else 1.0)


def _rotate(frame: np.ndarray, deg: int) -> np.ndarray:
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(deg)
    return frame if code is None else cv2.rotate(frame, code)


def _span(fit) -> float:
    xs = [p.x_px for p in fit.points]
    ys = [p.y_px for p in fit.points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _track(frames, times_ms, detector, diag):
    dets = [(t, detector.detect(f)[:8]) for t, f in zip(times_ms, frames)]
    return dets, find_ball_trajectory(dets, image_diagonal_px=diag, min_inliers=6)


def _select_track(frames, times_ms, *, kind: str, ball_color: str, roi_mask, diag: float, warnings: list[str]):
    """Returns (per-frame detections to walk past the arc, the chosen track).

    The learned detector is trusted when it produces a solid arc. A colour track wins only when
    it is both markedly longer and tight in an absolute sense, a fuller ball path rather than a
    bowler's run-up that merely out-spans a small, far ball. The learned detections are handed
    back whichever track won, because they are what the interception walk needs."""
    yolo = _track(frames, times_ms, YoloDetector(str(YOLO_WEIGHTS)), diag) if kind != "colour" else None
    if kind == "yolo":
        return yolo
    colours = [_track(frames, times_ms, ColourMotionDetector(c, roi_mask), diag)
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
        out.append({"t_ms": int(t_ms), "u": best["x"], "v": best["y"], "radius_px": best["radius_px"],
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
        step = max(1, round(1000 / req.tracking.sample_fps))
        end = min(req.segment.end_ms, meta.duration_ms - 1) if meta.duration_ms > 0 else req.segment.end_ms
        times_ms = list(range(req.segment.start_ms, end + 1, step))[:req.tracking.max_frames]
        frames: list[np.ndarray] = []
        for i, t in enumerate(times_ms):
            try:
                frames.append(_rotate(reader.frame_at_ms(t), req.video.rotation_deg))
            except VideoDecodeError as e:
                if not frames:
                    raise
                warnings.append(f"video truncated: analysed {len(frames)} of {len(times_ms)} frames ({e})")
                break
            if i % max(1, len(times_ms) // 10) == 0:
                report(5 + 20 * i // max(1, len(times_ms) - 1), "decode")
        times_ms = times_ms[:len(frames)]
    height, width = frames[0].shape[:2]
    cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])

    # ---- calibrate ----------------------------------------------------------
    report(30, "calibration")
    corners = _points(req.calibration, "pitch_corners", width, height)
    stumps = _points(req.calibration, "stump_quads", width, height)
    pose = solve_camera_pose(image_size=(width, height), stump_quads_px=stumps, pitch_corners_px=corners,
                             pitch_width_m=req.calibration.pitch_dimensions_m.width,
                             fov_deg=req.calibration.h_fov_deg,
                             pitch_length_m=req.calibration.pitch_dimensions_m.length)
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
    if not (1.5 <= pose.pitch_length_m <= 25.0):
        raise CalibrationError(f"Calibration rejected: derived pitch length {pose.pitch_length_m:.2f} m is implausible.")
    if pose.reproj_error_px > 8.0:
        warnings.append(f"high calibration reprojection error ({pose.reproj_error_px:.1f} px); re-tap the stump corners")
    leg_sign = _leg_sign(stumps, req.batsman_handedness)
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
                                        diag=diag, warnings=warnings)
    report(55, "tracking")
    if fit is None:
        warnings.append("no consistent ball trajectory found; check ball colour, lighting and framing")
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
    dets = [((p["t_ms"] - t0_ms) / 1000.0, p["u"], p["v"], p["radius_px"], max(0.05, p["confidence"]))
            for p in image_points]
    rec = reconstruct(pose, dets)
    if rec is None or rec.rms_px > MAX_FIT_RMS_PX:
        why = "did not converge" if rec is None else f"{rec.rms_px:.1f} px residual"
        warnings.append(f"3-D reconstruction discarded ({why}); the track or the calibration is unreliable")
        return finish()
    tr = rec.trajectory
    if not tr.bounce_observed:
        warnings.append("no bounce in the tracked window; the flight was fitted as a single parabola")

    # ---- predict and decide -----------------------------------------------------
    report(85, "lbw")
    t_last = dets[-1][0]
    pred = predict_stump_plane(rec)
    impact = tr.position(np.array([t_last]))[0]
    sig_bx, sig_by = bounce_sigma(rec)
    verdict = decide(leg_sign=leg_sign,
                     pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=sig_by,
                     impact_y=float(impact[1]), impact_sigma=position_sigma(rec, t_last)[1],
                     stump_y=pred.y if pred else None, stump_z=pred.z if pred else None,
                     sigma_y=pred.sigma_y if pred else 0.0, sigma_z=pred.sigma_z if pred else 0.0,
                     k=UNCERTAINTY_K)
    predicted = sample_path(tr, t_last, pred.t, 24) if pred and pred.t > t_last else np.empty((0, 4))
    confidence = max(0.20, min(0.95, 1.0 - ((pred.sigma_y + pred.sigma_z) if pred else 1.0) / 0.30))
    bounce_ms = round(t0_ms + tr.t_b * 1000.0) if tr.bounce_observed else None
    impact_ms = round(t0_ms + t_last * 1000.0)
    world_points = tr.position(np.array([d[0] for d in dets]))
    v0 = tr.velocity(0.0)

    result["world_trajectory"] = {
        "points_m": [{"t_ms": int(p["t_ms"]), "x": float(w[0]), "y": float(w[1]), "z": float(max(w[2], 0.0)),
                      "confidence": float(p["confidence"])} for p, w in zip(image_points, world_points)],
        "predicted_to_stumps_m": [{"t_ms": round(t0_ms + t * 1000.0), "x": float(x), "y": float(y), "z": float(z),
                                   "confidence": confidence} for t, x, y, z in predicted],
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
                   "sigma_x_m": sig_bx, "sigma_y_m": sig_by},
        "impact": {"t_ms": impact_ms, "x_m": float(impact[0]), "y_m": float(impact[1]), "z_m": float(max(impact[2], 0.0))},
    }
    result["lbw"] = {
        "decision": verdict.decision, "reason": verdict.reason,
        "checks": {"pitching_in_line": verdict.pitching_in_line, "impact_in_line": verdict.impact_in_line,
                   "wickets_hitting": verdict.wickets_hitting},
        "prediction": {"y_at_stumps_m": pred.y if pred else None, "z_at_stumps_m": pred.z if pred else None,
                       "stump_x_m": 0.0, "confidence": confidence,
                       "sigma_y_m": pred.sigma_y if pred else None, "sigma_z_m": pred.sigma_z if pred else None,
                       "uncertainty_k": UNCERTAINTY_K},
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
