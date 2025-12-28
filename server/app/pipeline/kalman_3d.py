"""
Extended Kalman Filter for 3D Ball Tracking with Physics-Based Process Model

Upgrades the 2D Kalman filter to full 3D with projectile motion dynamics.
This combines physics knowledge with Bayesian filtering for robust prediction.

State Vector:
    x = [px, py, pz, vx, vy, vz]ᵀ
    - Position: (px, py, pz) in world coordinates (meters)
    - Velocity: (vx, vy, vz) in world coordinates (m/s)

Process Model (prediction):
    x(t+Δt) = f(x(t), Δt) + w
    where f is projectile motion: p' = p + v·Δt, v' = v - [0, 0, g·Δt]ᵀ

Measurement Model (observation):
    z = h(x) + v
    where h is nonlinear camera projection: z = K·[R|T]·[px, py, pz]ᵀ

Reference:
- "Probabilistic Robotics" by Thrun, Burgard, Fox (2005)
"""

from __future__ import annotations

import numpy as np

# Physical constants
GRAVITY_MS2 = 9.81


class ExtendedKalmanFilter3D:
    """Extended Kalman Filter for 3D ball tracking with projectile motion.
    
    Attributes:
        state: Current state estimate [px, py, pz, vx, vy, vz]ᵀ
        covariance: State covariance matrix (6x6)
    """
    
    def __init__(
        self,
        *,
        initial_state: np.ndarray,  # shape (6,)
        initial_covariance: np.ndarray | None = None,  # shape (6, 6)
        process_noise_accel: float = 5.0,  # Acceleration noise (m/s²)
        measurement_noise_pixels: float = 5.0,  # Pixel measurement noise
    ):
        """Initialize Extended Kalman Filter.
        
        Args:
            initial_state: [px, py, pz, vx, vy, vz]ᵀ
            initial_covariance: Initial uncertainty (default: identity)
            process_noise_accel: Process noise in acceleration (m/s²)
            measurement_noise_pixels: Measurement noise in pixels
        """
        self.state = initial_state.astype(float)
        
        if initial_covariance is None:
            # Default: high uncertainty in velocity, moderate in position
            self.covariance = np.diag([1.0, 1.0, 0.5, 5.0, 5.0, 5.0])
        else:
            self.covariance = initial_covariance.astype(float)
        
        self.process_noise_accel = process_noise_accel
        self.measurement_noise_pixels = measurement_noise_pixels
    
    def predict(self, dt: float):
        """Predict next state using physics-based process model.
        
        Args:
            dt: Time step (seconds)
            
        Process Model:
            px' = px + vx·dt
            py' = py + vy·dt
            pz' = pz + vz·dt
            vx' = vx
            vy' = vy
            vz' = vz - g·dt
        """
        # State transition: projectile motion
        px, py, pz, vx, vy, vz = self.state
        
        # Predicted state
        px_new = px + vx * dt
        py_new = py + vy * dt
        pz_new = pz + vz * dt
        vx_new = vx
        vy_new = vy
        vz_new = vz - GRAVITY_MS2 * dt
        
        self.state = np.array([px_new, py_new, pz_new, vx_new, vy_new, vz_new])
        
        # Jacobian of process model (F matrix)
        F = np.array([
            [1, 0, 0, dt, 0,  0],
            [0, 1, 0, 0,  dt, 0],
            [0, 0, 1, 0,  0,  dt],
            [0, 0, 0, 1,  0,  0],
            [0, 0, 0, 0,  1,  0],
            [0, 0, 0, 0,  0,  1],
        ])
        
        # Process noise covariance (Q matrix)
        # Assume acceleration uncertainty
        q = self.process_noise_accel * dt**2
        Q = np.diag([
            q * dt**2 / 4,  # Position noise from acceleration
            q * dt**2 / 4,
            q * dt**2 / 4,
            q * dt,  # Velocity noise from acceleration
            q * dt,
            q * dt,
        ])
        
        # Covariance prediction
        self.covariance = F @ self.covariance @ F.T + Q
    
    def update(
        self,
        *,
        pixel_u: float,
        pixel_v: float,
        camera_matrix: np.ndarray,  # 3x3 intrinsic K
        rotation: np.ndarray,  # 3x3 extrinsic R
        translation: np.ndarray,  # 3x1 extrinsic T
    ):
        """Update state estimate with new 2D pixel measurement.
        
        Args:
            pixel_u: Horizontal pixel coordinate
            pixel_v: Vertical pixel coordinate
            camera_matrix: Camera intrinsic matrix K
            rotation: Camera rotation R (world → camera)
            translation: Camera translation T (world → camera)
            
        Measurement Model:
            P_cam = R·[px, py, pz]ᵀ + T
            [u, v, 1]ᵀ ∝ K·P_cam
        """
        # Current state prediction
        px, py, pz, vx, vy, vz = self.state
        P_world = np.array([[px], [py], [pz]])
        
        # Transform to camera coordinates
        P_cam = rotation @ P_world + translation
        
        # Check if behind camera
        if P_cam[2, 0] < 0.1:
            # Skip update if behind camera (invalid)
            return
        
        # Project to image plane
        P_img = camera_matrix @ P_cam
        u_pred = P_img[0, 0] / P_img[2, 0]
        v_pred = P_img[1, 0] / P_img[2, 0]
        
        # Measurement residual (innovation)
        z_measured = np.array([[pixel_u], [pixel_v]])
        z_predicted = np.array([[u_pred], [v_pred]])
        y = z_measured - z_predicted
        
        # Jacobian of measurement model (H matrix)
        # h(x) = K·R·[px, py, pz]ᵀ / (R·[px, py, pz]ᵀ)_z
        # This is complex; we compute numerically
        H = self._compute_measurement_jacobian(
            camera_matrix=camera_matrix,
            rotation=rotation,
            translation=translation,
        )
        
        # Measurement noise covariance (R matrix)
        R = np.array([
            [self.measurement_noise_pixels**2, 0],
            [0, self.measurement_noise_pixels**2],
        ])
        
        # Innovation covariance
        S = H @ self.covariance @ H.T + R
        
        # Kalman gain
        try:
            K_gain = self.covariance @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            # Singular matrix; skip update
            return
        
        # State update
        self.state = self.state + (K_gain @ y).flatten()
        
        # Covariance update (Joseph form for numerical stability)
        I = np.eye(6)
        self.covariance = (I - K_gain @ H) @ self.covariance
    
    def _compute_measurement_jacobian(
        self,
        *,
        camera_matrix: np.ndarray,
        rotation: np.ndarray,
        translation: np.ndarray,
    ) -> np.ndarray:
        """Compute Jacobian ∂h/∂x numerically.
        
        Returns:
            H matrix (2x6): derivatives of [u, v] w.r.t. [px, py, pz, vx, vy, vz]
        """
        epsilon = 1e-4
        H = np.zeros((2, 6))
        
        # Numerical differentiation for position components
        for i in range(3):  # px, py, pz
            state_plus = self.state.copy()
            state_plus[i] += epsilon
            
            P_world_plus = state_plus[:3].reshape(3, 1)
            P_cam_plus = rotation @ P_world_plus + translation
            
            if P_cam_plus[2, 0] < 0.1:
                continue
            
            P_img_plus = camera_matrix @ P_cam_plus
            u_plus = P_img_plus[0, 0] / P_img_plus[2, 0]
            v_plus = P_img_plus[1, 0] / P_img_plus[2, 0]
            
            # Current projection
            P_world = self.state[:3].reshape(3, 1)
            P_cam = rotation @ P_world + translation
            P_img = camera_matrix @ P_cam
            u_curr = P_img[0, 0] / P_img[2, 0]
            v_curr = P_img[1, 0] / P_img[2, 0]
            
            # Finite difference
            H[0, i] = (u_plus - u_curr) / epsilon
            H[1, i] = (v_plus - v_curr) / epsilon
        
        # Velocity components don't affect measurement (H[:, 3:6] = 0)
        
        return H
    
    def get_state(self) -> dict:
        """Get current state estimate.
        
        Returns:
            Dict with position, velocity, and uncertainty
        """
        px, py, pz, vx, vy, vz = self.state
        
        # Extract uncertainties (diagonal of covariance)
        pos_std = np.sqrt(np.diag(self.covariance[:3, :3]))
        vel_std = np.sqrt(np.diag(self.covariance[3:, 3:]))
        
        return {
            "position_m": np.array([px, py, pz]),
            "velocity_ms": np.array([vx, vy, vz]),
            "position_std_m": pos_std,
            "velocity_std_ms": vel_std,
        }
    
    def predict_future(self, dt: float, num_steps: int) -> list[dict]:
        """Predict future states without updating covariance.
        
        Args:
            dt: Time step per prediction
            num_steps: Number of steps to predict
            
        Returns:
            List of predicted states
        """
        predictions = []
        
        # Make a copy to avoid modifying current state
        state_copy = self.state.copy()
        
        for _ in range(num_steps):
            # Projectile motion
            px, py, pz, vx, vy, vz = state_copy
            
            px += vx * dt
            py += vy * dt
            pz += vz * dt
            vz -= GRAVITY_MS2 * dt
            
            state_copy = np.array([px, py, pz, vx, vy, vz])
            
            predictions.append({
                "position_m": np.array([px, py, pz]),
                "velocity_ms": np.array([vx, vy, vz]),
            })
        
        return predictions


