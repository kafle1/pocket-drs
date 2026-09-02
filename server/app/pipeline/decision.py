"""Leg before wicket under Law 36 of the MCC Laws of Cricket, with the review bands the
ICC playing conditions use for ball tracking and the estimator's own uncertainty folded in.

Three questions decide the appeal: did the ball pitch in line (or outside off), did it
strike the batter in line, and would it have hit the stumps. A monocular estimate of any
of these carries a stated 1-sigma bound; where the margin to a boundary is inside that
bound the verdict is umpire's call rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calibration import STUMP_HEIGHT_M, STUMP_OUTER_HALF_M
from .reconstruction import BALL_RADIUS_M

OUT, NOT_OUT, UMPIRES_CALL = "out", "not_out", "umpires_call"


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str
    pitching_in_line: bool
    impact_in_line: bool
    wickets_hitting: bool


def _band(value: float, edge: float, sigma: float, k: float) -> str:
    """Classify a signed distance to a boundary. Positive = inside.

    ``edge`` is the ICC umpire's-call width (a ball radius: less than half the ball inside
    the line is the umpire's decision). The band is widened to the estimate's own k-sigma
    when that is larger, so a marginal monocular call is never asserted."""
    band = max(edge, k * sigma)
    if value >= band:
        return "in"
    if value >= -band:
        return "marginal"
    return "out"


def decide(
    *,
    leg_sign: float,
    pitch_y: float | None,
    pitch_sigma: float,
    impact_y: float | None,
    impact_sigma: float,
    stump_y: float | None,
    stump_z: float | None,
    sigma_y: float,
    sigma_z: float,
    k: float = 1.0,
) -> Verdict:
    """``leg_sign`` maps world +y onto the batter's leg side (+1 or -1). Lateral quantities
    are metres from the middle-stump line; ``stump_z`` is the ball-centre height at the
    stump plane. Any None means the quantity was not measured."""
    R = BALL_RADIUS_M
    w = STUMP_OUTER_HALF_M
    reasons: list[str] = []
    marginal = False

    # Law 36.1.3: a ball pitching outside the line of the leg stump cannot bring an lbw
    pitching = True
    if pitch_y is not None:
        leg_dist = w - pitch_y * leg_sign          # positive = on or inside the leg line
        state = _band(leg_dist, R, pitch_sigma, k)
        if state == "out":
            pitching = False
            reasons.append(f"pitched outside leg ({abs(pitch_y) * 100:.0f} cm)")
        elif state == "marginal":
            marginal = True

    # Law 36.1.4: impact outside the line of off is not out if a shot was offered. We cannot
    # see the shot, so impact outside the line on either side is treated as not in line,
    # which is the batter's benefit.
    impact = True
    if impact_y is not None:
        dist = w - abs(impact_y)
        state = _band(dist, R, impact_sigma, k)
        if state == "out":
            impact = False
            side = "leg" if impact_y * leg_sign > 0 else "off"
            reasons.append(f"impact outside {side} ({abs(impact_y) * 100:.0f} cm)")
        elif state == "marginal":
            marginal = True

    hitting = False
    if stump_y is not None and stump_z is not None:
        lat = _band(w - abs(stump_y), R, sigma_y, k)
        top = _band(STUMP_HEIGHT_M - stump_z, R, sigma_z, k)
        if lat == "out" or top == "out" or stump_z < 0.0:
            reasons.append("missing the stumps")
        else:
            hitting = True
            if lat == "marginal" or top == "marginal":
                marginal = True
    else:
        reasons.append("no stump-plane prediction")

    if pitching and impact and hitting:
        if marginal:
            return Verdict(UMPIRES_CALL, "umpire's call: clipping the stumps", pitching, impact, hitting)
        return Verdict(OUT, "hitting the stumps", pitching, impact, hitting)
    if marginal and pitching and impact:
        return Verdict(UMPIRES_CALL, "umpire's call: " + "; ".join(reasons), pitching, impact, hitting)
    return Verdict(NOT_OUT, "; ".join(reasons) or "not out", pitching, impact, hitting)
