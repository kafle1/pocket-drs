"""LBW Decision Engine (ICC Rule 36 compliant).

Assesses LBW decisions from 3D ball trajectory.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ICC-standard cricket dimensions
WICKET_WIDTH_M = 0.2286  # 9 inches
WICKET_HEIGHT_M = 0.71   # 28 inches (stump height)
BALL_RADIUS_M = 0.036    # Cricket ball radius
STUMPS_X_M = 0.0         # Striker stumps at X=0


@dataclass(frozen=True)
class LBWDecision:
    """LBW decision result."""
    pitched_in_line: bool
    impact_in_line: bool
    hitting_stumps: bool
    decision: str  # "OUT", "NOT OUT", "UMPIRES CALL"
    reason: str
    confidence: float  # 0-1


def assess_lbw_3d(
    *,
    trajectory_3d: list[tuple[float, float, float]],  # [(x, y, z), ...]
    impact_point_3d: tuple[float, float, float],
    impact_on_pad: bool,
) -> LBWDecision:
    """Assess LBW from 3D trajectory.
    
    Args:
        trajectory_3d: Ball positions in world coords (meters)
        impact_point_3d: Impact position (x, y, z)
        impact_on_pad: True if hit pad (not bat)
        
    Returns:
        LBW decision with reasoning
    """
    if not impact_on_pad:
        return LBWDecision(
            pitched_in_line=False,
            impact_in_line=False,
            hitting_stumps=False,
            decision="NOT OUT",
            reason="Ball hit bat before pad",
            confidence=1.0,
        )
    
    # 1. Check pitching point
    bounce_point = _find_bounce_point(trajectory_3d)
    if bounce_point is None:
        return LBWDecision(
            pitched_in_line=False,
            impact_in_line=False,
            hitting_stumps=False,
            decision="NOT OUT",
            reason="Cannot determine pitching point",
            confidence=0.0,
        )
    
    pitch_x, pitch_y, pitch_z = bounce_point
    
    # Outside leg side check (ICC Rule 36.1.3)
    if pitch_y > (WICKET_WIDTH_M / 2 + BALL_RADIUS_M):
        return LBWDecision(
            pitched_in_line=False,
            impact_in_line=False,
            hitting_stumps=False,
            decision="NOT OUT",
            reason="Pitched outside leg stump",
            confidence=0.95,
        )
    
    pitched_in_line = True
    
    # 2. Check impact point
    imp_x, imp_y, imp_z = impact_point_3d
    
    # Outside off stump check (only if offering shot)
    # Simplified: assume offering shot
    impact_lateral_distance = abs(imp_y)
    
    if impact_lateral_distance > (WICKET_WIDTH_M / 2 + BALL_RADIUS_M):
        return LBWDecision(
            pitched_in_line=pitched_in_line,
            impact_in_line=False,
            hitting_stumps=False,
            decision="NOT OUT",
            reason="Impact outside off stump line",
            confidence=0.92,
        )
    
    impact_in_line = True
    
    # 3. Predict if ball would hit stumps
    hitting = _predict_hitting_stumps(trajectory_3d, impact_point_3d)
    
    if not hitting:
        return LBWDecision(
            pitched_in_line=pitched_in_line,
            impact_in_line=impact_in_line,
            hitting_stumps=False,
            decision="NOT OUT",
            reason="Ball missing stumps",
            confidence=0.90,
        )
    
    # All conditions met
    return LBWDecision(
        pitched_in_line=True,
        impact_in_line=True,
        hitting_stumps=True,
        decision="OUT",
        reason="All LBW conditions satisfied",
        confidence=0.90,
    )


def _find_bounce_point(trajectory: list[tuple[float, float, float]]) -> tuple[float, float, float] | None:
    """Find bounce point (where z ≈ ball_radius)."""
    for i, (x, y, z) in enumerate(trajectory):
        if i == 0:
            continue
        
        prev_z = trajectory[i-1][2]
        
        # Bounce detected: ball near ground and descending then ascending
        if z < BALL_RADIUS_M * 2 and prev_z > z:
            # Check next point if available
            if i + 1 < len(trajectory):
                next_z = trajectory[i+1][2]
                if next_z > z:
                    return (x, y, z)
    
    return None


def _predict_hitting_stumps(
    trajectory: list[tuple[float, float, float]],
    impact_point: tuple[float, float, float],
) -> bool:
    """Predict if ball would hit stumps using physics simulation."""
    # Find impact index
    imp_x, imp_y, imp_z = impact_point
    impact_idx = 0
    min_dist = float('inf')
    
    for i, (x, y, z) in enumerate(trajectory):
        dist = np.sqrt((x - imp_x)**2 + (y - imp_y)**2 + (z - imp_z)**2)
        if dist < min_dist:
            min_dist = dist
            impact_idx = i
    
    # Get velocity at impact (finite difference)
    if impact_idx == 0 or impact_idx >= len(trajectory) - 1:
        return False
    
    pre_point = trajectory[impact_idx - 1]
    post_point = trajectory[impact_idx + 1]
    
    dt = 0.01  # Assume 100 FPS spacing
    vx = (post_point[0] - pre_point[0]) / (2 * dt)
    vy = (post_point[1] - pre_point[1]) / (2 * dt)
    vz = (post_point[2] - pre_point[2]) / (2 * dt)
    
    # Simulate forward to stumps
    x, y, z = impact_point
    GRAVITY = 9.81
    
    for _ in range(200):  # Max 2 seconds
        x += vx * dt
        y += vy * dt
        z += vz * dt
        vz -= GRAVITY * dt
        
        # Reached stump plane
        if x <= STUMPS_X_M:
            # Check if ball intersects stump cylinder
            lateral_dist = abs(y)
            if lateral_dist <= (WICKET_WIDTH_M / 2 + BALL_RADIUS_M):
                if 0 <= z <= (WICKET_HEIGHT_M + BALL_RADIUS_M):
                    return True
            break
        
        # Ball went too high or underground
        if z < -0.1 or z > 3.0:
            break
    
    return False
