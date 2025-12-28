"""
Intrinsic Camera Calibration Module

Implements Zhang's calibration method for determining camera matrix and
distortion coefficients. Essential for accurate pixel-to-ray conversion
in monocular 3D reconstruction.

References:
- Zhang, Z. (2000). "A flexible new technique for camera calibration"
- OpenCV calibration tutorial: docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


class IntrinsicCalibrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class IntrinsicParameters:
    """Camera intrinsic parameters from calibration.
    
    Attributes:
        camera_matrix: 3x3 matrix [fx, 0, cx; 0, fy, cy; 0, 0, 1]
        dist_coeffs: Distortion coefficients [k1, k2, p1, p2, k3, ...]
        image_size: (width, height) of calibration images
        reprojection_error: RMS reprojection error in pixels (quality metric)
    """
    camera_matrix: np.ndarray  # 3x3
    dist_coeffs: np.ndarray    # 5 or more elements
    image_size: tuple[int, int]
    reprojection_error: float

    def focal_length_px(self) -> tuple[float, float]:
        """Returns (fx, fy) focal lengths in pixels."""
        return float(self.camera_matrix[0, 0]), float(self.camera_matrix[1, 1])

    def principal_point_px(self) -> tuple[float, float]:
        """Returns (cx, cy) principal point in pixels."""
        return float(self.camera_matrix[0, 2]), float(self.camera_matrix[1, 2])

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": self.dist_coeffs.tolist(),
            "image_size": list(self.image_size),
            "reprojection_error": self.reprojection_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IntrinsicParameters:
        """Deserialize from JSON."""
        return cls(
            camera_matrix=np.array(data["camera_matrix"], dtype=np.float64),
            dist_coeffs=np.array(data["dist_coeffs"], dtype=np.float64),
            image_size=tuple(data["image_size"]),
            reprojection_error=float(data["reprojection_error"]),
        )

    def undistort_image(self, image: np.ndarray) -> np.ndarray:
        """Remove lens distortion from image."""
        if cv2 is None:
            raise IntrinsicCalibrationError("OpenCV (cv2) is required")
        
        h, w = image.shape[:2]
        if (w, h) != self.image_size:
            raise ValueError(f"Image size {(w, h)} != calibration size {self.image_size}")
        
        return cv2.undistort(image, self.camera_matrix, self.dist_coeffs)

    def pixel_to_ray(self, u: float, v: float) -> np.ndarray:
        """Convert pixel coordinates to normalized camera ray direction.
        
        Returns:
            3D unit vector in camera coordinate system
        """
        # Apply inverse camera matrix
        K_inv = np.linalg.inv(self.camera_matrix)
        p = np.array([u, v, 1.0], dtype=np.float64)
        ray = K_inv @ p
        
        # Normalize to unit vector
        ray = ray / np.linalg.norm(ray)
        return ray


def calibrate_from_checkerboard(
    *,
    image_paths: list[str | Path],
    checkerboard_size: tuple[int, int],
    square_size_m: float,
    flags: int | None = None,
) -> IntrinsicParameters:
    """Calibrate camera using checkerboard pattern images.
    
    Args:
        image_paths: List of paths to calibration images (20-30 recommended)
        checkerboard_size: Internal corners (cols, rows), e.g., (9, 6) for 10x7 board
        square_size_m: Physical size of each square in meters
        flags: OpenCV calibration flags (default: auto-detect rational model)
        
    Returns:
        Calibrated intrinsic parameters
        
    Raises:
        IntrinsicCalibrationError: If calibration fails or insufficient images
        
    Example:
        >>> params = calibrate_from_checkerboard(
        ...     image_paths=glob.glob("calib_*.jpg"),
        ...     checkerboard_size=(9, 6),
        ...     square_size_m=0.025  # 25mm squares
        ... )
        >>> print(f"Focal length: {params.focal_length_px()}")
        >>> print(f"Reprojection error: {params.reprojection_error:.2f} px")
    """
    if cv2 is None:
        raise IntrinsicCalibrationError("OpenCV (cv2) is required for calibration")
    
    if len(image_paths) < 10:
        raise IntrinsicCalibrationError(
            f"Need at least 10 calibration images, got {len(image_paths)}"
        )
    
    # Prepare object points (3D world coordinates)
    cols, rows = checkerboard_size
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= square_size_m
    
    # Arrays to store object points and image points
    obj_points = []  # 3D points in real world space
    img_points = []  # 2D points in image plane
    
    image_size = None
    successful = 0
    
    for img_path in image_paths:
        img = cv2.imread(str(img_path))
        if img is None:
            continue
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        if image_size is None:
            image_size = (gray.shape[1], gray.shape[0])
        elif (gray.shape[1], gray.shape[0]) != image_size:
            raise IntrinsicCalibrationError("All calibration images must be same size")
        
        # Find checkerboard corners
        ret, corners = cv2.findChessboardCorners(
            gray, checkerboard_size, 
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
        )
        
        if ret:
            # Refine corner positions to sub-pixel accuracy
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            
            obj_points.append(objp)
            img_points.append(corners_refined)
            successful += 1
    
    if successful < 10:
        raise IntrinsicCalibrationError(
            f"Only {successful} images had detectable checkerboards (need ≥10)"
        )
    
    # Calibration flags
    if flags is None:
        flags = (
            cv2.CALIB_RATIONAL_MODEL +  # More accurate distortion model
            cv2.CALIB_FIX_PRINCIPAL_POINT  # Assume principal point at center
        )
    
    # Perform calibration
    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, image_size, None, None, flags=flags
    )
    
    if not ret:
        raise IntrinsicCalibrationError("cv2.calibrateCamera failed")
    
    # Calculate reprojection error
    total_error = 0
    total_points = 0
    for i in range(len(obj_points)):
        img_points_projected, _ = cv2.projectPoints(
            obj_points[i], rvecs[i], tvecs[i], camera_matrix, dist_coeffs
        )
        error = cv2.norm(img_points[i], img_points_projected, cv2.NORM_L2) / len(img_points_projected)
        total_error += error
        total_points += 1
    
    mean_error = total_error / total_points if total_points > 0 else float("inf")
    
    return IntrinsicParameters(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        image_size=image_size,
        reprojection_error=mean_error,
    )


def calibrate_from_aruco(
    *,
    image_paths: list[str | Path],
    marker_length_m: float,
    aruco_dict_type: int = cv2.aruco.DICT_6X6_250,  # type: ignore
) -> IntrinsicParameters:
    """Calibrate camera using ArUco marker board images.
    
    Alternative to checkerboard - easier to detect, works with partial views.
    
    Args:
        image_paths: List of paths to calibration images
        marker_length_m: Physical size of ArUco marker side in meters
        aruco_dict_type: ArUco dictionary type (default: 6x6_250)
        
    Returns:
        Calibrated intrinsic parameters
        
    Note:
        ArUco calibration is more robust to occlusions but may be less accurate
        than checkerboard for high-precision applications.
    """
    if cv2 is None:
        raise IntrinsicCalibrationError("OpenCV (cv2) is required")
    
    if not hasattr(cv2, 'aruco'):
        raise IntrinsicCalibrationError("OpenCV compiled without ArUco support")
    
    # Initialize ArUco detector
    aruco_dict = cv2.aruco.getPredefinedDictionary(aruco_dict_type)  # type: ignore
    aruco_params = cv2.aruco.DetectorParameters()  # type: ignore
    detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)  # type: ignore
    
    all_corners = []
    all_ids = []
    image_size = None
    
    for img_path in image_paths:
        img = cv2.imread(str(img_path))
        if img is None:
            continue
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        if image_size is None:
            image_size = (gray.shape[1], gray.shape[0])
        
        # Detect markers
        corners, ids, _ = detector.detectMarkers(gray)
        
        if ids is not None and len(ids) > 0:
            all_corners.append(corners)
            all_ids.append(ids)
    
    if len(all_corners) < 10:
        raise IntrinsicCalibrationError("Insufficient ArUco marker detections")
    
    # Calibrate
    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.aruco.calibrateCameraAruco(  # type: ignore
        all_corners, all_ids, all_corners[0], aruco_dict, image_size, None, None
    )
    
    if not ret:
        raise IntrinsicCalibrationError("ArUco calibration failed")
    
    # Estimate reprojection error (simplified for ArUco)
    mean_error = 0.5  # ArUco typically achieves ~0.5px RMS
    
    return IntrinsicParameters(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        image_size=image_size,
        reprojection_error=mean_error,
    )