class MultiHypothesisTracker:
    """Track multiple ball candidates using multiple EKF hypotheses.
    
    Useful when there are multiple potential ball detections (e.g., fielders, stumps).
    Each hypothesis tracks one candidate; we select the most likely one.
    """
    
    def __init__(self, max_hypotheses: int = 5):
        """Initialize multi-hypothesis tracker.
        
        Args:
            max_hypotheses: Maximum number of parallel hypotheses
        """
        self.hypotheses: list[ExtendedKalmanFilter3D] = []
        self.scores: list[float] = []
        self.max_hypotheses = max_hypotheses
    
    def add_hypothesis(self, ekf: ExtendedKalmanFilter3D, initial_score: float = 1.0):
        """Add a new tracking hypothesis."""
        if len(self.hypotheses) >= self.max_hypotheses:
            # Remove weakest hypothesis
            min_idx = int(np.argmin(self.scores))
            del self.hypotheses[min_idx]
            del self.scores[min_idx]
        
        self.hypotheses.append(ekf)
        self.scores.append(initial_score)
    
    def predict_all(self, dt: float):
        """Predict all hypotheses forward in time."""
        for ekf in self.hypotheses:
            ekf.predict(dt)
    
    def update_best_match(
        self,
        *,
        pixel_u: float,
        pixel_v: float,
        camera_matrix: np.ndarray,
        rotation: np.ndarray,
        translation: np.ndarray,
        max_distance_pixels: float = 50.0,
    ):
        """Update the hypothesis that best matches the observation.
        
        Args:
            pixel_u, pixel_v: Observed pixel coordinates
            camera_matrix, rotation, translation: Camera parameters
            max_distance_pixels: Maximum distance for valid match
        """
        if not self.hypotheses:
            return
        
        best_idx = None
        best_distance = max_distance_pixels
        
        # Find closest hypothesis
        for i, ekf in enumerate(self.hypotheses):
            px, py, pz, _, _, _ = ekf.state
            P_world = np.array([[px], [py], [pz]])
            P_cam = rotation @ P_world + translation
            
            if P_cam[2, 0] < 0.1:
                continue
            
            P_img = camera_matrix @ P_cam
            u_pred = P_img[0, 0] / P_img[2, 0]
            v_pred = P_img[1, 0] / P_img[2, 0]
            
            distance = np.sqrt((u_pred - pixel_u)**2 + (v_pred - pixel_v)**2)
            
            if distance < best_distance:
                best_distance = distance
                best_idx = i
        
        # Update best match
        if best_idx is not None:
            self.hypotheses[best_idx].update(
                pixel_u=pixel_u,
                pixel_v=pixel_v,
                camera_matrix=camera_matrix,
                rotation=rotation,
                translation=translation,
            )
            self.scores[best_idx] += 1.0  # Reward for match
        
        # Decay all scores
        self.scores = [s * 0.95 for s in self.scores]
    
    def get_best_hypothesis(self) -> ExtendedKalmanFilter3D | None:
        """Return the most confident hypothesis."""
        if not self.hypotheses:
            return None
        
        best_idx = int(np.argmax(self.scores))
        return self.hypotheses[best_idx]
