"""One review job, end to end.

decode -> calibrate from the tapped marks -> detect and associate the ball -> reconstruct
the delivery in metres -> predict the stump-plane crossing with its uncertainty -> Law 36
verdict -> overlay and metrics for the client.

The result schema is the client contract; see ``_assemble``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..models import ApiError
from .calibration import CalibrationError, solve_camera_pose
from .decision import decide
from .overlay import build_overlay
from .reconstruction import (BALL_RADIUS_M, Reconstruction, bounce_sigma, predict_stump_plane,
                             reconstruct, sample_path)
from .tracking import CombinedBallDetector, YoloBallDetector, build_pitch_roi_mask
from .trajectory import find_ball_trajectory
from .video import VideoDecodeError, VideoReader

_log = logging.getLogger("pocket_drs.pipeline")

# a correct full-pitch tap calibration sits well under 10 px; the bound scales with frame width
CALIB_REJECT_PX, CALIB_REJECT_FRAC = 25.0, 0.03
# pixel RMS above which the 3-D model does not explain the track and no verdict is given
MAX_FIT_RMS_PX = 12.0
UNCERTAINTY_K = 1.0

ProgressFn = Callable[[int, str], None]


@dataclass(frozen=True)
class PipelineOutput:
    result: dict
    warnings: list[str]


def _progress(fn: ProgressFn | None, pct: int, stage: str) -> None:
    if fn is not None:
        fn(int(max(0, min(100, pct))), stage)


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


def _points(req: dict, key: str, width: int, height: int, n: int) -> list[tuple[float, float]] | None:
    px, norm = req.get(f"{key}_px"), req.get(f"{key}_norm")
    if px and len(px) == n:
        return [(float(p["x"]), float(p["y"])) for p in px]
    if norm and len(norm) == n:
        return [(float(p["x"]) * width, float(p["y"]) * height) for p in norm]
    return None


def _quad_area(pts) -> float:
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _leg_sign(stumps: list[tuple[float, float]], handedness: str) -> float:
    """+1 when world +y is the batter's leg side. The nearer (larger) stump rectangle marks
    the camera's end; a left-hander and a bowler's-end view each flip the sign."""
    end = 1.0 if _quad_area(stumps[0:4]) >= _quad_area(stumps[4:8]) else -1.0
    hand = -1.0 if handedness.lower().startswith("l") else 1.0
    return end * hand


def _rotate(frame: np.ndarray, deg: int) -> np.ndarray:
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(deg % 360)
    return frame if code is None else cv2.rotate(frame, code)


def _int(d: dict, key: str, default: int | None = None) -> int:
    v = d.get(key, default)
    if v is None:
        raise ValueError(f"{key} is required")
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer")


# --------------------------------------------------------------------------- #
# detection and association
# --------------------------------------------------------------------------- #

def _yolo_weights() -> str | None:
    env = os.environ.get("POCKET_DRS_YOLO_WEIGHTS")
    if env:
        return env
    p = Path(__file__).resolve().parents[2] / "models" / "cricket_ball.pt"
    return str(p) if p.exists() else None


def _span(fit) -> float:
    if fit is None or not fit.points:
        return 0.0
    xs = [p.x_px for p in fit.points]; ys = [p.y_px for p in fit.points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _track(frames, times_ms, detector, mask, diag):
    dets = [(t, detector.detect(f, mask)[:8]) for t, f in zip(times_ms, frames)]
    return dets, find_ball_trajectory(dets, image_diagonal_px=diag, min_inliers=6)


def _select_track(frames, times_ms, *, kind, ball_color, roi_mask, diag, yolo_conf, warnings):
    """Run the requested detectors and keep the most ball-like track.

    The learned detector is trusted when it produces a solid arc. A colour track overrides it
    only when it is both markedly longer and tight in an absolute sense, which is a fuller
    ball path rather than a bowler's run-up that merely out-spans a small, far ball."""
    weights = _yolo_weights()
    if kind == "yolo":
        if not weights:
            raise ValueError("detector 'yolo' requested but no weights are installed")
        return _track(frames, times_ms, YoloBallDetector(weights, conf=yolo_conf), None, diag)
    if kind == "combined":
        return _track(frames, times_ms, CombinedBallDetector(ball_color=ball_color), roi_mask, diag)

    colour = []
    for c in [ball_color] + [c for c in ("red", "pink") if c != ball_color]:
        try:
            colour.append(_track(frames, times_ms, CombinedBallDetector(ball_color=c), roi_mask, diag))
        except Exception as e:                                        # noqa: BLE001
            warnings.append(f"colour detector '{c}' failed: {e}")
    yolo = None
    if weights:
        try:
            yolo = _track(frames, times_ms, YoloBallDetector(weights, conf=yolo_conf), None, diag)
        except Exception as e:                                        # noqa: BLE001
            warnings.append(f"learned detector unavailable, used colour and motion ({e})")

    def likeness(r):
        return (_span(r[1]), r[1].inliers if r[1] else 0, -(r[1].rms_px if r[1] else 0.0))

    solid = yolo is not None and yolo[1] is not None and len(yolo[1].points) >= 8 and yolo[1].inliers >= 6
    if solid:
        best = max(colour, key=likeness, default=None)
        if best is not None and best[1] is not None and _span(best[1]) >= 1.5 * _span(yolo[1]) \
                and best[1].rms_px <= 0.007 * diag:
            warnings.append("used the colour track over a shorter learned-detector arc")
            return best
        return yolo
    pool = colour + ([yolo] if yolo else [])
    return max(pool, key=likeness) if pool else ([], None)


