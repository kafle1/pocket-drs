"""
Physics-Constrained 3D Reconstruction for Cricket Ball Tracking

Implements monocular 3D trajectory estimation using projectile motion constraints.
This is the core innovation that allows accurate 3D tracking from a single camera.

Key Concept:
- A ball follows physics: x(t) = x₀ + v_x·t, z(t) = z₀ + v_z·t - 0.5·g·t²
- Each 2D detection gives a camera ray: ray = K⁻¹·[u, v, 1]
- We optimize depth (scale) along each ray to fit projectile motion

References:
- "What Players do with the Ball" (CVPR 2015) - Maksai et al.
- "Physics-based modeling" - Standard computer vision technique
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from .intrinsic_calib import IntrinsicParameters


# Physical constants
GRAVITY_MS2 = 9.81  # Earth's gravity
BALL_RADIUS_M = 0.036  # Cricket ball radius (7.2cm diameter)
BOUNCE_RESTITUTION = 0.55  # Coefficient of restitution for cricket ball on pitch


class ReconstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrajectoryState:
    """Complete 3D ball trajectory state.
    
    Attributes:
        position_m: [x, y, z] in world coordinates (meters)
        velocity_ms: [vx, vy, vz] in world coordinates (m/s)
        time_s: Time since release (seconds)
        confidence: Fit quality metric (0-1)
    """
    position_m: np.ndarray  # shape (3,)
    velocity_ms: np.ndarray  # shape (3,)
    time_s: float
    confidence: float

    def speed_ms(self) -> float:
        """Total speed magnitude."""
        return float(np.linalg.norm(self.velocity_ms))


@dataclass(frozen=True)
class Detection2D:
    """Single 2D ball detection from camera."""
    pixel_x: float
    pixel_y: float
    time_s: float
    confidence: float


def reconstruct_trajectory_3d(
    *,
    detections: list[Detection2D],
    intrinsics: IntrinsicParameters,
    extrinsics_R: np.ndarray,  # 3x3 rotation: world -> camera
    extrinsics_T: np.ndarray,  # 3x1 translation: world -> camera
    initial_guess: dict | None = None,
) -> list[TrajectoryState]:
    """Reconstruct 3D ball trajectory from 2D detections using physics constraints.
    
    Args:
        detections: List of 2D ball detections with timestamps
        intrinsics: Camera intrinsic parameters (K matrix, distortion)
        extrinsics_R: Rotation matrix (world to camera coordinates)
        extrinsics_T: Translation vector (world to camera coordinates)
        initial_guess: Optional initial parameters for optimization
        
    Returns:
        List of 3D trajectory states (one per detection)
        
    Raises:
        ReconstructionError: If optimization fails or insufficient data
        
    Algorithm:
    1. For each detection, compute camera ray: ray_i = K⁻¹ [u_i, v_i, 1]ᵀ
    2. Optimize [x₀, y₀, z₀, vₓ, vᵧ, v_z, t_release] to minimize:
           Σᵢ weight_i · ||P_projected(t_i) - P_observed(t_i)||²
       Subject to: P(t) = P₀ + V·t - [0, 0, 0.5·g·t²]ᵀ
    3. Return full 3D trajectory with confidence scores
    """
    if len(detections) < 5:
        raise ReconstructionError("Need at least 5 detections for reliable 3D reconstruction")
    
    # Sort detections by time
    detections = sorted(detections, key=lambda d: d.time_s)
    
    # Extract observations
    times = np.array([d.time_s for d in detections])
    pixels_u = np.array([d.pixel_x for d in detections])
    pixels_v = np.array([d.pixel_y for d in detections])
    confidences = np.array([d.confidence for d in detections])
    
    # Normalize times (relative to first detection)
    t_offset = times[0]
    times = times - t_offset
    
    # Initial guess for optimization
    if initial_guess is None:
        # Heuristic: assume ball is ~10m away, moving at ~20 m/s
        initial_guess = {
            "x0": 10.0,      # Distance from camera
            "y0": 0.0,       # Lateral position
            "z0": 1.5,       # Height above ground
            "vx": -15.0,     # Approaching camera
            "vy": 0.0,       # Lateral velocity
            "vz": -5.0,      # Downward component
            "t_release": 0.0,  # Release time offset
        }
    
    params_init = np.array([
        initial_guess["x0"],
        initial_guess["y0"],
        initial_guess["z0"],
        initial_guess["vx"],
        initial_guess["vy"],
        initial_guess["vz"],
        initial_guess["t_release"],
    ])
    
    # Define optimization problem
    def residuals(params):
        x0, y0, z0, vx, vy, vz, t_release = params
        
        errors = []
        for i, t_obs in enumerate(times):
            t = t_obs - t_release
            
            # Penalize invalid times
            if t < 0:
                errors.extend([1000.0, 1000.0])
                continue
            
            # 3D position at time t (projectile motion)
            x = x0 + vx * t
            y = y0 + vy * t
            z = z0 + vz * t - 0.5 * GRAVITY_MS2 * t**2
            
            # Sanity checks
            if z < -0.5 or z > 10.0:  # Ball underground or too high
                errors.extend([1000.0, 1000.0])
                continue
            
            P_world = np.array([x, y, z])
            
            # Transform to camera coordinates
            P_cam = extrinsics_R @ P_world + extrinsics_T.flatten()
            
            # Prevent division by zero
            if P_cam[2] < 0.1:  # Behind camera or too close
                errors.extend([1000.0, 1000.0])
                continue
            
            # Project to image
            P_img = intrinsics.camera_matrix @ P_cam
            u_pred = P_img[0] / P_img[2]
            v_pred = P_img[1] / P_img[2]
            
            # Weighted residual
            weight = confidences[i]
            errors.append(weight * (u_pred - pixels_u[i]))
            errors.append(weight * (v_pred - pixels_v[i]))
        
        return np.array(errors)
    
    # Solve using Levenberg-Marquardt
    try:
        result = least_squares(
            residuals,
            params_init,
            method='lm',  # Levenberg-Marquardt
            max_nfev=1000,
            ftol=1e-6,
            xtol=1e-6,
        )
    except Exception as e:
        raise ReconstructionError(f"Optimization failed: {e}")
    
    if not result.success:
        raise ReconstructionError(f"Optimization did not converge: {result.message}")
    
    # Extract optimized parameters
    x0, y0, z0, vx, vy, vz, t_release = result.x
    
    # Calculate fit quality (R²-like metric)
    residual_norm = np.linalg.norm(result.fun)
    total_observations = len(detections) * 2
    avg_residual = residual_norm / np.sqrt(total_observations)
    
    # Convert to confidence (lower residual = higher confidence)
    confidence = np.exp(-avg_residual / 10.0)  # Exponential decay
    confidence = float(np.clip(confidence, 0.0, 1.0))
    
    # Reconstruct full trajectory
    trajectory = []
    for t_obs in times:
        t = t_obs - t_release
        
        # 3D position
        x = x0 + vx * t
        y = y0 + vy * t
        z = z0 + vz * t - 0.5 * GRAVITY_MS2 * t**2
        
        # Velocity (accounting for gravity)
        vx_t = vx
        vy_t = vy
        vz_t = vz - GRAVITY_MS2 * t
        
        state = TrajectoryState(
            position_m=np.array([x, y, z]),
            velocity_ms=np.array([vx_t, vy_t, vz_t]),
            time_s=t_obs + t_offset,
            confidence=confidence,
        )
        trajectory.append(state)
    
    return trajectory


def detect_bounce(trajectory: list[TrajectoryState]) -> int | None:
    """Detect bounce point in trajectory (sudden change in vertical velocity).
    
    Returns:
        Index of bounce point, or None if no bounce detected
    """
    if len(trajectory) < 3:
        return None
    
    for i in range(1, len(trajectory) - 1):
        z_prev = trajectory[i - 1].position_m[2]
        z_curr = trajectory[i].position_m[2]
        z_next = trajectory[i + 1].position_m[2]
        
        vz_before = trajectory[i - 1].velocity_ms[2]
        vz_after = trajectory[i + 1].velocity_ms[2]
        
        # Bounce criteria:
        # 1. Ball near ground (z ≈ ball_radius)
        # 2. Vertical velocity changes sign
        if z_curr < 2 * BALL_RADIUS_M and z_curr < z_prev and z_curr < z_next:
            if vz_before < 0 and vz_after > 0:
                return i
    
    return None


def apply_bounce_physics(
    velocity_before: np.ndarray,
    surface_normal: np.ndarray = np.array([0, 0, 1]),  # Ground normal (upward)
) -> np.ndarray:
    """Apply bounce physics to velocity vector.
    
    Args:
        velocity_before: Velocity vector before bounce [vx, vy, vz]
        surface_normal: Surface normal vector (default: vertical ground)
        
    Returns:
        Velocity vector after bounce
    """
    # Decompose velocity into normal and tangential components
    v_normal = np.dot(velocity_before, surface_normal) * surface_normal
    v_tangential = velocity_before - v_normal
    
    # Apply coefficient of restitution to normal component (reverses direction)
    v_normal_after = -BOUNCE_RESTITUTION * v_normal
    
    # Tangential component preserved (ignoring friction for simplicity)
    velocity_after = v_tangential + v_normal_after
    
    return velocity_after


def predict_trajectory_forward(
    *,
    initial_state: TrajectoryState,
    duration_s: float,
    dt_s: float = 0.01,
) -> list[TrajectoryState]:
    """Simulate ball trajectory forward in time using physics.
    
    Used for post-impact prediction (Hawk-Eye style).
    
    Args:
        initial_state: Starting state (position + velocity)
        duration_s: How long to simulate
        dt_s: Time step for simulation (default: 10ms)
        
    Returns:
        Predicted trajectory states
    """
    states = []
    
    pos = initial_state.position_m.copy()
    vel = initial_state.velocity_ms.copy()
    t = initial_state.time_s
    
    while t - initial_state.time_s < duration_s:
        # Store current state
        states.append(TrajectoryState(
            position_m=pos.copy(),
            velocity_ms=vel.copy(),
            time_s=t,
            confidence=initial_state.confidence * 0.9,  # Slightly lower for predictions
        ))
        
        # Update physics (Euler integration)
        pos[0] += vel[0] * dt_s
        pos[1] += vel[1] * dt_s
        pos[2] += vel[2] * dt_s
        
        # Gravity affects vertical velocity
        vel[2] -= GRAVITY_MS2 * dt_s
        
        # Check for bounce
        if pos[2] <= BALL_RADIUS_M and vel[2] < 0:
            vel = apply_bounce_physics(vel)
            pos[2] = BALL_RADIUS_M  # Snap to ground level
        
        # Stop if ball goes underground (shouldn't happen with bounce)
        if pos[2] < -0.1:
            break
        
        t += dt_s
    
    return states


def trajectory_to_pitch_plane(
    trajectory: list[TrajectoryState],
    homography_matrix: np.ndarray,
) -> list[tuple[float, float]]:
    """Project 3D trajectory onto pitch ground plane using homography.
    
    Args:
        trajectory: 3D trajectory states
        homography_matrix: 3x3 homography mapping world XY to pitch XY
        
    Returns:
        List of (x, y) coordinates in pitch plane (meters)
    """
    pitch_points = []
    
    for state in trajectory:
        # Take X, Y coordinates (ignore Z)
        world_x, world_y = state.position_m[0], state.position_m[1]
        
        # Apply homography
        p = np.array([[world_x], [world_y], [1.0]])
        q = homography_matrix @ p
        
        if abs(q[2, 0]) < 1e-9:
            pitch_points.append((float("nan"), float("nan")))
            continue
        
        pitch_x = q[0, 0] / q[2, 0]
        pitch_y = q[1, 0] / q[2, 0]
        
        pitch_points.append((float(pitch_x), float(pitch_y)))
    
    return pitch_points
