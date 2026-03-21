from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..models import ApiError
from .calibration import CalibrationError, compute_homography, apply_homography
from .events import (
    estimate_bounce_index,
    estimate_bounce_index_from_pitch_plane,
    estimate_impact_index,
    estimate_impact_index_from_pitch_plane,
)
from .tracking import CombinedBallDetector, build_pitch_roi_mask
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


@dataclass(frozen=True, order=True)
class AutoTrackScore:
    moving_like: int
    x_span_m: float
    distinct_positions: int
    mapped_points: int
    avg_conf: float
    y_span_m: float


def _rotate_frame(frame: np.ndarray, rotation_deg: int) -> np.ndarray:
    """Rotate a BGR frame by multiples of 90 degrees."""
    r = int(rotation_deg) % 360
    if r == 0:
        return frame
    if r == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if r == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if r == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def _find_seed_auto(
    frames_bgr: list[np.ndarray],
    detector: CombinedBallDetector,
    scan_count: int = 8,
    roi_mask: np.ndarray | None = None,
) -> tuple[float, float] | None:
    """Scan the first *scan_count* frames and pick the most consistent cluster.

    We look for a detection that appears in multiple consecutive frames within
    a plausible radius. This avoids locking onto a single-frame false positive
    like a fielder's helmet or boundary board.
    """
    n = min(scan_count, len(frames_bgr))
    per_frame: list[list[dict]] = []
    for i in range(n):
        per_frame.append(detector.detect(frames_bgr[i], roi_mask))

    # Build candidate pool from the first frame.
    if not per_frame or not per_frame[0]:
        # Fallback: try each subsequent frame.
        for i in range(1, n):
            if per_frame[i]:
                best = max(per_frame[i], key=lambda d: d["confidence"])
                return (float(best["x"]), float(best["y"]))
        return None

    cluster_radius = 60.0
    best_seed: tuple[float, float] | None = None
    best_votes = 0
    best_conf = 0.0

    for cand in per_frame[0]:
        cx, cy = cand["x"], cand["y"]
        votes = 0
        for j in range(1, n):
            for d in per_frame[j]:
                if ((d["x"] - cx) ** 2 + (d["y"] - cy) ** 2) ** 0.5 < cluster_radius:
                    votes += 1
                    break
        if votes > best_votes or (votes == best_votes and cand["confidence"] > best_conf):
            best_votes = votes
            best_conf = cand["confidence"]
            best_seed = (float(cx), float(cy))

    return best_seed


def _smooth_track(track: list[TrackPoint], window: int = 3) -> list[TrackPoint]:
    """Median-smooth the raw track to remove single-frame outliers.

    Points with confidence < 0.1 (repeated-position placeholders) are not
    used as smoothing sources.
    """
    n = len(track)
    if n < window:
        return track

    smoothed: list[TrackPoint] = []
    half = window // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        xs = [track[j].x_px for j in range(lo, hi) if track[j].confidence >= 0.1]
        ys = [track[j].y_px for j in range(lo, hi) if track[j].confidence >= 0.1]
        if not xs:
            smoothed.append(track[i])
            continue
        mx = float(np.median(xs))
        my = float(np.median(ys))
        smoothed.append(TrackPoint(t_ms=track[i].t_ms, x_px=mx, y_px=my, confidence=track[i].confidence))
    return smoothed


def _reject_outliers(track: list[TrackPoint], max_jump_px: float = 120.0) -> list[TrackPoint]:
    """Drop points that jump unreasonably far from their neighbours."""
    if len(track) < 3:
        return track
    clean: list[TrackPoint] = [track[0]]
    for i in range(1, len(track)):
        dx = track[i].x_px - clean[-1].x_px
        dy = track[i].y_px - clean[-1].y_px
        if (dx * dx + dy * dy) ** 0.5 > max_jump_px and track[i].confidence < 0.4:
            continue
        clean.append(track[i])
    return clean


def _count_distinct_track_positions(track: list[TrackPoint]) -> int:
    return len({(round(p.x_px, 1), round(p.y_px, 1)) for p in track if p.confidence >= 0.1})


