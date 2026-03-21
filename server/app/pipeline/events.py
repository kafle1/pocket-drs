from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EventEstimate:
    index: int
    confidence: float


# ---------------------------------------------------------------------------
# Pixel-space heuristics (used when no calibration is available)
# ---------------------------------------------------------------------------

def estimate_bounce_index(y_px: list[float]) -> EventEstimate:
    """Heuristic bounce estimate using image Y motion.

    In image coordinates Y increases downward. A bounce typically shows
    a short upward movement (Y decreases) after a period of downward
    movement.
    """
    n = len(y_px)
    if n < 5:
        return EventEstimate(index=max(0, n - 1), confidence=0.1)

    dy = [y_px[i] - y_px[i - 1] for i in range(1, n)]

    for i in range(2, len(dy) - 1):
        if dy[i - 1] > 0 and dy[i] < 0:
            return EventEstimate(index=i, confidence=0.6)

    return EventEstimate(index=max(1, n // 3), confidence=0.2)


def estimate_impact_index(n_points: int) -> EventEstimate:
    if n_points <= 0:
        return EventEstimate(index=0, confidence=0.0)
    return EventEstimate(index=n_points - 1, confidence=0.5)


# ---------------------------------------------------------------------------
# Pitch-plane heuristics (calibrated)
# ---------------------------------------------------------------------------

def estimate_bounce_index_from_pitch_plane(
    x_m: list[float],
    y_m: list[float],
    pitch_length_m: float = 20.12,
) -> EventEstimate:
    """Estimate bounce using pitch-plane coordinates.

    The ball approaches from the bowler end (x ~ pitch_length) toward the
    striker end (x ~ 0), OR vice versa. Bounce is the first point in the
    realistic pitching zone where the trajectory shows a significant
    velocity change (deceleration on pitch contact).
    """
    n = len(x_m)
    if n < 5:
        return EventEstimate(index=max(0, n - 1), confidence=0.1)

    xs = np.array(x_m, dtype=float)
    ys = np.array(y_m, dtype=float)

    # Determine bowling direction.
    decreasing = xs[-1] < xs[0]  # bowler→striker = decreasing x
    zone_lo = pitch_length_m * 0.10
    zone_hi = pitch_length_m * 0.90

    dx = np.diff(xs)
    dy = np.diff(ys)

    # Smooth dx to reduce noise.
    if len(dx) >= 3:
        kernel = np.array([0.25, 0.5, 0.25])
        dx_smooth = np.convolve(dx, kernel, mode="same")
    else:
        dx_smooth = dx

    best_idx = -1
    best_conf = 0.0

    # Strategy 1: Look for x-velocity kink (deceleration at bounce).
    # The ball slows along x when it contacts the pitch.
    for i in range(2, n - 2):
        if not (zone_lo <= xs[i] <= zone_hi):
            continue

        if i < len(dx_smooth) and i + 1 < len(dx_smooth):
            v_before = abs(dx_smooth[i - 1]) + abs(dx_smooth[i])
            v_after = abs(dx_smooth[i]) + abs(dx_smooth[i + 1])
            if v_before > 0.05:  # minimum velocity threshold
                ratio = v_after / v_before
                if ratio < 0.5 or ratio > 2.0:
                    conf = 0.65
                    if best_idx < 0 or conf > best_conf:
                        best_idx = i
                        best_conf = conf
                    break  # take first significant kink

    # Strategy 2: y direction change (lateral deviation at bounce).
    if best_idx < 0:
        noise_thresh = 0.01  # m — ignore tiny lateral jitter
        for i in range(2, n - 1):
            if not (zone_lo <= xs[i] <= zone_hi):
                continue
            if i < len(dy) and i - 1 >= 0:
                if abs(dy[i - 1]) > noise_thresh and abs(dy[i]) > noise_thresh:
                    if np.sign(dy[i]) != np.sign(dy[i - 1]):
                        return EventEstimate(index=i, confidence=0.70)

    if best_idx >= 0:
        return EventEstimate(index=best_idx, confidence=best_conf)

    # Fallback: first point inside the pitching zone (from bowler's end).
    indices = range(n) if not decreasing else range(n)
    for i in indices:
        if zone_lo <= xs[i] <= zone_hi:
            return EventEstimate(index=i, confidence=0.25)

    return EventEstimate(index=max(1, n // 3), confidence=0.15)


def estimate_impact_index_from_pitch_plane(
    x_m: list[float],
    pitch_length_m: float = 20.12,
) -> EventEstimate:
    """Estimate impact — the first point near the striker crease (x ~ 0),
    guaranteed to be after a plausible bounce position.

    Handles both bowling directions: if x is decreasing (bowler→striker),
    impact is near x=0. If increasing, impact is near x=pitch_length.
    """
    n = len(x_m)
    if n <= 0:
        return EventEstimate(index=0, confidence=0.0)

    xs = np.array(x_m, dtype=float)

    # Determine bowling direction: ball travels toward lower or higher x.
    decreasing = xs[-1] < xs[0]

    if decreasing:
        crease_limit = 2.0  # striker crease at x ~ 0
        start = max(1, n // 3)
        for i in range(start, n):
            if xs[i] <= crease_limit:
                return EventEstimate(index=i, confidence=0.7)
        # Fallback: point with minimum x past 1/3 of track.
        sub = xs[start:]
        if len(sub) > 0:
            idx = int(np.argmin(sub)) + start
            return EventEstimate(index=idx, confidence=0.4)
    else:
        crease_limit = pitch_length_m - 2.0  # striker crease at x ~ pitch_length
        start = max(1, n // 3)
        for i in range(start, n):
            if xs[i] >= crease_limit:
                return EventEstimate(index=i, confidence=0.7)
        sub = xs[start:]
        if len(sub) > 0:
            idx = int(np.argmax(sub)) + start
            return EventEstimate(index=idx, confidence=0.4)

    idx = int(np.argmin(np.abs(xs)))
    return EventEstimate(index=idx, confidence=0.3)
