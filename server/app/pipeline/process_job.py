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
    build_overlay_px,
    predict_path_to_stumps,
    reconstruct_trajectory,
    solve_camera_pose,
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
# (which run several metres). Above this the 3D path does not explain the
# observations, so we discard it rather than render a fabricated trajectory.
MAX_FIT_RMS_M = 1.0


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


def _decode_point_pair(
    req: dict, key_px: str, key_norm: str, frame_width: int, frame_height: int
) -> list[tuple[float, float]] | None:
    pts_px = req.get(key_px)
    pts_norm = req.get(key_norm)
    if pts_px and len(pts_px) == 2:
        return [(float(p["x"]), float(p["y"])) for p in pts_px]
    if pts_norm and len(pts_norm) == 2:
        return [(float(p["x"]) * frame_width, float(p["y"]) * frame_height) for p in pts_norm]
    return None


def _decode_stump_bases(req: dict, frame_width: int, frame_height: int) -> list[tuple[float, float]] | None:
    return _decode_point_pair(req, "stump_bases_px", "stump_bases_norm", frame_width, frame_height)


def _decode_stump_tops(req: dict, frame_width: int, frame_height: int) -> list[tuple[float, float]] | None:
    # Stump tops are an out-of-plane (z = stump height) scale reference. With
    # only the 4 coplanar pitch corners the absolute pitch length is ambiguous
    # (a longer pitch viewed from higher reprojects identically); the 0.711 m
    # stump height pins that scale, so a calibration that includes the tops
    # recovers a physically correct camera pose on real, non-regulation strips.
    return _decode_point_pair(req, "stump_tops_px", "stump_tops_norm", frame_width, frame_height)


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


