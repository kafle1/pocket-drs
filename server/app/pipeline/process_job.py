from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import ApiError
from .calibration import CalibrationError, compute_homography, apply_homography
from .events import estimate_bounce_index, estimate_impact_index
from .tracking import MotionBallDetector
from .video import VideoDecodeError, VideoReader


# Cricket constants used for the 2D LBW approximation.
_WICKET_WIDTH_M = 0.2286
_BALL_RADIUS_M = 0.036


@dataclass(frozen=True)
class TrackPoint:
    t_ms: int
    x_px: float
    y_px: float
    confidence: float


def _rotate_frame(frame: np.ndarray, rotation_deg: int) -> np.ndarray:
    """Rotate a BGR frame by multiples of 90 degrees."""
    r = int(rotation_deg) % 360
    if r == 0:
        return frame
    try:
        import cv2

        if r == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if r == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if r == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except Exception:
        pass
    return frame


def _track_points(
    *,
    frames_bgr: list[np.ndarray],
    times_ms: list[int],
    mode: str,
    seed_xy: tuple[float, float] | None,
    search_radius_px: float,
) -> list[TrackPoint]:
    """Track ball centers (pixel space) using a simple motion detector.

    This is intentionally conservative and deterministic: it prefers continuity
    over occasional false positives.
    """

    if len(frames_bgr) != len(times_ms):
        raise ValueError("frames_bgr and times_ms length mismatch")

    detector = MotionBallDetector()

    track: list[TrackPoint] = []
    last_xy: tuple[float, float] | None = None
    prev_xy: tuple[float, float] | None = None

    if mode == "seeded":
        if seed_xy is None:
            raise ValueError("seed_px is required for seeded tracking")
        last_xy = (float(seed_xy[0]), float(seed_xy[1]))

    for i, frame in enumerate(frames_bgr):
        dets = detector.detect(frame)

        chosen = None
        if dets:
            if mode == "auto" and last_xy is None:
                chosen = max(dets, key=lambda d: float(d.get("confidence", 0.0)))
            else:
                # Prefer the detection closest to our predicted position.
                if last_xy is None:
                    chosen = max(dets, key=lambda d: float(d.get("confidence", 0.0)))
                else:
                    # Predict using constant-velocity (pixel space).
                    if prev_xy is not None:
                        px = last_xy[0] + (last_xy[0] - prev_xy[0])
                        py = last_xy[1] + (last_xy[1] - prev_xy[1])
                        pred = (px, py)
                    else:
                        pred = last_xy

                    best = None
                    best_score = float("inf")
                    for d in dets:
                        dx = float(d["x"]) - pred[0]
                        dy = float(d["y"]) - pred[1]
                        dist2 = dx * dx + dy * dy
                        if dist2 <= (search_radius_px * search_radius_px) and dist2 < best_score:
                            best = d
                            best_score = dist2
                    if best is None:
                        chosen = max(dets, key=lambda d: float(d.get("confidence", 0.0)))
                    else:
                        chosen = best

        if chosen is None:
            # No detection: repeat last known position with reduced confidence.
            if last_xy is None:
                continue
            x_px, y_px = last_xy
            conf = 0.05
        else:
            x_px = float(chosen["x"])
            y_px = float(chosen["y"])
            conf = float(chosen.get("confidence", 0.5))
            prev_xy = last_xy
            last_xy = (x_px, y_px)

        track.append(TrackPoint(t_ms=int(times_ms[i]), x_px=x_px, y_px=y_px, confidence=conf))

    return track


