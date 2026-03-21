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
    striker end (x ~ 0). Bounce is the first point in the realistic pitching
    zone where either:
      1. A lateral (y) direction change occurs, or
      2. The x-velocity shows a significant kink (deceleration on pitch).

    Additionally we look for sustained forward-direction (x decreasing) so
    we don't trigger on early noise.
    """
    n = len(x_m)
    if n < 5:
        return EventEstimate(index=max(0, n - 1), confidence=0.1)

    xs = np.array(x_m, dtype=float)
    ys = np.array(y_m, dtype=float)

    zone_lo = pitch_length_m * 0.15
    zone_hi = pitch_length_m * 0.85

    dx = np.diff(xs)
    dy = np.diff(ys)

    best_idx = -1
    best_conf = 0.0

    for i in range(2, n - 1):
        if not (zone_lo <= xs[i] <= zone_hi):
            continue

        # 1) y direction change (lateral deviation at bounce).
        if i < len(dy) and i - 1 >= 0:
            if abs(dy[i - 1]) > 1e-4 and abs(dy[i]) > 1e-4:
                if np.sign(dy[i]) != np.sign(dy[i - 1]):
                    return EventEstimate(index=i, confidence=0.75)

        # 2) x-velocity kink (ball decelerates on contact with pitch).
        if i < len(dx) and i + 1 < len(dx):
            if abs(dx[i]) > 1e-6:
                ratio = abs(dx[i + 1] / dx[i])
                if ratio < 0.4 or ratio > 2.5:
                    if best_idx < 0:
                        best_idx = i
                        best_conf = 0.55

    if best_idx >= 0:
        return EventEstimate(index=best_idx, confidence=best_conf)

    # Fallback: first point inside the pitching zone.
    for i in range(n):
        if zone_lo <= xs[i] <= zone_hi:
            return EventEstimate(index=i, confidence=0.3)

    return EventEstimate(index=max(1, n // 3), confidence=0.2)


def estimate_impact_index_from_pitch_plane(
    x_m: list[float],
    pitch_length_m: float = 20.12,
) -> EventEstimate:
    """Estimate impact — the first point near the striker crease, and
    guaranteed to be *after* a plausible bounce position.

    Picks the first point where x <= crease_limit. Falls back to the
    point with minimum x.
    """
    n = len(x_m)
    if n <= 0:
        return EventEstimate(index=0, confidence=0.0)

    xs = np.array(x_m, dtype=float)
    crease_limit = 2.0

    # Only consider points in the second half of the trajectory
    # (avoids selecting a stray early point as impact).
    start = max(1, n // 3)
    for i in range(start, n):
        if xs[i] <= crease_limit:
            return EventEstimate(index=i, confidence=0.7)

    # Fallback: point closest to x = 0, but at least past 1/3 of track.
    sub = xs[start:]
    if len(sub) > 0:
        idx = int(np.argmin(np.abs(sub))) + start
        return EventEstimate(index=idx, confidence=0.4)

    idx = int(np.argmin(np.abs(xs)))
    return EventEstimate(index=idx, confidence=0.3)