def _compute_metrics(points, fit) -> dict:
    """Broadcast-style delivery metrics (Speed / Spin / Swing) from the fit + track.

    - Speed: release speed of the ball, |v0|, in mph (metric only as good as the
      stump-anchored scale).
    - Swing factor: peak lateral deviation of the pre-bounce path from its
      release->bounce chord, as a percent of chord length. With a down-the-pitch
      camera the chord is near-vertical in the image, so the perpendicular
      deviation is the in-air sideways (swing) movement.
    - Spin: lateral angle of travel off the straight line down the pitch, in
      degrees (turn/drift proxy).

    These are estimates from a single camera; precise values need stereo.
    """
    speed_mph = math.sqrt(fit.vx ** 2 + fit.vy ** 2 + fit.vz ** 2) * 2.2369362921
    swing_sf = 0.0
    pts = sorted(points, key=lambda p: p.t_ms)
    if len(pts) >= 4:
        t0 = pts[0].t_ms
        bt = fit.bounce_t_ms
        pre = [p for p in pts if bt is None or (p.t_ms - t0) <= bt]
        if len(pre) < 3:
            pre = pts
        ax, ay = pre[0].x_px, pre[0].y_px
        bx, by = pre[-1].x_px, pre[-1].y_px
        chord = math.hypot(bx - ax, by - ay)
        if chord > 1.0:
            nx, ny = -(by - ay) / chord, (bx - ax) / chord
            dev = max(abs((p.x_px - ax) * nx + (p.y_px - ay) * ny) for p in pre)
            swing_sf = 100.0 * dev / chord
    spin_deg = abs(math.degrees(math.atan2(fit.vy, abs(fit.vx)))) if abs(fit.vx) > 1e-3 else 0.0
    return {
        "speed_mph": round(max(0.0, speed_mph), 1),
        "spin_deg": round(spin_deg, 1),
        "swing_sf": round(swing_sf, 1),
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
        pitch_length_m = float(dims.get("length"))
        pitch_width_m = float(dims.get("width"))
    except (TypeError, ValueError):
        raise ValueError("calibration.pitch_dimensions_m.{length,width} required")
    # Must be positive: run_pipeline reads the raw request dict, so the
    # Pydantic gt=0 constraint on the model never runs here.
    if not (pitch_length_m > 0.0 and pitch_width_m > 0.0):
        raise ValueError("calibration.pitch_dimensions_m.{length,width} must be positive")

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
    stump_bases_px = _decode_stump_bases(cal_req, width, height)
    stump_tops_px = _decode_stump_tops(cal_req, width, height)

    # Optional camera-specific overrides; sensible default works for typical phones.
    h_fov_deg = float(cal_req.get("h_fov_deg") or 67.0)

    # Stump-anchored calibration (preferred on real footage). When both stump
    # bases and tops are marked, the known 0.711 m stump height fixes the metric
    # scale, so we DERIVE the pitch length from the stumps rather than trusting
    # the user-entered length. Practice nets are rarely a regulation 20.12 m, and
    # a wrong entered length is the usual cause of a rejected calibration. The
    # turf "corners" stay only for the detection ROI / display — they need not
    # match a rectangle centred on the stumps, which they rarely do.
    use_stumps = (
        stump_bases_px is not None and len(stump_bases_px) == 2
        and stump_tops_px is not None and len(stump_tops_px) == 2
    )
    if use_stumps:
        pose, pitch_length_m = solve_camera_pose_from_stumps(
            image_size=(width, height),
            stump_bases_px=stump_bases_px,
            stump_tops_px=stump_tops_px,
            h_fov_deg=h_fov_deg,
        )
        best_attempt_label = "stumps"
    else:
        pose_attempts: list[tuple[str, list[tuple[float, float]]]] = [
            ("as-given", pitch_corners_px),
            # Reverse to handle a user who tapped counter-clockwise.
            ("reversed", list(reversed(pitch_corners_px))),
        ]
        candidate_poses: list[tuple[str, object]] = []
        for label, corners in pose_attempts:
            try:
                pose = solve_camera_pose(
                    image_size=(width, height),
                    pitch_corners_px=corners,
                    pitch_length_m=pitch_length_m,
                    pitch_width_m=pitch_width_m,
                    stump_bases_px=stump_bases_px,
                    stump_tops_px=stump_tops_px,
                    h_fov_deg=h_fov_deg,
                )
            except CalibrationError as e:
                warnings.append(f"PnP '{label}' failed: {e}")
                continue
            candidate_poses.append((label, pose))

        if not candidate_poses:
            raise CalibrationError("All PnP attempts failed — calibration is degenerate")

        # A real camera always sits above the pitch plane. Planar PnP has a
        # twofold mirror twin (one above, one below ground); solve_camera_pose
        # already drops the below-ground twin *within* one corner ordering, but
        # the two orderings are independent, so a below-ground twin from the
        # reversed ordering can still undercut the reprojection tie-break and
        # win. Enforce the above-ground constraint across all candidates here too.
        above_ground = [
            (lbl, p) for (lbl, p) in candidate_poses
            if float(p.cam_center_world.flatten()[2]) > 0.0
        ]
        if above_ground:
            candidate_poses = above_ground

        # A symmetric pitch (no stumps) lets multiple corner orderings reproject
        # equally well. Among orderings within 1 px of the best reproj, prefer
        # the one where the *first* corner pair (declared striker corners) is
        # closer to the recovered camera than the bowler corners — this is the
        # convention the calibration UI emits.
        def _striker_proximity(corners: list[tuple[float, float]], pose_obj) -> float:
            cam = pose_obj.cam_center_world.flatten()
            striker_x = 0.0
            bowler_x = pitch_length_m
            d_striker = abs(float(cam[0]) - striker_x)
            d_bowler = abs(float(cam[0]) - bowler_x)
            return d_striker - d_bowler  # negative means striker is closer (preferred)

        best_reproj = min(p.reproj_error_px for _, p in candidate_poses)
        tied = [(lbl, p) for (lbl, p) in candidate_poses if p.reproj_error_px <= best_reproj + 1.0]
        # Among tied candidates, smallest striker-proximity wins; reproj is the
        # final tie-breaker for unambiguous cases.
        tied.sort(key=lambda lp: (_striker_proximity(
            pitch_corners_px if lp[0] == "as-given" else list(reversed(pitch_corners_px)),
            lp[1],
        ), lp[1].reproj_error_px))
        best_attempt_label, best_pose = tied[0]
        if best_pose is None:
            raise CalibrationError("All PnP attempts failed — calibration is degenerate")
        pose = best_pose

    # Hard reject a calibration whose marks cannot form a consistent perspective
    # view. The marks always admit an exact 2D homography, but only a
    # geometrically valid set yields a low PnP reprojection error; a large error
    # means the recovered pose is meaningless. Proceeding would emit a
    # confident-but-wrong 3D reconstruction, so we stop here. The bound scales
    # with frame width to stay resolution-independent.
    what = "stump marks" if use_stumps else "pitch corners"
    reject_px = max(CALIB_REJECT_REPROJ_PX, CALIB_REJECT_REPROJ_FRAC * width)
    if pose.reproj_error_px > reject_px:
        raise CalibrationError(
            f"Calibration rejected: reprojection error {pose.reproj_error_px:.0f} px "
            f"exceeds {reject_px:.0f} px. The {what} are not consistent — re-mark "
            f"the {'base and top of both stump sets' if use_stumps else 'pitch corners'} "
            "precisely (zoom in), making sure each base sits at ground level."
        )
    if pose.reproj_error_px > 8.0:
        warnings.append(
            f"High reprojection error ({pose.reproj_error_px:.1f} px) — "
            f"calibration accuracy may be poor; re-mark the {what} precisely."
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
        candidates_results = [_combined_result()]
        if yolo_weights:
            try:
                detector = YoloBallDetector(str(yolo_weights), conf=float(track_req.get("yolo_conf", 0.2)))
                candidates_results.append(_track_with(detector, None))
            except Exception as e:  # noqa: BLE001 — missing ultralytics/torch or bad weights
                warnings.append(f"Learned detector unavailable, used motion+colour ({e})")
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

        track_payload = {
            "image_points": [
                {"t_ms": p.t_ms, "u": p.x_px, "v": p.y_px, "radius_px": p.radius_px, "confidence": p.confidence}
                for p in live_points
            ],
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
            prefer_linear=use_stumps,
        )

        if recon.world_points and recon.fit is not None and recon.fit.rms_m <= MAX_FIT_RMS_M:
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

            if recon.bounce_index is not None:
                bp = recon.world_points[recon.bounce_index]
                bounce_world = (bp.x_m, bp.y_m, bp.z_m)
            if recon.impact_index is not None:
                ip = recon.world_points[recon.impact_index]
                impact_world = (ip.x_m, ip.y_m, ip.z_m)

            # Decide bowling direction by sign of vx in the fit.
            target_x_m = 0.0 if recon.fit.vx < 0 else pitch_length_m
            stump_x_m = target_x_m

            # Predict path from impact to stumps.
            if recon.impact_index is not None:
                impact_t_ms = recon.world_points[recon.impact_index].t_ms - t0_ms
                predicted_path = predict_path_to_stumps(
                    recon.fit,
                    impact_t_ms=float(impact_t_ms),
                    target_x_m=target_x_m,
                )
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

            events_payload = {
                "bounce": {
                    "t_ms": int(recon.world_points[recon.bounce_index].t_ms) if recon.bounce_index is not None else None,
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
            impact_t_rel = (
                recon.world_points[recon.impact_index].t_ms - t0_ms
                if recon.impact_index is not None
                else recon.world_points[-1].t_ms - t0_ms
            )
            overlay_payload = build_overlay_px(
                pose=pose,
                fit=recon.fit,
                t0_ms=int(t0_ms),
                impact_t_rel_ms=float(impact_t_rel),
                predicted_path=predicted_path,
                pitch_length_m=pitch_length_m,
                bounce=(
                    (float(recon.world_points[recon.bounce_index].t_ms), *bounce_world)
                    if recon.bounce_index is not None and bounce_world is not None
                    else None
                ),
                impact=(
                    (float(recon.world_points[recon.impact_index].t_ms), *impact_world)
                    if recon.impact_index is not None and impact_world is not None
                    else None
                ),
            )
            metrics_payload = _compute_metrics(live_points, recon.fit)
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
            "notes": pose.notes + ([f"used corner order: {best_attempt_label}"] if best_attempt_label != "as-given" else []),
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
