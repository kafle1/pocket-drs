"""One review job, end to end.

decode -> calibrate from the tapped marks -> detect and associate the ball -> reconstruct the
delivery in metres -> predict the stump-plane crossing with its uncertainty -> Law 36 verdict
-> overlay and metrics for the client.

The result dict is the client contract:

    image_size       {width, height}
    calibration      {pose{K, R, t, cam_center_world_m, fx, fy, cx, cy, pitch_length_m, pitch_width_m,
                           stump_height_m, stump_width_m, fov_deg}, the sizes used being the ones the request stated,
                      quality{reproj_error_px, notes[], mark_residuals_px[{du, dv}] in the video's own pixels
                              in the order the marks were sent, used_creases}}
    track            {image_points[{t_ms, u, v, radius_px, confidence}]}, the matched ball in time order;
                     the last point stands in for the impact
    world_trajectory {points_m[{t_ms, x, y, z, confidence}], predicted_to_stumps_m[...],
                      fit{x0, y0, z0, vx, vy, vz, rms_px, rms_m, notes[]}, model{...}}
    events           {bounce{t_ms, x_m, y_m, z_m, sigma_x_m, sigma_y_m}, impact{t_ms, x_m, y_m, z_m}}
    lbw              {decision, reason, leg_sign, tones, checks{...}, prediction{y_at_stumps_m, z_at_stumps_m,
                      stump_x_m, u_y_m, u_z_m, U95_y_m, U95_z_m, sigma_fit_*, sigma_cal_*, calibrated}}
    overlay          pixel-space polylines and markers, see overlay.py
    metrics          {speed_kmh, speed_mph, spin_deg}, speed null when too uncertain to show,
                     spin null when no bounce was seen
    diagnostics      {warnings[], fit_rms_px when the track was thrown out}

world_trajectory, events, lbw and metrics are null when no verdict could be given, and overlay
then holds only the tracked flight; diagnostics.warnings says why.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import ApiError, CreateJobRequest
from .calibration import CalibrationError, fitting_length, solve_camera_pose
from .decision import decide
from .overlay import build_overlay
from .reconstruction import BALL_RADIUS_M, sample_path, speed_sigma
from .tracking import ColourMotionDetector, YoloDetector, corridor_mask, drop_impossible
from .trajectory import MAX_GAP_S, find_ball
from .uncertainty import GUARD_K, calibrated, calibration_sigma, camera_end, measurands
from .video import VideoDecodeError, read_frames

_log = logging.getLogger("pocket_drs.pipeline")

YOLO_WEIGHTS = Path(__file__).resolve().parents[2] / "models" / "cricket_ball.pt"
# a correct full-pitch tap calibration sits well under 10 px; the bound scales with frame width
CALIB_REJECT_PX, CALIB_REJECT_FRAC = 25.0, 0.03
MAX_IMPACT_X_M = 3.0      # in front of the batter's stumps; a long stride puts the front pad about 2.5 m out
MAX_BEHIND_M = 10.0       # further back, zoomed in, the picture flattens the pitch and can't tell 2 m from 10 m
# a speed known no better than this is left out rather than shown wrong
MAX_SPEED_SIGMA_KMH = 8.0

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


def _resolve(image_size: tuple[int, int], cal, taps: np.ndarray):
    """The pose from 8 stump marks then any crease marks, with the request's dimensions."""
    return solve_camera_pose(image_size=image_size, stump_quads_px=[tuple(p) for p in taps[:8]],
                             crease_marks_px=[tuple(p) for p in taps[8:]] or None,
                             pitch_length_m=cal.pitch_dimensions_m.length, pitch_width_m=cal.pitch_dimensions_m.width,
                             stump_height_m=cal.stumps_m.height, stump_width_m=cal.stumps_m.width)


def _track(frames, times_ms, detector, pose, fps: float):
    return find_ball(pose, [(t, drop_impossible(detector.detect(f), pose, fps)) for t, f in zip(times_ms, frames)])


