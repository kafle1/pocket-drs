"""Camera model and stump-anchored calibration.

World frame: X down the pitch (0 at the striker's stumps, L at the bowler's), Y across
the pitch, Z up. The two stump sets are the metric anchor: their height is fixed by the
Laws, so eight tapped stump corners and the given pitch length pin the camera pose and the
focal length; the four popping-crease ends, when tapped, add marks off the stump planes.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace

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
# Law 7: popping crease 1.22 m in front of the stumps, return creases 1.32 m either side of middle
CREASE_X_M, RETURN_CREASE_Y_M = 1.22, 1.32
FOV_SWEEP_DEG = (2.0, 160.0)
# long-axis field of view from phone specs: a 0.5x ultra-wide is about 110 deg, 10x zoom on the main lens about 7
PHONE_FOV_DEG = (5.0, 120.0)


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
    used_creases: bool
    refined: bool = False         # the reprojection refine ran and was kept
    tap_sigma_px: float = 0.0     # per-coordinate tap noise implied by the residual, 0 when exactly determined
    stump_height_m: float = STUMP_HEIGHT_M
    stump_width_m: float = 2 * STUMP_OUTER_HALF_M
    residuals_px: np.ndarray | None = None   # (n,2) fit minus tap, in the order the marks were given

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
            "stump+crease pose" if self.used_creases else "stump-only pose",
            "refined" if self.refined else "unrefined",
            f"length={self.pitch_length_m:.2f} m",
            f"stumps={self.stump_width_m:.3f}x{self.stump_height_m:.3f} m",
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


def _quad_area(pts) -> float:
    pts = [tuple(p) for p in pts]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2.0


def camera_at_striker(stump_quads_px) -> bool:
    """The nearer stump cluster looks larger, so it marks the end the phone stands behind."""
    return _quad_area(stump_quads_px[0:4]) >= _quad_area(stump_quads_px[4:8])


def mark_points(length: float, at_striker: bool, *, half_wicket: float = STUMP_OUTER_HALF_M,
                height: float = STUMP_HEIGHT_M) -> np.ndarray:
    """(12,3) world points of the marks in the order the app asks for them: striker stumps then
    bowler stumps, each top-left, top-right, bottom-right, bottom-left as seen on the screen,
    then the four ends of the popping creases clockwise on the screen from the striker end.
    Facing +x from the striker's end, screen left is +y; facing -x from the bowler's end it is -y."""
    yl = half_wicket if at_striker else -half_wicket
    side = [(yl, height), (-yl, height), (-yl, 0.0), (yl, 0.0)]
    cx, cy = CREASE_X_M, RETURN_CREASE_Y_M
    return np.array([(0.0, dy, dz) for dy, dz in side] + [(length, dy, dz) for dy, dz in side]
                    + [(cx, -cy, 0.0), (cx, cy, 0.0), (length - cx, cy, 0.0), (length - cx, -cy, 0.0)])


def _upright(quad: np.ndarray) -> np.ndarray:
    """Indices that put one set's corners in the image's TL, TR, BR, BL order, whatever order they were tapped in."""
    by_y = np.argsort(quad[:, 1])
    top, bottom = by_y[:2], by_y[2:]
    return np.concatenate([top[np.argsort(quad[top, 0])], bottom[np.argsort(-quad[bottom, 0])]])


def _pnp(obj: np.ndarray, img: np.ndarray, K: np.ndarray):
    try:
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_SQPNP)
    except cv2.error:                        # degenerate marks, eg all eight on one spot
        return None
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
    if not FOV_SWEEP_DEG[0] <= fov1 <= FOV_SWEEP_DEG[1]:
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
    crease_marks_px: list[tuple[float, float]] | None,
    pitch_length_m: float,
    pitch_width_m: float = PITCH_WIDTH_M,
    stump_height_m: float = STUMP_HEIGHT_M,
    stump_width_m: float = 2 * STUMP_OUTER_HALF_M,
    fov_deg: float | None = None,
    refine: bool = True,
) -> CameraPose:
    """Pose from eight stump corners (striker TL,TR,BR,BL then bowler TL,TR,BR,BL, as seen on
    the screen) and, optionally, the four popping-crease ends (mark_points). The FOV is swept when
    not supplied, then the pose gets a pixel least-squares refine over rotation, translation and the
    swept focal length. A refine that fails or leaves the admissible region is logged and the
    unrefined pose is kept. A view no phone camera has is refused.
    """
    if len(stump_quads_px) != 8:
        raise CalibrationError("Need exactly 8 stump corners (4 per end)")
    if crease_marks_px is not None and len(crease_marks_px) != 4:
        raise CalibrationError("Need exactly 4 crease marks, or none")
    width, height = image_size
    img = np.asarray(stump_quads_px, dtype=float)
    order = np.concatenate([_upright(img[:4]), 4 + _upright(img[4:])])
    img = img[order]
    at_striker = camera_at_striker(img)
    used_creases = crease_marks_px is not None
    obj = mark_points(pitch_length_m, at_striker, half_wicket=stump_width_m / 2, height=stump_height_m)
    if used_creases:
        img = np.vstack([img, np.asarray(crease_marks_px, dtype=float)])
        order = np.r_[order, 8:12]
    else:
        obj = obj[:8]

    def solve(fov):
        K = intrinsics(width, height, float(fov))
        sol = _pnp(obj, img, K)
        return None if sol is None else (sol[0], sol[1], sol[2], K, float(fov))

    if fov_deg is not None:
        best = solve(fov_deg)
    else:
        # log grid over the FOV, then a continuous polish from the best cell
        best = min(filter(None, map(solve, np.geomspace(*FOV_SWEEP_DEG, 60))), key=lambda c: c[0], default=None)
        if best is not None:
            res = minimize(lambda x: (solve(x[0]) or (1e9,))[0], [best[4]], method="Nelder-Mead",
                           bounds=[FOV_SWEEP_DEG], options={"xatol": 1e-2, "fatol": 1e-3})
            polished = solve(res.x[0])
            best = polished if polished is not None and polished[0] < best[0] else best
    if best is None:
        raise CalibrationError("Stump calibration is degenerate; re-mark the stump bases and tops.")

    err, R, t, K, fov = best
    refined = False
    if refine:
        out = _refine(obj, img, K, R, t, err, fov_deg is None, (width, height))
        if isinstance(out, str):
            _log.warning("calibration refine rejected, keeping the unrefined pose: %s", out)
        else:
            err, R, t, K = out
            fov = math.degrees(2.0 * math.atan((max(width, height) / 2.0) / float(K[0, 0])))
            refined = True
    if not PHONE_FOV_DEG[0] <= fov <= PHONE_FOV_DEG[1]:
        raise CalibrationError(f"The marks only fit a camera that sees {fov:.0f} degrees across, which no phone "
                               "camera does. Zoom in and re-mark the corners of both sets of stumps.")
    # err is the rms 2-D distance over the marks; spread it over the coordinates the fit left free
    n_obs = 2 * len(obj)
    tap_sigma = err * math.sqrt(n_obs / 2 / (n_obs - 6 - (fov_deg is None)))
    pose = CameraPose(K=K, R=R, t=t, reproj_error_px=err, fov_deg=fov, pitch_length_m=pitch_length_m,
                      pitch_width_m=pitch_width_m, used_creases=used_creases, refined=refined,
                      tap_sigma_px=tap_sigma, stump_height_m=stump_height_m, stump_width_m=stump_width_m)
    u, v, _ = pose.project(obj)
    res = np.empty_like(img)
    res[order] = np.column_stack([u, v]) - img
    return replace(pose, residuals_px=res)


def fitting_length(image_size, stump_quads_px, crease_marks_px, **dims) -> tuple[float, float] | None:
    """(length, reprojection error) of the pitch length the marks fit best. Only the crease marks make
    the length observable: from stumps alone a longer pitch fits as well as a wider lens."""
    fits = []
    for L in np.arange(10.0, 25.0 + 1e-9, 0.25):
        try:
            p = solve_camera_pose(image_size=image_size, stump_quads_px=stump_quads_px, crease_marks_px=crease_marks_px,
                                  pitch_length_m=float(L), refine=False, **dims)
        except CalibrationError:
            continue
        fits.append((float(L), p.reproj_error_px))
    return min(fits, key=lambda f: f[1], default=None)
