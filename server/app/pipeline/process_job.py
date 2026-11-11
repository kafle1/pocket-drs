"""One review job, end to end.

decode -> calibrate from the tapped marks -> line every frame up with the tapped one -> detect and
associate the ball -> reconstruct the delivery in metres -> predict the stump-plane crossing with
its uncertainty -> Law 36 verdict -> overlay and metrics for the client.

The result dict is the client contract:

    image_size       {width, height}
    calibration      {pose{K, R, t, cam_center_world_m, fx, fy, cx, cy, pitch_length_m, pitch_width_m,
                           stump_height_m, stump_width_m, fov_deg}, the sizes used being the ones the request stated,
                      quality{reproj_error_px, notes[], mark_residuals_px[{du, dv}] in the video's own pixels
                              in the order the marks were sent (null for a hidden mark), used_creases}}
    track            {image_points[{t_ms, u, v, radius_px, confidence}]}, the matched ball in time order, in the
                     tapped frame's pixels; the last point stands in for the impact
    world_trajectory {points_m[{t_ms, x, y, z, confidence}], predicted_to_stumps_m[...],
                      fit{x0, y0, z0, vx, vy, vz, rms_px, rms_m, notes[]}, model{...}}
    events           {bounce{t_ms, x_m, y_m, z_m, sigma_x_m, sigma_y_m}, impact{t_ms, x_m, y_m, z_m}}
    lbw              {verdict OUT | NOT_OUT | UMPIRES_CALL | CANT_TELL, confidence 0 to 1 (null unless OUT or
                      NOT_OUT), call_stands (the on-field call, with UMPIRES_CALL only), reason, leg_sign, tones,
                      checks{...}, prediction{y_at_stumps_m, z_at_stumps_m, stump_x_m, u_y_m, u_z_m, U95_y_m,
                      U95_z_m, sigma_fit_*, sigma_cal_*, calibrated}}; only verdict and confidence on a no call
                      made before the path was fitted
    no_call          {code, message, fix} when the verdict is CANT_TELL, else null
    overlay          pixel-space polylines and markers, see overlay.py
    metrics          {speed_kmh, speed_mph, spin_deg}, speed null when too uncertain to show,
                     spin null when no bounce was seen
    diagnostics      {warnings[], worst_mark (0 to 7, the stump mark furthest from the solved camera's view)}

The parts a no call never reached are null.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..models import ApiError, CreateJobRequest
from .calibration import CalibrationError, fitting_length, solve_camera_pose
from .decision import NOT_OUT, OUT, UMPIRES_CALL, decide
from .overlay import build_overlay
from .reconstruction import BALLS, sample_path, speed_sigma
from .tracking import ColourMotionDetector, YoloDetector, align, corridor_mask, drop_impossible, to_ref
from .trajectory import MAX_GAP_S, find_ball
from .uncertainty import GUARD_K, QTY, calibrated, calibration_sigma, camera_end, measurands, stability
from .video import NoCall, VideoDecodeError, read_frames

_log = logging.getLogger("pocket_drs.pipeline")

YOLO_WEIGHTS = Path(__file__).resolve().parents[2] / "models" / "cricket_ball.pt"
CANT_TELL = "CANT_TELL"
# a correct full-pitch tap calibration sits well under 10 px; the bound scales with frame width
CALIB_REJECT_PX, CALIB_REJECT_FRAC = 25.0, 0.03
MAX_IMPACT_X_M = 3.0      # in front of the batter's stumps; a long stride puts the front pad about 2.5 m out
REACHED_STUMPS_M = 0.15   # last seen this close to the stumps, the ball hit them or the keeper took it
EDGE_FRAC = 0.005         # a mark this close to the frame edge stands in for a stump base out of view
MAX_BEHIND_M = 10.0       # further back, zoomed in, the picture flattens the pitch and can't tell 2 m from 10 m
MAX_SPEED_SIGMA_KMH = 8.0           # a speed known no better than this is left out rather than shown wrong
# down the pitch a far or zoomed camera sees a metre as a few pixels, so the speed along it can be anything
MAX_VX_REL_SIGMA = 0.10
LENGTH_SIGMA_M = 0.5      # how far a typed pitch length may be off
MARK_BIAS_PX = 1.0        # a tap sits about this far off the true corner however carefully it's made
READOUT_S = 0.015         # a phone sensor reads its rows top to bottom over about this long
# colour finders tried when the trained finder sees nothing, for each ball type
COLOURS = {"leather": ("red", "pink"), "tennis": ("yellow",), "tape": ("yellow", "red")}
STRAIGHT_FILM = "Film from right behind the stumps with the phone held still, and keep the ball in view up to the batter."

ProgressFn = Callable[[int, str], None]


@dataclass(frozen=True)
class PipelineOutput:
    result: dict
    warnings: list[str]


def finite(obj):
    """JSON-safe copy: NaN and Inf become None, numpy scalars become Python numbers."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, np.generic):
        return finite(obj.item())
    if isinstance(obj, np.ndarray):
        return [finite(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {k: finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [finite(x) for x in obj]
    return obj


def _resolve(image_size: tuple[int, int], req, taps: np.ndarray, length_step: float = 0.0, fov_start: float | None = None):
    """The pose from 8 stump marks (NaN for a hidden one) then any crease marks, with the request's sizes."""
    st = req.calibration.stumps_m
    return solve_camera_pose(image_size=image_size, stump_quads_px=[None if np.isnan(p).any() else tuple(p) for p in taps[:8]],
                             crease_marks_px=[tuple(p) for p in taps[8:]] or None,
                             pitch_length_m=req.pitch_length_m + length_step, stump_height_m=st.height,
                             stump_width_m=st.width, fov_start=fov_start)


def _track(frames, times_ms, detector, pose, fps: float, maps, ball):
    """The ball one finder sees, its detections moved into the tapped frame by maps."""
    return find_ball(pose, [(t, drop_impossible(to_ref(detector.detect(f), H), pose, fps))
                            for t, f, H in zip(times_ms, frames, maps)], ball)


def detections(image_points: list[dict], height_px: int) -> list[tuple]:
    """(t_s from the first point, u, v, radius_px, weight) for the fit, each time moved on to when the
    sensor read the ball's row."""
    t0 = image_points[0]["t_ms"] / 1000.0
    return [(p["t_ms"] / 1000.0 - t0 + p["v"] / height_px * READOUT_S, p["u"], p["v"], p["radius_px"], max(0.05, p["confidence"]))
            for p in image_points]


def run_pipeline(*, video_path: Path, request_json: dict, artifacts_dir: Path,
                 progress: ProgressFn | None = None) -> PipelineOutput:
    req = CreateJobRequest.model_validate(request_json)
    warnings: list[str] = []
    result = {"image_size": None, "calibration": None, "track": None, "world_trajectory": None, "events": None,
              "lbw": None, "no_call": None, "overlay": None, "metrics": None,
              "diagnostics": {"warnings": warnings, "worst_mark": None}}
    try:
        _review(req, video_path, result, warnings, progress or (lambda pct, stage: None))
    except NoCall as e:
        result["lbw"] = {**(result["lbw"] or {}), "verdict": CANT_TELL, "confidence": None}
        result["no_call"] = {"code": e.code, "message": e.message, "fix": e.fix}
    return PipelineOutput(finite(result), warnings)


def _review(req, video_path: Path, result: dict, warnings: list[str], report: ProgressFn) -> None:
    """Fills result in place; raises NoCall at the first thing that rules a call out."""
    ball = BALLS[req.tracking.ball_type]
    if req.tracking.ball_type != "leather":
        warnings.append(f"{req.tracking.ball_type} ball calls are untested on real clips, so treat them as a guide")

    # ---- decode ------------------------------------------------------------
    report(5, "decode")
    cal = req.calibration
    frames, times_ms, ref, scale, cut = read_frames(str(video_path), start_ms=req.segment.start_ms, end_ms=req.segment.end_ms,
                                                    frame_ms=cal.frame_ms, capture_fps=req.capture_fps, warnings=warnings)
    height, width = frames[0].shape[:2]
    result["image_size"] = {"width": width, "height": height}

    # ---- calibrate ----------------------------------------------------------
    report(30, "calibration")
    taps = np.array([(np.nan, np.nan) if p is None else (p.x * width, p.y * height)
                     for p in [*cal.stump_quads_norm, *(cal.crease_marks_norm or [])]], dtype=float)
    edge = EDGE_FRAC * max(width, height)
    seen = taps[~np.isnan(taps).any(1)]
    if np.any((seen < edge) | (seen > np.array([width, height]) - edge)):
        raise CalibrationError("A mark sits on the edge of the picture, so those stumps may be cut off.",
                               "Film with both sets of stumps whole in view, then mark them again.")
    quads = taps[:8].reshape(2, 4, 2)
    lo, hi = np.nanmin(quads, 1), np.nanmax(quads, 1)
    mid = (lo + hi) / 2
    if np.all((mid[0] > lo[1]) & (mid[0] < hi[1])) or np.all((mid[1] > lo[0]) & (mid[1] < hi[0])):
        raise CalibrationError("Both sets of marks are on the same stumps.",
                               "Mark the batter's stumps and the bowler's; both ends must be in the picture.")
    resolve = partial(_resolve, (width, height), req)
    pose = resolve(taps)
    L = req.pitch_length_m
    # only the creases fix the length, so this is the one wrong setting the marks can point at
    fit = fitting_length((width, height), [None if np.isnan(p).any() else tuple(p) for p in taps[:8]],
                         [tuple(p) for p in taps[8:]], stump_height_m=cal.stumps_m.height,
                         stump_width_m=cal.stumps_m.width) if len(taps) > 8 and pose.reproj_error_px > 8.0 else None
    hint = (f"these marks fit a pitch of about {fit[0]:.0f} m, not the {L:.2f} m set; "
            f"if your pitch is {'shorter' if fit[0] < L else 'longer'}, set its length in settings"
            if fit and abs(fit[0] - L) > 1.0 and fit[1] < 0.5 * pose.reproj_error_px else None)
    res = pose.residuals_px / scale
    norms = np.hypot(res[:8, 0], res[:8, 1])
    result["diagnostics"]["worst_mark"] = int(np.nanargmax(norms))
    result["calibration"] = {
        "pose": {"K": pose.K.tolist(), "R": pose.R.tolist(), "t": pose.t.tolist(),
                 "cam_center_world_m": pose.centre_world.tolist(),
                 "fx": pose.fx, "fy": pose.fy, "cx": pose.cx, "cy": pose.cy,
                 "pitch_length_m": pose.pitch_length_m, "pitch_width_m": pose.pitch_width_m,
                 "stump_height_m": pose.stump_height_m, "stump_width_m": pose.stump_width_m,
                 "fov_deg": pose.fov_deg},
        # per mark, in the order sent: where the solved camera puts it minus where it was tapped
        "quality": {"reproj_error_px": pose.reproj_error_px, "notes": pose.notes,
                    "mark_residuals_px": [None if np.isnan(a) else {"du": float(a), "dv": float(b)} for a, b in res],
                    "used_creases": pose.used_creases},
    }
    if pose.reproj_error_px > max(CALIB_REJECT_PX, CALIB_REJECT_FRAC * width):
        raise CalibrationError(f"The marks don't line up{'; ' + hint if hint else ''}.",
                               f"Zoom in and mark again, starting with mark {result['diagnostics']['worst_mark'] + 1}, "
                               "and the crease ends if you marked them.")
    cam_x, cam_z = float(pose.centre_world[0]), float(pose.centre_world[2])
    # metres behind the nearer stumps; tapping both sets in one spot puts the phone 100 m back
    behind = max(-cam_x, cam_x - pose.pitch_length_m)
    if not (0.10 <= cam_z <= 5.0 and 0.0 < behind < 50.0):
        raise CalibrationError("The stump marks put the phone somewhere it can't be.",
                               "Mark the batter's stumps first, then the bowler's.")
    if hint:
        warnings.append(hint)
    elif pose.reproj_error_px > 8.0:
        warnings.append("the stump marks are a little off; re-marking them gives a surer call")
    if behind > MAX_BEHIND_M:
        raise NoCall("bad_marks", f"The phone was about {behind:.0f} m behind the stumps, too far to judge depth.",
                     "Stand right behind the bowler's stumps with the zoom off.")
    # taps read left to right put the camera upright behind the bowler, so world +y is a right-hander's leg side
    leg_sign = -1.0 if req.batsman_handedness == "left" else 1.0
    _log.info("calibration ok: reproj=%.2fpx length=%.2fm cam=(%.2f,%.2f,%.2f) fx=%.0f",
              pose.reproj_error_px, pose.pitch_length_m, *pose.centre_world, pose.fx)

    # ---- line up, detect and associate ----------------------------------------
    report(40, "tracking")
    maps = align(frames, ref)
    if maps is None:
        raise NoCall("camera_moved", "The phone moved while filming, so the marks no longer fit every frame.",
                     "Rest the phone on something or use a stand, and keep it still until the ball reaches the batter.")
    fps = 1000.0 / float(np.median(np.diff(times_ms))) if len(times_ms) > 1 else 0.0
    # the colour finders lean on background subtraction, so they need the frames already lined up
    lined = [f if H is None else cv2.warpPerspective(f, H, (width, height)) for f, H in zip(frames, maps)]
    mask = corridor_mask(frames[0].shape, pose)
    # every finder runs: the trained one alone followed a different ball on test5 and found none on test4
    tracks = [_track(frames, times_ms, YoloDetector(str(YOLO_WEIGHTS)), pose, fps, maps, ball)] + [
        _track(lined, times_ms, ColourMotionDetector(c, mask), pose, fps, [None] * len(lined), ball)
        for c in dict.fromkeys([c for c in [req.tracking.ball_color] if c] + list(COLOURS[req.tracking.ball_type]))]
    tracks = sorted(filter(None, tracks), key=lambda tr: tr.score, reverse=True)
    report(55, "tracking")
    if not tracks:
        result["track"] = {"image_points": []}
        # marks taken from behind the bowler but started on the near stumps read as a phone behind the batter
        raise NoCall("no_ball", f"No {req.tracking.ball_type} ball was found flying down the pitch.",
                     ("Mark the far stumps first, then the near ones. " if cam_x < 0 else "")
                     + f"Use a {'red or pink' if req.tracking.ball_type == 'leather' else 'bright yellow'} ball in good "
                     "light, with the whole pitch in view.")
    # the best-matched track whose 3-D fit holds; one that ran on past the pad onto a fielder doesn't
    fits = ((tr, measurands(pose, detections(tr.points, height), ball=ball, bounce=tr.model if tr.model.bounce_observed else None))
            for tr in tracks)
    track, meas = next(((tr, m) for tr, m in fits if m is not None), (tracks[0], None))
    image_points = track.points
    result["track"] = {"image_points": image_points}
    # drawn even without a call, so the user sees what was followed
    result["overlay"] = build_overlay(pose=pose, trajectory=track.model, t0_ms=image_points[0]["t_ms"],
                                      image_points=image_points, predicted=np.empty((0, 4)), bounce_ms=None, impact_ms=None)
    # the clip or the frame cap ran out while the ball was still being followed, so where it ends isn't the impact
    if image_points[-1]["t_ms"] >= times_ms[-1] - 1000 * MAX_GAP_S:
        raise NoCall("clip_cut", "The clip stops while the ball is still in flight.",
                     "Trim the clip to just the delivery." if cut else "Keep filming until the ball reaches the batter.")

    # ---- reconstruct ----------------------------------------------------------
    report(65, "reconstruction")
    t0_ms = image_points[0]["t_ms"]
    dets = detections(image_points, height)
    fit_kw = dict(ball=ball, bounce=track.model if track.model.bounce_observed else None)
    if meas is None:
        raise NoCall("implausible_fit", "The ball's path doesn't fit a real delivery with these stump marks.",
                     "Mark the stumps again, or try a clearer clip.")
    rec, pred, tr, impact, t_last = meas.rec, meas.pred, meas.rec.trajectory, meas.impact, meas.t_impact
    v0 = tr.velocity(0.0)
    speed = float(np.linalg.norm(v0))
    lo, hi = ball.speed_kmh
    if not lo <= speed * 3.6 <= hi:
        raise NoCall("implausible_fit", f"The fitted path has the ball at {speed * 3.6:.0f} km/h, which no bowler "
                     f"gives a {req.tracking.ball_type} ball, so the fit is wrong.", STRAIGHT_FILM)
    if not math.sqrt(max(float(rec.covariance[3, 3]), 0.0)) <= MAX_VX_REL_SIGMA * abs(float(tr.v_pre[0])):
        raise NoCall("range_too_wide", "From this view the ball's speed down the pitch can't be measured, so "
                     "where it ends up can't either.", STRAIGHT_FILM)
    if impact[0] > MAX_IMPACT_X_M:
        raise NoCall("implausible_fit", f"The ball was last seen {impact[0]:.1f} m in front of the stumps, too far "
                     "from the batter to place the impact.", STRAIGHT_FILM)
    if impact[0] < REACHED_STUMPS_M:
        wide = abs(impact[1]) - pose.stump_width_m / 2 > REACHED_STUMPS_M
        raise NoCall("ball_reached_stumps", f"The ball {'went past' if wide else 'reached'} the stumps "
                     f"({abs(impact[1]) * 100:.0f} cm from the middle one) without hitting the batter, so there's no lbw to judge.",
                     "Nothing to fix." if wide else "Nothing to fix: check the stumps for a bowled.")
    if not tr.bounce_observed and tr.t_b < t_last:
        raise NoCall("bounce_not_seen", "The ball must have bounced while it was hidden, so its path after the "
                     "bounce is a guess.", STRAIGHT_FILM)
    if pred is None:
        raise NoCall("range_too_wide", "The ball's path can't be carried on to the stumps.", STRAIGHT_FILM)

    # ---- predict and decide -----------------------------------------------------
    report(85, "lbw")
    sig_cal, _ = calibration_sigma(partial(resolve, fov_start=pose.fov_deg), taps, dets, meas, pose.tap_sigma_px,
                                   mark_bias_px=MARK_BIAS_PX, length_sigma_m=LENGTH_SIGMA_M, **fit_kw)
    variants = stability(pose, dets, meas, **fit_kw)
    # the refits' spread is model doubt the fit's own covariance doesn't see
    spread = {q: math.sqrt(np.mean([(m.values[q] - meas.values[q]) ** 2 for m in variants if m.values[q] is not None]
                                   or [0.0])) if meas.values[q] is not None else None for q in QTY}
    sig_fit = {q: None if s is None else math.hypot(meas.sigma_fit[q], s) for q, s in spread.items()}
    q = calibrated(camera_end(pose), leg_sign, meas.values, sig_fit, sig_cal, meas.x_b, tr.bounce_observed)
    # the pad is somewhere between the last seen point and the crease, so the ball's drift over that stretch is doubt too
    q["impact_y"]["sigma"] = math.hypot(q["impact_y"]["sigma"], abs(v0[1] / v0[0]) * max(impact[0] - 1.22, 0.0))
    # a refit's value carries the base's bias correction
    get = lambda k, m=meas: q[k]["value"] + m.values[k] - meas.values[k] if k in q and m.values[k] is not None else None

    def verdict(m=meas):
        return decide(leg_sign=leg_sign, pitch_y=get("pitch_y", m), pitch_sigma=q.get("pitch_y", {}).get("sigma"),
                      impact_y=get("impact_y", m), impact_sigma=q["impact_y"]["sigma"], stump_y=get("y", m),
                      stump_z=get("z", m), sigma_y=q["y"]["sigma"], sigma_z=q["z"]["sigma"], k=GUARD_K,
                      stump_half=pose.stump_width_m / 2, stump_height=pose.stump_height_m, ball_radius=ball.radius,
                      shot_played=req.shot_played)
    v = verdict()
    predicted = sample_path(tr, t_last, pred.t, 24) if pred.t > t_last else np.empty((0, 4))
    bounce_ms = t0_ms + tr.t_b * 1000.0 if tr.bounce_observed else None
    impact_ms = t0_ms + t_last * 1000.0
    world_points = tr.position(np.array([d[0] for d in dets]))
    result["world_trajectory"] = {
        "points_m": [{"t_ms": p["t_ms"], "x": float(w[0]), "y": float(w[1]), "z": float(max(w[2], 0.0)),
                      "confidence": float(p["confidence"])} for p, w in zip(image_points, world_points)],
        "predicted_to_stumps_m": [{"t_ms": t0_ms + t * 1000.0, "x": float(x), "y": float(y), "z": float(z)}
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
                   "z_m": ball.radius if tr.bounce_observed else None,
                   "sigma_x_m": math.sqrt(max(float(rec.covariance[1, 1]), 0.0)) if tr.bounce_observed else None,
                   "sigma_y_m": q["pitch_y"]["sigma"] if tr.bounce_observed else None},
        "impact": {"t_ms": impact_ms, "x_m": float(impact[0]), "y_m": float(impact[1]), "z_m": float(max(impact[2], 0.0))},
    }
    result["lbw"] = {
        "verdict": {OUT: "OUT", NOT_OUT: "NOT_OUT"}.get(v.decision, CANT_TELL),
        "confidence": v.p_out if v.decision == OUT else v.p_not_out if v.decision == NOT_OUT else None,
        "call_stands": None, "reason": v.reason, "leg_sign": leg_sign, "tones": v.tones,
        "checks": {"pitching_in_line": v.pitching_in_line, "impact_in_line": v.impact_in_line,
                   "wickets_hitting": v.wickets_hitting},
        # y and z have the rule's bias removed where it has one; u and U95 are the calibrated 68 and 95 % half-widths
        "prediction": {"y_at_stumps_m": get("y"), "z_at_stumps_m": get("z"), "stump_x_m": 0.0,
                       "u_y_m": q["y"]["u"], "u_z_m": q["z"]["u"], "U95_y_m": q["y"]["U95"], "U95_z_m": q["z"]["U95"],
                       "sigma_fit_y_m": sig_fit["y"], "sigma_fit_z_m": sig_fit["z"],
                       "sigma_cal_y_m": sig_cal["y"], "sigma_cal_z_m": sig_cal["z"], "calibrated": bool(tr.bounce_observed)},
    }
    result["overlay"] = build_overlay(pose=pose, trajectory=tr, t0_ms=t0_ms, image_points=image_points,
                                      predicted=predicted, bounce_ms=bounce_ms, impact_ms=impact_ms)
    speed_ok = speed_sigma(rec) * 3.6 <= MAX_SPEED_SIGMA_KMH       # written so a nan spread hides the speed too
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

    # ---- when the call can't stand -----------------------------------------------
    if not all(math.isfinite(q[k]["sigma"]) for k in q) or max(q["y"]["U95"], q["z"]["U95"]) > pose.stump_width_m / 2:
        raise NoCall("range_too_wide", "The ball's path at the stumps is known only to within "
                     f"{100 * max(q['y']['U95'], q['z']['U95']):.0f} cm, wider than half the stumps.", STRAIGHT_FILM)
    if not tr.bounce_observed:
        raise NoCall("bounce_not_seen", "The bounce wasn't seen, so the path can't be checked against real deliveries.",
                     "Keep the whole pitch in view so the bounce is filmed.")
    calls = {verdict(m).decision for m in variants} | {v.decision}
    if {OUT, NOT_OUT} <= calls:
        raise NoCall("call_unstable", "Small changes to the tracked points flip the call between out and not out.",
                     STRAIGHT_FILM)
    if v.decision == UMPIRES_CALL:
        if req.on_field_call == "none":
            raise NoCall("too_close", "The ball is too close to the edge to call either way.",
                         "Nothing to fix: with an on-field call set, that call stands.")
        result["lbw"].update(verdict="UMPIRES_CALL", call_stands=req.on_field_call.upper())


def map_exception_to_api_error(exc: Exception) -> ApiError:
    if isinstance(exc, VideoDecodeError):
        return ApiError(code="VIDEO_DECODE_FAILED", message=str(exc))
    # anything else is our bug, and its text would only show the user a traceback's last line
    return ApiError(code="INTERNAL_ERROR", message="Something went wrong checking this ball. Try again, or try another clip.")
