"""Camera calibration for cricket pitch tracking.

Provides:
- Extrinsic calibration: Camera pose (R, T) via solvePnP
- Homography: Image plane → pitch ground plane mapping
"""

from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


class CalibrationError(RuntimeError):
    pass


def calibrate_extrinsic(
    *,
    image_points: list[tuple[float, float]],
    world_points: list[tuple[float, float, float]],
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute camera pose (extrinsic parameters) using solvePnP.
    
    Args:
        image_points: 2D pixel coordinates [(u, v), ...]
        world_points: 3D world coordinates [(X, Y, Z), ...]
        camera_matrix: 3x3 intrinsic camera matrix K
        dist_coeffs: Distortion coefficients
        
    Returns:
        (R, T): Rotation matrix (3x3) and translation vector (3x1)
        
    Example:
        # Define pitch landmarks in world coordinates (meters)
        world_points = [
            (0.0, -1.52, 0.0),      # Striker crease left
            (0.0, 1.52, 0.0),       # Striker crease right
            (20.12, 1.52, 0.0),     # Bowler crease right
            (20.12, -1.52, 0.0),    # Bowler crease left
            (0.0, 0.0, 0.71),       # Striker stump top
            (20.12, 0.0, 0.71),     # Bowler stump top
        ]
        # User taps corresponding points in image
        image_points = [(x1, y1), (x2, y2), ...]
        R, T = calibrate_extrinsic(
            image_points=image_points,
            world_points=world_points,
            camera_matrix=K,
            dist_coeffs=dist,
        )
    """
    if cv2 is None:
        raise CalibrationError("OpenCV required for extrinsic calibration")
    
    if len(image_points) != len(world_points):
        raise CalibrationError("Image points and world points count mismatch")
    
    if len(image_points) < 4:
        raise CalibrationError("Need at least 4 point correspondences")
    
    object_pts = np.array(world_points, dtype=np.float32)
    image_pts = np.array(image_points, dtype=np.float32)
    
    success, rvec, tvec = cv2.solvePnP(
        object_pts,
        image_pts,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    
    if not success:
        raise CalibrationError("solvePnP failed to converge")
    
    # Convert rotation vector to matrix
    R, _ = cv2.Rodrigues(rvec)
    
    return R, tvec


def compute_homography(
    *,
    image_points: list[tuple[float, float]],
    world_points: list[tuple[float, float]],
) -> np.ndarray:
    """Compute homography from image to world ground plane.
    
    Args:
        image_points: Pixel coordinates [(u, v), ...]
        world_points: Ground plane coordinates [(X, Y), ...]
        
    Returns:
        3x3 homography matrix H such that world_point ~ H @ image_point
        
    Example:
        # Define 4 pitch corners in world coords (meters)
        world_points = [
            (0.0, -1.52),       # Striker end left
            (0.0, 1.52),        # Striker end right
            (20.12, 1.52),      # Bowler end right
            (20.12, -1.52),     # Bowler end left
        ]
        # User taps corners in image
        image_points = [(u1, v1), (u2, v2), (u3, v3), (u4, v4)]
        H = compute_homography(image_points=image_points, world_points=world_points)
    """
    if cv2 is None:
        raise CalibrationError("OpenCV required for homography computation")
    
    if len(image_points) != len(world_points):
        raise CalibrationError("Point count mismatch")
    
    if len(image_points) < 4:
        raise CalibrationError("Need at least 4 correspondences")
    
    src_pts = np.array(image_points, dtype=np.float32)
    dst_pts = np.array(world_points, dtype=np.float32)
    
    H, mask = cv2.findHomography(src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=5.0)
    
    if H is None:
        raise CalibrationError("Homography computation failed")
    
    return H


def apply_homography(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    """Apply homography to a single point."""
    p = np.array([[x], [y], [1.0]])
    q = H @ p
    if abs(q[2, 0]) < 1e-12:
        return float('nan'), float('nan')
    return float(q[0, 0] / q[2, 0]), float(q[1, 0] / q[2, 0])


def project_3d_to_image(
    *,
    world_point: np.ndarray,  # (3,) or (3,1)
    camera_matrix: np.ndarray,
    rotation: np.ndarray,
    translation: np.ndarray,
) -> tuple[float, float]:
    """Project 3D world point to 2D image coordinates.
    
    Returns:
        (u, v): Pixel coordinates
    """
    P = world_point.reshape(3, 1)
    P_cam = rotation @ P + translation
    
    if P_cam[2, 0] < 0.01:
        return float('nan'), float('nan')
    
    P_img = camera_matrix @ P_cam
    u = P_img[0, 0] / P_img[2, 0]
    v = P_img[1, 0] / P_img[2, 0]
    
    return float(u), float(v)
