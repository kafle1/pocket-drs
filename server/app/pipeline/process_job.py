"""End-to-end cricket DRS pipeline.

Decode → detect ball candidates → cluster into a trajectory → recover camera
pose via PnP → reconstruct 3D ball trajectory in world coordinates →
LBW decision based on the 3D trajectory.

Output schema (consumed by the Flutter client):

    {
      "video":            {duration_ms, fps},
      "image_size":       {width, height},
      "calibration": {
        "mode":           "taps",
        "pose":           {K, rvec, tvec, cam_center_world_m},
        "quality":        {reproj_error_px, score, notes}
      },
      "track": {
        "image_points":   [{t_ms, u, v, radius_px, confidence}, ...],
        "candidates_total": int,
        "inliers":          int,
        "rms_px":           float
      },
      "world_trajectory": {
        "points_m":             [{t_ms, x, y, z, confidence}, ...],
        "predicted_to_stumps_m":[{t_ms, x, y, z}, ...],
        "fit":                  {x0, y0, z0, vx, vy, vz, bounce_t_ms, rms_m}
      },
      "events": {
        "bounce":  {t_ms, x_m, y_m},
        "impact":  {t_ms, x_m, y_m, z_m}
      },
      "lbw": {
        "decision":   "out" | "not_out" | "umpires_call",
        "reason":     str,
        "checks":     {pitching_in_line, impact_in_line, wickets_hitting},
        "prediction": {y_at_stumps_m, z_at_stumps_m, stump_x_m, confidence}
      },
      "diagnostics": {warnings: [str], log_id}
    }
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
from .calibration import CalibrationError
from .reconstruction import (
    BALL_RADIUS_M,
    DEFAULT_STUMP_HEIGHT_M,
    GRAVITY_MS2,
    Reconstruction,
    backproject_to_ground,
    build_overlay_px,
    predict_path_to_stumps,
    reconstruct_trajectory,
    solve_camera_pose_from_stumps,
)
from .tracking import CombinedBallDetector, YoloBallDetector, build_pitch_roi_mask
from .trajectory import find_ball_trajectory
from .video import VideoDecodeError, VideoReader


_log = logging.getLogger("pocket_drs.pipeline")

# Cricket constants.
WICKET_HALF_WIDTH_M = 0.2286 / 2.0      # one stump line is ±wicket_half_width from centre
WICKET_GUARD_M = WICKET_HALF_WIDTH_M + BALL_RADIUS_M
UMPIRES_CALL_BAND_M = 0.050             # ±50 mm on the edge → umpire's call

# Calibration is rejected above this reprojection error. The fractional bound
# (~3% of frame width, ≈32 px on 1080p) keeps it resolution-independent; the
# absolute floor guards very small frames. A correct full-pitch tap calibration
# sits well under 10 px, so this only trips on broken/mismatched corners.
CALIB_REJECT_REPROJ_PX = 25.0
CALIB_REJECT_REPROJ_FRAC = 0.03

# A trustworthy projectile reconstruction sits well under this world-space RMS.
# Synthetic footage fits to ~0.02-0.22 m; real handheld clips carry more
# depth-from-size noise and land around 0.5-0.9 m even when correct, so the
# bound gives real footage headroom while still firmly rejecting clutter fits
# (which run several metres). Below this the fit is trusted with no caveat.
# Between this and MAX_FIT_RMS_M_HARD (scaled to the trajectory's own span)
# the fit is still used but flagged low-confidence — a delivery shot more
# end-on (ball moving along the camera axis) reconstructs looser because
# monocular depth is noisier there, and refusing it outright is worse than a
# best-effort tracked result with a warning. Above the hard ceiling the 3D
# path does not explain the observations, so we discard it.
MAX_FIT_RMS_M = 1.0
MAX_FIT_RMS_M_HARD = 2.0
# Fraction of the trajectory's down-pitch span allowed as fit RMS before the
# hard ceiling. 0.14 passes a ~12 m end-on net delivery at ~1.3 m RMS while a
# ~5 m synthetic/clean arc stays bound at the 1.0 m floor.
FIT_RMS_SPAN_FRAC = 0.14


ProgressFn = Callable[[int, str], None]


def _default_yolo_weights() -> str | None:
    """Bundled cricket-ball YOLO weights, if present (server/models/…)."""
    p = Path(__file__).resolve().parents[2] / "models" / "cricket_ball.pt"
    return str(p) if p.exists() else None


def _progress(fn: ProgressFn | None, pct: int, stage: str) -> None:
    if fn is not None:
        fn(int(max(0, min(100, pct))), stage)


def _rotate_frame(frame: np.ndarray, rotation_deg: int) -> np.ndarray:
    r = int(rotation_deg) % 360
    if r == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if r == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if r == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


@dataclass(frozen=True)
class PipelineOutput:
    result: dict
    warnings: list[str]


def _decode_pitch_corners(req: dict, frame_width: int, frame_height: int) -> list[tuple[float, float]] | None:
    pts_px = req.get("pitch_corners_px")
    pts_norm = req.get("pitch_corners_norm")
    if pts_px and len(pts_px) == 4:
        return [(float(p["x"]), float(p["y"])) for p in pts_px]
    if pts_norm and len(pts_norm) == 4:
        return [(float(p["x"]) * frame_width, float(p["y"]) * frame_height) for p in pts_norm]
    return None


def _decode_point_list(
    req: dict, key_px: str, key_norm: str,
    frame_width: int, frame_height: int,
    allowed_counts: tuple[int, ...],
) -> list[tuple[float, float]] | None:
    pts_px = req.get(key_px)
    pts_norm = req.get(key_norm)
    if pts_px and len(pts_px) in allowed_counts:
        return [(float(p["x"]), float(p["y"])) for p in pts_px]
    if pts_norm and len(pts_norm) in allowed_counts:
        return [(float(p["x"]) * frame_width, float(p["y"]) * frame_height) for p in pts_norm]
    return None


def _decode_stump_quads(req: dict, frame_width: int, frame_height: int) -> list[tuple[float, float]] | None:
    """Decode the 8-point stump-rectangle schema.

    ``stump_quads_norm``/``stump_quads_px`` is a flat list of 8 image points
    in fixed order: [striker_TL, striker_TR, striker_BR, striker_BL,
    bowler_TL, bowler_TR, bowler_BR, bowler_BL] — the bounding rectangle of
    each end's three-stump cluster. The top pair lives at z=stump_height,
    the bottom pair at z=0, lateral spread ±(STUMP_LATERAL_DX + ball
    radius) ≈ 0.132 m.
    """
    return _decode_point_list(
        req, "stump_quads_px", "stump_quads_norm",
        frame_width, frame_height, allowed_counts=(8,),
    )


def _decide_lbw(
    *,
    bounce: tuple[float, float, float] | None,
    impact: tuple[float, float, float] | None,
    pred_y_at_stumps: float | None,
    pred_z_at_stumps: float | None,
    stump_x_m: float,
    fit_rms_m: float,
) -> dict:
    """ICC-Rule-36-flavoured LBW decision from a real 3D reconstruction.

    Conventions: world Y centred on stump line.  ±WICKET_HALF_WIDTH is the
    stump width; +BALL_RADIUS_M each side is the ball-touching tolerance.
    """
    checks = {"pitching_in_line": True, "impact_in_line": True, "wickets_hitting": False}
    reason_parts: list[str] = []

    if bounce is not None:
        bx, by, _ = bounce
        # Pitched in line: |y| within ~stump-half-width + 1 stump (one full stump leg-side margin).
        # The "leg-stump line" rule allows ball pitching up to one stump width outside leg.
        leg_line_limit = WICKET_HALF_WIDTH_M + 0.1143  # one stump width outside leg
        if abs(by) > leg_line_limit:
            checks["pitching_in_line"] = False
            reason_parts.append(f"Pitched outside leg ({by*100:+.1f}cm)")

    if impact is not None:
        ix, iy, iz = impact
        # Impact in line: must be within stump line + ball radius on the off side
        # (leg side allowed wider per laws — ignored here).
        if iy > WICKET_GUARD_M + 0.05:
            checks["impact_in_line"] = False
            reason_parts.append(f"Impact outside off ({iy*100:+.1f}cm)")

    # Monocular depth-from-size on phone footage is precise to roughly
    # ±5 cm in Y at the stump plane and ±15 cm in Z. We widen the umpire's-
    # call margin in the vertical dimension to reflect that the system is
    # less confident about ball height than ball line, even though the same
    # physical "more than half the ball" rule applies in both.
    # Cricket DRS umpire's-call bands. Monocular Z noise is typically
    # ~2x the Y noise (ball moves along the camera axis so the radial
    # component is harder to resolve than the lateral one), so the Z band
    # is widened to one ball-diameter while Y stays at one ball-radius.
    MARGIN_Y_UMP = BALL_RADIUS_M           # 3.6 cm
    MARGIN_Z_UMP = 2.0 * BALL_RADIUS_M     # 7.2 cm

    decision = "not_out"
    margin_text = ""
    if pred_y_at_stumps is not None and pred_z_at_stumps is not None:
        hits_horizontal = abs(pred_y_at_stumps) <= WICKET_GUARD_M
        hits_vertical = 0.0 <= pred_z_at_stumps <= DEFAULT_STUMP_HEIGHT_M + BALL_RADIUS_M
        if hits_horizontal and hits_vertical:
            checks["wickets_hitting"] = True
            margin_y = WICKET_GUARD_M - abs(pred_y_at_stumps)
            margin_z_top = (DEFAULT_STUMP_HEIGHT_M + BALL_RADIUS_M) - pred_z_at_stumps
            margin_z_bot = pred_z_at_stumps
            # Per-axis umpire's-call bands; the tightest axis decides.
            in_y_band = margin_y <= MARGIN_Y_UMP
            in_z_band = (margin_z_top <= MARGIN_Z_UMP) or (margin_z_bot <= MARGIN_Z_UMP)
            margin = min(margin_y, margin_z_top, margin_z_bot)
            if in_y_band or in_z_band:
                margin_text = f" (margin {margin*100:.1f}cm umpires_band)"
            else:
                margin_text = f" (margin {margin*100:.1f}cm)"
        else:
            # Umpire's-call band on the *outside* of the stumps. Only the
            # axis that actually misses contributes a positive "outside"
            # distance; the well-inside axes are not part of the margin.
            candidates: list[float] = []
            if not hits_horizontal:
                candidates.append(abs(pred_y_at_stumps) - WICKET_GUARD_M)
            if not hits_vertical:
                if pred_z_at_stumps > DEFAULT_STUMP_HEIGHT_M + BALL_RADIUS_M:
                    candidates.append(pred_z_at_stumps - (DEFAULT_STUMP_HEIGHT_M + BALL_RADIUS_M))
                elif pred_z_at_stumps < 0.0:
                    candidates.append(-pred_z_at_stumps)
            min_outside = min(candidates) if candidates else 0.0
            if 0.0 < min_outside <= UMPIRES_CALL_BAND_M:
                margin_text = f" (just missing — {min_outside*100:.1f}cm)"

    if all(checks.values()):
        if margin_text and "umpires_band" in margin_text:
            decision = "umpires_call"
            reason_parts.append(f"Umpire's call — clipping{margin_text}")
        elif margin_text:
            decision = "out"
            reason_parts.append(f"Hitting stumps{margin_text}")
        else:
            decision = "out"
            reason_parts.append("Hitting stumps")
    else:
        if not reason_parts:
            reason_parts.append("Missing stumps")
        if margin_text and "just missing" in margin_text:
            decision = "umpires_call"
            reason_parts[-1] = "Umpire's call" + margin_text

    confidence = float(max(0.20, min(0.95, 1.0 - fit_rms_m * 1.5)))
    return {
        "decision": decision,
        "reason": " · ".join(reason_parts),
        "checks": checks,
        "prediction": {
            "y_at_stumps_m": float(pred_y_at_stumps) if pred_y_at_stumps is not None else None,
            "z_at_stumps_m": float(pred_z_at_stumps) if pred_z_at_stumps is not None else None,
            "stump_x_m": float(stump_x_m),
            "confidence": confidence,
        },
    }


def _extend_track_to_direction_change(
    detections_per_frame,
    fit_points,
    *,
    min_conf: float = 0.4,
    max_step_px_per_17ms: float = 130.0,
    min_step_px: float = 5.0,
    reversal_frames: int = 2,
) -> list[dict]:
    """Continue the ball track past the RANSAC fit until the ball changes
    direction.

    The 2-pass RANSAC keeps one smooth projectile arc — a clean delivery — as
    its inlier set. On real footage the detector still sees the ball for many
    frames past that arc (between the last fit point and the bat impact, and
    sometimes past it). We walk those frames forward with nearest-neighbour
    association, keeping the same proximity / step bounds that the post-impact
    helper used to use, but stop as soon as the ball's motion *reverses
    relative to its dominant direction*. ``reversal_frames`` consecutive
    reversed steps confirm a bat / pad interception so a single noisy frame
    does not cut the track short.

    Returns the extra frames (image-space) to append after ``fit_points``.
    """
    if len(fit_points) < 2:
        return []
    # Dominant direction from the tail of the fit so we are comparing against
    # the ball's actual motion at the end of the delivery, not the release.
    tail = fit_points[-min(4, len(fit_points)):]
    ref_du = float(tail[-1].x_px - tail[0].x_px)
    ref_dv = float(tail[-1].y_px - tail[0].y_px)
    if abs(ref_du) + abs(ref_dv) < 1.0:
        return []

    prev_t = float(fit_points[-1].t_ms)
    prev_u = float(fit_points[-1].x_px)
    prev_v = float(fit_points[-1].y_px)
    out: list[dict] = []
    reversed_run = 0

    for t_ms, cands in detections_per_frame:
        if t_ms <= prev_t:
            continue
        ball_cands = [
            c for c in cands
            if float(c.get("confidence", 0.0)) >= min_conf
            and c.get("source") == "yolo"
        ]
        if not ball_cands:
            continue
        dt = max(1.0, float(t_ms) - prev_t)
        max_step = max_step_px_per_17ms * (dt / 17.0)
        accepted: list[tuple[float, dict]] = []
        for c in ball_cands:
            d = math.hypot(float(c["x"]) - prev_u, float(c["y"]) - prev_v)
            if d < min_step_px or d > max_step:
                continue
            accepted.append((float(c["confidence"]), c))
        if not accepted:
            continue
        accepted.sort(reverse=True)
        best = accepted[0][1]
        du = float(best["x"]) - prev_u
        dv = float(best["y"]) - prev_v
        dot = du * ref_du + dv * ref_dv
        if dot < 0.0:
            reversed_run += 1
            if reversed_run >= reversal_frames:
                # Direction change confirmed — drop the reversed steps and stop.
                if reversed_run > 1:
                    out = out[: -(reversed_run - 1)]
                break
        else:
            reversed_run = 0
        out.append({
            "t_ms": int(t_ms),
            "u": float(best["x"]),
            "v": float(best["y"]),
            "radius_px": float(best.get("radius_px", 0.0)),
            "confidence": float(best["confidence"]),
        })
        prev_t = float(t_ms)
        prev_u = float(best["x"])
        prev_v = float(best["y"])
    return out


def _find_image_v_peak(points, *, min_post_frames: int = 2) -> int | None:
    """Index of the image-v peak that signals a real ground contact.

    A genuine bounce on the pitch is the only event that flips the ball's
    vertical image motion (downward → upward) while horizontal travel keeps
    its sign. We pick the last frame whose v is strictly greater than both
    its neighbours and whose post-peak descent is sustained for at least
    ``min_post_frames`` more frames so an end-of-clip detection drop-out
    does not masquerade as a bounce.
    """
    n = len(points)
    if n < 4 + min_post_frames:
        return None
    vs = [float(p.y_px) for p in points]
    peak_idx: int | None = None
    for i in range(1, n - 1):
        if not (vs[i] - vs[i - 1] > 1.0 and vs[i] - vs[i + 1] > 1.0):
            continue
        # Require sustained post-peak rise to reject noise.
        post_ok = True
        for k in range(1, min_post_frames + 1):
            if i + k >= n or vs[i + k] >= vs[i]:
                post_ok = False
                break
        if post_ok:
            peak_idx = i
    return peak_idx


def _detect_impact_frame(points) -> int | None:
    """Index of the bat/pad impact — where the ball hits something and changes
    direction — or None if it travels cleanly through to the stumps.

    The impact is a discontinuity in the ball's *horizontal* image motion: when
    it is intercepted, its left/right travel either collapses (it drops or rolls
    off the pad) or reverses (edged / played back). A bounce is deliberately NOT
    flagged here — a bounce flips only the vertical motion while the ball keeps
    its horizontal travel — so this cleanly separates "pitched" from "hit". The
    returned index is the last point still part of the live delivery; callers
    track up to it and predict beyond it. Returns None for a near-axial view
    where horizontal motion is too small to judge (falls back to stump-plane).
    """
    n = len(points)
    if n < 8:
        return None
    t = np.array([p.t_ms for p in points], dtype=float)
    u = np.array([p.x_px for p in points], dtype=float)
    dt = np.diff(t)
    dt[dt == 0] = 1.0
    du = np.diff(u) / dt  # horizontal image velocity (px/ms)
    med = float(np.median(np.abs(du)))
    if med < 0.02:
        return None
    sgn = np.sign(np.median(du))
    if sgn == 0:
        return None
    start = max(2, int(0.4 * n))
    for i in range(start, len(du) - 1):
        # A sustained reversal of horizontal travel — the ball never turns
        # round in the air unless it hit bat or pad. (A bounce flips only the
        # vertical motion, so it never trips this.) Natural perspective slow-down
        # only shrinks |du|, it does not flip the sign, so clean deliveries that
        # carry through to the stumps are left untouched.
        if (np.sign(du[i]) == -sgn and abs(du[i]) > 0.5 * med
                and np.sign(du[i + 1]) == -sgn):
            return i
    return None


def _compute_metrics(
    fit,
    *,
    image_points: list[dict] | None = None,
    world_points: list | None = None,
    bounce_index: int | None = None,
) -> dict:
    """Broadcast delivery metrics — Speed, Swing, Spin — from the fit + track.

    * Speed  — release speed |v0| (km/h + mph). Accuracy follows the
      calibrated scale; stump-anchored PnP lands within a few percent.
    * Swing  — the ball's sideways (across-pitch) movement in the air before it
      pitches, in centimetres: the change in world Y from release to the bounce
      point. (Measured on the ground plane so it is true lateral movement, not
      the in-image gravity sag.)
    * Spin   — the lateral angle the ball travels off the straight line down
      the pitch (drift / turn), in degrees, from the fitted velocity.
    """
    speed_ms = math.sqrt(fit.vx ** 2 + fit.vy ** 2 + fit.vz ** 2)
    spin_deg = (
        abs(math.degrees(math.atan2(fit.vy, abs(fit.vx))))
        if abs(fit.vx) > 1e-3 else 0.0
    )

    swing_cm = 0.0
    try:
        if world_points and len(world_points) >= 3:
            n = len(world_points)
            bi = bounce_index if (bounce_index is not None and 1 < bounce_index < n) else n - 1
            swing_cm = abs(float(world_points[bi].y_m) - float(world_points[0].y_m)) * 100.0
    except Exception:  # noqa: BLE001 — metric is best-effort, never fatal
        swing_cm = 0.0

    return {
        "speed_kmh": round(max(0.0, speed_ms * 3.6), 1),
        "speed_mph": round(max(0.0, speed_ms * 2.2369362921), 1),
        "swing_sf": round(max(0.0, swing_cm), 1),   # sideways air movement (cm)
        "spin_deg": round(max(0.0, spin_deg), 1),   # drift/turn off straight (deg)
    }


def _require_int(d: dict, key: str, label: str) -> int:
    """Read a required integer field, raising a clean ValueError (mapped to
    INVALID_REQUEST) for missing, null, or non-numeric values rather than
    leaking a KeyError/TypeError as an INTERNAL_ERROR."""
    value = d.get(key)
    if value is None:
        raise ValueError(f"{label} is required")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer")


def run_pipeline(
    *,
    video_path: Path,
    request_json: dict,
    artifacts_dir: Path,
    progress: ProgressFn | None = None,
) -> PipelineOutput:
    warnings: list[str] = []
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    if not isinstance(request_json, dict):
        raise ValueError("request body must be a JSON object")

    seg = request_json.get("segment")
    if not isinstance(seg, dict):
        raise ValueError("segment is required")
    start_ms = _require_int(seg, "start_ms", "segment.start_ms")
    end_ms = _require_int(seg, "end_ms", "segment.end_ms")
    if end_ms <= start_ms:
        raise ValueError("Invalid segment: end_ms must be greater than start_ms")

    track_req = request_json.get("tracking") or {}
    sample_fps = _require_int(track_req, "sample_fps", "tracking.sample_fps") if track_req.get("sample_fps") is not None else 30
    max_frames = _require_int(track_req, "max_frames", "tracking.max_frames") if track_req.get("max_frames") is not None else 180
    if sample_fps < 1:
        raise ValueError("tracking.sample_fps must be >= 1")
    if max_frames < 1:
        raise ValueError("tracking.max_frames must be >= 1")
    ball_color = str(track_req.get("ball_color") or "red")

    rotation_deg = int(((request_json.get("video") or {}).get("rotation_deg")) or 0)

    cal_req = request_json.get("calibration") or {}
    if cal_req.get("mode") != "taps":
        raise ValueError("calibration.mode must be 'taps' (only mode currently supported)")
    dims = cal_req.get("pitch_dimensions_m") or {}
    try:
        pitch_width_m = float(dims.get("width"))
    except (TypeError, ValueError):
        raise ValueError("calibration.pitch_dimensions_m.width required")
    # Length is optional. When the caller pins it (a known regulation 20.12 m
    # match pitch) it becomes the authoritative scale the pose is built around.
    # When omitted we geometry-fit it from the stump marks, so non-regulation
    # indoor / practice nets (test4/test5 are far shorter than 20.12 m)
    # calibrate to their real length instead of being forced to 20.12 m — which
    # over-constrains the pose and spikes the reprojection error (test4 jumps
    # from ~4 px geometry-fit to 45 px when forced to 20.12 m + a pinned FOV).
    # NOTE: monocular scale from taps alone is weakly observable (the
    # FOV x length trade-off is near-degenerate), so for the most accurate
    # absolute scale on a known full pitch the client should still pin length.
    length_raw = dims.get("length")
    if length_raw is None:
        pitch_length_m = 0.0  # signal "let the solver geometry-fit the length"
    else:
        try:
            pitch_length_m = float(length_raw)
        except (TypeError, ValueError):
            raise ValueError("calibration.pitch_dimensions_m.length must be numeric")
    if pitch_width_m <= 0.0 or pitch_length_m < 0.0:
        raise ValueError("calibration.pitch_dimensions_m must be positive")

    # ----------------------------- decode -----------------------------
    _progress(progress, 5, "decode")
    with VideoReader(str(video_path)) as reader:
        meta = reader.meta
        if meta.duration_ms and start_ms >= meta.duration_ms:
            raise ValueError("Segment starts after video end")

        dt_ms = max(1, int(round(1000 / max(1, sample_fps))))
        # Never sample past the real end of the video. `frame_at_ms` clamps an
        # out-of-range time to the last frame, so requesting beyond the duration
        # (the app sends a wide end_ms to mean "the whole clip") would feed the
        # tracker duplicate frozen frames — static clutter that survives near
        # the end and corrupts the bounce/impact fit (the ball appears to stop
        # being tracked after the pitch). Cap sampling at the actual duration.
        end_cap = end_ms
        if meta.duration_ms and meta.duration_ms > 0:
            end_cap = min(end_ms, meta.duration_ms - 1)
        times_ms: list[int] = []
        t = start_ms
        while t <= end_cap and len(times_ms) < max_frames:
            times_ms.append(int(t))
            t += dt_ms

        frames: list[np.ndarray] = []
        for i, t_ms in enumerate(times_ms):
            try:
                f = reader.frame_at_ms(t_ms)
            except VideoDecodeError as e:
                # Sustained decode failure means the file is truncated past
                # this point (metadata over-reports the frame count). Analyse
                # the frames we actually have rather than padding with stale
                # duplicates or aborting outright.
                if frames:
                    warnings.append(
                        f"Video truncated: analysing {len(frames)} of "
                        f"{len(times_ms)} requested frames ({e})"
                    )
                    break
                raise
            f = _rotate_frame(f, rotation_deg)
            frames.append(f)
            if i and (i % max(1, len(times_ms) // 10) == 0):
                _progress(progress, 5 + int(20 * (i / max(1, len(times_ms) - 1))), "decode")

        height, width = frames[0].shape[:2]
        try:
            cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])
        except Exception:
            pass

    # ----------------------------- calibrate (PnP) -----------------------------
    _progress(progress, 30, "calibration")

    pitch_corners_px = _decode_pitch_corners(cal_req, width, height)
    if pitch_corners_px is None:
        raise ValueError("calibration.pitch_corners_px or .pitch_corners_norm required")
    stump_quads_px = _decode_stump_quads(cal_req, width, height)
    if stump_quads_px is None:
        raise ValueError(
            "calibration.stump_quads_px or .stump_quads_norm "
            "(8 points: striker TL/TR/BR/BL then bowler TL/TR/BR/BL) is required"
        )

    # Camera horizontal FOV — optional override. When the caller does not
    # supply one (the usual case from the app), the calibration solver
    # auto-fits FOV jointly with pitch length from the stump marks, so a
    # zoomed phone shot does not get rejected for "high reprojection".
    _fov_raw = cal_req.get("h_fov_deg")
    h_fov_deg = float(_fov_raw) if _fov_raw not in (None, "", 0) else None

    # Stump-anchored calibration. The 8 tapped stump rectangle corners +
    # 4 pitch turf corners feed a joint PnP that jointly auto-fits the
    # camera FOV and the pitch length when the caller doesn't pin them.
    pose, pitch_length_m = solve_camera_pose_from_stumps(
        image_size=(width, height),
        stump_quads_px=stump_quads_px,
        pitch_corners_px=(
            pitch_corners_px if pitch_corners_px and len(pitch_corners_px) == 4
            else None
        ),
        pitch_width_m=pitch_width_m,
        h_fov_deg=h_fov_deg,
        known_length_m=pitch_length_m if pitch_length_m > 0.0 else None,
    )

    # Hard reject a calibration whose marks cannot form a consistent
    # perspective view. The marks always admit an exact 2D homography but
    # only a geometrically valid set yields a low PnP reprojection error;
    # a large error means the recovered pose is meaningless. Proceeding
    # would emit a confident-but-wrong 3D reconstruction, so we stop here.
    # The bound scales with frame width to stay resolution-independent.
    reject_px = max(CALIB_REJECT_REPROJ_PX, CALIB_REJECT_REPROJ_FRAC * width)
    if pose.reproj_error_px > reject_px:
        raise CalibrationError(
            f"Calibration rejected: reprojection error {pose.reproj_error_px:.0f} px "
            f"exceeds {reject_px:.0f} px. The stump marks are not consistent — "
            "re-tap the four corners of each stump cluster more precisely."
        )
    if pose.reproj_error_px > 8.0:
        warnings.append(
            f"High reprojection error ({pose.reproj_error_px:.1f} px) — "
            "calibration accuracy may be poor; re-tap the stump corners precisely."
        )

    # Physical-plausibility invariants. A phone is held above the pitch (cam_z>0)
    # and never sits more than a few metres up. If either is violated, the pose
    # may have fitted a mirrored or otherwise non-physical twin; refuse to use
    # it for the 3D reconstruction rather than silently emitting garbage.
    cam_z = float(pose.cam_center_world.flatten()[2])
    if not (0.10 <= cam_z <= 5.0):
        raise CalibrationError(
            f"Calibration rejected: recovered camera height {cam_z:.2f} m is "
            "outside the plausible phone range (0.10–5.00 m). The marks likely "
            "form a mirror twin; re-mark them in the canonical order "
            "(striker before bowler, base before top)."
        )
    if not (1.5 <= pitch_length_m <= 25.0):
        raise CalibrationError(
            f"Calibration rejected: derived pitch length {pitch_length_m:.2f} m "
            "is outside the plausible range (1.5–25.0 m). The stump marks may "
            "be at very different image scales — re-mark them."
        )
    _log.info(
        "calibration ok: reproj=%.2fpx length=%.2fm cam=(%.2f,%.2f,%.2f) fx=%.0f",
        pose.reproj_error_px,
        pitch_length_m,
        float(pose.cam_center_world.flatten()[0]),
        float(pose.cam_center_world.flatten()[1]),
        cam_z,
        pose.fx,
    )

    # Score: 1.0 at 0 px error, 0.0 at >=20 px.
    cal_score = float(max(0.05, min(0.99, 1.0 - pose.reproj_error_px / 20.0)))

    # ----------------------------- detect + trajectory -----------------------------
    _progress(progress, 40, "tracking")

    roi_mask = build_pitch_roi_mask(frames[0].shape, pitch_corners_px)
    image_diag = math.hypot(width, height)

    # Detector selection. The motion+colour detector is reliable on clean
    # (e.g. synthetic) footage but collapses on cluttered real phone clips,
    # where moving people produce more motion than the ball. A learned YOLO
    # detector isolates the ball directly and is far more robust there. The
    # default mode is "auto": run both available detectors and keep whichever
    # yields the more ball-like track. Explicit "yolo"/"combined" force one.
    # YOLO runs without the pitch ROI mask — it already rejects non-ball pixels
    # and the airborne arc rises out of the pitch quad.
    detector_kind = str(track_req.get("detector") or "auto").lower()
    yolo_weights = (
        track_req.get("yolo_weights")
        or os.environ.get("POCKET_DRS_YOLO_WEIGHTS")
        or _default_yolo_weights()
    )

    def _track_with(detector, detect_mask) -> tuple[list[tuple[int, list[dict]]], object | None]:
        dets_pf: list[tuple[int, list[dict]]] = []
        for i, frame in enumerate(frames):
            # Cap candidates per frame so RANSAC seed pairs stay bounded.
            dets_pf.append((times_ms[i], detector.detect(frame, detect_mask)[:8]))
        fit_ = find_ball_trajectory(dets_pf, image_diagonal_px=image_diag, min_inliers=6)
        return dets_pf, fit_

    def _ball_likeness(result: tuple[list, object | None]) -> tuple[float, int, float]:
        """Rank a candidate track. A real delivery sweeps a long, smooth arc
        across the frame; clutter (a near-static person, the bowler's body)
        yields a short, loose cluster even when it has many detections. So we
        rank by image-space span first, then inliers, then tightness."""
        fit_ = result[1]
        if fit_ is None or len(fit_.points) < 2:
            return (-1.0, 0, 0.0)
        xs = [p.x_px for p in fit_.points]
        ys = [p.y_px for p in fit_.points]
        span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        return (span, fit_.inliers, -fit_.rms_px)

    def _combined_result() -> tuple[list[tuple[int, list[dict]]], object | None]:
        return _track_with(CombinedBallDetector(ball_color=ball_color), roi_mask)

    if detector_kind == "yolo":
        if not yolo_weights:
            raise ValueError("tracking.detector='yolo' requires tracking.yolo_weights")
        detector = YoloBallDetector(str(yolo_weights), conf=float(track_req.get("yolo_conf", 0.2)))
        detections_per_frame, fit = _track_with(detector, None)
    elif detector_kind == "combined":
        detections_per_frame, fit = _combined_result()
    else:  # "auto"
        # Try every detector we have and pick the most ball-like track. The
        # caller-supplied ``ball_color`` is the first colour-detector seed;
        # we also run the alternate colour so a clip with a non-default
        # ball (white in lights, pink ball, etc.) is not rejected just
        # because the request did not specify it.
        candidates_results: list[tuple[list, object | None]] = []
        seeds = [ball_color] + [c for c in ("red", "pink") if c != ball_color]
        for colour in seeds:
            try:
                candidates_results.append(
                    _track_with(CombinedBallDetector(ball_color=colour), roi_mask)
                )
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Colour detector '{colour}' failed: {e}")
        yolo_result: tuple[list, object | None] | None = None
        if yolo_weights:
            try:
                detector = YoloBallDetector(str(yolo_weights), conf=float(track_req.get("yolo_conf", 0.2)))
                yolo_result = _track_with(detector, None)
                candidates_results.append(yolo_result)
            except Exception as e:  # noqa: BLE001 — missing ultralytics/torch or bad weights
                warnings.append(f"Learned detector unavailable, used motion+colour ({e})")
        # Prefer the ball-specific YOLO track when it forms a solid arc. The
        # colour/motion detectors rank by image span, which a near-camera
        # bowler's run-up (large, fast foreground motion of white kit/limbs)
        # can win over the small, far real ball — so "most ball-like by span"
        # silently locks onto the bowler. YOLO only fires on ball-like objects,
        # so a confident YOLO arc is the trustworthy one; fall back to the
        # span ranking only when YOLO is absent or too sparse to trust.
        yolo_fit = yolo_result[1] if yolo_result else None
        yolo_solid = (
            yolo_fit is not None
            and len(getattr(yolo_fit, "points", []) or []) >= 8
            and getattr(yolo_fit, "inliers", 0) >= 6
        )
        if yolo_solid:
            detections_per_frame, fit = yolo_result  # type: ignore[assignment]
            if any(_ball_likeness(c) > _ball_likeness(yolo_result) for c in candidates_results if c is not yolo_result):
                warnings.append(
                    "Preferred the learned ball detector over a higher-span "
                    "colour/motion track (likely foreground clutter such as the "
                    "bowler's run-up)."
                )
        elif not candidates_results:
            detections_per_frame, fit = ([], None)
        else:
            best = max(candidates_results, key=_ball_likeness)
            detections_per_frame, fit = best
    _progress(progress, 55, "tracking")

    track_payload: dict
    world_trajectory_payload: dict | None = None
    events_payload: dict | None = None
    lbw_payload: dict | None = None
    overlay_payload: dict | None = None
    metrics_payload: dict | None = None
    bounce_world: tuple[float, float, float] | None = None
    impact_world: tuple[float, float, float] | None = None
    predicted_path: list[tuple[float, float, float, float]] = []

    if fit is None:
        warnings.append("No consistent ball trajectory found — check ball colour, lighting, ROI.")
        track_payload = {
            "image_points": [],
            "candidates_total": sum(len(d) for _, d in detections_per_frame),
            "inliers": 0,
            "rms_px": 0.0,
        }
    else:
        # Track the live delivery up to the bat/pad impact (the direction
        # change), then predict the rest. A bounce is kept (the ball plays on);
        # only a genuine interception truncates the tracked flight.
        impact_i = _detect_impact_frame(fit.points)
        if impact_i is not None and impact_i + 1 < 6:
            impact_i = None
        live_points = fit.points if impact_i is None else fit.points[: impact_i + 1]
        if impact_i is not None:
            warnings.append(
                "Ball intercepted (direction change) — tracked the delivery to "
                "impact and predicted the path on to the stumps."
            )

        # Continue the visible track past the RANSAC fit using the per-frame
        # detector output. The fit's inlier set is the smooth delivery arc;
        # the detector still sees the ball through the bounce-to-bat segment
        # (and a few more frames into bat contact), which are too few to form
        # a second RANSAC arc but are real ball positions. We walk them
        # forward until the ball reverses direction — that is the genuine
        # bat / pad interception — and surface them through
        # ``track.image_points`` so the rendered flight line carries the ball
        # to where it actually goes, not where the delivery arc stops.
        extension = _extend_track_to_direction_change(detections_per_frame, live_points)

        image_points_payload = [
            {"t_ms": p.t_ms, "u": p.x_px, "v": p.y_px,
             "radius_px": p.radius_px, "confidence": p.confidence}
            for p in live_points
        ]
        image_points_payload.extend(extension)
        track_payload = {
            "image_points": image_points_payload,
            "candidates_total": fit.candidates_total,
            "inliers": len(live_points),
            "rms_px": fit.rms_px,
        }

        # ----------------------------- 3D reconstruction -----------------------------
        _progress(progress, 65, "reconstruction")
        det_for_recon = [
            (p.t_ms, p.x_px, p.y_px, p.radius_px, p.confidence)
            for p in live_points
        ]
        recon = reconstruct_trajectory(
            pose=pose,
            detections=det_for_recon,
            pitch_length_m=pitch_length_m,
            pitch_width_m=pitch_width_m,
            # With a stump-anchored pose the gravity-constrained linear solver
            # gives a smooth, correctly-oriented arc; the depth-from-size chain
            # is kept for un-stumped (e.g. synthetic) footage.
            # The stump-anchored pose is always trusted now, so the
            # gravity-constrained linear solver is the right reconstruction
            # path. The legacy depth-from-size chain (prefer_linear=False)
            # is kept only for synthetic clips that calibrate via corners.
            prefer_linear=True,
        )

        # Adaptive acceptance: scale the RMS bound to the trajectory's own
        # down-pitch span so harder, more end-on deliveries are not refused
        # outright. Tight fits pass silently; loose-but-usable fits pass with a
        # low-confidence warning; only fits above the hard ceiling are dropped.
        fit_ok = bool(recon.world_points) and recon.fit is not None
        if fit_ok:
            _xs = [p.x_m for p in recon.world_points]
            _span_m = max(_xs) - min(_xs)
            _rms_limit = min(
                MAX_FIT_RMS_M_HARD, max(MAX_FIT_RMS_M, FIT_RMS_SPAN_FRAC * _span_m)
            )
            fit_ok = recon.fit.rms_m <= _rms_limit
            if fit_ok and recon.fit.rms_m > MAX_FIT_RMS_M:
                warnings.append(
                    f"3D trajectory fit is loose ({recon.fit.rms_m:.2f} m RMS over "
                    f"a {_span_m:.1f} m path) — this camera angle is more end-on, "
                    "so depth recovery is less certain; treat speed and the line/"
                    "height decision as indicative rather than exact."
                )
        if fit_ok:
            t0_ms = recon.world_points[0].t_ms
            world_trajectory_payload = {
                "points_m": [
                    {"t_ms": p.t_ms, "x": p.x_m, "y": p.y_m, "z": p.z_m, "confidence": p.confidence}
                    for p in recon.world_points
                ],
                "fit": {
                    "x0": recon.fit.x0, "y0": recon.fit.y0, "z0": recon.fit.z0,
                    "vx": recon.fit.vx, "vy": recon.fit.vy, "vz": recon.fit.vz,
                    "bounce_t_ms": recon.fit.bounce_t_ms,
                    "rms_m": recon.fit.rms_m,
                    "notes": recon.fit.notes,
                },
                "predicted_to_stumps_m": [],
            }

            bounce_t_ms_fallback: float | None = None
            if recon.bounce_index is not None:
                bp = recon.world_points[recon.bounce_index]
                bounce_world = (bp.x_m, bp.y_m, bp.z_m)
            else:
                # Fall-back: the projectile fit does not commit to a bounce
                # when the post-bounce arc is only one or two frames long
                # (typical for a yorker / late bounce). Look for a v-peak in
                # the *image* trajectory — the ball only reverses its
                # downward image motion when it pitches — and read the
                # reconstructed world point at that frame so the bounce
                # marker stays consistent with the rest of the trajectory.
                # Skip the marker unless the post-peak rise is sustained
                # over at least two frames, otherwise an isolated detection
                # dropout near the end of the clip would masquerade as a
                # bounce.
                peak_idx = _find_image_v_peak(live_points, min_post_frames=1)
                if peak_idx is not None and 0 <= peak_idx < len(recon.world_points):
                    wp = recon.world_points[peak_idx]
                    # Pin z to the ball-on-ground height — the v-peak is a
                    # ground-contact event by construction. The reconstructed
                    # z is depth-from-size noisy in the bounce region; using
                    # the contact height keeps the bounce marker sitting on
                    # the pitch instead of floating mid-air.
                    bounce_world = (wp.x_m, wp.y_m, BALL_RADIUS_M)
                    bounce_t_ms_fallback = float(wp.t_ms)
            if recon.impact_index is not None:
                ip = recon.world_points[recon.impact_index]
                impact_world = (ip.x_m, ip.y_m, ip.z_m)

            # Decide bowling direction by sign of vx in the fit.
            target_x_m = 0.0 if recon.fit.vx < 0 else pitch_length_m
            stump_x_m = target_x_m

            # Project the bounce-aware fit forward to the stump plane,
            # starting at the latest visible image detection (which carries
            # the per-frame extension past the last RANSAC inlier — that
            # extra frame or two is real ball motion, so the prediction
            # should pick up from it rather than from an earlier "impact"
            # the smoother chose).
            last_track_t_ms = max(p["t_ms"] for p in image_points_payload)
            impact_t_ms = float(last_track_t_ms - t0_ms)
            predicted_path = predict_path_to_stumps(
                recon.fit,
                impact_t_ms=impact_t_ms,
                target_x_m=target_x_m,
            )
            if predicted_path:
                world_trajectory_payload["predicted_to_stumps_m"] = [
                    {"t_ms": int(t0_ms + tp), "x": x, "y": y, "z": z}
                    for (tp, x, y, z) in predicted_path
                ]

            # ----------------------------- LBW -----------------------------
            _progress(progress, 85, "lbw")
            # Y, Z at stump plane (use the last point of predicted_path; falls back to extrapolation).
            if predicted_path:
                last = predicted_path[-1]
                y_at_stumps = last[2]
                z_at_stumps = last[3]
            elif recon.impact_index is not None:
                # Linear extrapolation from impact along the same trajectory.
                ip = recon.world_points[recon.impact_index]
                y_at_stumps = ip.y_m
                z_at_stumps = ip.z_m
            else:
                y_at_stumps = z_at_stumps = None

            bounce_t_ms_evt: int | None = None
            if recon.bounce_index is not None:
                bounce_t_ms_evt = int(recon.world_points[recon.bounce_index].t_ms)
            elif bounce_world is not None:
                bounce_t_ms_evt = int(bounce_t_ms_fallback) if bounce_t_ms_fallback is not None else None
            events_payload = {
                "bounce": {
                    "t_ms": bounce_t_ms_evt,
                    "x_m": float(bounce_world[0]) if bounce_world else None,
                    "y_m": float(bounce_world[1]) if bounce_world else None,
                },
                "impact": {
                    "t_ms": int(recon.world_points[recon.impact_index].t_ms) if recon.impact_index is not None else None,
                    "x_m": float(impact_world[0]) if impact_world else None,
                    "y_m": float(impact_world[1]) if impact_world else None,
                    "z_m": float(impact_world[2]) if impact_world else None,
                },
            }

            lbw_payload = _decide_lbw(
                bounce=bounce_world,
                impact=impact_world,
                pred_y_at_stumps=y_at_stumps,
                pred_z_at_stumps=z_at_stumps,
                stump_x_m=stump_x_m,
                fit_rms_m=recon.fit.rms_m,
            )

            # ---------------------------- video overlay ----------------------------
            # Project the full path + prediction + stumps into image pixels so the
            # client can draw the Hawk-Eye overlay straight onto the source video.
            # The flight overlay spans the whole reconstructed arc (release →
            # last reconstructed point). For a normal delivery the points are
            # truncated at impact, so this IS the release→impact segment; but
            # when the impact resolves to the very first frame (a degenerate or
            # very early direction change, as on some net clips) keying off the
            # impact index collapsed the flight to nothing — the last
            # reconstructed point always gives a drawable arc.
            impact_t_rel = recon.world_points[-1].t_ms - t0_ms
            overlay_payload = build_overlay_px(
                pose=pose,
                fit=recon.fit,
                t0_ms=int(t0_ms),
                impact_t_rel_ms=float(impact_t_rel),
                predicted_path=predicted_path,
                pitch_length_m=pitch_length_m,
                pitch_width_m=pitch_width_m,
                bounce=(
                    (float(bounce_t_ms_evt if bounce_t_ms_evt is not None else 0), *bounce_world)
                    if bounce_world is not None
                    else None
                ),
                impact=(
                    (float(recon.world_points[recon.impact_index].t_ms), *impact_world)
                    if recon.impact_index is not None and impact_world is not None
                    else None
                ),
            )
            metrics_payload = _compute_metrics(
                recon.fit,
                image_points=image_points_payload,
                world_points=recon.world_points,
                bounce_index=recon.bounce_index,
            )
        elif recon.fit is not None and recon.fit.rms_m > MAX_FIT_RMS_M:
            warnings.append(
                f"3D reconstruction discarded — trajectory fit error "
                f"{recon.fit.rms_m:.2f} m exceeds {MAX_FIT_RMS_M:.2f} m. The ball "
                "track or pitch calibration is unreliable; re-mark the pitch "
                "corners or check the entered pitch dimensions."
            )
        else:
            warnings.append(
                "3D reconstruction failed — pixel trajectory exists but didn't fit a valid projectile."
            )

    # ----------------------------- assemble result -----------------------------
    _progress(progress, 95, "finalize")

    calibration_payload = {
        "mode": "taps",
        "pose": {
            "K": pose.K.tolist(),
            "rvec": pose.rvec.flatten().tolist(),
            "tvec": pose.tvec.flatten().tolist(),
            "cam_center_world_m": pose.cam_center_world.flatten().tolist(),
            "fx": pose.fx, "fy": pose.fy, "cx": pose.cx, "cy": pose.cy,
        },
        "quality": {
            "reproj_error_px": float(pose.reproj_error_px),
            "score": cal_score,
            "notes": pose.notes,
        },
    }

    result = {
        "video": {"duration_ms": int(meta.duration_ms), "fps_est": float(meta.fps)},
        "image_size": {"width": width, "height": height},
        "calibration": calibration_payload,
        "track": track_payload,
        "world_trajectory": world_trajectory_payload,
        "events": events_payload,
        "lbw": lbw_payload,
        "overlay": overlay_payload,
        "metrics": metrics_payload,
        "diagnostics": {"warnings": warnings, "log_id": "server.log"},
    }

    try:
        (artifacts_dir / "result_debug.json").write_text(json.dumps(result, indent=2, default=str))
    except Exception:
        pass

    _progress(progress, 100, "done")
    return PipelineOutput(result=result, warnings=warnings)


def map_exception_to_api_error(exc: Exception) -> ApiError:
    msg = str(exc) if str(exc) else exc.__class__.__name__
    if isinstance(exc, VideoDecodeError):
        return ApiError(code="VIDEO_DECODE_FAILED", message=msg, details=None)
    if isinstance(exc, CalibrationError):
        return ApiError(code="CALIBRATION_DEGENERATE", message=msg, details=None)
    if isinstance(exc, ValueError):
        return ApiError(code="INVALID_REQUEST", message=msg, details=None)
    return ApiError(code="INTERNAL_ERROR", message=msg, details=None)