def _compute_taps_homography(
    *,
    corners_px: list[tuple[float, float]],
    pitch_length_m: float,
    pitch_width_m: float,
    stump_bases_px: list[tuple[float, float]] | None,
) -> tuple[np.ndarray, list[str]]:
    """Compute a robust homography, optionally refined with two stump bases."""
    half_w = pitch_width_m / 2.0
    world_points = [
        (0.0, -half_w),
        (0.0, half_w),
        (pitch_length_m, half_w),
        (pitch_length_m, -half_w),
    ]

    H0 = compute_homography(image_points=corners_px, world_points=world_points)

    notes: list[str] = []
    if stump_bases_px and len(stump_bases_px) == 2:
        # Order stump bases using the preliminary homography: striker is closer to x=0.
        p0 = stump_bases_px[0]
        p1 = stump_bases_px[1]
        x0, _y0 = apply_homography(H0, p0[0], p0[1])
        x1, _y1 = apply_homography(H0, p1[0], p1[1])
        if np.isfinite(x0) and np.isfinite(x1):
            if x0 <= x1:
                striker, bowler = p0, p1
            else:
                striker, bowler = p1, p0
        else:
            striker, bowler = p0, p1

        world_points_refined = world_points + [(0.0, 0.0), (pitch_length_m, 0.0)]
        image_points_refined = list(corners_px) + [striker, bowler]
        H = compute_homography(image_points=image_points_refined, world_points=world_points_refined)
        notes.append("Refined homography using both stump bases")
        return H, notes

    return H0, notes


def _assess_lbw_2d(
    *,
    pitch_points_m: list[tuple[float, float]],
    bounce_index: int,
    impact_index: int,
    point_confidences: list[float] | None,
) -> dict | None:
    """2D LBW decision using only pitch-plane XY.

    Produces the API shape expected by the Flutter client:
      - decision: out | not_out | umpires_call
      - prediction.y_at_stumps_m
    """
    n = len(pitch_points_m)
    if n < 3:
        return None

    bounce_i = int(max(0, min(n - 1, bounce_index)))
    impact_i = int(max(0, min(n - 1, impact_index)))
    if impact_i <= 0:
        impact_i = n - 1

    pitch_x, pitch_y = pitch_points_m[bounce_i]
    imp_x, imp_y = pitch_points_m[impact_i]

    line_thresh = (_WICKET_WIDTH_M / 2.0) + _BALL_RADIUS_M

    # Fit y(x) from (post-bounce .. impact) and evaluate at x=0.
    i0 = max(0, min(bounce_i, impact_i))
    i1 = max(i0 + 1, impact_i)
    xs = np.array([pitch_points_m[i][0] for i in range(i0, i1 + 1)], dtype=float)
    ys = np.array([pitch_points_m[i][1] for i in range(i0, i1 + 1)], dtype=float)

    if point_confidences is not None and len(point_confidences) == n:
        ws = np.array([max(1e-3, float(point_confidences[i])) for i in range(i0, i1 + 1)], dtype=float)
    else:
        ws = np.ones_like(xs)

    # Drop non-finite samples.
    mask = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(ws)
    xs, ys, ws = xs[mask], ys[mask], ws[mask]
    if len(xs) < 2:
        # Always return a JSON-safe prediction.
        y_at_stumps = float(imp_y)
        r2 = 0.0
    else:
        deg = 2 if len(xs) >= 3 else 1
        try:
            coeff = np.polyfit(xs, ys, deg=deg, w=ws)
            y_pred = np.polyval(coeff, xs)
            y_at_stumps = float(np.polyval(coeff, 0.0))
        except Exception:
            # Fall back to linear extrapolation using the last two points.
            x1, y1 = xs[-2], ys[-2]
            x2, y2 = xs[-1], ys[-1]
            if abs(x2 - x1) < 1e-9:
                y_at_stumps = float(imp_y)
                y_pred = np.full_like(xs, imp_y)
            else:
                m = (y2 - y1) / (x2 - x1)
                b = y2 - m * x2
                y_at_stumps = float(b)
                y_pred = m * xs + b

        # r^2-like quality metric.
        ss_res = float(np.sum((ys - y_pred) ** 2))
        ss_tot = float(np.sum((ys - float(np.mean(ys))) ** 2))
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
        r2 = float(np.clip(r2, 0.0, 1.0))

    # Determine "leg side" sign from the impact location (best available proxy).
    leg_sign = 1.0 if abs(imp_y) < 1e-6 else (1.0 if imp_y > 0 else -1.0)

    pitched_in_line = not (pitch_y * leg_sign > line_thresh)
    # Simplified impact-in-line (assumes shot offered).
    impact_in_line = abs(imp_y) <= line_thresh

    # Hitting stumps in 2D = lateral intersection at x=0.
    dist_to_center = abs(y_at_stumps)
    hitting = dist_to_center <= line_thresh

    # Umpire's call band near the edge.
    edge = line_thresh
    margin = 0.01  # 1cm band
    if not pitched_in_line:
        decision = "not_out"
        reason = "Pitched outside leg stump"
    elif not impact_in_line:
        decision = "not_out"
        reason = "Impact outside off stump line"
    else:
        if hitting and abs(dist_to_center - edge) <= margin:
            decision = "umpires_call"
            reason = "Projected clipping stumps (margin)"
        elif hitting:
            decision = "out"
            reason = "Projected to hit stumps"
        else:
            decision = "not_out"
            reason = "Projected to miss stumps"

    confidence = float(np.clip(0.2 + 0.8 * r2, 0.0, 1.0))

    return {
        "likely_out": bool(pitched_in_line and impact_in_line and hitting and decision == "out"),
        "checks": {
            "pitching_in_line": bool(pitched_in_line),
            "impact_in_line": bool(impact_in_line),
            "wickets_hitting": bool(hitting),
        },
        "prediction": {
            "y_at_stumps_m": float(y_at_stumps),
            "confidence": confidence,
            "r_squared": float(r2),
        },
        "decision": decision,
        "reason": reason,
    }


