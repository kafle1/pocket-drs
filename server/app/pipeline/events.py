from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventEstimate:
    index: int
    confidence: float


def estimate_bounce_index(y_px: list[float]) -> EventEstimate:
    """Heuristic bounce estimate using image Y motion.

    In image coordinates, Y typically increases downward.
    A bounce often produces a short upward movement (Y decreases) after a period
    of downward movement.

    This is a heuristic, not a certified detection.
    """

    n = len(y_px)
    if n < 5:
        return EventEstimate(index=max(0, n - 1), confidence=0.1)

    dy = [y_px[i] - y_px[i - 1] for i in range(1, n)]

    # Find a sign change from positive (down) to negative (up).
    for i in range(2, len(dy) - 1):
        if dy[i - 1] > 0 and dy[i] < 0:
            return EventEstimate(index=i, confidence=0.6)

    # Fallback: pick a plausible early point.
    return EventEstimate(index=max(1, n // 3), confidence=0.2)


def estimate_impact_index(n_points: int) -> EventEstimate:
    if n_points <= 0:
        return EventEstimate(index=0, confidence=0.0)
    return EventEstimate(index=n_points - 1, confidence=0.5)