def detections(image_points: list[dict]) -> list[tuple]:
    """(t_s from the first point, u, v, radius_px, weight) for the fit."""
    return [((p["t_ms"] - image_points[0]["t_ms"]) / 1000.0, p["u"], p["v"], p["radius_px"], max(0.05, p["confidence"]))
            for p in image_points]


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
    marks = lambda norm, px: [(p.x * width, p.y * height) for p in norm] if norm else [(p.x * scale, p.y * scale) for p in px or []]
    taps = np.array(marks(cal.stump_quads_norm, cal.stump_quads_px) + marks(cal.crease_marks_norm, cal.crease_marks_px), dtype=float)
    pose = _resolve((width, height), cal, taps)
    L = cal.pitch_dimensions_m.length
    fit = fitting_length((width, height), [tuple(p) for p in taps[:8]], [tuple(p) for p in taps[8:]],
                         stump_height_m=cal.stumps_m.height, stump_width_m=cal.stumps_m.width) if len(taps) > 8 else None
    # only the creases fix the length, so this is the one wrong setting the marks can point at
    hint = (f"these marks fit a pitch of about {fit[0]:.1f} m, not the {L:.2f} m set; "
            f"if your pitch is {'shorter' if fit[0] < L else 'longer'}, set its length in settings"
            if fit and abs(fit[0] - L) > 1.0 and fit[1] < 0.5 * pose.reproj_error_px else None)
    reject = max(CALIB_REJECT_PX, CALIB_REJECT_FRAC * width)
    if pose.reproj_error_px > reject:
        raise CalibrationError(
            f"The marks don't line up{'; ' + hint if hint else ''}. Zoom in and re-mark the corners of both sets "
            "of stumps, and the crease ends if you marked them.")
    cam_x, cam_z = float(pose.centre_world[0]), float(pose.centre_world[2])
    # metres behind the nearer stumps; tapping both sets in one spot puts the phone 100 m back
    behind = max(-cam_x, cam_x - pose.pitch_length_m)
    if not (0.10 <= cam_z <= 5.0 and 0.0 < behind < 50.0):
        raise CalibrationError(
            "The stump marks put the phone somewhere it can't be. Mark the batter's stumps first, then the "
            "bowler's.")
    if hint:
        warnings.append(hint)
    elif pose.reproj_error_px > 8.0:
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
                     "stump_height_m": pose.stump_height_m, "stump_width_m": pose.stump_width_m,
                     "fov_deg": pose.fov_deg},
            # per mark, in the order sent: where the solved camera puts it minus where it was tapped
            "quality": {"reproj_error_px": pose.reproj_error_px, "notes": pose.notes,
                        "mark_residuals_px": [{"du": float(a), "dv": float(b)} for a, b in pose.residuals_px / scale],
                        "used_creases": pose.used_creases},
        },
        "track": None, "world_trajectory": None, "events": None, "lbw": None, "overlay": None, "metrics": None,
        "diagnostics": {"warnings": warnings},
    }

    def finish(no_call: str | None = None) -> PipelineOutput:
        if no_call:
            warnings.insert(0, no_call)   # both apps show the first warning as why there's no call
        clean = _finite(result)
        (artifacts_dir / "result_debug.json").write_text(json.dumps(clean, indent=2))
        return PipelineOutput(clean, warnings)

    if behind > MAX_BEHIND_M:
        return finish(f"no call, as the phone was about {behind:.0f} m behind the stumps; stand right behind the "
                      "bowler's stumps with the zoom off")

    # ---- detect and associate ------------------------------------------------
    report(40, "tracking")
    mask = corridor_mask(frames[0].shape, pose)
    fps = 1000.0 / float(np.median(np.diff(times_ms))) if len(times_ms) > 1 else 0.0
    # the learned detector, then the picked colour first; a wrong pick still finds a red or pink ball
    detectors = [YoloDetector(str(YOLO_WEIGHTS))] + [ColourMotionDetector(c, mask) for c in dict.fromkeys([req.tracking.ball_color, "red", "pink"])]
    tracks = [_track(frames, times_ms, d, pose, fps) for d in detectors]
    track = max(filter(None, tracks), key=lambda tr: tr.score, default=None)
    report(55, "tracking")
    if track is None:
        result["track"] = {"image_points": []}
        # marks taken from behind the bowler but started on the near stumps read as a phone behind the batter
        return finish("no ball found; use a red or pink ball in good light, with the whole pitch in view" +
                      ("; if you filmed from behind the bowler, mark the far stumps first" if cam_x < 0 else ""))
    image_points = track.points
    result["track"] = {"image_points": image_points}
    # drawn even without a call, so the user sees what was followed
    result["overlay"] = build_overlay(pose=pose, trajectory=track.model, t0_ms=image_points[0]["t_ms"],
                                      image_points=image_points, predicted=np.empty((0, 4)), bounce_ms=None, impact_ms=None)
    # the clip or the frame cap ran out while the ball was still being followed, so where it ends isn't the impact
    if image_points[-1]["t_ms"] >= times_ms[-1] - 1000 * MAX_GAP_S:
        return finish("no call, as the ball was still in flight where the check stopped; " +
                      ("trim the clip to just the delivery" if cut else "keep a moment after the ball reaches the batter"))

    # ---- reconstruct ----------------------------------------------------------
    report(65, "reconstruction")
    t0_ms = image_points[0]["t_ms"]
    dets = detections(image_points)
    meas = measurands(pose, dets)
    if meas is None:
        return finish("the ball's path doesn't match the stump marks; re-mark the stumps or try a clearer clip")
    rec, pred, tr, impact, t_last = meas.rec, meas.pred, meas.rec.trajectory, meas.impact, meas.t_impact
    if not tr.bounce_observed:
        warnings.append("no bounce seen, so the ball was treated as a full toss")

    # ---- predict and decide -----------------------------------------------------
    report(85, "lbw")
    if pred is None:
        return finish("the ball's path couldn't be carried on to the stumps; try a clip where the ball stays in view up to the batter")
    sig_cal, _ = calibration_sigma(partial(_resolve, (width, height), cal), taps, dets, meas, pose.tap_sigma_px)
    q = calibrated(camera_end(pose), leg_sign, meas.values, meas.sigma_fit, sig_cal, meas.x_b, tr.bounce_observed)
    used = [q["y"]["sigma"], q["z"]["sigma"], q["impact_y"]["sigma"]] + ([q["pitch_y"]["sigma"]] if tr.bounce_observed else [])
    # a perturbed solve that failed leaves an infinite sigma; once the miss is bigger than the stumps are tall,
    # the path can't tell hitting from missing
    if not all(map(math.isfinite, used)) or math.hypot(q["y"]["sigma"], q["z"]["sigma"]) > pose.stump_height_m:
        return finish("the ball's path is too unsure to call; re-mark the stumps or try a clearer clip")
    # the track ends where the ball was last seen; well short of the batter that's a lost ball, not the pad
    if impact[0] > MAX_IMPACT_X_M:
        return finish("no call, as the ball was lost before it reached the batter; film against a plain "
                      "background with the ball in view up to the pad")
    get = lambda k: q[k]["value"] if k in q else None
    verdict = decide(leg_sign=leg_sign, pitch_y=get("pitch_y"), pitch_sigma=q.get("pitch_y", {}).get("sigma"),
                     impact_y=get("impact_y"), impact_sigma=q["impact_y"]["sigma"],
                     stump_y=get("y"), stump_z=get("z"), sigma_y=q["y"]["sigma"], sigma_z=q["z"]["sigma"], k=GUARD_K,
                     stump_half=pose.stump_width_m / 2, stump_height=pose.stump_height_m)
    predicted = sample_path(tr, t_last, pred.t, 24) if pred.t > t_last else np.empty((0, 4))
    bounce_ms = round(t0_ms + tr.t_b * 1000.0) if tr.bounce_observed else None
    impact_ms = round(t0_ms + t_last * 1000.0)
    world_points = tr.position(np.array([d[0] for d in dets]))
    v0 = tr.velocity(0.0)

    result["world_trajectory"] = {
        "points_m": [{"t_ms": int(p["t_ms"]), "x": float(w[0]), "y": float(w[1]), "z": float(max(w[2], 0.0)),
                      "confidence": float(p["confidence"])} for p, w in zip(image_points, world_points)],
        "predicted_to_stumps_m": [{"t_ms": round(t0_ms + t * 1000.0), "x": float(x), "y": float(y), "z": float(z)}
                                  for t, x, y, z in predicted],
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
                   "sigma_x_m": math.sqrt(max(float(rec.covariance[1, 1]), 0.0)) if tr.bounce_observed else None,
                   "sigma_y_m": q["pitch_y"]["sigma"] if tr.bounce_observed else None},
        "impact": {"t_ms": impact_ms, "x_m": float(impact[0]), "y_m": float(impact[1]), "z_m": float(max(impact[2], 0.0))},
    }
    result["lbw"] = {
        "decision": verdict.decision, "reason": verdict.reason, "leg_sign": leg_sign, "tones": verdict.tones,
        "checks": {"pitching_in_line": verdict.pitching_in_line, "impact_in_line": verdict.impact_in_line,
                   "wickets_hitting": verdict.wickets_hitting},
        # y and z have the rule's bias removed where it has one; u and U95 are the calibrated 68 and 95 % half-widths
        "prediction": {"y_at_stumps_m": get("y"), "z_at_stumps_m": get("z"), "stump_x_m": 0.0,
                       "u_y_m": q["y"]["u"], "u_z_m": q["z"]["u"], "U95_y_m": q["y"]["U95"], "U95_z_m": q["z"]["U95"],
                       "sigma_fit_y_m": meas.sigma_fit["y"], "sigma_fit_z_m": meas.sigma_fit["z"],
                       "sigma_cal_y_m": sig_cal["y"], "sigma_cal_z_m": sig_cal["z"], "calibrated": bool(tr.bounce_observed)},
    }
    result["overlay"] = build_overlay(pose=pose, trajectory=tr, t0_ms=int(t0_ms), image_points=image_points,
                                      predicted=predicted, bounce_ms=bounce_ms, impact_ms=impact_ms)
    speed = float(np.linalg.norm(v0))
    # written so a nan spread hides the speed too
    speed_ok = speed_sigma(rec) * 3.6 <= MAX_SPEED_SIGMA_KMH
    if not speed_ok:
        warnings.append("speed not shown, as the ball was seen too briefly to time it; keep the bowler's hand in view")
    result["metrics"] = {
        "speed_kmh": round(speed * 3.6, 1) if speed_ok else None,
        "speed_mph": round(speed * 2.2369362921, 1) if speed_ok else None,
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
