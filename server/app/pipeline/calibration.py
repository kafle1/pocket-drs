"""Camera model and stump-anchored calibration.

World frame: X down the pitch (0 at the striker's stumps, L at the bowler's), Y across
the pitch, Z up. The two stump sets are the metric anchor: their height is fixed by the
Laws, so eight tapped stump corners plus the four pitch corners pin the camera pose and,
when the caller does not supply them, the focal length and the pitch length.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import least_squares, minimize

_log = logging.getLogger("pocket_drs.pipeline")

# Law 8: the wicket is 22.86 cm wide over the outer edges and 71.12 cm tall, stumps at most 3.81 cm across
STUMP_HEIGHT_M = 0.711
STUMP_HALF_WIDTH_M = 0.01905      # half thickness of one stump
STUMP_OUTER_HALF_M = 0.1143       # outer edge of the outer stump, half of 22.86 cm
STUMP_LATERAL_DX_M = STUMP_OUTER_HALF_M - STUMP_HALF_WIDTH_M   # middle stump centre to outer stump centre
PITCH_LENGTH_M = 20.12
PITCH_WIDTH_M = 3.05
FOV_RANGE_DEG = (20.0, 130.0)     # long-axis field of view, telephoto to ultra-wide
LENGTH_RANGE_M = (2.0, 25.0)


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
    pitch_width_m: float
    used_corners: bool
    refined: bool = False         # the reprojection refine ran and was kept

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
    def notes(self) -> list[str]:
        return [
            "stump+corner pose" if self.used_corners else "stump-only pose",
            "refined" if self.refined else "unrefined",
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


def _refine(obj: np.ndarray, img: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray, err0: float,
            free_focal: bool, image_size: tuple[int, int]):
    """Pixel least squares over rotation, translation and, when it is free, the focal length, from the
    PnP pose. SQPnP minimises an object-space error, so its pose is not the best fit to the taps and
    loses up to 4x in sd on some pose coordinates (paper/theory/CRLB-NOTES.md, section 5).
    Returns (err, R, t, K) or a reason string when the result is not usable."""
    f0, cx, cy = float(K[0, 0]), float(K[0, 2]), float(K[1, 2])
    n = 7 if free_focal else 6

    def project(z):
        Rz = cv2.Rodrigues(z[:3])[0] @ R
        pc = obj @ Rz.T + t + z[3:6]
        return Rz, pc, f0 + (z[6] if free_focal else 0.0)

    def res(z):
        _, pc, f = project(z)
        return np.concatenate([f * pc[:, 0] / pc[:, 2] + cx - img[:, 0], f * pc[:, 1] / pc[:, 2] + cy - img[:, 1]])

    try:
        sol = least_squares(res, np.zeros(n), method="lm", x_scale=([1e-3] * 3 + [1e-2] * 3 + [10.0])[:n])
    except (ValueError, np.linalg.LinAlgError) as e:
        return f"solver error: {e}"
    if not sol.success or not np.all(np.isfinite(sol.x)):
        return f"did not converge ({sol.message})"
    R1, pc, f1 = project(sol.x)
    t1 = t + sol.x[3:6]
    # the same admissible region the grid search uses: FOV range, camera above the ground, taps in front
    fov1 = math.degrees(2.0 * math.atan((max(image_size) / 2.0) / f1)) if f1 > 0 else float("nan")
    if not FOV_RANGE_DEG[0] <= fov1 <= FOV_RANGE_DEG[1]:
        return f"focal length left the FOV range (fov {fov1:.1f} deg)"
    if float((-R1.T @ t1)[2]) <= 0.0 or np.any(pc[:, 2] <= 0.0):
        return "pose flipped behind the marks or below the ground"
    err1 = float(np.sqrt(np.sum(sol.fun ** 2) / len(obj)))
    if not math.isfinite(err1) or err1 > err0:
        return f"reprojection error rose from {err0:.2f} to {err1:.2f} px"
    K1 = K.copy()
    K1[0, 0] = K1[1, 1] = f1
    return err1, R1, t1, K1


def solve_camera_pose(
    *,
    image_size: tuple[int, int],
    stump_quads_px: list[tuple[float, float]],
    pitch_corners_px: list[tuple[float, float]] | None,
    pitch_width_m: float = PITCH_WIDTH_M,
    fov_deg: float | None = None,
    pitch_length_m: float | None = None,
    refine: bool = True,
) -> CameraPose:
    """Pose from eight stump corners (striker TL,TR,BR,BL then bowler TL,TR,BR,BL) and,
    optionally, the four pitch corners (striker-left, striker-right, bowler-right,
    bowler-left). FOV and pitch length are swept when not supplied.

    The corners sit off the stump plane and break the focal-length/pitch-length ambiguity the
    stumps alone leave open. They are dropped when they disagree with the stumps, because the
    stump height is the one dimension the Laws fix exactly.

    The winning pose then gets a pixel least-squares refine over rotation, translation and the focal
    length when it was swept (pitch length stays where the sweep put it). A refine that fails or
    leaves the admissible region is logged and the unrefined pose is kept.
    """
    if len(stump_quads_px) != 8:
        raise CalibrationError("Need exactly 8 stump corners (4 per end)")
    if pitch_corners_px is not None and len(pitch_corners_px) != 4:
        raise CalibrationError("Need exactly 4 pitch corners, or none")
    width, height = image_size
    stump_img = np.asarray(stump_quads_px, dtype=float)
    corner_img = None if pitch_corners_px is None else np.asarray(pitch_corners_px, dtype=float)

    fov_grid = [fov_deg] if fov_deg is not None else np.arange(FOV_RANGE_DEG[0], FOV_RANGE_DEG[1] + 1e-9, 5.0)
    len_grid = [pitch_length_m] if pitch_length_m is not None else np.arange(LENGTH_RANGE_M[0], LENGTH_RANGE_M[1] + 1e-9, 0.5)
    free = [i for i, v in enumerate((fov_deg, pitch_length_m)) if v is None]
    lo = np.array([FOV_RANGE_DEG[0], LENGTH_RANGE_M[0]])
    hi = np.array([FOV_RANGE_DEG[1], LENGTH_RANGE_M[1]])

    def solve(fov, L, use_corners):
        K = intrinsics(width, height, float(fov))
        obj, img = _stump_object_points(L), stump_img
        if use_corners:
            obj, img = np.vstack([obj, _corner_object_points(L, pitch_width_m)]), np.vstack([img, corner_img])
        sol = _pnp(obj, img, K)
        return None if sol is None else (sol[0], sol[1], sol[2], K, float(fov), float(L))

    def sweep(use_corners: bool):
        # grid over whatever is free (5 deg, 0.5 m), then a continuous polish from the best cell
        cells = (solve(f, L, use_corners) for f in fov_grid for L in len_grid)
        best = min((c for c in cells if c is not None), key=lambda c: c[0], default=None)
        if best is None or not free:
            return best
        x0 = np.array([best[4], best[5]])

        def err(x):
            z = x0.copy(); z[free] = x
            sol = solve(z[0], z[1], use_corners)
            return sol[0] if sol is not None else 1e9

        res = minimize(err, x0[free], method="Nelder-Mead", bounds=list(zip(lo[free], hi[free])),
                       options={"xatol": 1e-2, "fatol": 1e-3})
        z = x0.copy(); z[free] = res.x
        sol = solve(z[0], z[1], use_corners)
        return sol if sol is not None and sol[0] < best[0] else best

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
    refined = False
    if refine:
        obj, img = _stump_object_points(L), stump_img
        if used_corners:
            obj, img = np.vstack([obj, _corner_object_points(L, pitch_width_m)]), np.vstack([img, corner_img])
        out = _refine(obj, img, K, R, t, err, fov_deg is None, (width, height))
        if isinstance(out, str):
            _log.warning("calibration refine rejected, keeping the unrefined pose: %s", out)
        else:
            err, R, t, K = out
            fov = math.degrees(2.0 * math.atan((max(width, height) / 2.0) / float(K[0, 0])))
            refined = True
    return CameraPose(K=K, R=R, t=t, reproj_error_px=err, fov_deg=fov, pitch_length_m=L,
                      pitch_width_m=pitch_width_m, used_corners=used_corners, refined=refined)
