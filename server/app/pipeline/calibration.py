"""Camera model and stump-anchored calibration.

World frame: X down the pitch (0 at the striker's stumps, L at the bowler's), Y across
the pitch, Z up. The two stump sets are the metric anchor: their height is fixed by the
Laws, so eight tapped stump corners plus the four pitch corners pin the camera pose and,
when the caller does not supply them, the focal length and the pitch length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

STUMP_HEIGHT_M = 0.711
STUMP_LATERAL_DX_M = 0.114        # middle stump centre to outer stump centre
STUMP_HALF_WIDTH_M = 0.018        # half thickness of one stump
STUMP_OUTER_HALF_M = STUMP_LATERAL_DX_M + STUMP_HALF_WIDTH_M   # outer edge of the outer stump
PITCH_LENGTH_M = 20.12
PITCH_WIDTH_M = 3.05


class CalibrationError(Exception):
    """The tapped marks cannot form a consistent perspective view."""


@dataclass(frozen=True)
class CameraPose:
    K: np.ndarray                 # 3x3 intrinsics
    R: np.ndarray                 # 3x3 world -> camera rotation
    t: np.ndarray                 # 3, world -> camera translation
    reproj_error_px: float
    fov_deg: float
    pitch_length_m: float
    used_corners: bool

    @property
    def fx(self) -> float:
        return float(self.K[0, 0])

    @property
    def fy(self) -> float:
        return float(self.K[1, 1])

    @property
    def cx(self) -> float:
        return float(self.K[0, 2])

    @property
    def cy(self) -> float:
        return float(self.K[1, 2])

    @property
    def centre_world(self) -> np.ndarray:
        return -self.R.T @ self.t

    @property
    def behind_striker(self) -> bool:
        """True when the camera sits at the striker's end (world x below mid-pitch)."""
        return float(self.centre_world[0]) < self.pitch_length_m / 2.0

    @property
    def notes(self) -> list[str]:
        return [
            "stump+corner pose" if self.used_corners else "stump-only pose",
            f"length={self.pitch_length_m:.2f} m",
            f"reproj={self.reproj_error_px:.2f} px",
            f"fov={self.fov_deg:.0f} deg",
            f"cam_height={float(self.centre_world[2]):.2f} m",
        ]

    def project(self, xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """World points (N,3) -> pixel u, v and camera depth. Vectorised."""
        p = np.atleast_2d(xyz) @ self.R.T + self.t
        depth = p[:, 2]
        safe = np.where(np.abs(depth) < 1e-9, 1e-9, depth)
        u = self.fx * p[:, 0] / safe + self.cx
        v = self.fy * p[:, 1] / safe + self.cy
        return u, v, depth

    def project_one(self, x: float, y: float, z: float) -> tuple[float, float, float] | None:
        u, v, d = self.project(np.array([[x, y, z]]))
        if d[0] <= 0.05:
            return None
        return float(u[0]), float(v[0]), float(d[0])

    def ray_world(self, u: float, v: float) -> np.ndarray:
        """Unit direction in world coordinates of the ray through pixel (u, v)."""
        r = np.array([(u - self.cx) / self.fx, (v - self.cy) / self.fy, 1.0])
        r = self.R.T @ r
        return r / np.linalg.norm(r)

    def backproject_to_plane(self, u: float, v: float, z_plane: float) -> np.ndarray | None:
        """Intersect the pixel ray with the horizontal plane z = z_plane. Exact, no size cue."""
        c = self.centre_world
        r = self.ray_world(u, v)
        if abs(r[2]) < 1e-9:
            return None
        s = (z_plane - c[2]) / r[2]
        if s <= 0:
            return None
        return c + s * r


def intrinsics(width: int, height: int, fov_deg: float) -> np.ndarray:
    """K from the field of view along the frame's long axis, square pixels, centred principal point."""
    if not (1.0 < fov_deg < 179.0):
        raise CalibrationError(f"fov_deg must be in (1, 179), got {fov_deg}")
    f = (max(width, height) / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    return np.array([[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]])


def _stump_object_points(length: float) -> np.ndarray:
    w, h = STUMP_OUTER_HALF_M, STUMP_HEIGHT_M
    side = [(-w, h), (w, h), (w, 0.0), (-w, 0.0)]          # TL, TR, BR, BL as tapped
    return np.array([(0.0, dy, dz) for dy, dz in side] + [(length, dy, dz) for dy, dz in side])


def _corner_object_points(length: float, width: float) -> np.ndarray:
    hw = width / 2.0
    return np.array([(0.0, -hw, 0.0), (0.0, hw, 0.0), (length, hw, 0.0), (length, -hw, 0.0)])


def _pnp(obj: np.ndarray, img: np.ndarray, K: np.ndarray):
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_SQPNP)
    if not ok:
        return None
    R, _ = cv2.Rodrigues(rvec)
    t = tvec.reshape(3)
    if float((-R.T @ t)[2]) <= 0.0:          # camera below the ground: mirror twin
        return None
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
    err = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img) ** 2, axis=1))))
    if not math.isfinite(err):
        return None
    return err, R, t