def _map_track_to_pitch_plane(
    *,
    track: list[TrackPoint],
    homography: np.ndarray,
    pitch_length_m: float,
    pitch_width_m: float,
    max_jump_m: float | None = 2.0,
    monotonic_tolerance_m: float | None = 1.0,
) -> list[tuple[int, float, float, float]]:
    mapped: list[tuple[int, float, float, float]] = []

    half_w = pitch_width_m / 2.0
    margin_x = 1.5
    margin_y = 1.0
    x_lo, x_hi = -margin_x, pitch_length_m + margin_x
    y_lo, y_hi = -(half_w + margin_y), half_w + margin_y
    prev_mapped: tuple[float, float] | None = None
    for p in track:
        if p.confidence < 0.1:
            continue
        x_m, y_m = apply_homography(homography, p.x_px, p.y_px)
        if not (np.isfinite(x_m) and np.isfinite(y_m)):
            continue
        if not (x_lo <= x_m <= x_hi and y_lo <= y_m <= y_hi):
            continue
        if max_jump_m is not None and prev_mapped is not None:
            dx = x_m - prev_mapped[0]
            dy = y_m - prev_mapped[1]
            if (dx * dx + dy * dy) ** 0.5 > max_jump_m:
                continue
        prev_mapped = (x_m, y_m)
        mapped.append((p.t_ms, x_m, y_m, p.confidence))

    if monotonic_tolerance_m is not None and len(mapped) >= 3:
        x_first = mapped[0][1]
        x_last = mapped[-1][1]
        decreasing = x_last < x_first
        cleaned: list[tuple[int, float, float, float]] = [mapped[0]]
        for m in mapped[1:]:
            prev_x = cleaned[-1][1]
            if decreasing and m[1] > prev_x + monotonic_tolerance_m:
                continue
            if not decreasing and m[1] < prev_x - monotonic_tolerance_m:
                continue
            cleaned.append(m)
        mapped = cleaned

    return mapped


def _score_auto_track_candidate(
    *,
    track: list[TrackPoint],
    homography: np.ndarray,
    pitch_length_m: float,
    pitch_width_m: float,
) -> tuple[AutoTrackScore, list[tuple[int, float, float, float]]]:
    mapped = _map_track_to_pitch_plane(
        track=track,
        homography=homography,
        pitch_length_m=pitch_length_m,
        pitch_width_m=pitch_width_m,
        max_jump_m=None,
        monotonic_tolerance_m=None,
    )

    if not mapped:
        return AutoTrackScore(0, 0.0, _count_distinct_track_positions(track), 0, 0.0, 0.0), mapped

    xs = [p[1] for p in mapped]
    ys = [p[2] for p in mapped]
    x_span = float(max(xs) - min(xs))
    y_span = float(max(ys) - min(ys))
    distinct_positions = _count_distinct_track_positions(track)
    confident = [p.confidence for p in track if p.confidence >= 0.1]
    avg_conf = float(np.mean(confident)) if confident else 0.0

    required_x_span = max(2.5, pitch_length_m * 0.15)
    moving_like = int(len(mapped) >= 8 and x_span >= required_x_span and distinct_positions >= 12)

    return AutoTrackScore(
        moving_like=moving_like,
        x_span_m=x_span,
        distinct_positions=distinct_positions,
        mapped_points=len(mapped),
        avg_conf=avg_conf,
        y_span_m=y_span,
    ), mapped


def _candidate_seeds_from_frames(
    *,
    frames_bgr: list[np.ndarray],
    detector: CombinedBallDetector,
    roi_mask: np.ndarray | None,
    scan_count: int = 12,
    per_frame_limit: int = 6,
    dedupe_cell_px: float = 20.0,
) -> list[tuple[float, float]]:
    candidates: list[tuple[float, float]] = []
    seen: set[tuple[int, int]] = set()

    for frame in frames_bgr[:scan_count]:
        for det in detector.detect(frame, roi_mask)[:per_frame_limit]:
            key = (round(float(det["x"]) / dedupe_cell_px), round(float(det["y"]) / dedupe_cell_px))
            if key in seen:
                continue
            seen.add(key)
            candidates.append((float(det["x"]), float(det["y"])))

    return candidates


