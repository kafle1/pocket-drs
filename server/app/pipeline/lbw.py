from __future__ import annotations

from dataclasses import dataclass

import numpy as np


WICKET_WIDTH_M = 0.2286
BALL_RADIUS_M = 0.036
LINE_TOLERANCE_M = BALL_RADIUS_M
UMPIRES_CALL_ZONE_M = BALL_RADIUS_M


@dataclass(frozen=True)
class LbwAssessment:
    pitched_in_line: bool
    impact_in_line: bool
    wickets_hitting: bool
    y_at_stumps_m: float
    decision: str


def _in_line_y(y_m: float) -> bool:
    tol = (WICKET_WIDTH_M / 2.0) + LINE_TOLERANCE_M
    return abs(y_m) <= tol


def _fit_y_over_x(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float] | None:
    # y = a + b*x
    if xs.size < 2:
        return None

    mask = np.isfinite(xs) & np.isfinite(ys)
    xs = xs[mask]
    ys = ys[mask]
    if xs.size < 2:
        return None

    sum_x = float(xs.sum())
    sum_y = float(ys.sum())
    sum_xx = float((xs * xs).sum())
    sum_xy = float((xs * ys).sum())
    n = float(xs.size)

    denom = (n * sum_xx - sum_x * sum_x)
    if abs(denom) < 1e-9:
        return None

    b = (n * sum_xy - sum_x * sum_y) / denom
    a = (sum_y - b * sum_x) / n
    return a, b


def assess_lbw(
    *,
    pitch_plane_points: list[tuple[float, float]],
    pitch_index: int,
    impact_index: int,
    prediction_tail_points: int = 10,
) -> LbwAssessment:
    if not pitch_plane_points:
        raise ValueError("pitch_plane_points must not be empty")
    if pitch_index < 0 or pitch_index >= len(pitch_plane_points):
        raise IndexError("pitch_index out of range")
    if impact_index < 0 or impact_index >= len(pitch_plane_points):
        raise IndexError("impact_index out of range")
    if impact_index <= pitch_index:
        raise ValueError("impact_index must be > pitch_index")

    pitch_x, pitch_y = pitch_plane_points[pitch_index]
    impact_x, impact_y = pitch_plane_points[impact_index]

    tail_start = max(pitch_index + 1, impact_index - prediction_tail_points + 1)
    tail = pitch_plane_points[tail_start : impact_index + 1]

    xs = np.array([p[0] for p in tail], dtype=np.float64)
    ys = np.array([p[1] for p in tail], dtype=np.float64)

    fit = _fit_y_over_x(xs, ys)
    if fit is None:
        y_at_stumps = float(impact_y)
    else:
        a, b = fit
        y_at_stumps = float(a + b * 0.0)

    pitched_in_line = _in_line_y(float(pitch_y))
    impact_in_line = _in_line_y(float(impact_y))
    wickets_hitting = _in_line_y(float(y_at_stumps))

    y_abs = abs(y_at_stumps)
    stumps_zone = WICKET_WIDTH_M / 2.0
    umpires_call_outer = stumps_zone + UMPIRES_CALL_ZONE_M

    if y_abs <= stumps_zone:
        wicket_decision = "OUT"
    elif y_abs <= umpires_call_outer:
        wicket_decision = "UMPIRE'S CALL - Clipping stumps"
    else:
        wicket_decision = "NOT OUT - Missing stumps"

    if not pitched_in_line:
        decision = "NOT OUT - Pitched outside leg"
    elif not impact_in_line:
        decision = "NOT OUT - Impact outside line"
    else:
        decision = wicket_decision

    return LbwAssessment(
        pitched_in_line=pitched_in_line,
        impact_in_line=impact_in_line,
        wickets_hitting=wickets_hitting,
        y_at_stumps_m=y_at_stumps,
        decision=decision,
    )
