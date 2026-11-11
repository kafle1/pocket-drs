"""Leg before wicket under Law 36 of the MCC Laws of Cricket, with the review bands of the
ICC playing conditions (Men's Test, Dec 2023, Appendix D 3.4) and the estimator's own
uncertainty folded in.

Three questions decide the appeal: did the ball pitch in line (or outside off), did it
strike the batter in line, and would it have hit the stumps. A monocular estimate of any
of these carries a calibrated interval; where the margin to a boundary is inside its guarded
half-width the verdict is umpire's call rather than a guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .calibration import STUMP_HEIGHT_M, STUMP_OUTER_HALF_M
from .reconstruction import BALL_RADIUS_M

OUT, NOT_OUT, UMPIRES_CALL = "out", "not_out", "umpires_call"
BAIL_RISE_M = 0.0127                                  # Law 8.3.1: bails sit at most 1.27 cm above the stumps


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str
    pitching_in_line: bool
    impact_in_line: bool
    wickets_hitting: bool | None     # None: no stump-plane prediction
    p_out: float                     # chance every check is clearly in, from the 1-sigmas; nan with no prediction
    p_not_out: float                 # chance one check is clearly out

    @property
    def tones(self) -> dict[str, str]:
        """Each DRS row's colour: out goes against the batter, not_out saves him, umpires_call is the close one."""
        def tone(ok: bool | None, close: str) -> str:
            return NOT_OUT if not ok else UMPIRES_CALL if self.decision == UMPIRES_CALL and close in self.reason else OUT
        return {"pitching": tone(self.pitching_in_line, "pitching close"),
                "impact": tone(self.impact_in_line, "impact close"),
                "wickets": tone(self.wickets_hitting, "clipping")}


def _band(value: float, outer: float, sigma: float, k: float) -> str:
    """Classify the ball centre's signed distance inside a boundary. Positive = inside.

    ICC umpire's call sits only outside the edge: centre outside but part of the ball still
    in, so ``outer`` is a ball radius for impact and wickets and 0 for pitching. ``sigma`` is the
    calibrated 95 % half-width over 1.96, and k*sigma widens that band on both sides."""
    g = k * sigma
    if value >= g:
        return "in"
    if value > -outer - g:
        return "marginal"
    return "out"


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _p(value: float, sigma: float) -> float:
    """Chance the true signed distance is above zero."""
    return _phi(value / sigma) if sigma > 0 else float(value > 0)


def _inside_zone(y: float, z: float, w: float, top: float) -> tuple[float, float, float]:
    """Signed distance from the ball centre into the stumps' face (negative outside, measured to the
    nearest edge or corner), and its slope in y and z."""
    dy, dz = abs(y) - w, z - top
    if dy > 0 and dz > 0:                              # beside and above: the corner is nearest
        r = math.hypot(dy, dz)
        return -r, -math.copysign(dy / r, y), -dz / r
    if dy >= dz:
        return -dy, -math.copysign(1.0, y), 0.0
    return -dz, 0.0, -1.0


def decide(
    *,
    leg_sign: float,
    pitch_y: float | None,
    pitch_sigma: float | None,
    impact_y: float | None,
    impact_sigma: float,
    stump_y: float | None,
    stump_z: float | None,
    sigma_y: float | None,
    sigma_z: float | None,
    k: float = 1.0,
    stump_half: float = STUMP_OUTER_HALF_M,
    stump_height: float = STUMP_HEIGHT_M,
    ball_radius: float = BALL_RADIUS_M,
    shot_played: bool = True,
) -> Verdict:
    """``leg_sign`` maps world +y onto the batter's leg side (+1 or -1). Lateral quantities
    are metres from the middle-stump line, distances in the reasons are from the outer edge of
    the stumps; ``stump_z`` is the ball-centre height at the stump plane. Any None means the
    quantity was not measured. The stumps are the ones in the clip, regulation unless stated."""
    R = ball_radius
    w = stump_half
    top_m = stump_height + BAIL_RISE_M      # ICC 2021: zone top is the top of the stumps with bails
    reasons: list[str] = []
    close: list[str] = []
    p_in, p_clear = [], []                  # per check: chance clearly in, and chance not clearly out

    # Law 36.1.3: a ball pitching outside the line of the leg stump cannot bring an lbw.
    # Judged on the ball centre with no umpire's call (Appendix D 3.4.4).
    pitching = True
    if pitch_y is not None:
        leg_dist = w - pitch_y * leg_sign          # positive = on or inside the leg line
        p_in.append(_p(leg_dist, pitch_sigma))
        p_clear.append(p_in[-1])
        state = _band(leg_dist, 0.0, pitch_sigma, k)
        if state == "out":
            pitching = False
            reasons.append(f"pitched outside leg ({-leg_dist * 100:.0f} cm outside the stump line)")
        elif state == "marginal":
            close.append("pitching close to leg stump")

    # Law 36.1.4: impact outside off is not out only when a shot was offered; outside leg never is.
    impact = True
    if impact_y is not None and (shot_played or impact_y * leg_sign > 0):
        dist = w - abs(impact_y)
        p_in.append(_p(dist, impact_sigma))
        p_clear.append(_p(dist + R, impact_sigma))
        state = _band(dist, R, impact_sigma, k)
        if state == "out":
            impact = False
            side = "leg" if impact_y * leg_sign > 0 else "off"
            reasons.append(f"impact outside {side} ({-dist * 100:.0f} cm outside the stump line)")
        elif state == "marginal":
            close.append("impact close to the stump line")

    hitting = None                 # unknown without a stump-plane prediction
    if stump_y is not None and stump_z is not None:
        d, gy, gz = _inside_zone(stump_y, stump_z, w, top_m)
        s = math.hypot(gy * sigma_y, gz * sigma_z)
        p_in.append(_p(d, s))
        p_clear.append(_p(d + R, s))
        state = _band(d, R, s, k)
        if state == "out" or stump_z < 0.0:
            hitting = False
            reasons.append("missing the stumps")
        else:
            hitting = True
            if state == "marginal":
                close.append("clipping the stumps")
    else:
        reasons.append("no stump-plane prediction")
    p_out = math.prod(p_in) if hitting is not None else float("nan")
    p_not_out = 1.0 - math.prod(p_clear) if hitting is not None else float("nan")

    # a clear fail on any of the three is not out, even when another one is marginal or unmeasured
    if pitching and impact and hitting is not False:
        if close or hitting is None:
            why = "no stump-plane prediction" if hitting is None else ", ".join(close)
            return Verdict(UMPIRES_CALL, f"umpire's call: {why}", pitching, impact, hitting, p_out, p_not_out)
        return Verdict(OUT, "hitting the stumps", pitching, impact, hitting, p_out, p_not_out)
    return Verdict(NOT_OUT, "; ".join(reasons) or "not out", pitching, impact, hitting, p_out, p_not_out)
