"""Calibrated DRS event and prediction model.

This layer turns a recovered pixel track into cricket-facing events:

* pitching / bounce point on the ground plane,
* bat/pad impact or last usable pre-deflection observation,
* predicted path from that impact point to the wicket.

The 3D projectile fit remains useful for smooth height and timing, but LBW
line decisions are safest when the post-bounce line comes from calibrated
ground-plane evidence.  That avoids the common monocular failure where a
single-camera projectile fit invents lateral drift and then pins the whole
prediction back to the bounce point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .reconstruction import (
    CameraPose,
    COEFFICIENT_OF_RESTITUTION_Z,
    GRAVITY_MS2,
    ProjectileFit,
    backproject_to_ground,
    predict_path_to_stumps,
)
from .trajectory import TrajectoryPoint


@dataclass(frozen=True)
class CalibratedDrsModel:
    bounce_index: int | None
    bounce_t_ms: int | None
    bounce_world: tuple[float, float, float] | None
    impact_index: int | None
    impact_t_ms: int | None
    impact_world: tuple[float, float, float] | None
    predicted_path: list[tuple[float, float, float, float]]
    y_at_stumps_m: float | None
    z_at_stumps_m: float | None
    stump_x_m: float
    notes: list[str]


def _smooth(values: np.ndarray) -> np.ndarray:
    if len(values) < 3:
        return values.copy()
    out = values.copy()
    out[1:-1] = 0.25 * values[:-2] + 0.50 * values[1:-1] + 0.25 * values[2:]
    return out


def _observed_bounce_index(points: list[TrajectoryPoint]) -> tuple[int | None, str | None]:
    """Find a visible pitch contact from the image track.

    In an umpire-style view, the bounce is usually the local maximum of image
    ``v``: the ball descends toward the pitch (v grows), touches down, then
    rises/rebounds or is intercepted (v falls).  We prefer the last strong peak
    so a small early detector wobble is not mistaken for the pitch point.
    """
    n = len(points)
    if n < 5:
        return None, None
    raw_vs = np.array([p.y_px for p in points], dtype=float)
    vs = _smooth(raw_vs)
    ts = np.array([p.t_ms for p in points], dtype=float)
    dt = np.diff(ts)
    dt[dt == 0.0] = 1.0
    dv = np.diff(vs) / dt
    med_speed = float(np.median(np.abs(dv))) if len(dv) else 0.0
    min_drop = max(1.5, 0.025 * (float(raw_vs.max()) - float(raw_vs.min())))
    min_slope = max(0.01, 0.20 * med_speed)

    best_i: int | None = None
    best_score = -1.0
    lo = max(1, int(0.35 * n))
    hi = n - 1
    for i in range(lo, hi):
        before = raw_vs[i] - raw_vs[i - 1]
        after = raw_vs[i] - raw_vs[i + 1]
        if before < min_drop or after < min_drop:
            continue
        if i - 1 < len(dv) and i < len(dv):
            if dv[i - 1] < min_slope or dv[i] > -min_slope:
                continue
        score = before + after + 0.01 * i
        if score > best_score:
            best_i = i
            best_score = score

    if best_i is None:
        return None, None
    return best_i, f"observed image-v peak at track[{best_i}]"


def _model_z_at(fit: ProjectileFit, t_rel_ms: float) -> float:
    t = max(0.0, float(t_rel_ms) / 1000.0)
    if fit.bounce_t_ms is not None and t >= fit.bounce_t_ms / 1000.0:
        tb = fit.bounce_t_ms / 1000.0
        vz_at_b = fit.vz - GRAVITY_MS2 * tb
        vz_post = -COEFFICIENT_OF_RESTITUTION_Z * vz_at_b
        tp = t - tb
        return max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp * tp)
    return max(0.0, fit.z0 + fit.vz * t - 0.5 * GRAVITY_MS2 * t * t)


def _world_on_ray(
    pose: CameraPose,
    point: TrajectoryPoint,
    *,
    z_target: float,
) -> tuple[float, float, float] | None:
    w = backproject_to_ground(pose, point.x_px, point.y_px, z_target=z_target)
    if w is None:
        return None
    return float(w[0]), float(w[1]), float(w[2])


def _ground_points_for_line(
    *,
    pose: CameraPose,
    points: list[TrajectoryPoint],
    bounce_idx: int | None,
    impact_idx: int | None,
) -> list[tuple[float, float, float]]:
    if not points:
        return []
    if bounce_idx is None:
        start = max(0, len(points) - 5)
    else:
        start = max(0, bounce_idx)
    end = impact_idx if impact_idx is not None else len(points) - 1
    if end < start:
        end = len(points) - 1

    out: list[tuple[float, float, float]] = []
    for p in points[start:end + 1]:
        g = backproject_to_ground(pose, p.x_px, p.y_px, z_target=0.0)
        if g is None:
            continue
        out.append((float(g[0]), float(g[1]), float(p.confidence)))
    return out


def _fit_ground_line_y_of_x(
    ground_points: list[tuple[float, float, float]],
) -> tuple[float, float] | None:
    """Fit y = a*x + b through calibrated ground-plane points."""
    if len(ground_points) < 2:
        return None
    xs = np.array([p[0] for p in ground_points], dtype=float)
    ys = np.array([p[1] for p in ground_points], dtype=float)
    ws = np.clip(np.array([p[2] for p in ground_points], dtype=float), 0.05, 1.0)
    if float(xs.max() - xs.min()) < 0.05:
        return None
    try:
        a, b = np.polyfit(xs, ys, 1, w=ws)
    except Exception:
        return None
    if not (math.isfinite(a) and math.isfinite(b)):
        return None
    return float(a), float(b)


def _line_y(line: tuple[float, float] | None, x: float) -> float | None:
    if line is None:
        return None
    return float(line[0] * x + line[1])


def _linear_prediction(
    *,
    impact_rel_ms: float,
    impact_world: tuple[float, float, float],
    target_x_m: float,
    line: tuple[float, float] | None,
    fit: ProjectileFit | None = None,
    n_steps: int = 18,
) -> list[tuple[float, float, float, float]]:
    """Straight-line ground continuation from impact to the wicket.

    Used only when the ballistic projectile continuation cannot be sampled
    (degenerate horizontal speed, or impact already at the stump plane). The
    lateral line comes from calibrated ground evidence; the HEIGHT still comes
    from the projectile model (``_model_z_at``) so the predicted ball keeps a
    physical arc instead of collapsing flat onto the pitch.
    """
    ix, iy, iz = impact_world
    # Time the ball would reach the stump plane at constant horizontal speed;
    # used to sample the ballistic height across the continuation.
    target_rel_ms: float | None = None
    if fit is not None and abs(fit.vx) > 1e-3:
        cand = ((target_x_m - fit.x0) / fit.vx) * 1000.0
        if cand > impact_rel_ms:
            target_rel_ms = cand
    out: list[tuple[float, float, float, float]] = []
    for i in range(1, n_steps + 1):
        s = i / n_steps
        x = ix + (target_x_m - ix) * s
        y = _line_y(line, x) if line is not None else iy
        if target_rel_ms is not None:
            t_rel = impact_rel_ms + (target_rel_ms - impact_rel_ms) * s
        else:
            t_rel = impact_rel_ms + 20.0 * i
        z = _model_z_at(fit, t_rel) if fit is not None else max(0.0, iz * (1.0 - s))
        out.append((float(t_rel), float(x), float(y), float(z)))
    return out


def evaluate_calibrated_drs(
    *,
    pose: CameraPose,
    live_points: list[TrajectoryPoint],
    post_impact_points: list[TrajectoryPoint],
    fit: ProjectileFit,
    t0_ms: int,
    pitch_length_m: float,
) -> CalibratedDrsModel:
    notes: list[str] = []
    target_x_m = 0.0 if fit.vx < 0.0 else float(pitch_length_m)

    bounce_idx, bounce_note = _observed_bounce_index(live_points)
    bounce_from_model = False
    if bounce_note:
        notes.append(bounce_note)

    if bounce_idx is None and fit.bounce_t_ms is not None and live_points:
        target_t = float(t0_ms) + float(fit.bounce_t_ms)
        observed_max = max(p.t_ms for p in live_points)
        observed_min = min(p.t_ms for p in live_points)
        if observed_min <= target_t <= observed_max:
            bounce_idx = int(np.argmin([abs(p.t_ms - target_t) for p in live_points]))
            bounce_from_model = True
            notes.append(f"model bounce inside observed track at track[{bounce_idx}]")

    bounce_world: tuple[float, float, float] | None = None
    bounce_t_ms: int | None = None
    if bounce_from_model and fit.bounce_t_ms is not None:
        tb = float(fit.bounce_t_ms) / 1000.0
        bx = fit.x0 + fit.vx * tb
        by = fit.y0 + fit.vy * tb
        if -2.0 <= bx <= pitch_length_m + 2.0:
            bounce_world = (float(bx), float(by), 0.0)
            bounce_t_ms = int(round(float(t0_ms) + float(fit.bounce_t_ms)))
    elif bounce_idx is not None and 0 <= bounce_idx < len(live_points):
        bp = live_points[bounce_idx]
        bw = _world_on_ray(pose, bp, z_target=0.0)
        if bw is not None:
            bounce_world = bw
            bounce_t_ms = int(bp.t_ms)

    if bounce_world is None and fit.bounce_t_ms is not None:
        tb = float(fit.bounce_t_ms) / 1000.0
        bx = fit.x0 + fit.vx * tb
        by = fit.y0 + fit.vy * tb
        if -2.0 <= bx <= pitch_length_m + 2.0:
            bounce_world = (float(bx), float(by), 0.0)
            bounce_t_ms = int(round(float(t0_ms) + float(fit.bounce_t_ms)))
            notes.append("model/extrapolated bounce used")

    # The RANSAC layer separates a reversed second arc into post_impact_points.
    # Those detections prove the ball changed direction, but they are not part
    # of the live DRS path: from the boundary onward the overlay must predict
    # what would have happened without bat/pad contact.
    impact_idx: int | None = len(live_points) - 1 if live_points else None
    if impact_idx is not None and bounce_idx is not None and impact_idx < bounce_idx:
        impact_idx = bounce_idx
    impact_world: tuple[float, float, float] | None = None
    impact_t_ms: int | None = None
    if impact_idx is not None and 0 <= impact_idx < len(live_points):
        ip = live_points[impact_idx]
        rel_ms = float(ip.t_ms - t0_ms)
        z_est = _model_z_at(fit, rel_ms)
        iw = _world_on_ray(pose, ip, z_target=z_est)
        # Keep the marker on the source pixel; if the model height is unstable,
        # the ground-plane projection is still a valid line/impact fallback.
        if iw is None:
            iw = _world_on_ray(pose, ip, z_target=0.0)
        if iw is not None:
            impact_world = iw
            impact_t_ms = int(ip.t_ms)

    ground_line_pts = _ground_points_for_line(
        pose=pose,
        points=live_points,
        bounce_idx=bounce_idx,
        impact_idx=impact_idx,
    )
    line = _fit_ground_line_y_of_x(ground_line_pts)
    if line is not None:
        notes.append(f"post-bounce ground line from {len(ground_line_pts)} point(s)")

    impact_rel_ms = (
        float(impact_t_ms - t0_ms)
        if impact_t_ms is not None
        else float(max(0, live_points[-1].t_ms - t0_ms)) if live_points else 0.0
    )
    # Predict the ball's continuation from impact to the stump plane as if it
    # had carried on untouched. HEIGHT and timing always come from the
    # ballistic projectile model so the predicted ball follows a physical arc
    # (descending, or kicking up off the pitch), never a flat skid. Only the
    # lateral line is replaced by calibrated ground evidence below — a single
    # camera resolves sideways drift poorly, so the observed ground line is the
    # trustworthy source for the wicket-line (y) decision.
    predicted = predict_path_to_stumps(
        fit,
        impact_t_ms=impact_rel_ms,
        target_x_m=target_x_m,
    )
    if predicted:
        notes.append("ballistic post-impact prediction to stumps")
    elif impact_world is not None:
        predicted = _linear_prediction(
            impact_rel_ms=impact_rel_ms,
            impact_world=impact_world,
            target_x_m=target_x_m,
            line=line,
            fit=fit,
        )
        notes.append("linear fallback prediction used")

    if line is not None and predicted:
        predicted = [
            (tp, x, float(_line_y(line, x)), z)
            for (tp, x, _y, z) in predicted
        ]

    y_at_stumps: float | None = None
    z_at_stumps: float | None = None
    if predicted:
        y_at_stumps = float(predicted[-1][2])
        z_at_stumps = float(predicted[-1][3])
    elif line is not None:
        y_at_stumps = float(_line_y(line, target_x_m))

    if post_impact_points:
        notes.append(
            "post-impact deflection detected and excluded from live path: "
            f"{len(post_impact_points)} point(s)"
        )

    return CalibratedDrsModel(
        bounce_index=bounce_idx,
        bounce_t_ms=bounce_t_ms,
        bounce_world=bounce_world,
        impact_index=impact_idx,
        impact_t_ms=impact_t_ms,
        impact_world=impact_world,
        predicted_path=predicted,
        y_at_stumps_m=y_at_stumps,
        z_at_stumps_m=z_at_stumps,
        stump_x_m=float(target_x_m),
        notes=notes,
    )
