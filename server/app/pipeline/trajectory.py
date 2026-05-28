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
    # Post-impact deflection arc, when present: a second constant-acceleration
    # arc detected AFTER the primary one with a horizontal direction change
    # (pad/bat deflection in cricket). Kept separate from `points` because the
    # downstream projectile fit assumes one smooth parabola; the overlay still
    # renders these so the user can see the ball was tracked past the impact.
    post_impact_points: list[TrajectoryPoint] = None  # type: ignore[assignment]


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


def _search_best_arc(
    candidates: list[list[dict]],
    times: list[int],
    *,
    image_diagonal_px: float,
    search_radius_px: float,
    min_inliers: int,
    max_seed_pairs: int,
    total_candidates: int,
    exclude: set[tuple[int, int]] | None = None,
) -> tuple[TrajectoryFit | None, set[tuple[int, int]]]:
    """Recover the single best constant-acceleration arc by RANSAC.

    `exclude` holds (frame_idx, detection_idx) pairs already claimed by an
    earlier arc; they are skipped both as seeds and as inliers so a later pass
    can find a *different* arc — the far side of a bounce. Returns the winning
    fit together with the set of (frame_idx, detection_idx) it claimed.
    """
    exclude = exclude or set()
    n_frames = len(candidates)

    # Seed hypotheses from detection pairs across the WHOLE clip. A delivery can
    # be released anywhere in the (often untrimmed) segment, so we pair every
    # frame with a short forward window rather than only the opening frames.
    pair_span = max(2, n_frames // 4)
    seed_pairs: list[tuple[int, int, int, int]] = []
    for i in range(n_frames):
        for j in range(i + 1, min(n_frames, i + pair_span + 1)):
            for ai in range(len(candidates[i])):
                if (i, ai) in exclude:
                    continue
                for bj in range(len(candidates[j])):
                    if (j, bj) in exclude:
                        continue
                    seed_pairs.append((i, ai, j, bj))
    if len(seed_pairs) > max_seed_pairs:
        # Subsample uniformly so we don't blow up on noisy frames.
        idx = np.linspace(0, len(seed_pairs) - 1, max_seed_pairs).astype(int)
        seed_pairs = [seed_pairs[k] for k in idx]
    if not seed_pairs:
        return None, set()

    best_fit: TrajectoryFit | None = None
    best_keys: set[tuple[int, int]] = set()

    # Image-space gravity seeds for a phone-held camera; the LSQ refinement
    # adjusts the exact value. Zero covers near-axis (umpire-POV) motion.
    g_seed_options = [0.0, 5e-4, 2e-3]

    for (i, ai, j, bj) in seed_pairs:
        x0, y0 = candidates[i][ai]["x"], candidates[i][ai]["y"]
        x1, y1 = candidates[j][bj]["x"], candidates[j][bj]["y"]
        dt_ij = float(times[j] - times[i])
        if dt_ij <= 0:
            continue
        vx = (x1 - x0) / dt_ij
        vy = (y1 - y0) / dt_ij

        # Reject seeds whose displacement is too small to be the ball.
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
                    if (k, di) in exclude:
                        continue
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
            if best_fit is None or (fit.inliers, -fit.rms_px) > (best_fit.inliers, -best_fit.rms_px):
                best_fit = fit
                best_keys = set(inliers)

    return best_fit, best_keys


def _merge_bounce_arcs(
    fit_a: TrajectoryFit,
    fit_b: TrajectoryFit,
    *,
    search_radius_px: float,
) -> TrajectoryFit | None:
    """Stitch two arcs that meet at a bounce into one continuous track.

    A bouncing ball is two parabolas sharing the bounce instant. Only the
    horizontal image motion is continuous across the bounce — the vertical
    velocity flips — so the join is validated on horizontal evidence alone:

      * the arcs are disjoint and time-ordered (one clearly precedes the other),
      * the gap between them is at most a few sampled frames (the ball is
        smallest and most often missed right at the pitch),
      * both travel the same left/right direction at a similar horizontal pace,
      * extrapolating the earlier arc at its own horizontal velocity lands near
        where the later arc begins.

    When those hold the two are the one ball and we concatenate them; otherwise
    the second arc is unrelated clutter and we return None (keep only the first).
    """
    if not fit_a.points or not fit_b.points:
        return None
    early, late = (
        (fit_a, fit_b) if fit_a.points[0].t_ms <= fit_b.points[0].t_ms else (fit_b, fit_a)
    )
    e = early.points
    l = late.points

    # Disjoint and ordered in time — no interleaving.
    if l[0].t_ms <= e[-1].t_ms:
        return None

    # Bounded gap: a few times the typical sampling interval of the earlier arc.
    dts = [e[k].t_ms - e[k - 1].t_ms for k in range(1, len(e)) if e[k].t_ms > e[k - 1].t_ms]
    dt_typ = float(np.median(dts)) if dts else float(l[0].t_ms - e[-1].t_ms)
    gap_ms = float(l[0].t_ms - e[-1].t_ms)
    if dt_typ > 0 and gap_ms > 6.0 * dt_typ:
        return None

    # Same horizontal travel direction across the join.
    dir_e = e[-1].x_px - e[0].x_px
    dx_join = l[0].x_px - e[-1].x_px
    if dir_e != 0.0 and dx_join != 0.0 and math.copysign(1.0, dir_e) != math.copysign(1.0, dx_join):
        return None

    # Similar horizontal pace (sign + magnitude) — the ball does not change its
    # left/right speed appreciably at the bounce.
    vxa, vxb = early.px_per_ms_x, late.px_per_ms_x
    if vxa != 0.0 and vxb != 0.0:
        if math.copysign(1.0, vxa) != math.copysign(1.0, vxb):
            return None
        ratio = abs(vxb) / abs(vxa)
        if ratio < 0.4 or ratio > 2.5:
            return None

    # Horizontal continuity: the earlier arc, run forward at its own velocity,
    # should reach the later arc's first detection in x.
    x_pred = e[-1].x_px + early.px_per_ms_x * gap_ms
    if abs(x_pred - l[0].x_px) > 3.0 * search_radius_px:
        return None

    points = list(e) + list(l)
    n = len(points)
    rms = math.sqrt(
        (early.rms_px ** 2 * len(e) + late.rms_px ** 2 * len(l)) / max(1, n)
    )
    return TrajectoryFit(
        points=points,
        inliers=early.inliers + late.inliers,
        candidates_total=early.candidates_total,
        rms_px=rms,
        px_per_ms_x=early.px_per_ms_x,
        px_per_ms_y=early.px_per_ms_y,
        notes=list(early.notes) + list(late.notes) + [
            f"merged post-bounce arc: +{len(l)} pts across {gap_ms:.0f}ms gap"
        ],
    )


def _extend_track(
    points: list[TrajectoryPoint],
    candidates: list[list[dict]],
    times: list[int],
    *,
    search_radius_px: float,
    max_gap: int = 2,
) -> list[TrajectoryPoint]:
    """Greedily absorb clean detections at the two ends of a recovered arc.

    The constant-acceleration image model fits the bulk of the flight, but a
    fast, near-axial ball accelerates in the image under perspective, so the
    last (and first) genuine detections fall just outside the *global* fit's
    search radius and get dropped — the track stops short of the stumps (or of
    the release). We locally extrapolate a quadratic through the arc's end
    points and accept the nearest detection that continues it, frame by frame,
    re-fitting as we go so the extrapolation tracks the curvature. Bounded by
    the search radius and a small consecutive-gap tolerance so static clutter
    near the stumps is not absorbed.
    """
    if len(points) < 3:
        return points

    n_frames = len(candidates)
    idx_of_t = {t: i for i, t in enumerate(times)}

    def local_predict(end_pts: list[TrajectoryPoint], t_ms: int) -> tuple[float, float]:
        t0 = end_pts[0].t_ms
        ts = np.array([p.t_ms - t0 for p in end_pts], dtype=float)
        deg = min(2, len(end_pts) - 1)
        cu = np.polyfit(ts, np.array([p.x_px for p in end_pts]), deg)
        cv = np.polyfit(ts, np.array([p.y_px for p in end_pts]), deg)
        return float(np.polyval(cu, t_ms - t0)), float(np.polyval(cv, t_ms - t0))

    def nearest(fi: int, pu: float, pv: float) -> dict | None:
        best, best_d2 = None, search_radius_px * search_radius_px
        for d in candidates[fi]:
            d2 = (d["x"] - pu) ** 2 + (d["y"] - pv) ** 2
            if d2 < best_d2:
                best_d2, best = d2, d
        return best

    def as_point(fi: int, d: dict) -> TrajectoryPoint:
        return TrajectoryPoint(
            t_ms=int(times[fi]), x_px=float(d["x"]), y_px=float(d["y"]),
            radius_px=float(d.get("radius_px", 0.0)),
            confidence=float(d.get("confidence", 0.5)),
        )

    # Forward from the last point.
    pts_fwd = list(points)
    last_i = idx_of_t.get(pts_fwd[-1].t_ms, n_frames - 1)
    gap = 0
    for fi in range(last_i + 1, n_frames):
        pu, pv = local_predict(pts_fwd[-8:], times[fi])
        d = nearest(fi, pu, pv)
        if d is None:
            gap += 1
            if gap > max_gap:
                break
            continue
        gap = 0
        pts_fwd.append(as_point(fi, d))

    # Backward from the first point (operate on a forward-time list, prepend).
    first_i = idx_of_t.get(points[0].t_ms, 0)
    gap = 0
    for fi in range(first_i - 1, -1, -1):
        pu, pv = local_predict(pts_fwd[:8], times[fi])
        d = nearest(fi, pu, pv)
        if d is None:
            gap += 1
            if gap > max_gap:
                break
            continue
        gap = 0
        pts_fwd.insert(0, as_point(fi, d))

    pts_fwd.sort(key=lambda p: p.t_ms)
    return pts_fwd


def find_ball_trajectory(
    detections_by_frame: list[tuple[int, list[dict]]],
    *,
    image_diagonal_px: float,
    min_inliers: int = 6,
    search_radius_px: float | None = None,
    max_seed_pairs: int = 1500,
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
    frames = _suppress_static_clutter(frames, image_diagonal_px=image_diagonal_px)
    total_candidates = sum(len(d) for _, d in frames)
    if total_candidates < min_inliers:
        return None

    # Index detections per frame by their array index for fast inlier lookup.
    candidates: list[list[dict]] = [list(d) for _, d in frames]
    times: list[int] = [t for t, _ in frames]

    # First pass: recover the dominant constant-acceleration arc.
    fit_a, claimed_a = _search_best_arc(
        candidates, times,
        image_diagonal_px=image_diagonal_px,
        search_radius_px=search_radius_px,
        min_inliers=min_inliers,
        max_seed_pairs=max_seed_pairs,
        total_candidates=total_candidates,
    )
    if fit_a is None:
        return None

    # A bouncing delivery is two parabolas joined at the pitch. The pass above
    # locks onto the dominant one — usually the longer pre-bounce descent — and
    # rejects the other side as outliers, which is exactly why a cleanly tracked
    # ball appears to "stop" at the bounce. Recover that second arc from the
    # detections the first pass did not claim and stitch it on when it continues
    # the same horizontal flight (a real bounce flips only the vertical motion).
    best_fit = fit_a
    fit_b, _ = _search_best_arc(
        candidates, times,
        image_diagonal_px=image_diagonal_px,
        search_radius_px=search_radius_px,
        min_inliers=max(3, min_inliers // 2),
        max_seed_pairs=max_seed_pairs,
        total_candidates=total_candidates,
        exclude=claimed_a,
    )
    post_impact: list[TrajectoryPoint] | None = None
    if fit_b is not None:
        merged = _merge_bounce_arcs(fit_a, fit_b, search_radius_px=search_radius_px)
        if merged is not None:
            best_fit = merged
        else:
            # No clean bounce continuation, but a real second arc still came
            # from somewhere. Only treat it as a post-impact deflection when
            # the horizontal direction has CLEARLY reversed (pad/bat contact)
            # and the arc lives within a plausible reaction window after the
            # primary arc — otherwise it's tracking noise from late-frame
            # clutter and we leave the primary arc untouched.
            early, late = (
                (fit_a, fit_b) if fit_a.points[0].t_ms <= fit_b.points[0].t_ms else (fit_b, fit_a)
            )
            if late.points[0].t_ms > early.points[-1].t_ms:
                gap_ms = late.points[0].t_ms - early.points[-1].t_ms
                vx_e, vx_l = early.px_per_ms_x, late.px_per_ms_x
                same_dir = vx_e * vx_l > 0.0
                # Real deflection: opposite signs AND comparable magnitudes
                # (rebound retains ~30-150% of incoming pace, not 5%).
                reversed_pace_ok = (
                    not same_dir
                    and abs(vx_e) > 0.05 and abs(vx_l) > 0.05
                    and 0.3 < abs(vx_l) / abs(vx_e) < 3.0
                )
                if reversed_pace_ok and 0 < gap_ms < 1000:
                    best_fit = early
                    post_impact = list(late.points)

    # Recover the clean detections the constant-acceleration model drops at the
    # ends (a fast, near-axial ball accelerates in the image under perspective),
    # so the track reaches the release and the stumps rather than stopping short
    # — which otherwise forces a long, error-prone extrapolation downstream.
    extended = _extend_track(best_fit.points, candidates, times, search_radius_px=search_radius_px)
    added = len(extended) - len(best_fit.points)
    if added > 0:
        best_fit = TrajectoryFit(
            points=extended,
            inliers=len(extended),
            candidates_total=best_fit.candidates_total,
            rms_px=best_fit.rms_px,
            px_per_ms_x=best_fit.px_per_ms_x,
            px_per_ms_y=best_fit.px_per_ms_y,
            notes=list(best_fit.notes) + [f"extended ends +{added}"],
            post_impact_points=best_fit.post_impact_points,
        )
    if post_impact is not None and best_fit.post_impact_points is None:
        best_fit = TrajectoryFit(
            points=best_fit.points,
            inliers=best_fit.inliers,
            candidates_total=best_fit.candidates_total,
            rms_px=best_fit.rms_px,
            px_per_ms_x=best_fit.px_per_ms_x,
            px_per_ms_y=best_fit.px_per_ms_y,
            notes=list(best_fit.notes) + [f"post-impact arc: +{len(post_impact)} pts"],
            post_impact_points=post_impact,
        )

    # Final-track validation: a genuine ball traverses a meaningful fraction
    # of the image. A track whose points span almost no distance is a static
    # cluster that survived per-seed gating — reject it so the pipeline
    # reports "no trajectory" rather than fabricating a decision from clutter.
    if len(best_fit.points) >= 2:
        xs_t = [p.x_px for p in best_fit.points]
        ys_t = [p.y_px for p in best_fit.points]
        span = math.hypot(max(xs_t) - min(xs_t), max(ys_t) - min(ys_t))
        min_span = max(40.0, 0.06 * image_diagonal_px)  # ~130 px on 1080p
        if span < min_span:
            return None

    return best_fit