def _impact_index(points) -> int | None:
    """Last point of the live delivery: a sustained reversal of horizontal image travel is a
    bat or pad interception. A bounce flips only vertical motion, so it never trips this."""
    n = len(points)
    if n < 8:
        return None
    t = np.array([p.t_ms for p in points], dtype=float)
    u = np.array([p.x_px for p in points], dtype=float)
    dt = np.diff(t); dt[dt == 0] = 1.0
    du = np.diff(u) / dt
    med = float(np.median(np.abs(du)))
    sgn = np.sign(np.median(du))
    if med < 0.02 or sgn == 0:
        return None
    for i in range(max(2, int(0.4 * n)), len(du) - 1):
        if np.sign(du[i]) == -sgn and abs(du[i]) > 0.5 * med and np.sign(du[i + 1]) == -sgn:
            return i
    return None


def _extend_to_reversal(dets_per_frame, points, *, min_conf=0.4, max_step_per_17ms=130.0) -> list[dict]:
    """Walk the learned detections forward past the fitted arc until the ball reverses."""
    if len(points) < 2:
        return []
    tail = points[-min(4, len(points)):]
    ref = (tail[-1].x_px - tail[0].x_px, tail[-1].y_px - tail[0].y_px)
    if abs(ref[0]) + abs(ref[1]) < 1.0:
        return []
    prev_t, prev_u, prev_v = float(points[-1].t_ms), points[-1].x_px, points[-1].y_px
    out, reversed_run = [], 0
    for t_ms, cands in dets_per_frame:
        if t_ms <= prev_t:
            continue
        ok = [c for c in cands if c.get("source") == "yolo" and float(c.get("confidence", 0)) >= min_conf]
        if not ok:
            continue
        max_step = max_step_per_17ms * max(1.0, t_ms - prev_t) / 17.0
        ok = [c for c in ok if 5.0 <= math.hypot(c["x"] - prev_u, c["y"] - prev_v) <= max_step]
        if not ok:
            continue
        best = max(ok, key=lambda c: c["confidence"])
        if (best["x"] - prev_u) * ref[0] + (best["y"] - prev_v) * ref[1] < 0:
            reversed_run += 1
            if reversed_run >= 2:
                return out[:-(reversed_run - 1)] if reversed_run > 1 else out
        else:
            reversed_run = 0
        out.append({"t_ms": int(t_ms), "u": float(best["x"]), "v": float(best["y"]),
                    "radius_px": float(best.get("radius_px", 0.0)), "confidence": float(best["confidence"])})
        prev_t, prev_u, prev_v = float(t_ms), float(best["x"]), float(best["y"])
    return out


# --------------------------------------------------------------------------- #
# the job
# --------------------------------------------------------------------------- #

