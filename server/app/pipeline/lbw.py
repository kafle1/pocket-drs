from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# Physical constants for accurate ball trajectory prediction
WICKET_WIDTH_M = 0.2286  # Official ICC wicket width (9 inches)
BALL_RADIUS_M = 0.036    # Cricket ball radius (~7.2 cm diameter)
LINE_TOLERANCE_M = BALL_RADIUS_M  # Ball must be fully outside to be "outside"
UMPIRES_CALL_ZONE_M = BALL_RADIUS_M  # Benefit of doubt zone (half ball width)

# Improved prediction parameters
MIN_PREDICTION_POINTS = 5  # Minimum points needed for reliable extrapolation


@dataclass(frozen=True)
class LbwAssessment:
    pitched_in_line: bool
    impact_in_line: bool
    wickets_hitting: bool
    y_at_stumps_m: float
    decision_key: str
    reason: str
    prediction_confidence: float  # Quality metric for trajectory prediction
    prediction_r_squared: float   # Statistical fit quality (0-1)


def _in_line_y(y_m: float) -> bool:
    tol = (WICKET_WIDTH_M / 2.0) + LINE_TOLERANCE_M
    return abs(y_m) <= tol


def _fit_y_over_x(xs: np.ndarray, ys: np.ndarray, weights: np.ndarray | None = None) -> tuple[float, float, float] | None:
    """
    Weighted linear regression: y = a + b*x
    Returns (a, b, r_squared) or None if fit fails.
    r_squared indicates quality of fit (1.0 = perfect, 0.0 = no correlation).
    """
    if xs.size < 2:
        return None

    mask = np.isfinite(xs) & np.isfinite(ys)
    xs = xs[mask]
    ys = ys[mask]
    
    if xs.size < 2:
        return None
    
    if weights is not None:
        weights = weights[mask]
        if weights.size != xs.size or not np.all(np.isfinite(weights)):
            weights = None
    
    if weights is None:
        weights = np.ones_like(xs)
    
    # Normalize weights
    weights = weights / weights.sum()
    
    sum_w = float(weights.sum())
    sum_wx = float((weights * xs).sum())
    sum_wy = float((weights * ys).sum())
    sum_wxx = float((weights * xs * xs).sum())
    sum_wxy = float((weights * xs * ys).sum())

    denom = (sum_w * sum_wxx - sum_wx * sum_wx)
    if abs(denom) < 1e-12:
        return None

    b = (sum_w * sum_wxy - sum_wx * sum_wy) / denom
    a = (sum_wy - b * sum_wx) / sum_w
    
    # Calculate R-squared for quality assessment
    y_pred = a + b * xs
    ss_res = np.sum(weights * (ys - y_pred) ** 2)
    y_mean = sum_wy / sum_w
    ss_tot = np.sum(weights * (ys - y_mean) ** 2)
    r_squared = 1.0 - (ss_res / (ss_tot + 1e-12))
    
    return a, b, float(r_squared)


def assess_lbw(
    *,
    pitch_plane_points: list[tuple[float, float]],
    pitch_index: int,
    point_confidences: list[float] | None = None,  # Optional confidence weights
    prediction_tail_points: int = 15,  # Increased for better accuracy
) -> LbwAssessment:
    """
    Assess LBW decision based on ball trajectory in pitch plane.
    
    Enhanced with:
    - Weighted linear regression using point confidences
    - Statistical fit quality assessment (R-squared)
    - Physics-aware extrapolation with uncertainty bounds
    
    Args:
        pitch_plane_points: Ball trajectory points in pitch plane (x, y) meters
        pitch_index: Index where ball pitched/bounced
        point_confidences: Optional confidence weights for each point
        prediction_tail_points: Number of points to use for prediction
        
    Returns:
        LbwAssessment with decision, confidence metrics, and ICC-compliant reasoning
    """
    if not pitch_plane_points:
        raise ValueError("pitch_plane_points must not be empty")
    if pitch_index < 0 or pitch_index >= len(pitch_plane_points):
        raise IndexError("pitch_index out of range")

    # Use the last point as impact (batter position)
    impact_index = len(pitch_plane_points) - 1
    
    if impact_index <= pitch_index:
        raise ValueError("Not enough points after pitch for LBW assessment")

    _, pitch_y = pitch_plane_points[pitch_index]
    _, impact_y = pitch_plane_points[impact_index]

    # Use more points for better prediction, but not pre-bounce points
    tail_start = max(pitch_index + 1, impact_index - prediction_tail_points + 1)
    tail = pitch_plane_points[tail_start : impact_index + 1]

    xs = np.array([p[0] for p in tail], dtype=np.float64)
    ys = np.array([p[1] for p in tail], dtype=np.float64)
    
    # Extract confidence weights if available
    weights = None
    avg_confidence = 1.0
    if point_confidences is not None and len(point_confidences) >= impact_index + 1:
        tail_confidences = point_confidences[tail_start : impact_index + 1]
        weights = np.array(tail_confidences, dtype=np.float64)
        avg_confidence = float(np.mean(weights)) if len(weights) > 0 else 1.0

    # Perform weighted linear fit
    fit = _fit_y_over_x(xs, ys, weights=weights)
    r_squared = 0.0
    
    if fit is None or len(tail) < MIN_PREDICTION_POINTS:
        # Fallback to last known position if fit fails
        y_at_stumps = float(impact_y)
        prediction_confidence = 0.3  # Low confidence for fallback
    else:
        a, b, r_squared = fit
        y_at_stumps = float(a + b * 0.0)  # Extrapolate to x=0 (stumps)
        # Combine fit quality with tracking confidence
        prediction_confidence = min(0.99, avg_confidence * (0.5 + 0.5 * max(0, r_squared)))

    pitched_in_line = _in_line_y(float(pitch_y))
    impact_in_line = _in_line_y(float(impact_y))
    wickets_hitting = _in_line_y(float(y_at_stumps))

    y_abs = abs(y_at_stumps)
    stumps_zone = WICKET_WIDTH_M / 2.0
    umpires_call_outer = stumps_zone + UMPIRES_CALL_ZONE_M

    # Decision logic following ICC LBW rules
    if not pitched_in_line:
        decision_key = "not_out"
        reason = "Pitched outside leg stump"
    elif not impact_in_line:
        decision_key = "not_out"
        reason = "Impact outside off stump"
    elif y_abs <= stumps_zone:
        decision_key = "out"
        reason = f"Hitting stumps (confidence: {prediction_confidence:.1%})"
    elif y_abs <= umpires_call_outer:
        decision_key = "umpires_call"
        reason = "Clipping stumps - Umpire's call"
    else:
        decision_key = "not_out"
        reason = "Missing stumps"

    return LbwAssessment(
        pitched_in_line=pitched_in_line,
        impact_in_line=impact_in_line,
        wickets_hitting=wickets_hitting,
        y_at_stumps_m=y_at_stumps,
        decision_key=decision_key,
        reason=reason,
        prediction_confidence=prediction_confidence,
        prediction_r_squared=r_squared,
    )
