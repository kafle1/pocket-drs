"""Pixel-space overlay for the client: the tracked flight, the predicted path to the stumps,
the pitch outline and the wickets, all projected through the calibrated camera so the app
draws straight onto the source video."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import splev, splprep

from .calibration import CameraPose, STUMP_HEIGHT_M
from .reconstruction import Trajectory, sample_path


def _pt(pose: CameraPose, x: float, y: float, z: float) -> dict | None:
    p = pose.project_one(x, y, z)
    return None if p is None else {"u": round(p[0], 2), "v": round(p[1], 2)}


def _smooth(points: list[tuple[int, float, float]], n_out: int = 64) -> list[tuple[int, float, float]]:
    """A smoothing spline through the detections so the tracer reads as one clean arc."""
    if len(points) < 4:
        return points
    try:
        arr = np.array([[p[1] for p in points], [p[2] for p in points]], dtype=float)
        tck, _ = splprep(arr, s=float(arr.shape[1]) * 6.0, k=min(3, arr.shape[1] - 1))
        uu = np.linspace(0.0, 1.0, n_out)
        out = splev(uu, tck)
        t0, t1 = points[0][0], points[-1][0]
        return [(int(round(t0 + (t1 - t0) * i / (n_out - 1))), float(a), float(b))
                for i, (a, b) in enumerate(zip(out[0], out[1]))]
    except Exception:
        return points


def build_overlay(
    *,
    pose: CameraPose,
    trajectory: Trajectory,
    t0_ms: int,
    image_points: list[dict],
    predicted: np.ndarray,            # rows of t_s, x, y, z from sample_path
    bounce_ms: int | None,
    impact_ms: int | None,
    corridor_half_m: float = 0.18,
) -> dict:
    path: list[dict] = []
    obs = sorted(((int(p["t_ms"]), float(p["u"]), float(p["v"])) for p in image_points), key=lambda p: p[0])
    for t, u, v in _smooth(obs):
        path.append({"t_ms": t, "phase": "flight", "u": round(u, 2), "v": round(v, 2)})
    for t, x, y, z in predicted:
        p = _pt(pose, x, y, z)
        if p is not None:
            path.append({"t_ms": int(t0_ms + t * 1000.0), "phase": "predicted", **p})

    def marker(t_ms: int | None) -> dict | None:
        if t_ms is None:
            return None
        x, y, z = trajectory.position(np.array([(t_ms - t0_ms) / 1000.0]))[0]
        p = _pt(pose, x, y, max(z, 0.0))
        return None if p is None else {"t_ms": int(t_ms), **p}

    def stumps(x: float) -> dict | None:
        base, top = _pt(pose, x, 0.0, 0.0), _pt(pose, x, 0.0, STUMP_HEIGHT_M)
        return None if base is None or top is None else {"base": base, "top": top}

    L, hw = pose.pitch_length_m, 3.05 / 2.0
    corridor = [_pt(pose, 0.0, -corridor_half_m, 0.0), _pt(pose, 0.0, corridor_half_m, 0.0),
                _pt(pose, L, corridor_half_m, 0.0), _pt(pose, L, -corridor_half_m, 0.0)]
    rect = [_pt(pose, 0.0, -hw, 0.0), _pt(pose, 0.0, hw, 0.0), _pt(pose, L, hw, 0.0), _pt(pose, L, -hw, 0.0)]
    centre = [q for q in (_pt(pose, L * i / 40, 0.0, 0.0) for i in range(41)) if q is not None]
    return {
        "path_px": path,
        "bounce_px": marker(bounce_ms),
        "impact_px": marker(impact_ms),
        "stumps_px": {"striker": stumps(0.0), "bowler": stumps(L)},
        "corridor_px": corridor if all(corridor) else None,
        "pitch_rect_px": rect if all(rect) else None,
        "centerline_px": centre if len(centre) >= 2 else None,
    }