def _track_points_auto_with_pitch_context(
    *,
    frames_bgr: list[np.ndarray],
    times_ms: list[int],
    search_radius_px: float,
    ball_color: str,
    roi_mask: np.ndarray | None,
    homography: np.ndarray,
    pitch_length_m: float,
    pitch_width_m: float,
) -> list[TrackPoint]:
    fallback_track = _track_points(
        frames_bgr=frames_bgr,
        times_ms=times_ms,
        mode="auto",
        seed_xy=None,
        search_radius_px=search_radius_px,
        ball_color=ball_color,
        roi_mask=roi_mask,
    )
    best_track = fallback_track
    best_score, _ = _score_auto_track_candidate(
        track=fallback_track,
        homography=homography,
        pitch_length_m=pitch_length_m,
        pitch_width_m=pitch_width_m,
    )

    detector = CombinedBallDetector(ball_color=ball_color)
    for seed_xy in _candidate_seeds_from_frames(
        frames_bgr=frames_bgr,
        detector=detector,
        roi_mask=roi_mask,
    ):
        track = _track_points(
            frames_bgr=frames_bgr,
            times_ms=times_ms,
            mode="seeded",
            seed_xy=seed_xy,
            search_radius_px=search_radius_px,
            ball_color=ball_color,
            roi_mask=roi_mask,
        )
        score, _ = _score_auto_track_candidate(
            track=track,
            homography=homography,
            pitch_length_m=pitch_length_m,
            pitch_width_m=pitch_width_m,
        )
        if score > best_score:
            best_score = score
            best_track = track

    return best_track


def _track_points(
    *,
    frames_bgr: list[np.ndarray],
    times_ms: list[int],
    mode: str,
    seed_xy: tuple[float, float] | None,
    search_radius_px: float,
    ball_color: str = "red",
    roi_mask: np.ndarray | None = None,
) -> list[TrackPoint]:
    """Track ball centres (pixel space) using combined motion+color detection.

    Key improvements over the naive approach:
    - Auto-mode scans several frames and picks the most consistent cluster.
    - Adaptive search radius that tightens as the trajectory stabilises.
    - Constant-velocity prediction so the search window follows the ball.
    - Optional ROI mask restricts detection to pitch area.
    - Post-tracking median smoothing + outlier rejection.
    """

    if len(frames_bgr) != len(times_ms):
        raise ValueError("frames_bgr and times_ms length mismatch")

    detector = CombinedBallDetector(ball_color=ball_color)

    track: list[TrackPoint] = []
    last_xy: tuple[float, float] | None = None
    prev_xy: tuple[float, float] | None = None
    base_radius = float(search_radius_px)
    consecutive_miss = 0

    if mode == "seeded":
        if seed_xy is None:
            raise ValueError("seed_px is required for seeded tracking")
        last_xy = (float(seed_xy[0]), float(seed_xy[1]))
    elif mode == "auto":
        auto_seed = _find_seed_auto(frames_bgr, detector, roi_mask=roi_mask)
        if auto_seed is not None:
            last_xy = auto_seed

    for i, frame in enumerate(frames_bgr):
        dets = detector.detect(frame, roi_mask)

        chosen = None
        if dets:
            if last_xy is None:
                chosen = max(dets, key=lambda d: float(d.get("confidence", 0.0)))
            else:
                # Constant-velocity prediction.
                if prev_xy is not None:
                    px = last_xy[0] + (last_xy[0] - prev_xy[0])
                    py = last_xy[1] + (last_xy[1] - prev_xy[1])
                    pred = (px, py)
                else:
                    pred = last_xy

                # Adaptive radius: widen when missing, tighten when stable.
                radius = base_radius + consecutive_miss * 15.0
                radius = min(radius, base_radius * 2.5)

                best = None
                best_score = float("inf")
                for d in dets:
                    dx = float(d["x"]) - pred[0]
                    dy = float(d["y"]) - pred[1]
                    dist2 = dx * dx + dy * dy
                    if dist2 <= radius * radius and dist2 < best_score:
                        best = d
                        best_score = dist2
                chosen = best

        if chosen is None:
            consecutive_miss += 1
            if last_xy is None:
                continue
            # Repeat last position with very low confidence.
            x_px, y_px = last_xy
            conf = 0.05
        else:
            consecutive_miss = 0
            x_px = float(chosen["x"])
            y_px = float(chosen["y"])
            conf = float(chosen.get("confidence", 0.5))
            prev_xy = last_xy
            last_xy = (x_px, y_px)

        track.append(TrackPoint(t_ms=int(times_ms[i]), x_px=x_px, y_px=y_px, confidence=conf))

    # Post-processing: reject outliers then median-smooth.
    track = _reject_outliers(track, max_jump_px=base_radius * 1.5)
    track = _smooth_track(track, window=3)

    return track


