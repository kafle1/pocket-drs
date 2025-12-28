"""Integration tests for Pocket DRS pipeline."""

import numpy as np
import pytest

from app.pipeline.calibration import (
    compute_homography,
    apply_homography,
    project_3d_to_image,
)
from app.pipeline.intrinsic_calib import IntrinsicParameters
from app.pipeline.reconstruction import (
    Detection2D,
    reconstruct_trajectory_3d,
    predict_trajectory_forward,
    TrajectoryState,
)
from app.pipeline.kalman_3d import ExtendedKalmanFilter3D
from app.pipeline.lbw import assess_lbw_3d


def test_homography_basic():
    """Test homography computation and application."""
    # Simple 4-point correspondence
    image_pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
    world_pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
    
    H = compute_homography(image_points=image_pts, world_points=world_pts)
    
    # Test forward mapping
    wx, wy = apply_homography(H, 50, 50)
    assert abs(wx - 5.0) < 0.1
    assert abs(wy - 5.0) < 0.1


def test_intrinsic_calibration():
    """Test intrinsic parameters structure."""
    K = np.array([
        [800, 0, 640],
        [0, 800, 360],
        [0, 0, 1],
    ])
    dist = np.zeros(5)
    
    intrinsics = IntrinsicParameters(
        camera_matrix=K,
        dist_coeffs=dist,
        image_size=(1280, 720),
        reprojection_error=0.3,
    )
    
    # Test pixel to ray conversion
    ray = intrinsics.pixel_to_ray(640, 360)
    assert abs(ray[0]) < 0.01  # Should point forward
    assert abs(ray[1]) < 0.01
    assert abs(ray[2] - 1.0) < 0.01


def test_3d_projection():
    """Test 3D to 2D projection."""
    K = np.eye(3) * 100
    K[2, 2] = 1
    R = np.eye(3)
    T = np.array([[0], [0], [5]])  # Camera 5m behind origin
    
    # Point at origin
    world_pt = np.array([0, 0, 0])
    u, v = project_3d_to_image(
        world_point=world_pt,
        camera_matrix=K,
        rotation=R,
        translation=T,
    )
    
    # Should project near image center
    assert np.isfinite(u) and np.isfinite(v)


def test_ekf_predict():
    """Test Extended Kalman Filter prediction."""
    initial_state = np.array([10.0, 0.0, 1.5, -15.0, 0.0, -5.0])  # Ball moving toward camera
    ekf = ExtendedKalmanFilter3D(initial_state=initial_state)
    
    # Predict 0.1 seconds
    ekf.predict(0.1)
    
    state = ekf.get_state()
    
    # Position should have moved
    assert state["position_m"][0] < 10.0  # Moved closer to camera
    # Vertical velocity should decrease (gravity)
    assert state["velocity_ms"][2] < -5.0


def test_lbw_out_decision():
    """Test LBW decision for clear OUT case."""
    # Trajectory: ball pitches in line, hits pad in line, hitting stumps
    trajectory = [
        (15.0, 0.0, 0.5),   # Approaching
        (12.0, 0.0, 0.4),
        (10.0, 0.0, 0.06),  # Bounce (slightly above ground)
        (8.0, 0.0, 0.2),
        (5.0, 0.0, 0.3),
        (3.0, 0.0, 0.35),   # Near stumps
        (1.0, 0.0, 0.4),
        (0.0, 0.0, 0.45),   # At stumps, hitting height
    ]
    
    impact_point = (1.5, 0.0, 0.35)  # In line, hitting stumps
    
    decision = assess_lbw_3d(
        trajectory_3d=trajectory,
        impact_point_3d=impact_point,
        impact_on_pad=True,
    )
    
    # Should be OUT or at least hitting stumps
    assert decision.hitting_stumps
    assert decision.pitched_in_line
    assert decision.impact_in_line


def test_lbw_pitched_outside_leg():
    """Test NOT OUT for ball pitched outside leg."""
    trajectory = [
        (15.0, 0.5, 0.5),   # Pitched outside leg (y > 0.1143)
        (12.0, 0.4, 0.4),
        (10.0, 0.4, 0.036), # Bounce outside leg
        (5.0, 0.2, 0.3),
    ]
    
    impact_point = (3.0, 0.1, 0.35)
    
    decision = assess_lbw_3d(
        trajectory_3d=trajectory,
        impact_point_3d=impact_point,
        impact_on_pad=True,
    )
    
    assert decision.decision == "NOT OUT"
    assert "outside leg" in decision.reason.lower()


def test_lbw_impact_outside_off():
    """Test NOT OUT for impact outside off stump."""
    trajectory = [
        (15.0, 0.0, 0.5),
        (10.0, 0.0, 0.036),
        (5.0, 0.1, 0.3),
    ]
    
    impact_point = (3.0, 0.3, 0.35)  # Outside off (y > 0.1143 + ball_radius)
    
    decision = assess_lbw_3d(
        trajectory_3d=trajectory,
        impact_point_3d=impact_point,
        impact_on_pad=True,
    )
    
    assert decision.decision == "NOT OUT"
    assert "outside off" in decision.reason.lower() or "outside" in decision.reason.lower()


def test_trajectory_prediction():
    """Test forward trajectory prediction."""
    initial_state = TrajectoryState(
        position_m=np.array([10.0, 0.0, 1.0]),
        velocity_ms=np.array([-10.0, 0.0, 2.0]),
        time_s=0.0,
        confidence=0.95,
    )
    
    predicted = predict_trajectory_forward(
        initial_state=initial_state,
        duration_s=1.0,
        dt_s=0.1,
    )
    
    assert len(predicted) > 0
    
    # Last point should be further along
    last_state = predicted[-1]
    assert last_state.position_m[0] < 10.0  # Moved forward
    assert last_state.position_m[2] >= 0  # Above ground or bounced


def test_detection_2d_structure():
    """Test Detection2D data structure."""
    det = Detection2D(
        pixel_x=320.5,
        pixel_y=240.8,
        time_s=0.1,
        confidence=0.95,
    )
    
    assert det.pixel_x == 320.5
    assert det.time_s == 0.1
    assert 0 <= det.confidence <= 1