def solve_camera_pose(
    *,
    image_size: tuple[int, int],
    stump_quads_px: list[tuple[float, float]],
    pitch_corners_px: list[tuple[float, float]] | None,
    pitch_width_m: float = PITCH_WIDTH_M,
    fov_deg: float | None = None,
    pitch_length_m: float | None = None,
) -> CameraPose:
    """Pose from eight stump corners (striker TL,TR,BR,BL then bowler TL,TR,BR,BL) and,
    optionally, the four pitch corners (striker-left, striker-right, bowler-right,
    bowler-left). FOV and pitch length are swept when not supplied.

    The corners sit off the stump plane and break the focal-length/pitch-length ambiguity the
    stumps alone leave open. They are dropped when they disagree with the stumps, because the
    stump height is the one dimension the Laws fix exactly.
    """
    if len(stump_quads_px) != 8:
        raise CalibrationError("Need exactly 8 stump corners (4 per end)")
    if pitch_corners_px is not None and len(pitch_corners_px) != 4:
        raise CalibrationError("Need exactly 4 pitch corners, or none")
    width, height = image_size
    stump_img = np.asarray(stump_quads_px, dtype=float)
    corner_img = None if pitch_corners_px is None else np.asarray(pitch_corners_px, dtype=float)

    fovs = [fov_deg] if fov_deg is not None else [28, 34, 40, 46, 52, 58, 64, 70, 78, 86]
    lengths = [pitch_length_m] if pitch_length_m is not None else list(np.arange(2.0, 26.0001, 0.05))

    def sweep(use_corners: bool):
        best = None
        for fov in fovs:
            K = intrinsics(width, height, float(fov))
            for L in lengths:
                obj = _stump_object_points(L)
                img = stump_img
                if use_corners:
                    obj = np.vstack([obj, _corner_object_points(L, pitch_width_m)])
                    img = np.vstack([img, corner_img])
                sol = _pnp(obj, img, K)
                if sol is not None and (best is None or sol[0] < best[0]):
                    best = (sol[0], sol[1], sol[2], K, float(fov), float(L))
        return best

    joint = sweep(True) if corner_img is not None else None
    stumps_only = sweep(False)
    if joint is None and stumps_only is None:
        raise CalibrationError("Stump calibration is degenerate; re-mark the stump bases and tops.")

    used_corners = False
    best = stumps_only
    if joint is not None:
        tol = max(6.0, 0.012 * width)
        if stumps_only is None or joint[0] <= max(tol, 2.0 * stumps_only[0] + 3.0):
            best, used_corners = joint, True

    err, R, t, K, fov, L = best
    return CameraPose(K=K, R=R, t=t, reproj_error_px=err, fov_deg=fov,
                      pitch_length_m=L, used_corners=used_corners)