def run_pipeline(*, video_path: Path, request_json: dict, artifacts_dir: Path,
                 progress: ProgressFn | None = None) -> PipelineOutput:
    warnings: list[str] = []
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if not isinstance(request_json, dict):
        raise ValueError("request body must be a JSON object")

    seg = request_json.get("segment")
    if not isinstance(seg, dict):
        raise ValueError("segment is required")
    start_ms, end_ms = _int(seg, "start_ms"), _int(seg, "end_ms")
    if end_ms <= start_ms:
        raise ValueError("segment.end_ms must be greater than segment.start_ms")
    track_req = request_json.get("tracking") or {}
    sample_fps = _int(track_req, "sample_fps", 30)
    max_frames = _int(track_req, "max_frames", 180)
    if sample_fps < 1 or max_frames < 1:
        raise ValueError("tracking.sample_fps and tracking.max_frames must be positive")
    ball_color = str(track_req.get("ball_color") or "red")
    detector_kind = str(track_req.get("detector") or "auto").lower()
    yolo_conf = float(track_req.get("yolo_conf", 0.2))
    handedness = str(request_json.get("batsman_handedness") or "right")
    rotation = int((request_json.get("video") or {}).get("rotation_deg") or 0)

    cal = request_json.get("calibration") or {}
    if cal.get("mode") != "taps":
        raise ValueError("calibration.mode must be 'taps'")
    dims = cal.get("pitch_dimensions_m") or {}
    try:
        pitch_width = float(dims.get("width"))
    except (TypeError, ValueError):
        raise ValueError("calibration.pitch_dimensions_m.width is required")
    length_raw = dims.get("length")
    pitch_length = None if length_raw is None else float(length_raw)
    if pitch_width <= 0 or (pitch_length is not None and pitch_length <= 0):
        raise ValueError("calibration.pitch_dimensions_m must be positive")
    fov_raw = cal.get("h_fov_deg")
    fov = float(fov_raw) if fov_raw not in (None, "", 0) else None

    # ---- decode ------------------------------------------------------------
    _progress(progress, 5, "decode")
    with VideoReader(str(video_path)) as reader:
        meta = reader.meta
        if meta.duration_ms and start_ms >= meta.duration_ms:
            raise ValueError("segment starts after the end of the video")
        step = max(1, int(round(1000 / sample_fps)))
        end_cap = min(end_ms, meta.duration_ms - 1) if meta.duration_ms > 0 else end_ms
        times_ms = list(range(start_ms, end_cap + 1, step))[:max_frames]
        frames: list[np.ndarray] = []
        for i, t in enumerate(times_ms):
            try:
                frames.append(_rotate(reader.frame_at_ms(t), rotation))
            except VideoDecodeError as e:
                if not frames:
                    raise
                warnings.append(f"video truncated: analysed {len(frames)} of {len(times_ms)} frames ({e})")
                break
            if i and i % max(1, len(times_ms) // 10) == 0:
                _progress(progress, 5 + int(20 * i / max(1, len(times_ms) - 1)), "decode")
        times_ms = times_ms[:len(frames)]
    height, width = frames[0].shape[:2]
    cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])

    # ---- calibrate ----------------------------------------------------------
    _progress(progress, 30, "calibration")
    corners = _points(cal, "pitch_corners", width, height, 4)
    stumps = _points(cal, "stump_quads", width, height, 8)
    if corners is None:
        raise ValueError("calibration.pitch_corners_px or pitch_corners_norm (4 points) is required")
    if stumps is None:
        raise ValueError("calibration.stump_quads_px or stump_quads_norm (8 points) is required")
    pose = solve_camera_pose(image_size=(width, height), stump_quads_px=stumps, pitch_corners_px=corners,
                             pitch_width_m=pitch_width, fov_deg=fov, pitch_length_m=pitch_length)
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
    leg_sign = _leg_sign(stumps, handedness)
    _log.info("calibration ok: reproj=%.2fpx length=%.2fm cam=(%.2f,%.2f,%.2f) fx=%.0f",
              pose.reproj_error_px, pose.pitch_length_m, *pose.centre_world, pose.fx)

    # ---- detect and associate ------------------------------------------------
    _progress(progress, 40, "tracking")
    diag = math.hypot(width, height)
    roi_mask = build_pitch_roi_mask(frames[0].shape, corners)
    dets_per_frame, fit = _select_track(frames, times_ms, kind=detector_kind, ball_color=ball_color,
                                        roi_mask=roi_mask, diag=diag, yolo_conf=yolo_conf, warnings=warnings)
    _progress(progress, 55, "tracking")

    if fit is None:
        warnings.append("no consistent ball trajectory found; check ball colour, lighting and framing")
        return PipelineOutput(_assemble(meta, width, height, pose, {"image_points": [], "candidates_total":
                              sum(len(d) for _, d in dets_per_frame), "inliers": 0, "rms_px": 0.0},
                              None, None, None, None, None, warnings, artifacts_dir), warnings)

    cut = _impact_index(fit.points)
    live = fit.points if cut is None or cut + 1 < 6 else fit.points[:cut + 1]
    if cut is not None and cut + 1 >= 6:
        warnings.append("ball intercepted; tracked the delivery to impact and predicted the rest")
    image_points = [{"t_ms": p.t_ms, "u": p.x_px, "v": p.y_px, "radius_px": p.radius_px, "confidence": p.confidence}
                    for p in live]
    image_points.extend(_extend_to_reversal(dets_per_frame, live))
    track = {"image_points": image_points, "candidates_total": fit.candidates_total,
             "inliers": len(live), "rms_px": fit.rms_px}

    # ---- reconstruct ----------------------------------------------------------
    _progress(progress, 65, "reconstruction")
    t0_ms = image_points[0]["t_ms"]
    dets = [((p["t_ms"] - t0_ms) / 1000.0, p["u"], p["v"], p["radius_px"], max(0.05, p["confidence"]))
            for p in image_points]
    rec = reconstruct(pose, dets)
    if rec is None or rec.rms_px > MAX_FIT_RMS_PX:
        why = "did not converge" if rec is None else f"{rec.rms_px:.1f} px residual"
        warnings.append(f"3-D reconstruction discarded ({why}); the track or the calibration is unreliable")
        return PipelineOutput(_assemble(meta, width, height, pose, track, None, None, None, None, None,
                                        warnings, artifacts_dir), warnings)
    warnings.extend(n for n in rec.notes if "no bounce" in n)

    # ---- predict and decide -----------------------------------------------------
    _progress(progress, 85, "lbw")
    tr = rec.trajectory
    t_last = dets[-1][0]
    pred = predict_stump_plane(rec, 0.0)
    impact = tr.position(np.array([t_last]))[0]
    sig_bx, sig_by = bounce_sigma(rec)
    verdict = decide(leg_sign=leg_sign,
                     pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=sig_by,
                     impact_y=float(impact[1]), impact_sigma=pred.sigma_y if pred else 0.0,
                     stump_y=pred.y if pred else None, stump_z=pred.z if pred else None,
                     sigma_y=pred.sigma_y if pred else 0.0, sigma_z=pred.sigma_z if pred else 0.0,
                     k=UNCERTAINTY_K)
    t_stumps = pred.t if pred is not None else t_last
    predicted = sample_path(tr, t_last, max(t_last, t_stumps), 24)
    sigma_sum = (pred.sigma_y + pred.sigma_z) if pred else 1.0
    confidence = float(max(0.20, min(0.95, 1.0 - sigma_sum / 0.30)))

    bounce_ms = int(round(t0_ms + tr.t_b * 1000.0)) if tr.bounce_observed else None
    impact_ms = int(round(t0_ms + t_last * 1000.0))
    world_points = tr.position(np.array([d[0] for d in dets]))
    v0 = tr.velocity(0.0)
    world = {
        "points_m": [{"t_ms": int(p["t_ms"]), "x": float(w[0]), "y": float(w[1]), "z": float(max(w[2], 0.0)),
                      "confidence": float(p["confidence"])} for p, w in zip(image_points, world_points)],
        "predicted_to_stumps_m": [{"t_ms": int(round(t0_ms + t * 1000.0)), "x": float(x), "y": float(y),
                                   "z": float(z), "confidence": confidence} for t, x, y, z in predicted],
        "fit": {"x0": float(world_points[0][0]), "y0": float(world_points[0][1]), "z0": float(world_points[0][2]),
                "vx": float(v0[0]), "vy": float(v0[1]), "vz": float(v0[2]),
                "bounce_t_ms": tr.t_b * 1000.0 if tr.bounce_observed else None,
                "rms_px": rec.rms_px, "rms_m": rec.rms_px * float(np.mean(pose.project(world_points)[2])) / pose.fx,
                "notes": rec.notes},
        "model": tr.as_dict(),
    }
    events = {
        "bounce": {"t_ms": bounce_ms, "x_m": float(tr.x_b) if tr.bounce_observed else None,
                   "y_m": float(tr.y_b) if tr.bounce_observed else None,
                   "z_m": BALL_RADIUS_M if tr.bounce_observed else None,
                   "sigma_x_m": sig_bx, "sigma_y_m": sig_by},
        "impact": {"t_ms": impact_ms, "x_m": float(impact[0]), "y_m": float(impact[1]), "z_m": float(max(impact[2], 0.0))},
    }
    lbw = {
        "decision": verdict.decision, "reason": verdict.reason,
        "checks": {"pitching_in_line": verdict.pitching_in_line, "impact_in_line": verdict.impact_in_line,
                   "wickets_hitting": verdict.wickets_hitting},
        "prediction": {"y_at_stumps_m": pred.y if pred else None, "z_at_stumps_m": pred.z if pred else None,
                       "stump_x_m": 0.0, "confidence": confidence,
                       "sigma_y_m": pred.sigma_y if pred else None, "sigma_z_m": pred.sigma_z if pred else None,
                       "uncertainty_k": UNCERTAINTY_K},
    }
    overlay = build_overlay(pose=pose, trajectory=tr, t0_ms=int(t0_ms), image_points=image_points,
                            predicted=predicted, bounce_ms=bounce_ms, impact_ms=impact_ms)
    metrics = _metrics(tr, world_points)
    return PipelineOutput(_assemble(meta, width, height, pose, track, world, events, lbw, overlay, metrics,
                                    warnings, artifacts_dir), warnings)