@dataclass(frozen=True)
class PipelineOutput:
    result: dict
    warnings: list[str]


ProgressFn = Callable[[int, str], None]


def _progress(fn: ProgressFn | None, pct: int, stage: str) -> None:
    if fn is not None:
        fn(int(max(0, min(100, pct))), stage)


def run_pipeline(
    *,
    video_path: Path,
    request_json: dict,
    artifacts_dir: Path,
    progress: ProgressFn | None = None,
) -> PipelineOutput:
    warnings: list[str] = []

    segment = request_json["segment"]
    start_ms = int(segment["start_ms"])
    end_ms = int(segment["end_ms"])

    tracking_req = request_json["tracking"]
    sample_fps = int(tracking_req.get("sample_fps", 30))
    max_frames = int(tracking_req.get("max_frames", 180))

    tracking_mode = str(tracking_req.get("mode") or "seeded")
    seed = tracking_req.get("seed_px")

    video_info = request_json.get("video") or {}
    rotation_deg = int(video_info.get("rotation_deg") or 0)

    _progress(progress, 5, "decode")

    with VideoReader(str(video_path)) as reader:
        meta = reader.meta

        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("Invalid segment")
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
                frame = reader.frame_at_ms(t_ms)
                frame = _rotate_frame(frame, rotation_deg)
                frames.append(frame)
            except VideoDecodeError as e:
                warnings.append(str(e))
                # Keep a placeholder by repeating the last good frame if possible.
                if frames:
                    frames.append(frames[-1])
                else:
                    raise

            if i == 0:
                h, w = frames[0].shape[:2]
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                try:
                    import cv2

                    cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])
                except Exception:
                    pass

            if i and (i % max(1, len(times_ms) // 10) == 0):
                _progress(progress, 5 + int(25 * (i / max(1, len(times_ms) - 1))), "decode")

        _progress(progress, 35, "tracking")

        seed_xy = (float(seed["x"]), float(seed["y"])) if isinstance(seed, dict) else None
        if tracking_mode not in {"auto", "seeded"}:
            raise ValueError("tracking.mode must be 'auto' or 'seeded'")

        track = _track_points(
            frames_bgr=frames,
            times_ms=times_ms,
            mode=tracking_mode,
            seed_xy=seed_xy,
            search_radius_px=160.0,
        )

        if not track:
            raise RuntimeError("Tracking produced no points")

        width = int(frames[0].shape[1])
        height = int(frames[0].shape[0])

        track_points_payload = [
            {"t_ms": p.t_ms, "x_px": p.x_px, "y_px": p.y_px, "confidence": p.confidence}
            for p in track
        ]

        _progress(progress, 60, "calibration")

        cal_req = request_json.get("calibration") or {}
        cal_mode = cal_req.get("mode", "none")

        calibration_payload: dict = {"mode": cal_mode, "homography": None, "quality": None}
        pitch_plane_payload: dict | None = None

        H = None
        if cal_mode == "taps":
            corners_px = cal_req.get("pitch_corners_px")
            corners_norm = cal_req.get("pitch_corners_norm")
            stump_bases_px = cal_req.get("stump_bases_px")
            stump_bases_norm = cal_req.get("stump_bases_norm")
            dims = cal_req.get("pitch_dimensions_m")
            if not dims:
                raise ValueError("calibration.pitch_dimensions_m is required")

            if corners_px:
                pts = [(float(p["x"]), float(p["y"])) for p in corners_px]
            elif corners_norm:
                pts = [(float(p["x"]) * width, float(p["y"]) * height) for p in corners_norm]
            else:
                raise ValueError("Provide calibration.pitch_corners_px or calibration.pitch_corners_norm")

            stump_pts: list[tuple[float, float]] | None = None
            if stump_bases_px and isinstance(stump_bases_px, list) and len(stump_bases_px) == 2:
                try:
                    stump_pts = [(float(p["x"]), float(p["y"])) for p in stump_bases_px]
                except Exception:
                    stump_pts = None
            elif stump_bases_norm and isinstance(stump_bases_norm, list) and len(stump_bases_norm) == 2:
                try:
                    stump_pts = [(float(p["x"]) * width, float(p["y"]) * height) for p in stump_bases_norm]
                except Exception:
                    stump_pts = None

            pitch_length_m = float(dims["length"])
            pitch_width_m = float(dims["width"])
            H, notes = _compute_taps_homography(
                corners_px=pts,
                pitch_length_m=pitch_length_m,
                pitch_width_m=pitch_width_m,
                stump_bases_px=stump_pts,
            )
            calibration_payload["homography"] = {"matrix": H.tolist()}
            calibration_payload["quality"] = {"score": 0.7 if notes else 0.6, "notes": notes}

            mapped = []
            for p in track:
                x_m, y_m = apply_homography(H, p.x_px, p.y_px)
                if not (np.isfinite(x_m) and np.isfinite(y_m)):
                    continue
                mapped.append((p.t_ms, x_m, y_m, p.confidence))
            pitch_plane_points = [
                {"t_ms": t_ms, "x_m": float(x_m), "y_m": float(y_m)}
                for (t_ms, x_m, y_m, _conf) in mapped
            ]
            pitch_plane_payload = {"points_m": pitch_plane_points}

        _progress(progress, 75, "events")

        overrides = request_json.get("overrides") or {}
        bounce_idx = overrides.get("bounce_index")
        impact_idx = overrides.get("impact_index")

        def _clamp_index(i: int, n: int) -> int:
            if n <= 0:
                return 0
            return max(0, min(n - 1, i))

        bounce_est = estimate_bounce_index([p.y_px for p in track])
        if bounce_idx is not None:
            bounce_est = bounce_est.__class__(index=int(bounce_idx), confidence=1.0)

        impact_est = estimate_impact_index(len(track))
        if impact_idx is not None:
            impact_est = impact_est.__class__(index=int(impact_idx), confidence=1.0)

        # Clamp indices to keep downstream consumers safe.
        bounce_i = _clamp_index(int(bounce_est.index), len(track))
        impact_i = _clamp_index(int(impact_est.index), len(track))

        events_payload = {
            "bounce": {"index": bounce_i, "confidence": float(bounce_est.confidence)},
            "impact": {"index": impact_i, "confidence": float(impact_est.confidence)},
        }

        lbw_payload = None
        if pitch_plane_payload is not None:
            _progress(progress, 85, "lbw")
            pts_m = [(float(p["x_m"]), float(p["y_m"])) for p in pitch_plane_payload["points_m"]]
            point_confidences = [float(p.confidence) for p in track]
            lbw_payload = _assess_lbw_2d(
                pitch_points_m=pts_m,
                bounce_index=bounce_i,
                impact_index=impact_i,
                point_confidences=point_confidences,
            )

        _progress(progress, 98, "finalize")

        result = {
            "video": {"duration_ms": int(meta.duration_ms), "fps_est": float(meta.fps)},
            "diagnostics": {"warnings": warnings, "log_id": "server.log"},
            "track": {"points": track_points_payload},
            "calibration": calibration_payload,
            "pitch_plane": pitch_plane_payload,
            "events": events_payload,
            "lbw": lbw_payload,
            "image_size": {"width": width, "height": height},
        }

        # Save a compact debug track for inspection.
        try:
            (artifacts_dir / "debug_track.json").write_text(json.dumps(result["track"], indent=2))
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
