"""One review job, end to end.

decode -> calibrate from the tapped marks -> detect and associate the ball -> reconstruct the
delivery in metres -> predict the stump-plane crossing with its uncertainty -> Law 36 verdict
-> overlay and metrics for the client.

The result dict is the client contract:

    image_size       {width, height}
    calibration      {pose{K, R, t, cam_center_world_m, fx, fy, cx, cy, pitch_length_m, pitch_width_m, fov_deg},
                      quality{reproj_error_px, notes[]}}
    track            {image_points[{t_ms, u, v, radius_px, confidence}]}, the matched ball in time order;
                     the last point stands in for the impact
    world_trajectory {points_m[{t_ms, x, y, z, confidence}], predicted_to_stumps_m[...],
                      fit{x0, y0, z0, vx, vy, vz, rms_px, rms_m, notes[]}, model{...}}
    events           {bounce{t_ms, x_m, y_m, z_m, sigma_x_m, sigma_y_m}, impact{t_ms, x_m, y_m, z_m}}
    lbw              {decision, reason, checks{...}, prediction{y_at_stumps_m, z_at_stumps_m, stump_x_m,
                      confidence, sigma_y_m, sigma_z_m, uncertainty_k}}
    overlay          pixel-space polylines and markers, see overlay.py
    metrics          {speed_kmh, speed_mph, swing_cm, spin_deg}, speed null when too uncertain to show,
                     swing and spin null when no bounce was seen
    diagnostics      {warnings[], fit_rms_px when the track was thrown out}

world_trajectory, events, lbw and metrics are null when no verdict could be given, and overlay
then holds only the tracked flight; diagnostics.warnings says why.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import ApiError, CreateJobRequest
from .calibration import STUMP_HEIGHT_M, CalibrationError, solve_camera_pose
from .decision import decide
from .overlay import build_overlay
from .reconstruction import (BALL_RADIUS_M, Detection, Reconstruction, bounce_sigma, position_sigma,
                             predict_stump_plane, reconstruct, sample_path, speed_sigma)
from .tracking import ColourMotionDetector, corridor_mask
from .trajectory import MAX_GAP_S, find_ball
from .video import VideoDecodeError, read_frames

_log = logging.getLogger("pocket_drs.pipeline")

# a correct full-pitch tap calibration sits well under 10 px; the bound scales with frame width
CALIB_REJECT_PX, CALIB_REJECT_FRAC = 25.0, 0.03
# above this pixel residual the 3-D model does not explain the track and no verdict is given
MAX_FIT_RMS_PX = 12.0
UNCERTAINTY_K = 1.0
# a speed known no better than this is left out rather than shown wrong
MAX_SPEED_SIGMA_KMH = 8.0
# re-solves with jittered taps; a tap is never assumed better than MIN_TAP_SD_PX
CAL_SAMPLES = 24
MIN_TAP_SD_PX = 1.0

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


def _calibration_spread(stumps: list[tuple[float, float]], image_size: tuple[int, int], length: float, width: float,
                        tap_sd: float, dets: list[Detection], rec: Reconstruction, t_last: float) -> np.ndarray | None:
    """1-sigma of (pitch y, bounce x, impact y, stump y, stump z, speed) from tap error alone.

    A tap error moves the whole path at once, so the fit's pixel covariance can't see it. The taps
    are jittered by their own residual, the camera and the path are solved again, and the spread
    is what the marks leave unknown. None when half the re-solves fail: the marks don't pin the camera."""
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(CAL_SAMPLES):
        taps = np.asarray(stumps, float) + rng.normal(0.0, tap_sd, (8, 2))
        try:
            pose = solve_camera_pose(image_size=image_size, stump_quads_px=[tuple(p) for p in taps],
                                     pitch_length_m=length, pitch_width_m=width)
        except CalibrationError:
            continue
        r = reconstruct(pose, dets, rec.trajectory)
        p = predict_stump_plane(r) if r is not None else None
        if p is None:
            continue
        tr = r.trajectory
        rows.append((tr.y_b, tr.x_b, tr.position(t_last)[0][1], p.y, p.z, np.linalg.norm(tr.velocity(0.0))))
    return np.std(rows, axis=0) if len(rows) >= CAL_SAMPLES // 2 else None


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
    frames, times_ms, scale, cut = read_frames(str(video_path), start_ms=req.segment.start_ms, end_ms=req.segment.end_ms,
                                   sample_fps=req.tracking.sample_fps, max_frames=req.tracking.max_frames,
                                   warnings=warnings)
    height, width = frames[0].shape[:2]

    # ---- calibrate ----------------------------------------------------------
    report(30, "calibration")
    cal = req.calibration
    stumps = ([(p.x * width, p.y * height) for p in cal.stump_quads_norm] if cal.stump_quads_norm
              else [(p.x * scale, p.y * scale) for p in cal.stump_quads_px])
    pose = solve_camera_pose(image_size=(width, height), stump_quads_px=stumps,
                             pitch_length_m=cal.pitch_dimensions_m.length, pitch_width_m=cal.pitch_dimensions_m.width)
    reject = max(CALIB_REJECT_PX, CALIB_REJECT_FRAC * width)
    if pose.reproj_error_px > reject:
        raise CalibrationError(
            "The stump marks don't line up. Zoom in and re-mark the corners of both sets of stumps.")
    cam_x, cam_z = float(pose.centre_world[0]), float(pose.centre_world[2])
    # metres behind the nearer stumps; tapping both sets in one spot puts the phone 100 m back
    behind = max(-cam_x, cam_x - pose.pitch_length_m)
    if not (0.10 <= cam_z <= 5.0 and 0.0 < behind < 50.0):
        raise CalibrationError(
            "The stump marks put the phone somewhere it can't be. Mark the batter's stumps first, then the "
            "bowler's.")
    if pose.reproj_error_px > 8.0:
        warnings.append("the stump marks are a little off; re-marking them gives a surer call")
    # taps read left to right put the camera upright behind the bowler, so world +y is a right-hander's leg side
    leg_sign = -1.0 if req.batsman_handedness == "left" else 1.0
    _log.info("calibration ok: reproj=%.2fpx length=%.2fm cam=(%.2f,%.2f,%.2f) fx=%.0f",
              pose.reproj_error_px, pose.pitch_length_m, *pose.centre_world, pose.fx)

    result = {
        "image_size": {"width": width, "height": height},
        "calibration": {
            "pose": {"K": pose.K.tolist(), "R": pose.R.tolist(), "t": pose.t.tolist(),
                     "cam_center_world_m": pose.centre_world.tolist(),
                     "fx": pose.fx, "fy": pose.fy, "cx": pose.cx, "cy": pose.cy,
                     "pitch_length_m": pose.pitch_length_m, "pitch_width_m": pose.pitch_width_m,
                     "fov_deg": pose.fov_deg},
            "quality": {"reproj_error_px": pose.reproj_error_px, "notes": pose.notes},
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
    mask = corridor_mask(frames[0].shape, pose)
    tracks = []
    # the picked colour first; a wrong pick still finds a red or pink ball
    for colour in dict.fromkeys([req.tracking.ball_color, "red", "pink"]):
        detector = ColourMotionDetector(colour, mask)
        tracks.append(find_ball(pose, [(t, detector.detect(f)) for t, f in zip(times_ms, frames)]))
    track = max(filter(None, tracks), key=lambda tr: tr.score, default=None)
    report(55, "tracking")
    if track is None:
        warnings.append("no ball found; use a red or pink ball in good light, with the whole pitch in view")
        result["track"] = {"image_points": []}
        return finish()
    image_points = track.points
    result["track"] = {"image_points": image_points}
    # drawn even without a call, so the user sees what was followed
    result["overlay"] = build_overlay(pose=pose, trajectory=track.model, t0_ms=image_points[0]["t_ms"],
                                      image_points=image_points, predicted=np.empty((0, 4)), bounce_ms=None, impact_ms=None)
    # the clip or the frame cap ran out while the ball was still being followed, so where it ends isn't the impact
    if image_points[-1]["t_ms"] >= times_ms[-1] - 1000 * MAX_GAP_S:
        warnings.append("no call, as the ball was still in flight where the check stopped; " +
                        ("trim the clip to just the delivery" if cut else "keep a moment after the ball reaches the batter"))
        return finish()

    # ---- reconstruct ----------------------------------------------------------
    report(65, "reconstruction")
    t0_ms = image_points[0]["t_ms"]
    dets = [((p["t_ms"] - t0_ms) / 1000.0, p["u"], p["v"], max(0.05, p["confidence"]))
            for p in image_points]
    rec = reconstruct(pose, dets, track.model)
    if rec is None or rec.rms_px > MAX_FIT_RMS_PX:
        if rec is not None:
            result["diagnostics"]["fit_rms_px"] = rec.rms_px
        warnings.append("the ball's path doesn't match the stump marks; re-mark the stumps or try a clearer clip")
        return finish()
    tr = rec.trajectory
    if not tr.bounce_observed:
        warnings.append("no bounce seen, so the ball was treated as a full toss")

    # ---- predict and decide -----------------------------------------------------
    report(85, "lbw")
    t_last = dets[-1][0]
    pred = predict_stump_plane(rec)
    if pred is None:
        warnings.append("the ball's path couldn't be carried on to the stumps; try a clip where the ball stays in view up to the batter")
        return finish()
    spread = _calibration_spread(stumps, (width, height), cal.pitch_dimensions_m.length, cal.pitch_dimensions_m.width,
                                 max(pose.reproj_error_px, MIN_TAP_SD_PX), dets, rec, t_last)
    if spread is None:
        warnings.append("the stump marks aren't precise enough for a call; zoom in and re-mark the corners")
        return finish()
    cal_pitch_y, cal_bounce_x, cal_impact_y, cal_y, cal_z, cal_speed = (float(s) for s in spread)
    pred = replace(pred, sigma_y=math.hypot(pred.sigma_y, cal_y), sigma_z=math.hypot(pred.sigma_z, cal_z))
    sig_bx, sig_by = bounce_sigma(rec)
    sig_bx, sig_by = math.hypot(sig_bx, cal_bounce_x), math.hypot(sig_by, cal_pitch_y)
    sig_impact = math.hypot(position_sigma(rec, t_last)[1], cal_impact_y)
    # a singular fit leaves nan sigmas, which pass every band and would read as a sure call
    used = [pred.sigma_y, pred.sigma_z, sig_impact] + ([sig_by] if tr.bounce_observed else [])
    # once the 1-sigma miss is bigger than the stumps are tall, the path can't tell hitting from missing
    if not all(map(math.isfinite, used)) or math.hypot(pred.sigma_y, pred.sigma_z) > STUMP_HEIGHT_M:
        warnings.append("the ball's path is too unsure to call; re-mark the stumps or try a clearer clip")
        return finish()
    impact = tr.position(np.array([t_last]))[0]
    verdict = decide(leg_sign=leg_sign,
                     pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=sig_by,
                     impact_y=float(impact[1]), impact_sigma=sig_impact,
                     stump_y=pred.y, stump_z=pred.z, sigma_y=pred.sigma_y, sigma_z=pred.sigma_z,
                     k=UNCERTAINTY_K)
    predicted = sample_path(tr, t_last, pred.t, 24) if pred.t > t_last else np.empty((0, 4))
    confidence = max(0.20, min(0.95, 1.0 - (pred.sigma_y + pred.sigma_z) / 0.30))
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
        "prediction": {"y_at_stumps_m": pred.y, "z_at_stumps_m": pred.z,
                       "stump_x_m": 0.0, "confidence": confidence,
                       "sigma_y_m": pred.sigma_y, "sigma_z_m": pred.sigma_z,
                       "uncertainty_k": UNCERTAINTY_K},
    }
    result["overlay"] = build_overlay(pose=pose, trajectory=tr, t0_ms=int(t0_ms), image_points=image_points,
                                      predicted=predicted, bounce_ms=bounce_ms, impact_ms=impact_ms)
    speed = float(np.linalg.norm(v0))
    fit_speed_sd = speed_sigma(rec)
    # written so a nan spread hides the speed too
    speed_ok = math.hypot(fit_speed_sd, cal_speed) * 3.6 <= MAX_SPEED_SIGMA_KMH
    if not speed_ok:
        warnings.append("speed not shown, as the stump marks leave it unsure; zoom in and re-mark the corners"
                        if cal_speed > fit_speed_sd else
                        "speed not shown, as the ball was seen too briefly to time it; keep the bowler's hand in view")
    result["metrics"] = {
        "speed_kmh": round(speed * 3.6, 1) if speed_ok else None,
        "speed_mph": round(speed * 2.2369362921, 1) if speed_ok else None,
        # how far swing alone moved the ball sideways between the first sighting and the bounce, cm; null with no bounce seen
        "swing_cm": round(50.0 * abs(tr.swing) * tr.t_b ** 2, 1) if tr.bounce_observed else None,
        # the turn between the heading into the pitch and the heading off it
        "spin_deg": round(abs(math.degrees(math.atan2(float(tr.v_post[1]), abs(float(tr.v_post[0])))
                                           - math.atan2(float(tr.v_pre[1]), abs(float(tr.v_pre[0]))))), 1)
                    if tr.bounce_observed else None,
    }
    return finish()


def map_exception_to_api_error(exc: Exception) -> ApiError:
    if isinstance(exc, VideoDecodeError):
        return ApiError(code="VIDEO_DECODE_FAILED", message=str(exc))
    if isinstance(exc, CalibrationError):
        return ApiError(code="CALIBRATION_DEGENERATE", message=str(exc))
    # anything else is our bug, and its text would only show the user a traceback's last line
    return ApiError(code="INTERNAL_ERROR", message="Something went wrong checking this ball. Try again, or try another clip.")