def _compute_taps_homography(
    *,
    corners_px: list[tuple[float, float]],
    pitch_length_m: float,
    pitch_width_m: float,
    stump_bases_px: list[tuple[float, float]] | None,
) -> tuple[np.ndarray, list[str], float]:
    """Compute a robust homography, optionally refined with two stump bases.

    Returns (H, notes, reproj_error_m) where reproj_error_m is the mean
    reprojection error in meters when corners are projected through H.
    """
    half_w = pitch_width_m / 2.0
    world_points = [
        (0.0, -half_w),
        (0.0, half_w),
        (pitch_length_m, half_w),
        (pitch_length_m, -half_w),
    ]

    H0 = compute_homography(image_points=corners_px, world_points=world_points)

    notes: list[str] = []
    final_H = H0
    final_img_pts = corners_px
    final_world_pts = world_points

    if stump_bases_px and len(stump_bases_px) == 2:
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

        final_world_pts = world_points + [(0.0, 0.0), (pitch_length_m, 0.0)]
        final_img_pts = list(corners_px) + [striker, bowler]
        final_H = compute_homography(image_points=final_img_pts, world_points=final_world_pts)
        notes.append("Refined homography using both stump bases")

    # Reprojection quality: project image points through H and compare to expected world points.
    total_err = 0.0
    for ip, wp in zip(final_img_pts, final_world_pts):
        wx, wy = apply_homography(final_H, ip[0], ip[1])
        if np.isfinite(wx) and np.isfinite(wy):
            total_err += ((wx - wp[0]) ** 2 + (wy - wp[1]) ** 2) ** 0.5
        else:
            total_err += 10.0  # penalty for non-finite projection
    reproj_err = total_err / max(1, len(final_img_pts))

    if reproj_err > 1.0:
        notes.append(f"High reprojection error ({reproj_err:.2f}m) — calibration may be inaccurate")

    return final_H, notes, reproj_err


