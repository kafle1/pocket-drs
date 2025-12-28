"""Integrated Ball Tracking Pipeline

Combines all components into a complete tracking system.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .intrinsic_calib import IntrinsicParameters
from .kalman_3d import ExtendedKalmanFilter3D, MultiHypothesisTracker
from .reconstruction import (
    Detection2D,
    ReconstructionError,
    reconstruct_trajectory_3d,
    predict_trajectory_forward,
    detect_bounce,
    TrajectoryState,
)
from .tracking import MotionBallDetector, ColorBallDetector


@dataclass
class CameraCalibration:
    """Complete camera calibration."""
    intrinsics: IntrinsicParameters
    rotation: np.ndarray  # 3x3
    translation: np.ndarray  # 3x1
    homography: np.ndarray | None = None


@dataclass
class TrackingResult:
    """Result for one frame."""
    frame_number: int
    timestamp_s: float
    pixel_x: float | None
    pixel_y: float | None
    position_3d: np.ndarray | None
    velocity_3d: np.ndarray | None
    confidence: float


class BallTracker:
    """Main tracking pipeline."""
    
    def __init__(
        self,
        *,
        calibration: CameraCalibration,
        detector_type: str = "motion",
        yolo_model_path: str | None = None,
    ):
        self.calibration = calibration
        
        if detector_type == "yolo":
            raise NotImplementedError("YOLO coming soon. Use 'motion' or 'color'")
        elif detector_type == "motion":
            self.detector = MotionBallDetector()
        elif detector_type == "color":
            self.detector = ColorBallDetector()
        else:
            raise ValueError(f"Unknown detector: {detector_type}")
        
        self.tracker = MultiHypothesisTracker(max_hypotheses=3)
        self.detections_buffer: list[Detection2D] = []
        self.trajectory_3d: list[TrajectoryState] | None = None
    
    def process_frame(
        self,
        frame: np.ndarray,
        frame_number: int,
        timestamp_s: float,
    ) -> TrackingResult:
        """Process single frame."""
        detections = self.detector.detect(frame)
        
        if not detections:
            self.tracker.predict_all(1/60.0)
            return TrackingResult(
                frame_number=frame_number,
                timestamp_s=timestamp_s,
                pixel_x=None,
                pixel_y=None,
                position_3d=None,
                velocity_3d=None,
                confidence=0.0,
            )
        
        best_det = max(detections, key=lambda d: d["confidence"])
        pixel_x = best_det["x"]
        pixel_y = best_det["y"]
        conf = best_det["confidence"]
        
        # Update tracker
        if self.detections_buffer:
            dt = timestamp_s - self.detections_buffer[-1].time_s
        else:
            dt = 1/60.0
        
        self.tracker.predict_all(dt)
        self.tracker.update_best_match(
            pixel_u=pixel_x,
            pixel_v=pixel_y,
            camera_matrix=self.calibration.intrinsics.camera_matrix,
            rotation=self.calibration.rotation,
            translation=self.calibration.translation,
        )
        
        # Buffer detection
        detection = Detection2D(
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            time_s=timestamp_s,
            confidence=conf,
        )
        self.detections_buffer.append(detection)
        
        # 3D reconstruction
        if len(self.detections_buffer) >= 5:
            try:
                self.trajectory_3d = reconstruct_trajectory_3d(
                    detections=self.detections_buffer[-15:],
                    intrinsics=self.calibration.intrinsics,
                    extrinsics_R=self.calibration.rotation,
                    extrinsics_T=self.calibration.translation,
                )
            except ReconstructionError:
                self.trajectory_3d = None
        
        # Get state
        best_ekf = self.tracker.get_best_hypothesis()
        if best_ekf:
            state = best_ekf.get_state()
            position_3d = state["position_m"]
            velocity_3d = state["velocity_ms"]
        else:
            position_3d = None
            velocity_3d = None
        
        return TrackingResult(
            frame_number=frame_number,
            timestamp_s=timestamp_s,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            position_3d=position_3d,
            velocity_3d=velocity_3d,
            confidence=conf,
        )
    
    def get_predicted_trajectory(self, duration_s: float = 2.0) -> list[TrajectoryState] | None:
        """Predict future trajectory."""
        if not self.trajectory_3d:
            return None
        
        return predict_trajectory_forward(
            initial_state=self.trajectory_3d[-1],
            duration_s=duration_s,
            dt_s=0.01,
        )
    
    def get_bounce_point(self) -> TrajectoryState | None:
        """Get bounce point."""
        if not self.trajectory_3d:
            return None
        
        idx = detect_bounce(self.trajectory_3d)
        return self.trajectory_3d[idx] if idx is not None else None


def create_tracker_from_calibration_files(
    intrinsic_calib_path: str,
    extrinsic_R_path: str | None = None,
    extrinsic_T_path: str | None = None,
    homography_path: str | None = None,
    detector_type: str = "motion",
) -> BallTracker:
    """Create tracker from saved calibration."""
    intrinsics = IntrinsicParameters.from_json(intrinsic_calib_path)
    
    if extrinsic_R_path and extrinsic_T_path:
        rotation = np.load(extrinsic_R_path)
        translation = np.load(extrinsic_T_path)
    else:
        rotation = np.eye(3)
        translation = np.zeros((3, 1))
    
    homography = np.load(homography_path) if homography_path else None
    
    calibration = CameraCalibration(
        intrinsics=intrinsics,
        rotation=rotation,
        translation=translation,
        homography=homography,
    )
    
    return BallTracker(calibration=calibration, detector_type=detector_type)