def _metrics(tr, world_points) -> dict:
    """Release speed, swing in the air and turn off the pitch, as a broadcast would show them."""
    speed = float(np.linalg.norm(tr.velocity(0.0)))
    swing_cm = abs(float(tr.y_b - world_points[0][1])) * 100.0 if tr.bounce_observed else 0.0
    turn = math.degrees(math.atan2(float(tr.v_post[1] - tr.v_pre[1]), abs(float(tr.v_pre[0])))) \
        if tr.bounce_observed and abs(tr.v_pre[0]) > 1e-3 else 0.0
    return {"speed_kmh": round(speed * 3.6, 1), "speed_mph": round(speed * 2.2369362921, 1),
            "swing_sf": round(swing_cm, 1), "spin_deg": round(abs(turn), 1)}


def _assemble(meta, width, height, pose, track, world, events, lbw, overlay, metrics, warnings, artifacts_dir) -> dict:
    result = {
        "video": {"duration_ms": int(meta.duration_ms), "fps_est": float(meta.fps)},
        "image_size": {"width": width, "height": height},
        "calibration": {
            "mode": "taps",
            "pose": {"K": pose.K.tolist(), "R": pose.R.tolist(), "t": pose.t.tolist(),
                     "cam_center_world_m": pose.centre_world.tolist(),
                     "fx": pose.fx, "fy": pose.fy, "cx": pose.cx, "cy": pose.cy,
                     "pitch_length_m": pose.pitch_length_m, "fov_deg": pose.fov_deg},
            "quality": {"reproj_error_px": pose.reproj_error_px,
                        "score": float(max(0.05, min(0.99, 1.0 - pose.reproj_error_px / 20.0))),
                        "notes": pose.notes},
        },
        "track": track, "world_trajectory": world, "events": events, "lbw": lbw,
        "overlay": overlay, "metrics": metrics,
        "diagnostics": {"warnings": warnings, "log_id": "server.log"},
    }
    result = _finite(result)
    (artifacts_dir / "result_debug.json").write_text(json.dumps(result, indent=2))
    return result


def map_exception_to_api_error(exc: Exception) -> ApiError:
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, VideoDecodeError):
        return ApiError(code="VIDEO_DECODE_FAILED", message=msg, details=None)
    if isinstance(exc, CalibrationError):
        return ApiError(code="CALIBRATION_DEGENERATE", message=msg, details=None)
    if isinstance(exc, ValueError):
        return ApiError(code="INVALID_REQUEST", message=msg, details=None)
    return ApiError(code="INTERNAL_ERROR", message=msg, details=None)