def _assess_lbw_2d(
    *,
    pitch_points_m: list[tuple[float, float]],
    bounce_index: int,
    impact_index: int,
    point_confidences: list[float] | None,
    pitch_length_m: float = 20.12,
) -> dict | None:
    """2D LBW decision using only pitch-plane XY.

    Handles both bowling directions (x decreasing or increasing).
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

    # Determine bowling direction.
    x_first = pitch_points_m[0][0]
    x_last = pitch_points_m[-1][0]
    decreasing = x_last < x_first  # ball moving toward x=0 (striker @ x=0)
    stump_x = 0.0 if decreasing else pitch_length_m

    pitch_x, pitch_y = pitch_points_m[bounce_i]
    imp_x, imp_y = pitch_points_m[impact_i]

    line_thresh = (_WICKET_WIDTH_M / 2.0) + _BALL_RADIUS_M

    # Fit y(x) from (post-bounce .. impact) and evaluate at stump_x.
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
        y_at_stumps = float(imp_y)
        r2 = 0.0
    else:
        deg = 2 if len(xs) >= 3 else 1
        try:
            coeff = np.polyfit(xs, ys, deg=deg, w=ws)
            y_pred = np.polyval(coeff, xs)
            y_at_stumps = float(np.polyval(coeff, stump_x))
        except Exception:
            x1, y1 = xs[-2], ys[-2]
            x2, y2 = xs[-1], ys[-1]
            if abs(x2 - x1) < 1e-9:
                y_at_stumps = float(imp_y)
                y_pred = np.full_like(xs, imp_y)
            else:
                m = (y2 - y1) / (x2 - x1)
                b = y2 - m * x2
                y_at_stumps = float(m * stump_x + b)
                y_pred = m * xs + b

        ss_res = float(np.sum((ys - y_pred) ** 2))
        ss_tot = float(np.sum((ys - float(np.mean(ys))) ** 2))
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
        r2 = float(np.clip(r2, 0.0, 1.0))

    # Determine leg side — positive y is leg side for right-hand batsman.
    # We use the direction of the majority of points as a heuristic.
    leg_sign = 1.0 if imp_y >= 0 else -1.0

    pitched_in_line = not (pitch_y * leg_sign > line_thresh)
    impact_in_line = abs(imp_y) <= line_thresh * 2.0  # slightly wider for impact

    dist_to_center = abs(y_at_stumps)
    hitting = dist_to_center <= line_thresh

    # Umpire's call: ball clipping the edge of the stumps.
    uc_margin = 0.02  # 2cm band around stump edge
    if not pitched_in_line:
        decision = "not_out"
        reason = "Pitched outside leg stump"
    elif not impact_in_line:
        decision = "not_out"
        reason = "Impact outside off stump line"
    else:
        if hitting and abs(dist_to_center - line_thresh) <= uc_margin:
            decision = "umpires_call"
            reason = "Projected clipping stumps (margin)"
        elif hitting:
            decision = "out"
            reason = "Projected to hit stumps"
        else:
            if abs(dist_to_center - line_thresh) <= uc_margin:
                decision = "umpires_call"
                reason = "Projected just missing stumps (margin)"
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
            "stump_x_m": float(stump_x),
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
                    cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])
                except Exception:
                    pass

            if i and (i % max(1, len(times_ms) // 10) == 0):
                _progress(progress, 5 + int(25 * (i / max(1, len(times_ms) - 1))), "decode")

        _progress(progress, 35, "tracking")

        seed_xy = (float(seed["x"]), float(seed["y"])) if isinstance(seed, dict) else None
        if tracking_mode not in {"auto", "seeded"}:
            raise ValueError("tracking.mode must be 'auto' or 'seeded'")

        ball_color = str(tracking_req.get("ball_color", "red"))

        # Resolution-adaptive search radius: ~5% of frame diagonal, clamped [30, 100].
        frame_diag = (w * w + h * h) ** 0.5
        search_radius = min(100.0, max(30.0, frame_diag * 0.05))

        # --- Build ROI mask from calibration corners before tracking ---
        roi_mask: np.ndarray | None = None
        auto_track_h: np.ndarray | None = None
        auto_track_pitch_length_m = 20.12
        auto_track_pitch_width_m = 3.05
        cal_req_early = request_json.get("calibration") or {}
        if cal_req_early.get("mode") == "taps":
            _corners_px = cal_req_early.get("pitch_corners_px")
            _corners_norm = cal_req_early.get("pitch_corners_norm")
            _dims = cal_req_early.get("pitch_dimensions_m") or {}
            if _corners_px:
                roi_corners = [(float(p["x"]), float(p["y"])) for p in _corners_px]
            elif _corners_norm:
                roi_corners = [(float(p["x"]) * w, float(p["y"]) * h) for p in _corners_norm]
            else:
                roi_corners = None
            if roi_corners and len(roi_corners) == 4:
                roi_mask = build_pitch_roi_mask(frames[0].shape, roi_corners, margin_factor=0.6)
                try:
                    auto_track_pitch_length_m = float(_dims.get("length", auto_track_pitch_length_m))
                    auto_track_pitch_width_m = float(_dims.get("width", auto_track_pitch_width_m))
                    auto_track_h, _notes, _reproj = _compute_taps_homography(
                        corners_px=roi_corners,
                        pitch_length_m=auto_track_pitch_length_m,
                        pitch_width_m=auto_track_pitch_width_m,
                        stump_bases_px=None,
                    )
                except Exception:
                    auto_track_h = None

        if tracking_mode == "auto" and auto_track_h is not None:
            track = _track_points_auto_with_pitch_context(
                frames_bgr=frames,
                times_ms=times_ms,
                search_radius_px=search_radius,
                ball_color=ball_color,
                roi_mask=roi_mask,
                homography=auto_track_h,
                pitch_length_m=auto_track_pitch_length_m,
                pitch_width_m=auto_track_pitch_width_m,
            )
        else:
            track = _track_points(
                frames_bgr=frames,
                times_ms=times_ms,
                mode=tracking_mode,
                seed_xy=seed_xy,
                search_radius_px=search_radius,
                ball_color=ball_color,
                roi_mask=roi_mask,
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
        pitch_plane_points: list[dict] = []
        mapped: list[tuple[int, float, float, float]] = []
        pitch_length_m: float = 20.12
        pitch_width_m: float = 3.05

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
            base_h, base_notes, base_reproj_err = _compute_taps_homography(
                corners_px=pts,
                pitch_length_m=pitch_length_m,
                pitch_width_m=pitch_width_m,
                stump_bases_px=None,
            )
            H = base_h
            notes = list(base_notes)
            reproj_err = base_reproj_err

            best_score, _ = _score_auto_track_candidate(
                track=track,
                homography=base_h,
                pitch_length_m=pitch_length_m,
                pitch_width_m=pitch_width_m,
            )

            if stump_pts is not None:
                refined_h, refined_notes, refined_reproj_err = _compute_taps_homography(
                    corners_px=pts,
                    pitch_length_m=pitch_length_m,
                    pitch_width_m=pitch_width_m,
                    stump_bases_px=stump_pts,
                )
                refined_score, _ = _score_auto_track_candidate(
                    track=track,
                    homography=refined_h,
                    pitch_length_m=pitch_length_m,
                    pitch_width_m=pitch_width_m,
                )
                if refined_score > best_score:
                    H = refined_h
                    notes = list(refined_notes)
                    reproj_err = refined_reproj_err
                    best_score = refined_score
                else:
                    notes.append("Skipped stump refinement because corner-only mapping matched the track better")

            # Quality score: 0.9 for excellent (<0.3m error), down to 0.3 for poor (>2m).
            quality_score = float(np.clip(0.9 - reproj_err * 0.3, 0.3, 0.9))
            calibration_payload["homography"] = {"matrix": H.tolist()}
            calibration_payload["quality"] = {
                "score": quality_score,
                "reproj_error_m": round(reproj_err, 4),
                "notes": notes,
            }

            strict_mapped = _map_track_to_pitch_plane(
                track=track,
                homography=H,
                pitch_length_m=pitch_length_m,
                pitch_width_m=pitch_width_m,
            )
            relaxed_mapped = _map_track_to_pitch_plane(
                track=track,
                homography=H,
                pitch_length_m=pitch_length_m,
                pitch_width_m=pitch_width_m,
                max_jump_m=None,
                monotonic_tolerance_m=None,
            )
            mapped = strict_mapped
            if len(mapped) < 5 and len(relaxed_mapped) > len(mapped):
                mapped = relaxed_mapped
                notes.append(
                    "Used relaxed pitch-plane filtering because strict filtering removed too many points"
                )

            pitch_plane_points = [
                {"t_ms": t_ms, "x_m": float(x_m), "y_m": float(y_m)}
                for (t_ms, x_m, y_m, _conf) in mapped
            ]
            pitch_plane_payload = {"points_m": pitch_plane_points}

            # Warn if we lost too many points during filtering.
            raw_count = len(track)
            mapped_count = len(mapped)
            if mapped_count < 5:
                warnings.append(
                    f"Only {mapped_count}/{raw_count} track points survived pitch-plane "
                    "filtering — calibration may be inaccurate or ball was off-pitch"
                )
            elif mapped_count < raw_count * 0.15:
                warnings.append(
                    f"Only {mapped_count}/{raw_count} track points survived pitch-plane "
                    "filtering — many detections were outside the pitch area"
                )

        _progress(progress, 75, "events")

        overrides = request_json.get("overrides") or {}
        bounce_idx = overrides.get("bounce_index")
        impact_idx = overrides.get("impact_index")

        def _clamp_index(i: int, n: int) -> int:
            if n <= 0:
                return 0
            return max(0, min(n - 1, i))

        # Use pitch-plane coordinates for event detection when available,
        # falling back to pixel-space heuristics.
        n_pp = len(pitch_plane_points) if pitch_plane_payload is not None else 0
        if pitch_plane_payload is not None and n_pp >= 5:
            pp_x = [p["x_m"] for p in pitch_plane_points]
            pp_y = [p["y_m"] for p in pitch_plane_points]
            bounce_est = estimate_bounce_index_from_pitch_plane(
                pp_x, pp_y, pitch_length_m=pitch_length_m,
            )
            impact_est = estimate_impact_index_from_pitch_plane(
                pp_x, pitch_length_m=pitch_length_m,
            )
        else:
            bounce_est = estimate_bounce_index([p.y_px for p in track])
            impact_est = estimate_impact_index(len(track))

        if bounce_idx is not None:
            bounce_est = bounce_est.__class__(index=int(bounce_idx), confidence=1.0)
        if impact_idx is not None:
            impact_est = impact_est.__class__(index=int(impact_idx), confidence=1.0)

        # Clamp indices to the pitch-plane array (which may differ from track).
        effective_n = n_pp if n_pp > 0 else len(track)
        bounce_i = _clamp_index(int(bounce_est.index), effective_n)
        impact_i = _clamp_index(int(impact_est.index), effective_n)

        events_payload = {
            "bounce": {"index": bounce_i, "confidence": float(bounce_est.confidence)},
            "impact": {"index": impact_i, "confidence": float(impact_est.confidence)},
        }

        lbw_payload = None
        if pitch_plane_payload is not None and n_pp >= 3:
            _progress(progress, 85, "lbw")
            pts_m = [(float(p["x_m"]), float(p["y_m"])) for p in pitch_plane_points]
            # Build confidences that correspond to the filtered pitch_plane points.
            pp_confidences = [c for (_, _, _, c) in mapped]
            lbw_payload = _assess_lbw_2d(
                pitch_points_m=pts_m,
                bounce_index=bounce_i,
                impact_index=impact_i,
                point_confidences=pp_confidences,
                pitch_length_m=pitch_length_m,
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
