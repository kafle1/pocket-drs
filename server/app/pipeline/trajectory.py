"""Multi-frame trajectory association via RANSAC over a constant-acceleration model.

The per-frame detector emits many candidates (people, shadows, kit, the ball).
A single ball trajectory is the unique subset of candidates that satisfies a
smooth motion model across time.  This module recovers it by:

1. For each pair of detections in early frames, hypothesise an initial state
   (position, velocity).
2. Forward-propagate that hypothesis with constant downward image-acceleration
   (the ball pulls down due to gravity *plus* perspective foreshortening).
3. Count how many subsequent detections lie within a search radius of the
   propagated position.  The hypothesis with the most inliers wins.
4. Refine with a least-squares fit on the inlier set.

The result is a list of `(t_ms, x_px, y_px, radius_px, confidence)` tuples
covering only the frames where the ball was seen, plus a per-tuple confidence
that is high when the model fit is tight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TrajectoryPoint:
    t_ms: int
    x_px: float
    y_px: float
    radius_px: float
    confidence: float


@dataclass(frozen=True)
class TrajectoryFit:
    points: list[TrajectoryPoint]
    inliers: int          # number of detections that supported the fit
    candidates_total: int # total candidates considered across frames
    rms_px: float         # RMS reprojection error in pixels
    px_per_ms_x: float    # mean image velocity, x
    px_per_ms_y: float    # mean image velocity, y
    notes: list[str]


def _propagate(
    *,
    x0: float,
    y0: float,
    vx: float,           # px / ms
    vy: float,           # px / ms
    ay: float,           # px / ms^2 (downward, positive = falling)
    dt: float,           # ms
) -> tuple[float, float]:
    """Constant-acceleration image-space propagation."""
    return (x0 + vx * dt, y0 + vy * dt + 0.5 * ay * dt * dt)


def _frames_in_order(
    detections_by_frame: list[tuple[int, list[dict]]],
) -> list[tuple[int, list[dict]]]:
    return sorted(detections_by_frame, key=lambda x: x[0])


def _suppress_static_clutter(
    frames: list[tuple[int, list[dict]]],
    *,
    image_diagonal_px: float,
    occupancy_frac: float = 0.30,
) -> list[tuple[int, list[dict]]]:
    """Drop detections that recur at the same image location across the clip.

    A genuine cricket ball passes through any given pixel neighbourhood in at
    most one or two frames. A static red/round object (sponsor logo, helmet,
    distant kit, bat handle) sits in the same place for the whole sequence
    and is the dominant false-positive in handheld footage. Standard
    background-modelling practice: treat anything persistent as background.

    For each detection we count how many *other* frames contain a detection
    within a small radius. If that occupancy exceeds `occupancy_frac` of all
    frames, the detection is static clutter and is removed.
    """
    n_frames = len(frames)
    if n_frames < 6:
        return frames
    radius = max(12.0, 0.012 * image_diagonal_px)  # ~26 px on 1080p
    r2 = radius * radius

    # Per-frame representative points (use every detection).
    pts_per_frame: list[list[tuple[float, float]]] = [
        [(float(d["x"]), float(d["y"])) for d in dets] for _, dets in frames
    ]

    cleaned: list[tuple[int, list[dict]]] = []
    for fi, (t_ms, dets) in enumerate(frames):
        kept: list[dict] = []
        for d in dets:
            dx0, dy0 = float(d["x"]), float(d["y"])
            occ = 0
            for fj in range(n_frames):
                if fj == fi:
                    continue
                for (px, py) in pts_per_frame[fj]:
                    if (px - dx0) ** 2 + (py - dy0) ** 2 <= r2:
                        occ += 1
                        break
            if occ <= occupancy_frac * n_frames:
                kept.append(d)
        cleaned.append((t_ms, kept))
    return cleaned


def find_ball_trajectory(
    detections_by_frame: list[tuple[int, list[dict]]],
    *,
    image_diagonal_px: float,
    min_inliers: int = 6,
    search_radius_px: float | None = None,
    max_seed_pairs: int = 600,
) -> TrajectoryFit | None:
    """Find the dominant ball trajectory across frames.

    Parameters
    ----------
    detections_by_frame:
        List of (t_ms, [detection_dict]).  Each detection_dict needs at least
        x, y, radius_px, confidence.
    image_diagonal_px:
        Used to scale tolerances.  Pass sqrt(w^2 + h^2) of the source frame.
    min_inliers:
        Reject hypotheses with fewer than this many supporting detections.
    search_radius_px:
        Tolerance for an in-frame detection to count as an inlier.  Defaults
        to ~3 % of the image diagonal which works for typical 1080p phone
        footage at umpire-POV framing.
    """
    frames = _frames_in_order(detections_by_frame)
    n_frames = len(frames)
    if n_frames < 4:
        return None

    if search_radius_px is None:
        search_radius_px = max(15.0, 0.03 * image_diagonal_px)

    # Suppress static clutter (sponsor logos, helmets, bat handles) before
    # association — these are the dominant false positive in handheld footage
    # and the RANSAC will happily fit a "trajectory" through a static cluster.
    raw_total = sum(len(d) for _, d in frames)
    frames = _suppress_static_clutter(frames, image_diagonal_px=image_diagonal_px)
    total_candidates = sum(len(d) for _, d in frames)
    if total_candidates < min_inliers:
        return None

    # Index detections per frame by their array index for fast inlier lookup.
    candidates: list[list[dict]] = [list(d) for _, d in frames]
    times: list[int] = [t for t, _ in frames]

    # We seed hypotheses from pairs of detections in the *earliest* frames
    # because those are most likely to contain the ball release.  Try the
    # first ~25 % of the sequence as seed window.
    seed_window = max(2, n_frames // 4)

    # Collect seed pairs (i, ai, j, bj) where i < j are frame indices and
    # ai/bj are detection indices within those frames.
    seed_pairs: list[tuple[int, int, int, int]] = []
    for i in range(seed_window):
        for j in range(i + 1, min(n_frames, i + seed_window + 1)):
            for ai in range(len(candidates[i])):
                for bj in range(len(candidates[j])):
                    seed_pairs.append((i, ai, j, bj))
    if len(seed_pairs) > max_seed_pairs:
        # Subsample uniformly so we don't blow up on noisy frames.
        idx = np.linspace(0, len(seed_pairs) - 1, max_seed_pairs).astype(int)
        seed_pairs = [seed_pairs[k] for k in idx]

    if not seed_pairs:
        return None

    best_fit: TrajectoryFit | None = None

    # Image-space gravity for a phone-held camera at typical pitch framings.
    # Physical g of 9.81 m/s^2 projects to ~1e-3 px/ms^2 at 5-10 m subject
    # distance with fy ~ 900. We sample a small grid plus zero (umpire-POV
    # motion can be almost purely along the camera axis, giving near-zero
    # image acceleration). The LSQ refinement adjusts the exact value.
    g_seed_options = [0.0, 5e-4, 2e-3]

    for (i, ai, j, bj) in seed_pairs:
        x0, y0 = candidates[i][ai]["x"], candidates[i][ai]["y"]
        x1, y1 = candidates[j][bj]["x"], candidates[j][bj]["y"]
        dt_ij = float(times[j] - times[i])
        if dt_ij <= 0:
            continue
        vx = (x1 - x0) / dt_ij
        vy = (y1 - y0) / dt_ij

        # Reject seeds whose total displacement is too small to be the ball.
        # Use displacement (scaled to the image diagonal) rather than absolute
        # speed: under umpire-POV the ball moves chiefly along the camera axis
        # and its image-plane velocity can be modest even at 130 km/h. The
        # original 0.1 px/ms cutoff masked exactly that case.
        disp_px = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        min_disp_px = max(2.0, 0.002 * image_diagonal_px)  # ~4 px on 1080p
        if disp_px < min_disp_px:
            continue

        for g_seed in g_seed_options:
            inliers: list[tuple[int, int]] = []  # (frame_idx, det_idx)
            sq_err_sum = 0.0
            for k in range(i, n_frames):
                dt_k = float(times[k] - times[i])
                px, py = _propagate(x0=x0, y0=y0, vx=vx, vy=vy, ay=g_seed, dt=dt_k)
                # Pick the closest in-frame detection if any is within radius.
                best_d = None
                best_d2 = search_radius_px * search_radius_px
                best_idx = -1
                for di, d in enumerate(candidates[k]):
                    dx = d["x"] - px
                    dy = d["y"] - py
                    d2 = dx * dx + dy * dy
                    if d2 < best_d2:
                        best_d2 = d2
                        best_d = d
                        best_idx = di
                if best_d is not None:
                    inliers.append((k, best_idx))
                    sq_err_sum += best_d2

            if len(inliers) < min_inliers:
                continue
            rms = (sq_err_sum / len(inliers)) ** 0.5

            # Refine via weighted LSQ on the inlier set.
            ts = np.array([times[k] - times[i] for (k, _) in inliers], dtype=float)
            xs = np.array([candidates[k][di]["x"] for (k, di) in inliers], dtype=float)
            ys = np.array([candidates[k][di]["y"] for (k, di) in inliers], dtype=float)
            ws = np.array([candidates[k][di]["confidence"] for (k, di) in inliers], dtype=float)
            ws = np.clip(ws, 0.1, 1.0)

            # x(t) = x0 + vx * t   (linear)
            # y(t) = y0 + vy * t + 0.5 * ay * t^2  (quadratic)
            try:
                vx_fit, x0_fit = np.polyfit(ts, xs, 1, w=ws)
                ay_half, vy_fit, y0_fit = np.polyfit(ts, ys, 2, w=ws)
                ay_fit = 2.0 * ay_half
            except Exception:
                continue

            # Recompute residuals after refinement.
            x_pred = x0_fit + vx_fit * ts
            y_pred = y0_fit + vy_fit * ts + 0.5 * ay_fit * ts * ts
            resid = np.hypot(xs - x_pred, ys - y_pred)
            rms_refined = float(np.sqrt(np.mean(resid * resid)))

            # Reject refinements that are noticeably worse than the seed.
            if rms_refined > rms * 1.5:
                continue

            # Build trajectory points.
            traj_pts: list[TrajectoryPoint] = []
            for (k, di) in inliers:
                d = candidates[k][di]
                # Confidence: detector conf * fit-tightness.
                tightness = max(0.1, 1.0 - (resid[inliers.index((k, di))] / search_radius_px))
                conf = float(min(1.0, 0.4 * d["confidence"] + 0.6 * tightness))
                traj_pts.append(TrajectoryPoint(
                    t_ms=int(times[k]),
                    x_px=float(d["x"]),
                    y_px=float(d["y"]),
                    radius_px=float(d.get("radius_px", 0.0)),
                    confidence=conf,
                ))

            fit = TrajectoryFit(
                points=traj_pts,
                inliers=len(inliers),
                candidates_total=total_candidates,
                rms_px=rms_refined,
                px_per_ms_x=float(vx_fit),
                px_per_ms_y=float(vy_fit),
                notes=[f"seed_g={g_seed:.1f}", f"refined ay={ay_fit:.3f}"],
            )

            # Score: prefer more inliers, then tighter fit.
            if best_fit is None:
                best_fit = fit
            else:
                if (fit.inliers, -fit.rms_px) > (best_fit.inliers, -best_fit.rms_px):
                    best_fit = fit

    # Final-track validation: a genuine ball traverses a meaningful fraction
    # of the image. A track whose points span almost no distance is a static
    # cluster that survived per-seed gating — reject it so the pipeline
    # reports "no trajectory" rather than fabricating a decision from clutter.
    if best_fit is not None and len(best_fit.points) >= 2:
        xs_t = [p.x_px for p in best_fit.points]
        ys_t = [p.y_px for p in best_fit.points]
        span = math.hypot(max(xs_t) - min(xs_t), max(ys_t) - min(ys_t))
        min_span = max(40.0, 0.06 * image_diagonal_px)  # ~130 px on 1080p
        if span < min_span:
            return None

    return best_fit
