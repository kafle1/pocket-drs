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
    predict_path_to_stumps,
    reconstruct_trajectory,
    solve_camera_pose,
)
from .tracking import CombinedBallDetector, build_pitch_roi_mask
from .trajectory import find_ball_trajectory
from .video import VideoDecodeError, VideoReader


_log = logging.getLogger("pocket_drs.pipeline")

# Cricket constants.
WICKET_HALF_WIDTH_M = 0.2286 / 2.0      # one stump line is ±wicket_half_width from centre
WICKET_GUARD_M = WICKET_HALF_WIDTH_M + BALL_RADIUS_M
UMPIRES_CALL_BAND_M = 0.050             # ±50 mm on the edge → umpire's call


ProgressFn = Callable[[int, str], None]


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


def _decode_stump_bases(req: dict, frame_width: int, frame_height: int) -> list[tuple[float, float]] | None:
    pts_px = req.get("stump_bases_px")
    pts_norm = req.get("stump_bases_norm")
    if pts_px and len(pts_px) == 2:
        return [(float(p["x"]), float(p["y"])) for p in pts_px]
    if pts_norm and len(pts_norm) == 2:
        return [(float(p["x"]) * frame_width, float(p["y"]) * frame_height) for p in pts_norm]
    return None


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


def run_pipeline(
    *,
    video_path: Path,
    request_json: dict,
    artifacts_dir: Path,
    progress: ProgressFn | None = None,
) -> PipelineOutput:
    warnings: list[str] = []
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    seg = request_json["segment"]
    start_ms = int(seg["start_ms"])
    end_ms = int(seg["end_ms"])
    if end_ms <= start_ms:
        raise ValueError("Invalid segment")

    track_req = request_json.get("tracking") or {}
    sample_fps = int(track_req.get("sample_fps", 30))
    max_frames = int(track_req.get("max_frames", 180))
    ball_color = str(track_req.get("ball_color", "red"))

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
        times_ms: list[int] = []
        t = start_ms
        while t <= end_ms and len(times_ms) < max_frames:
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

    # Optional camera-specific overrides; sensible default works for typical phones.
    h_fov_deg = float(cal_req.get("h_fov_deg") or 67.0)

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
                h_fov_deg=h_fov_deg,
            )
        except CalibrationError as e:
            warnings.append(f"PnP '{label}' failed: {e}")
            continue
        candidate_poses.append((label, pose))

    if not candidate_poses:
        raise CalibrationError("All PnP attempts failed — calibration is degenerate")

    # A symmetric pitch (no stumps) lets multiple corner orderings reproject
    # equally well. Among orderings within 1 px of the best reproj, prefer the
    # one where the *first* corner pair (declared striker corners) is closer
    # to the recovered camera than the bowler corners — this is the convention
    # the calibration UI emits.
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
    if pose.reproj_error_px > 8.0:
        warnings.append(
            f"High PnP reprojection error ({pose.reproj_error_px:.1f} px) — "
            "calibration accuracy may be poor; re-mark pitch corners precisely."
        )

    # Score: 1.0 at 0 px error, 0.0 at >=20 px.
    cal_score = float(max(0.05, min(0.99, 1.0 - pose.reproj_error_px / 20.0)))

    # ----------------------------- detect + trajectory -----------------------------
    _progress(progress, 40, "tracking")

    roi_mask = build_pitch_roi_mask(frames[0].shape, pitch_corners_px)
    detector = CombinedBallDetector(ball_color=ball_color)
    image_diag = math.hypot(width, height)

    detections_per_frame: list[tuple[int, list[dict]]] = []
    for i, frame in enumerate(frames):
        dets = detector.detect(frame, roi_mask)
        # Cap candidates per frame so RANSAC seed pairs stay bounded.
        detections_per_frame.append((times_ms[i], dets[:8]))
        if i and (i % max(1, len(frames) // 8) == 0):
            _progress(progress, 40 + int(15 * (i / max(1, len(frames) - 1))), "tracking")

    fit = find_ball_trajectory(
        detections_per_frame,
        image_diagonal_px=image_diag,
        min_inliers=6,
    )

    track_payload: dict
    world_trajectory_payload: dict | None = None
    events_payload: dict | None = None
    lbw_payload: dict | None = None
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
        track_payload = {
            "image_points": [
                {"t_ms": p.t_ms, "u": p.x_px, "v": p.y_px, "radius_px": p.radius_px, "confidence": p.confidence}
                for p in fit.points
            ],
            "candidates_total": fit.candidates_total,
            "inliers": fit.inliers,
            "rms_px": fit.rms_px,
        }

        # ----------------------------- 3D reconstruction -----------------------------
        _progress(progress, 65, "reconstruction")
        det_for_recon = [
            (p.t_ms, p.x_px, p.y_px, p.radius_px, p.confidence)
            for p in fit.points
        ]
        recon = reconstruct_trajectory(
            pose=pose,
            detections=det_for_recon,
            pitch_length_m=pitch_length_m,
            pitch_width_m=pitch_width_m,
        )

        if recon.world_points and recon.fit is not None:
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
