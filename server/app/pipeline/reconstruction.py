"""Monocular 3D reconstruction of a cricket ball trajectory.

Approach (umpire-POV camera):

1. Estimate camera intrinsics K from frame size.  We assume a typical phone
   FOV (~67 deg horizontal) which gives fx = fy ~= 0.9 * image_width.  This
   is good enough to within ~5 % for any modern smartphone in landscape or
   portrait.  Refining K from a single planar pattern is unreliable, so we
   keep it fixed.

2. Use cv2.solvePnP with 6 known world points (4 pitch corners on Z=0 plus
   2 stump tops at known height) to get the camera extrinsics (rvec, tvec).
   This yields a full 3D camera pose in the world frame defined as:
       X = along the pitch length (0 at striker crease, 20.12 at bowler crease)
       Y = pitch width  (negative = leg side for right-hander, positive = off)
       Z = height above ground (positive up)

3. For each detected ball with image position (u,v) and pixel radius r:
     a. Compute the back-projection ray from camera centre through (u,v).
     b. Compute depth from ball-size cue:  d = fx * R_real / r_pixel
        where R_real ~= 0.036 m (cricket ball radius).
     c. 3D point in camera frame = ray_unit * d.
     d. Transform to world frame via the inverse extrinsics.

4. Apply a projectile-motion fit to the world (X, Y, Z) trajectory:
     X(t) = X0 + Vx*t
     Y(t) = Y0 + Vy*t
     Z(t) = Z0 + Vz*t - 0.5 * 9.81 * t^2 + bounce reflection
   This step rejects outliers (depth-from-size is noisy when the ball is
   tiny in the image) and produces a smooth, physically plausible trajectory
   that we can extrapolate forward to the stump plane for LBW.

The output is a list of (t_ms, X, Y, Z) world points in metres plus the
fitted velocities and a per-point confidence based on residual to the fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import least_squares

from .calibration import CalibrationError

GRAVITY_MS2 = 9.81
BALL_RADIUS_M = 0.036
DEFAULT_STUMP_HEIGHT_M = 0.711
COEFFICIENT_OF_RESTITUTION_Z = 0.55  # bounce energy retained vertically

# Default bowling-direction guess: ball travels from bowler (X=L) to striker (X=0).
DEFAULT_PITCH_LENGTH_M = 20.12


@dataclass(frozen=True)
class CameraPose:
    K: np.ndarray            # 3x3 intrinsics
    rvec: np.ndarray         # 3x1 Rodrigues rotation (world->camera)
    tvec: np.ndarray         # 3x1 translation
    R: np.ndarray            # 3x3 rotation matrix
    R_inv: np.ndarray        # 3x3, world from camera
    cam_center_world: np.ndarray  # 3x1 camera optical centre in world
    fx: float
    fy: float
    cx: float
    cy: float
    reproj_error_px: float
    notes: list[str]


@dataclass(frozen=True)
class WorldPoint:
    t_ms: int
    x_m: float
    y_m: float
    z_m: float
    confidence: float
    depth_m: float           # along camera viewing ray
    radius_px: float


@dataclass(frozen=True)
class ProjectileFit:
    # State at t=0 (first observed ball position):
    x0: float
    y0: float
    z0: float
    vx: float
    vy: float
    vz: float
    # Bounce time relative to t=0; None if no bounce in observed window.
    bounce_t_ms: float | None
    rms_m: float
    notes: list[str]


@dataclass(frozen=True)
class Reconstruction:
    pose: CameraPose
    world_points: list[WorldPoint]
    fit: ProjectileFit | None
    bounce_index: int | None
    impact_index: int | None


# ---------------------------------------------------------------------------
# Camera pose
# ---------------------------------------------------------------------------

def estimate_intrinsics(image_width: int, image_height: int, *, h_fov_deg: float = 67.0) -> np.ndarray:
    """Approximate K for a phone camera given its frame size and horizontal FOV.

    For typical smartphones the horizontal FOV is in [60, 75] deg; 67 is a
    safe centre.  Errors here translate ~linearly into depth bias which is
    correctable later but doesn't matter for relative geometry on the pitch.
    """
    if not (1.0 < float(h_fov_deg) < 179.0):
        raise CalibrationError(
            f"h_fov_deg must be in (1, 179) degrees, got {h_fov_deg}"
        )
    fx = (image_width / 2.0) / math.tan(math.radians(h_fov_deg) / 2.0)
    fy = fx  # square pixels assumption (true for all modern phones)
    cx = image_width / 2.0
    cy = image_height / 2.0
    K = np.array([
        [fx, 0.0, cx],
        [0.0, fy, cy],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    return K


def solve_camera_pose(
    *,
    image_size: tuple[int, int],   # (width, height)
    pitch_corners_px: list[tuple[float, float]],
    pitch_length_m: float,
    pitch_width_m: float,
    stump_bases_px: list[tuple[float, float]] | None = None,  # (striker, bowler)
    stump_tops_px: list[tuple[float, float]] | None = None,   # (striker_top, bowler_top)
    stump_height_m: float = DEFAULT_STUMP_HEIGHT_M,
    h_fov_deg: float = 67.0,
) -> CameraPose:
    """Recover camera pose by PnP using 4 corners + optional stumps.

    The pitch corner order is the same the calibration UI emits:
        striker-left, striker-right, bowler-right, bowler-left
    World frame: X along pitch (0 = striker crease, +pitch_length_m = bowler
    crease), Y across pitch (positive = off side for right-hander, taken from
    image right when looking from striker toward bowler), Z up.
    """
    if cv2 is None:
        raise CalibrationError("OpenCV required for camera pose")
    if len(pitch_corners_px) != 4:
        raise CalibrationError("Need exactly 4 pitch corners for PnP")

    half_w = pitch_width_m / 2.0
    object_pts: list[tuple[float, float, float]] = [
        (0.0,             -half_w, 0.0),  # striker-left
        (0.0,              half_w, 0.0),  # striker-right
        (pitch_length_m,   half_w, 0.0),  # bowler-right
        (pitch_length_m,  -half_w, 0.0),  # bowler-left
    ]
    image_pts: list[tuple[float, float]] = list(pitch_corners_px)

    if stump_bases_px is not None and len(stump_bases_px) == 2:
        object_pts.append((0.0,            0.0, 0.0))
        object_pts.append((pitch_length_m, 0.0, 0.0))
        image_pts.append(stump_bases_px[0])
        image_pts.append(stump_bases_px[1])

    if stump_tops_px is not None and len(stump_tops_px) == 2:
        object_pts.append((0.0,            0.0, stump_height_m))
        object_pts.append((pitch_length_m, 0.0, stump_height_m))
        image_pts.append(stump_tops_px[0])
        image_pts.append(stump_tops_px[1])

    width, height = image_size
    K = estimate_intrinsics(width, height, h_fov_deg=h_fov_deg)
    dist = np.zeros((4, 1), dtype=np.float64)

    obj_arr = np.array(object_pts, dtype=np.float64)
    img_arr = np.array(image_pts, dtype=np.float64)

    # Planar PnP has a twofold mirror ambiguity. solvePnPGeneric with IPPE
    # returns both solutions; we pick the one whose camera centre lies above
    # the pitch (Z > 0), breaking the underground-twin failure mode.
    z_zero = np.allclose(obj_arr[:, 2], 0.0)
    if z_zero and len(obj_arr) >= 4:
        flag = cv2.SOLVEPNP_IPPE
        n_sols, rvecs, tvecs, _ = cv2.solvePnPGeneric(obj_arr, img_arr, K, dist, flags=flag)
        if n_sols == 0:
            raise CalibrationError("solvePnP failed to converge")
        candidates = list(zip(rvecs, tvecs))
    else:
        flag = cv2.SOLVEPNP_ITERATIVE
        ok, rvec_it, tvec_it = cv2.solvePnP(obj_arr, img_arr, K, dist, flags=flag)
        if not ok:
            raise CalibrationError("solvePnP failed to converge")
        candidates = [(rvec_it, tvec_it)]

    best_rvec = best_tvec = None
    best_R = best_R_inv = best_cam = None
    best_reproj = float("inf")
    above_found = False
    for rv, tv in candidates:
        R_i, _ = cv2.Rodrigues(rv)
        R_inv_i = R_i.T
        cam_i = -R_inv_i @ tv.reshape(3, 1)
        proj_i, _ = cv2.projectPoints(obj_arr, rv, tv, K, dist)
        proj_i = proj_i.reshape(-1, 2)
        reproj_i = float(np.sqrt(np.mean(np.sum((proj_i - img_arr) ** 2, axis=1))))
        above = float(cam_i[2, 0]) > 0.0
        # Strict preference: any above-ground solution beats any below; within
        # the same class, lower reprojection error wins.
        if above and not above_found:
            best_rvec, best_tvec = rv, tv
            best_R, best_R_inv, best_cam = R_i, R_inv_i, cam_i
            best_reproj = reproj_i
            above_found = True
        elif above == above_found and reproj_i < best_reproj:
            best_rvec, best_tvec = rv, tv
            best_R, best_R_inv, best_cam = R_i, R_inv_i, cam_i
            best_reproj = reproj_i
    if best_rvec is None:
        # Every PnP candidate was non-finite (e.g. all four corners identical
        # or collinear). Fail explicitly so the caller maps this to a
        # calibration error rather than crashing downstream on None fields.
        raise CalibrationError(
            "PnP returned no finite solution — pitch corners are degenerate"
        )

    rvec, tvec = best_rvec, best_tvec
    R, R_inv, cam_center = best_R, best_R_inv, best_cam
    reproj = best_reproj

    notes: list[str] = [
        f"{len(obj_arr)}-point PnP",
        f"flag={flag}",
        f"sols={len(candidates)}",
        f"cam_above_pitch={above_found}",
    ]
    return CameraPose(
        K=K,
        rvec=rvec,
        tvec=tvec,
        R=R,
        R_inv=R_inv,
        cam_center_world=cam_center,
        fx=float(K[0, 0]),
        fy=float(K[1, 1]),
        cx=float(K[0, 2]),
        cy=float(K[1, 2]),
        reproj_error_px=reproj,
        notes=notes,
    )


def solve_camera_pose_from_stumps(
    *,
    image_size: tuple[int, int],            # (width, height)
    stump_bases_px: list[tuple[float, float]],  # (striker, bowler)
    stump_tops_px: list[tuple[float, float]],   # (striker, bowler)
    stump_height_m: float = DEFAULT_STUMP_HEIGHT_M,
    h_fov_deg: float = 67.0,
    length_min_m: float = 2.0,
    length_max_m: float = 26.0,
) -> tuple[CameraPose, float]:
    """Recover the camera pose AND the pitch length from the two stump sets.

    The four stump marks — two bases on the ground and two tops at the known
    stump height — lie in the vertical plane through the pitch centre line. The
    stump height is a metric scale reference, so the only remaining unknown is
    the stump-to-stump length. We grid-search that length and keep the value
    whose PnP reprojection is smallest (the curve has a clear minimum at the
    true length because the known height pins the absolute scale).

    This removes the need for the user to know the real pitch length — essential
    for practice nets that are not a regulation 20.12 m — and is far more
    reliable than the wide, edge-less turf "corners", whose taps rarely match a
    rectangle centred on the stumps. Returns (pose, derived_length_m).
    """
    if cv2 is None:
        raise CalibrationError("OpenCV required for camera pose")
    if len(stump_bases_px) != 2 or len(stump_tops_px) != 2:
        raise CalibrationError("Need exactly 2 stump bases and 2 stump tops")

    width, height = image_size
    K = estimate_intrinsics(width, height, h_fov_deg=h_fov_deg)
    dist = np.zeros((4, 1), dtype=np.float64)
    img = np.array(
        [stump_bases_px[0], stump_tops_px[0], stump_bases_px[1], stump_tops_px[1]],
        dtype=np.float64,
    )

    best: tuple | None = None
    # 0.1 m steps give length to within a stump's width — finer than the
    # reprojection minimum is meaningful at this noise level.
    n_steps = max(2, int(round((length_max_m - length_min_m) / 0.1)) + 1)
    for length in np.linspace(length_min_m, length_max_m, n_steps):
        obj = np.array(
            [(0.0, 0.0, 0.0), (0.0, 0.0, stump_height_m),
             (float(length), 0.0, 0.0), (float(length), 0.0, stump_height_m)],
            dtype=np.float64,
        )
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_SQPNP)
        if not ok:
            continue
        R, _ = cv2.Rodrigues(rvec)
        R_inv = R.T
        cam = -R_inv @ tvec.reshape(3, 1)
        # A real camera sits above the ground.
        if float(cam[2, 0]) <= 0.0:
            continue
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
        proj = proj.reshape(-1, 2)
        reproj = float(np.sqrt(np.mean(np.sum((proj - img) ** 2, axis=1))))
        if not math.isfinite(reproj):
            continue
        if best is None or reproj < best[0]:
            best = (reproj, float(length), rvec, tvec, R, R_inv, cam)

    if best is None:
        raise CalibrationError(
            "Stump calibration is degenerate — re-mark the stump bases and tops."
        )

    reproj, length, rvec, tvec, R, R_inv, cam = best
    notes = [
        "stump-anchored pose",
        f"derived length={length:.2f} m",
        f"reproj={reproj:.1f}px",
    ]
    return (
        CameraPose(
            K=K,
            rvec=rvec,
            tvec=tvec,
            R=R,
            R_inv=R_inv,
            cam_center_world=cam,
            fx=float(K[0, 0]),
            fy=float(K[1, 1]),
            cx=float(K[0, 2]),
            cy=float(K[1, 2]),
            reproj_error_px=reproj,
            notes=notes,
        ),
        length,
    )


# ---------------------------------------------------------------------------
# Per-detection 3D from depth-from-size
# ---------------------------------------------------------------------------

def _backproject_ray(pose: CameraPose, u: float, v: float) -> np.ndarray:
    """Unit ray in *camera* coordinates pointing through pixel (u,v)."""
    x = (u - pose.cx) / pose.fx
    y = (v - pose.cy) / pose.fy
    ray = np.array([x, y, 1.0], dtype=np.float64)
    ray /= np.linalg.norm(ray)
    return ray


def backproject_to_ground(pose: CameraPose, u: float, v: float, z_target: float = 0.0) -> np.ndarray | None:
    """Back-project pixel (u, v) onto a horizontal world plane z = z_target.

    This is exact given the calibrated pose — no depth-from-size noise.
    Returns world (x, y, z_target) or None if the ray is parallel to the
    plane / above the horizon.
    """
    ray_cam = _backproject_ray(pose, u, v)
    ray_world = pose.R_inv @ ray_cam.reshape(3, 1)
    rw = ray_world.flatten()
    cam_w = pose.cam_center_world.flatten()
    dz = rw[2]
    if abs(dz) < 1e-6:
        return None
    s = (z_target - cam_w[2]) / dz
    if s <= 0:
        return None
    return np.array([cam_w[0] + s * rw[0], cam_w[1] + s * rw[1], z_target], dtype=np.float64)


def _camera_to_world(pose: CameraPose, point_cam: np.ndarray) -> np.ndarray:
    """Transform a column vector in camera frame to world frame."""
    p = point_cam.reshape(3, 1)
    return (pose.R_inv @ (p - pose.tvec.reshape(3, 1))).reshape(3)


def detection_to_world(
    pose: CameraPose,
    *,
    u: float,
    v: float,
    radius_px: float,
    ball_radius_m: float = BALL_RADIUS_M,
) -> tuple[np.ndarray, float]:
    """Return (world_xyz, depth_m) for a detection with known pixel radius.

    Depth from size:  d = fx * R_real / r_pixel  (Thales' theorem on the
    pinhole camera, valid for r_pixel small relative to focal length).
    The pixel radius is measured by minEnclosingCircle on the contour.
    """
    # Phrased as a positive assertion so NaN/Inf (which fail every comparison)
    # are rejected too, not just genuinely-small radii.
    if not (radius_px >= 0.5):
        raise ValueError("Detection radius invalid for depth estimation")
    depth = (pose.fx * ball_radius_m) / float(radius_px)
    ray = _backproject_ray(pose, u, v)  # unit, camera frame
    point_cam = ray * depth
    world = _camera_to_world(pose, point_cam)
    return world, float(depth)


# ---------------------------------------------------------------------------
# Projectile-motion fit
# ---------------------------------------------------------------------------

def _fit_projectile_no_bounce(
    times_s: np.ndarray, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray, ws: np.ndarray
) -> tuple[float, float, float, float, float, float, float]:
    """Weighted LSQ for X(t), Y(t) linear + Z(t) gravity-constrained quadratic.

    Returns (x0, vx, y0, vy, z0, vz, rms).  Z fit imposes a = -g (gravity),
    so we only solve for z0 and vz from the linearised  z + 0.5 g t^2 = z0 + vz t.
    """
    if len(times_s) < 3:
        raise ValueError("Need at least 3 points for projectile fit")

    sw = np.sqrt(np.maximum(ws, 1e-3))

    # Linear x.
    A = np.stack([np.ones_like(times_s), times_s], axis=1) * sw[:, None]
    b = xs * sw
    sol_x, *_ = np.linalg.lstsq(A, b, rcond=None)
    x0, vx = float(sol_x[0]), float(sol_x[1])

    # Linear y.
    b = ys * sw
    sol_y, *_ = np.linalg.lstsq(A, b, rcond=None)
    y0, vy = float(sol_y[0]), float(sol_y[1])

    # z-correction: solve for (z0, vz) from  z + 0.5 g t^2 = z0 + vz t
    z_corr = zs + 0.5 * GRAVITY_MS2 * times_s * times_s
    b = z_corr * sw
    sol_z, *_ = np.linalg.lstsq(A, b, rcond=None)
    z0, vz = float(sol_z[0]), float(sol_z[1])

    # RMS in 3D against fitted curve.
    x_pred = x0 + vx * times_s
    y_pred = y0 + vy * times_s
    z_pred = z0 + vz * times_s - 0.5 * GRAVITY_MS2 * times_s * times_s
    resid = np.sqrt((xs - x_pred) ** 2 + (ys - y_pred) ** 2 + (zs - z_pred) ** 2)
    rms = float(np.sqrt(np.mean(resid * resid)))
    return x0, vx, y0, vy, z0, vz, rms


def _refine_with_bounce(
    times_s: np.ndarray, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray, ws: np.ndarray,
    *, bounce_t_min_s: float, bounce_t_max_s: float, restitution: float = COEFFICIENT_OF_RESTITUTION_Z,
) -> tuple[float, float, float, float, float, float, float, float] | None:
    """Search for a bounce time that improves the fit.

    Strategy: grid-search bounce time t_b in (bounce_t_min, bounce_t_max).
    For each candidate t_b, fit pre-bounce projectile to t < t_b and
    post-bounce projectile to t >= t_b, with the post-bounce vz set to
    -restitution * vz_at_bounce.  Pick the t_b that minimises total RMS.

    Returns (x0, vx, y0, vy, z0, vz, t_b, rms) or None if no improvement.
    """
    candidates = np.linspace(bounce_t_min_s, bounce_t_max_s, 18)
    best = None
    for t_b in candidates:
        pre = times_s < t_b
        post = ~pre
        if pre.sum() < 2 or post.sum() < 2:
            continue
        try:
            x0, vx, y0, vy, z0, vz, rms_pre = _fit_projectile_no_bounce(
                times_s[pre], xs[pre], ys[pre], zs[pre], ws[pre]
            )
        except Exception:
            continue

        # Velocity at t_b from the pre fit.
        vz_at_tb = vz - GRAVITY_MS2 * t_b
        # Post-bounce we constrain vz' = -e * vz_at_tb at t = t_b.
        # Re-parameterise post-segment with origin at t_b.
        tp = times_s[post] - t_b
        # x_post(tp) = x_at_tb + vx * tp  (continue same vx, ground friction ignored)
        x_at_tb = x0 + vx * t_b
        y_at_tb = y0 + vy * t_b
        # Predicted post values (no free params for x,y after fixing the joint).
        x_pred_post = x_at_tb + vx * tp
        y_pred_post = y_at_tb + vy * tp
        z_pred_post = 0.0 + (-restitution * vz_at_tb) * tp - 0.5 * GRAVITY_MS2 * tp * tp
        # Snap z=0 at bounce — ball sits on ground at t_b.

        resid_pre_x = xs[pre] - (x0 + vx * times_s[pre])
        resid_pre_y = ys[pre] - (y0 + vy * times_s[pre])
        resid_pre_z = zs[pre] - (z0 + vz * times_s[pre] - 0.5 * GRAVITY_MS2 * times_s[pre] ** 2)
        resid_post = np.sqrt((xs[post] - x_pred_post) ** 2 + (ys[post] - y_pred_post) ** 2 + (zs[post] - z_pred_post) ** 2)
        resid_pre = np.sqrt(resid_pre_x ** 2 + resid_pre_y ** 2 + resid_pre_z ** 2)
        all_resid = np.concatenate([resid_pre, resid_post])
        rms = float(np.sqrt(np.mean(all_resid * all_resid)))

        if best is None or rms < best[-1]:
            best = (x0, vx, y0, vy, z0, vz, float(t_b), rms)
    return best


def fit_projectile(
    world_points: list[WorldPoint],
    *,
    pitch_length_m: float = DEFAULT_PITCH_LENGTH_M,
) -> ProjectileFit | None:
    """Fit a projectile (with optional bounce) to the world-space trajectory."""
    if len(world_points) < 4:
        return None

    t0_ms = world_points[0].t_ms
    times_s = np.array([(p.t_ms - t0_ms) / 1000.0 for p in world_points], dtype=float)
    xs = np.array([p.x_m for p in world_points], dtype=float)
    ys = np.array([p.y_m for p in world_points], dtype=float)
    zs = np.array([p.z_m for p in world_points], dtype=float)
    ws = np.array([max(0.05, p.confidence) for p in world_points], dtype=float)

    try:
        x0, vx, y0, vy, z0, vz, rms_no_b = _fit_projectile_no_bounce(times_s, xs, ys, zs, ws)
    except Exception:
        return None

    notes = [f"no-bounce rms={rms_no_b:.3f}m"]

    # Try to find a bounce that improves things.  Bounce search window is
    # the middle 60 % of the observed time range.
    duration = float(times_s[-1] - times_s[0])
    if duration > 0.20 and len(times_s) >= 6:
        t_lo = times_s[0] + 0.20 * duration
        t_hi = times_s[0] + 0.80 * duration
        bounce_fit = _refine_with_bounce(times_s, xs, ys, zs, ws, bounce_t_min_s=t_lo, bounce_t_max_s=t_hi)
        if bounce_fit is not None and bounce_fit[-1] < rms_no_b * 0.9:
            x0, vx, y0, vy, z0, vz, t_b, rms = bounce_fit
            notes.append(f"bounce-fit rms={rms:.3f}m at t={t_b*1000:.0f}ms")
            return ProjectileFit(
                x0=x0, y0=y0, z0=z0, vx=vx, vy=vy, vz=vz,
                bounce_t_ms=float(t_b * 1000.0),
                rms_m=float(rms),
                notes=notes,
            )

    return ProjectileFit(
        x0=x0, y0=y0, z0=z0, vx=vx, vy=vy, vz=vz,
        bounce_t_ms=None,
        rms_m=float(rms_no_b),
        notes=notes,
    )


def solve_bounce_trajectory_linear(
    pose: CameraPose,
    detections: list[tuple[int, float, float, float, float]],
    *,
    gravity: float = GRAVITY_MS2,
    restitution: float = COEFFICIENT_OF_RESTITUTION_Z,
) -> tuple[ProjectileFit, float] | None:
    """Bounce-aware gravity-constrained linear trajectory recovery.

    Grid-searches the bounce time. For each candidate it linearly solves the
    pre-bounce and post-bounce parabolas independently (each via
    `solve_projectile_linear`), and scores the split by combined pixel
    reprojection error. The winning split yields the pre-bounce 6-vector
    plus a vz chosen so the downstream restitution model reproduces the
    linearly-recovered post-bounce vertical velocity.

    Returns (fit, rms_px) — the combined pixel reprojection RMS lets the caller
    compare it head-to-head with the single-parabola `solve_projectile_linear`
    — or None if no split fits.
    """
    if len(detections) < 8:
        return None
    dets = sorted(detections, key=lambda d: d[0])
    t0_ms = dets[0][0]
    total_s = (dets[-1][0] - t0_ms) / 1000.0
    if total_s < 0.2:
        return None

    best: ProjectileFit | None = None
    best_rms_px = float("inf")

    for frac in np.linspace(0.25, 0.75, 11):
        t_b_s = frac * total_s
        t_b_ms = t0_ms + t_b_s * 1000.0
        pre = [d for d in dets if d[0] <= t_b_ms]
        post = [d for d in dets if d[0] > t_b_ms]
        if len(pre) < 3 or len(post) < 3:
            continue
        pre_res = solve_projectile_linear(pose, pre, gravity=gravity)
        post_res = solve_projectile_linear(pose, post, gravity=gravity)
        if pre_res is None or post_res is None:
            continue
        pre_fit, pre_rms = pre_res
        post_fit, post_rms = post_res
        # Combined reprojection RMS over all points (RMS, not sum, so it is
        # directly comparable to the single-parabola fit's rms_px).
        combined_rms = math.sqrt(
            (pre_rms ** 2 * len(pre) + post_rms ** 2 * len(post)) / max(1, len(pre) + len(post))
        )
        if combined_rms >= best_rms_px:
            continue
        # post_fit was solved with its own t=0 at the first post-bounce
        # detection. Its vz is the post-bounce vertical velocity near the
        # bounce. Choose pre-bounce vz so the restitution model reproduces it:
        #   vz_post = -e * (vz_pre - g*t_b)  =>  vz_pre = g*t_b - vz_post/e
        vz_post = post_fit.vz
        vz_pre = gravity * t_b_s - vz_post / max(restitution, 1e-3)
        best_rms_px = combined_rms
        best = ProjectileFit(
            x0=pre_fit.x0, y0=pre_fit.y0, z0=pre_fit.z0,
            vx=pre_fit.vx, vy=pre_fit.vy, vz=vz_pre,
            bounce_t_ms=float(t_b_s * 1000.0),
            rms_m=0.0,
            notes=[
                "bounce-aware linear solve (Ribnick 2009)",
                f"t_b={t_b_s*1000:.0f}ms pre_rms={pre_rms:.2f}px post_rms={post_rms:.2f}px",
            ],
        )
    if best is None:
        return None
    return best, best_rms_px


def solve_projectile_linear(
    pose: CameraPose,
    detections: list[tuple[int, float, float, float, float]],
    *,
    gravity: float = GRAVITY_MS2,
) -> tuple[ProjectileFit, float] | None:
    """Closed-form 3D projectile recovery from monocular image observations.

    Implements the gravity-constrained linear formulation of Ribnick,
    Atev & Papanikolopoulos, "Estimating 3D Positions and Velocities of
    Projectiles from Monocular Views" (IEEE TPAMI 2009).

    A projectile in world coordinates is
        Xw(t) = x0 + vx t
        Yw(t) = y0 + vy t
        Zw(t) = z0 + vz t - 0.5 g t^2
    The camera maps Pw -> Pc = R Pw + T, then u = fx Pc_x / Pc_z + cx,
    v = fy Pc_y / Pc_z + cy. Cross-multiplying the projection equations
    removes the division and, crucially, the only nonlinear term
    (0.5 g t^2) is a *known* constant because g is known. The result is a
    system that is LINEAR in the six unknowns theta = [x0,y0,z0,vx,vy,vz]:

        [(u-cx) a_z - fx a_x] . theta = fx b_x - (u-cx) b_z
        [(v-cy) a_z - fy a_y] . theta = fy b_y - (v-cy) b_z

    where Pc_* = a_*(t) . theta + b_*(t). With >= 3 observations this is an
    over-determined linear least-squares problem, so there is no seed, no
    local minima, and gravity fixes the absolute scale.

    Returns (fit, rms_px) or None if the system is degenerate.
    """
    if len(detections) < 3:
        return None

    R = pose.R
    T = pose.tvec.reshape(3)
    fx, fy, cx, cy = pose.fx, pose.fy, pose.cx, pose.cy

    t0_ms = detections[0][0]
    rows: list[np.ndarray] = []
    rhs: list[float] = []

    for t_ms, u, v, _r, conf in detections:
        t = (t_ms - t0_ms) / 1000.0
        w = max(0.05, float(conf)) ** 0.5
        # Pc_* = a_* . theta + b_*, with theta = [x0,y0,z0,vx,vy,vz].
        # Xw = x0 + vx t  -> coeffs over theta: [1,0,0,t,0,0]
        # Yw = y0 + vy t  -> [0,1,0,0,t,0]
        # Zw = z0 + vz t  -> [0,0,1,0,0,t]   (gravity handled in b)
        # Pc_row_k = R[k,0]*Xw + R[k,1]*Yw + R[k,2]*Zw + T[k]
        g_off = -0.5 * gravity * t * t  # gravity contribution to Zw
        a = np.zeros((3, 6), dtype=float)
        b = np.zeros(3, dtype=float)
        for k in range(3):
            a[k, 0] = R[k, 0]
            a[k, 1] = R[k, 1]
            a[k, 2] = R[k, 2]
            a[k, 3] = R[k, 0] * t
            a[k, 4] = R[k, 1] * t
            a[k, 5] = R[k, 2] * t
            b[k] = R[k, 2] * g_off + T[k]
        a_x, a_y, a_z = a[0], a[1], a[2]
        b_x, b_y, b_z = b[0], b[1], b[2]
        # u constraint
        rows.append(w * ((u - cx) * a_z - fx * a_x))
        rhs.append(w * (fx * b_x - (u - cx) * b_z))
        # v constraint
        rows.append(w * ((v - cy) * a_z - fy * a_y))
        rhs.append(w * (fy * b_y - (v - cy) * b_z))

    A = np.asarray(rows, dtype=float)
    bb = np.asarray(rhs, dtype=float)
    try:
        theta, *_ = np.linalg.lstsq(A, bb, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(theta)):
        return None

    x0, y0, z0, vx, vy, vz = (float(v) for v in theta)

    # Reprojection RMS in pixels.
    sq = 0.0
    n = 0
    for t_ms, u, v, _r, _conf in detections:
        t = (t_ms - t0_ms) / 1000.0
        xw = x0 + vx * t
        yw = y0 + vy * t
        zw = z0 + vz * t - 0.5 * gravity * t * t
        proj = _project_world(pose, xw, yw, zw)
        if proj is None:
            sq += 1e6
            n += 1
            continue
        up, vp, _ = proj
        sq += (u - up) ** 2 + (v - vp) ** 2
        n += 1
    rms_px = float(math.sqrt(sq / max(1, n)))

    return (
        ProjectileFit(
            x0=x0, y0=y0, z0=z0, vx=vx, vy=vy, vz=vz,
            bounce_t_ms=None,
            rms_m=0.0,
            notes=["linear gravity-constrained solve (Ribnick 2009)"],
        ),
        rms_px,
    )


# ---------------------------------------------------------------------------
# End-to-end reconstruct + classify bounce / impact
# ---------------------------------------------------------------------------

def _project_world(pose: CameraPose, x: float, y: float, z: float) -> tuple[float, float, float] | None:
    """Project world point through camera; returns (u, v, depth) or None if behind camera."""
    p_world = np.array([[x], [y], [z]], dtype=np.float64)
    p_cam = pose.R @ p_world + pose.tvec.reshape(3, 1)
    depth = float(p_cam[2, 0])
    if depth <= 0.05:
        return None
    u = pose.fx * (p_cam[0, 0] / depth) + pose.cx
    v = pose.fy * (p_cam[1, 0] / depth) + pose.cy
    return float(u), float(v), depth


def _projectile_at(params: np.ndarray, t_s: float, *, has_bounce: bool, t_b: float | None,
                   restitution: float = COEFFICIENT_OF_RESTITUTION_Z) -> tuple[float, float, float]:
    """Compute (x, y, z) from 6-param projectile state at time t_s.

    `params` = [x0, y0, z0, vx, vy, vz].  When has_bounce is True we use the
    analytically-correct ground-touch time computed from the pre-bounce
    parabola, not the externally-supplied `t_b`. Using the physical bounce
    time keeps the trajectory continuous (z is exactly 0 at the bounce) and
    avoids the discontinuity that previously produced bad post-bounce arcs.
    The supplied `t_b` is used only as a hint to enable the bounce branch.
    """
    x0, y0, z0, vx, vy, vz = params
    # Pre-bounce parabola.
    def z_pre(t):
        return z0 + vz * t - 0.5 * GRAVITY_MS2 * t * t

    if has_bounce and t_b is not None:
        # Solve z(t)=0: 0.5*g*t² - vz*t - z0 = 0 → t = (vz + sqrt(vz² + 2 g z0)) / g.
        disc = vz * vz + 2.0 * GRAVITY_MS2 * max(z0, 0.0)
        if disc <= 0 or z0 <= 0:
            t_ground = max(t_b, 0.01)
        else:
            t_ground = (vz + math.sqrt(disc)) / GRAVITY_MS2
            if t_ground <= 0:
                t_ground = max(t_b, 0.01)
        if t_s < t_ground:
            x = x0 + vx * t_s
            y = y0 + vy * t_s
            z = max(0.0, z_pre(t_s))
        else:
            vz_at_b = vz - GRAVITY_MS2 * t_ground
            vz_post = -restitution * vz_at_b
            tp = t_s - t_ground
            x = (x0 + vx * t_ground) + vx * tp
            y = (y0 + vy * t_ground) + vy * tp
            z = max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp * tp)
    else:
        x = x0 + vx * t_s
        y = y0 + vy * t_s
        z = max(0.0, z_pre(t_s))
    return x, y, z


def _bundle_adjust_trajectory(
    *,
    pose: CameraPose,
    detections: list[tuple[int, float, float, float, float]],
    seed: ProjectileFit,
    radius_weight: float = 0.0,
    pitch_length_m: float | None = None,
) -> ProjectileFit | None:
    """Refine the 6 trajectory parameters by minimising pixel + radius residuals.

    Pixel residuals dominate (3 pixel units = 1 unit weight); radius residual
    has its own weight because radius noise is multiplicative and only
    informative at close depths. When `pitch_length_m` is supplied an
    additional penalty steers the optimiser toward trajectories that span
    most of the pitch, which is essential when the ball moves along the
    camera optical axis (depth-from-size alone is too weak to localise the
    ball longitudinally).

    If the seed has a bounce, we keep it as a fixed knot and only refine the
    pre-bounce 6 params (post-bounce trajectory is determined by joint).
    """
    if not detections:
        return None

    t0_ms = detections[0][0]
    times_s = np.array([(d[0] - t0_ms) / 1000.0 for d in detections], dtype=float)
    us = np.array([d[1] for d in detections], dtype=float)
    vs = np.array([d[2] for d in detections], dtype=float)
    rs = np.array([d[3] for d in detections], dtype=float)
    ws = np.array([max(0.05, d[4]) for d in detections], dtype=float)

    has_bounce = seed.bounce_t_ms is not None
    t_b = seed.bounce_t_ms / 1000.0 if has_bounce else None

    # Direction prior: with the camera at one end of the pitch the ball is
    # expected to travel from the far crease to the near crease. We compute
    # the expected endpoints based on the sign of the seed velocity.
    expected_x0: float | None = None
    expected_x_end: float | None = None
    if pitch_length_m is not None and pitch_length_m > 0 and seed.vx != 0:
        if seed.vx < 0:
            expected_x0 = pitch_length_m
            expected_x_end = 0.0
        else:
            expected_x0 = 0.0
            expected_x_end = pitch_length_m
    t_end_s = float(times_s[-1])

    def residuals(params):
        out = []
        for i, t in enumerate(times_s):
            x, y, z = _projectile_at(params, t, has_bounce=has_bounce, t_b=t_b)
            proj = _project_world(pose, x, y, z)
            if proj is None:
                # Heavy penalty for behind-camera predictions.
                out.extend([1000.0, 1000.0, 1000.0])
                continue
            u_pred, v_pred, depth = proj
            r_pred = pose.fx * BALL_RADIUS_M / depth
            # Pixel residual scaled by 1.
            out.append((us[i] - u_pred) * ws[i])
            out.append((vs[i] - v_pred) * ws[i])
            # Radius residual: scaled to be comparable in magnitude to pixel
            # residuals. depth = fx*R/r, so d(depth)/d(r) = -fx*R/r^2 = -depth/r.
            # A 1px error in radius corresponds to (depth/r) m error in depth.
            # We use ratio residual (r_obs/r_pred - 1) which is dimensionless
            # and comparable to (1px / r_pred) — i.e. the radius-relative noise.
            if rs[i] > 1.0 and r_pred > 1.0:
                # Bigger detections give more reliable radius info; weight grows with r.
                size_w = min(1.0, r_pred / 6.0)
                out.append(radius_weight * size_w * ws[i] * (rs[i] / r_pred - 1.0))
            else:
                out.append(0.0)
        # Soft pitch-traversal prior. Pixel residuals dominate, this just
        # nudges the optimiser away from degenerate solutions when the ball
        # moves along the camera axis. A 1m endpoint deviation contributes
        # ~1.5 units, comparable to a small pixel error.
        if expected_x0 is not None and expected_x_end is not None:
            x_init, _, _ = _projectile_at(params, 0.0, has_bounce=has_bounce, t_b=t_b)
            x_final, _, _ = _projectile_at(params, t_end_s, has_bounce=has_bounce, t_b=t_b)
            prior_weight = 1.5
            out.append(prior_weight * (x_init - expected_x0))
            out.append(prior_weight * (x_final - expected_x_end))
        return np.asarray(out, dtype=float)

    x0_arr = np.array([seed.x0, seed.y0, seed.z0, seed.vx, seed.vy, seed.vz], dtype=float)

    # Physical bounds: ball release is above ground in front of the camera,
    # delivered with realistic phone-pace velocities. The Trust-Region
    # Reflective solver supports bounds, unlike Levenberg-Marquardt.
    span = (pitch_length_m or 30.0) + 5.0
    lower = np.array([-span, -3.0,  0.0, -50.0, -5.0, -8.0])
    upper = np.array([ span,  3.0,  3.5,  50.0,  5.0,  2.0])
    # Clip seed to bounds so the solver starts on a valid point.
    x0_arr = np.clip(x0_arr, lower + 1e-3, upper - 1e-3)

    try:
        sol = least_squares(
            residuals, x0_arr,
            method="trf",
            bounds=(lower, upper),
            max_nfev=200,
            xtol=1e-8, ftol=1e-8,
        )
    except Exception:
        return None

    p = sol.x
    rms_pixels = float(np.sqrt(np.mean(sol.fun ** 2)))
    notes = list(seed.notes) + [f"bundle-adj rms_resid={rms_pixels:.3f}", f"nfev={sol.nfev}"]

    # Bundle adjustment occasionally flips vx sign when the ball moves along
    # the camera axis (depth-from-size alone cannot disambiguate direction).
    # If that happens we reject the optimised solution and keep the seed,
    # which preserves the direction implied by the depth-from-size lift.
    if seed.vx != 0 and (p[3] * seed.vx) < 0:
        notes.append("bundle-adj rejected: vx sign flipped")
        p = np.array([seed.x0, seed.y0, seed.z0, seed.vx, seed.vy, seed.vz], dtype=float)

    # Compute world RMS for our reporting (recompute residuals in world coords).
    world_resids = []
    for i, t in enumerate(times_s):
        x, y, z = _projectile_at(p, t, has_bounce=has_bounce, t_b=t_b)
        proj = _project_world(pose, x, y, z)
        if proj is None:
            continue
        # Approximate world error from pixel error via local depth scaling.
        u_pred, v_pred, depth = proj
        pix_err = math.hypot(us[i] - u_pred, vs[i] - v_pred)
        world_resids.append(pix_err * depth / pose.fx)
    rms_world = float(np.sqrt(np.mean(np.array(world_resids) ** 2))) if world_resids else seed.rms_m

    return ProjectileFit(
        x0=float(p[0]), y0=float(p[1]), z0=float(p[2]),
        vx=float(p[3]), vy=float(p[4]), vz=float(p[5]),
        bounce_t_ms=seed.bounce_t_ms,
        rms_m=rms_world,
        notes=notes,
    )


def _search_bounce_then_bundle(
    *,
    pose: CameraPose,
    detections: list[tuple[int, float, float, float, float]],
    seed_no_bounce: ProjectileFit,
    pitch_length_m: float | None = None,
) -> ProjectileFit:
    """Grid-search bounce time and bundle-adjust each candidate; return best."""
    if not detections:
        return seed_no_bounce
    t0_ms = detections[0][0]
    duration_s = (detections[-1][0] - t0_ms) / 1000.0
    if duration_s < 0.20 or len(detections) < 6:
        return _bundle_adjust_trajectory(
            pose=pose, detections=detections, seed=seed_no_bounce,
            pitch_length_m=pitch_length_m,
        ) or seed_no_bounce

    best = _bundle_adjust_trajectory(
        pose=pose, detections=detections, seed=seed_no_bounce,
        pitch_length_m=pitch_length_m,
    ) or seed_no_bounce

    for t_b_s in np.linspace(0.20 * duration_s, 0.80 * duration_s, 12):
        seeded = ProjectileFit(
            x0=seed_no_bounce.x0, y0=seed_no_bounce.y0, z0=seed_no_bounce.z0,
            vx=seed_no_bounce.vx, vy=seed_no_bounce.vy, vz=seed_no_bounce.vz,
            bounce_t_ms=float(t_b_s * 1000.0),
            rms_m=seed_no_bounce.rms_m,
            notes=list(seed_no_bounce.notes),
        )
        candidate = _bundle_adjust_trajectory(
            pose=pose, detections=detections, seed=seeded,
            pitch_length_m=pitch_length_m,
        )
        if candidate is None:
            continue
        if candidate.rms_m < best.rms_m * 0.95:
            best = candidate
    return best


def reconstruct_trajectory(
    *,
    pose: CameraPose,
    detections: list[tuple[int, float, float, float, float]],  # (t_ms, x_px, y_px, radius_px, conf)
    pitch_length_m: float = DEFAULT_PITCH_LENGTH_M,
    pitch_width_m: float = 3.05,
    prefer_linear: bool = False,
) -> Reconstruction:
    """Build the full 3D reconstruction from per-frame ball detections.

    Filters out detections whose lifted world-position is implausible
    (e.g. behind the camera, far above realistic release height, way off the
    pitch laterally) before fitting.
    """
    raw: list[WorldPoint] = []
    for t_ms, u, v, r, conf in detections:
        if r < 0.5:
            continue
        try:
            w_xyz, depth = detection_to_world(pose, u=u, v=v, radius_px=r)
        except Exception:
            continue
        x, y, z = float(w_xyz[0]), float(w_xyz[1]), float(w_xyz[2])
        # Plausibility gate: ball must be roughly on/above the pitch.
        if not (-3.0 <= x <= pitch_length_m + 3.0):
            continue
        if abs(y) > pitch_width_m * 1.5:
            continue
        if not (-0.2 <= z <= 4.5):
            continue
        if depth <= 0.5 or depth > pitch_length_m + 6.0:
            continue
        raw.append(WorldPoint(
            t_ms=int(t_ms), x_m=x, y_m=y, z_m=z,
            confidence=float(conf),
            depth_m=float(depth),
            radius_px=float(r),
        ))

    # ---- Trajectory fit ---------------------------------------------------
    # Two reconstruction routes:
    #
    #  * prefer_linear (real, stump-calibrated footage): solve the trajectory
    #    directly with the gravity-constrained linear method of Ribnick, Atev &
    #    Papanikolopoulos (IEEE TPAMI 2009). Given an accurate pose it recovers a
    #    smooth, correctly-oriented arc straight from the pixel track + gravity —
    #    no depth-from-size cues — which avoids the "cliff" and direction flips
    #    the engineered chain produces on noisy handheld phone clips.
    #
    #  * otherwise (e.g. synthetic, no stumps): the depth-from-size seed +
    #    bounded bundle adjustment + image-space bounce anchor chain, which is
    #    more accurate when the calibration and ball sizes are clean.
    good_dets = [d for d in detections if d[3] >= 0.5]

    fit: ProjectileFit | None = None
    used_linear = False
    if prefer_linear and len(good_dets) >= 3:
        lin = solve_projectile_linear(pose, good_dets)
        if lin is not None and math.isfinite(lin[0].vx):
            lin_fit, lin_rms_px = lin
            # Express the pixel residual in metres for the downstream quality
            # gate (a pixel error maps to a world error scaled by depth / focal).
            depth_ref = abs(float(pose.cam_center_world.flatten()[2])) + pitch_length_m * 0.5
            px_to_m = depth_ref / max(1.0, pose.fx)
            fit = ProjectileFit(
                x0=lin_fit.x0, y0=lin_fit.y0, z0=lin_fit.z0,
                vx=lin_fit.vx, vy=lin_fit.vy, vz=lin_fit.vz,
                bounce_t_ms=None,
                rms_m=float(lin_rms_px * px_to_m),
                notes=list(lin_fit.notes),
            )
            used_linear = True

            # A real delivery bounces. The single parabola above cannot bend at
            # the pitch, so on a bounced ball it fits one smooth arc with no
            # pitch point and a prediction that ignores the bounce. Solve the
            # two-parabola (pre/post-bounce) linear model as well and keep it
            # when it explains the pixels clearly better. The 0.9 margin stops a
            # genuine full-toss (no bounce) from being handed a spurious one.
            bl = solve_bounce_trajectory_linear(pose, good_dets)
            if bl is not None and math.isfinite(bl[0].vx) and bl[1] < lin_rms_px * 0.9:
                bl_fit, bl_rms_px = bl
                fit = ProjectileFit(
                    x0=bl_fit.x0, y0=bl_fit.y0, z0=bl_fit.z0,
                    vx=bl_fit.vx, vy=bl_fit.vy, vz=bl_fit.vz,
                    bounce_t_ms=bl_fit.bounce_t_ms,
                    rms_m=float(bl_rms_px * px_to_m),
                    notes=list(bl_fit.notes),
                )

    if not used_linear:
        fit_seed = fit_projectile(raw, pitch_length_m=pitch_length_m)
        if fit_seed is not None and len(detections) >= 6:
            fit = _search_bounce_then_bundle(
                pose=pose,
                detections=good_dets,
                seed_no_bounce=fit_seed,
                pitch_length_m=pitch_length_m,
            )
        else:
            fit = fit_seed

        # Fallback: when the depth-from-size chain fails to produce any fit (e.g.
        # the lifted world points were all rejected by the plausibility gate),
        # try the gravity-constrained linear solver. It needs only image
        # observations and the known pose, so it can still recover a trajectory
        # when the depth-from-size lift is degenerate.
        if fit is None and len(good_dets) >= 8:
            bl = solve_bounce_trajectory_linear(pose, good_dets)
            if bl is not None:
                fit = bl[0]

    # Sanity guard: a real delivery traverses most of the pitch. If the fit
    # barely moves, rebuild a geometry-based estimate from the pitch length.
    # (Skipped for the linear route, whose arc is already physically derived.)
    if (
        not used_linear
        and fit is not None
        and pitch_length_m
        and detections
        and len(detections) >= 4
    ):
        t_first = float(detections[0][0]) / 1000.0
        t_last = float(detections[-1][0]) / 1000.0
        dt_s = max(0.05, t_last - t_first)
        if abs(fit.vx) * dt_s < 0.30 * pitch_length_m:
            cam_x = float(pose.cam_center_world.flatten()[0])
            cam_at_striker = cam_x < pitch_length_m * 0.5
            direction = -1.0 if cam_at_striker else 1.0
            x0_geo = pitch_length_m if cam_at_striker else 0.0
            speed_geo = pitch_length_m / dt_s
            geo = ProjectileFit(
                x0=x0_geo, y0=fit.y0, z0=2.0,
                vx=direction * speed_geo, vy=fit.vy, vz=-3.0,
                bounce_t_ms=fit.bounce_t_ms,
                rms_m=fit.rms_m,
                notes=list(fit.notes) + ["geometry rebuild: traversal < 30% pitch"],
            )
            cand = _bundle_adjust_trajectory(
                pose=pose, detections=good_dets, seed=geo,
                pitch_length_m=pitch_length_m,
            )
            fit = cand if (cand is not None and abs(cand.vx) * dt_s >= 0.30 * pitch_length_m) else geo

    # Image-space bounce anchor: back-project the bounce-frame pixel onto the
    # calibrated ground plane (z=0) for an exact world bounce position, then
    # re-anchor the trajectory. This is more robust than depth-from-size
    # because the bounce z is known to be zero.
    # (Skipped for the linear route — its arc already comes from the geometry.)
    if not used_linear and detections and len(detections) >= 8:
        sorted_dets = sorted(detections, key=lambda d: d[0])
        vs = np.array([d[2] for d in sorted_dets], dtype=float)
        ts = np.array([d[0] for d in sorted_dets], dtype=float)
        smooth = np.copy(vs)
        for i in range(1, len(vs) - 1):
            smooth[i] = (vs[i - 1] + vs[i] + vs[i + 1]) / 3.0
        lo = int(0.15 * len(smooth))
        hi = int(0.85 * len(smooth))
        if hi > lo + 1:
            bounce_local_idx = int(lo + int(np.argmin(smooth[lo:hi])))
            t_bounce_ms = float(ts[bounce_local_idx])
            u_b = float(sorted_dets[bounce_local_idx][1])
            v_b = float(sorted_dets[bounce_local_idx][2])
            anchor = backproject_to_ground(pose, u_b, v_b, z_target=0.0)
            if anchor is not None and -3.0 <= anchor[0] <= pitch_length_m + 3.0:
                if fit is None:
                    dt_total = max(0.05, (sorted_dets[-1][0] - sorted_dets[0][0]) / 1000.0)
                    cam_x = float(pose.cam_center_world.flatten()[0])
                    direction = -1.0 if cam_x < pitch_length_m * 0.5 else 1.0
                    speed = pitch_length_m / dt_total
                    fit = ProjectileFit(
                        x0=0.0, y0=0.0, z0=2.0,
                        vx=direction * speed, vy=0.0, vz=-3.0,
                        bounce_t_ms=t_bounce_ms - sorted_dets[0][0],
                        rms_m=2.0,
                        notes=["synthesised from bounce anchor"],
                    )
                t0_ms = sorted_dets[0][0]
                t_b_s = (t_bounce_ms - t0_ms) / 1000.0
                # Release-height anchor: back-project the first detection at an
                # assumed release height (z ~ 2 m). With the exact ground
                # bounce anchor this yields vx and vy from world geometry.
                u0, v0 = float(sorted_dets[0][1]), float(sorted_dets[0][2])
                rel = backproject_to_ground(pose, u0, v0, z_target=2.0)
                new_y0 = float(anchor[1]) - fit.vy * t_b_s
                new_vx = fit.vx
                new_vy = fit.vy
                if rel is not None and t_b_s > 0.05:
                    cand_vx = (float(anchor[0]) - float(rel[0])) / t_b_s
                    cand_vy = (float(anchor[1]) - float(rel[1])) / t_b_s
                    if 10.0 < abs(cand_vx) < 50.0:
                        new_vx = cand_vx
                        new_vy = cand_vy
                        new_y0 = float(rel[1])
                new_x0 = float(anchor[0]) - new_vx * t_b_s
                new_vz = (0.5 * GRAVITY_MS2 * t_b_s * t_b_s - fit.z0) / max(t_b_s, 0.01)
                fit = ProjectileFit(
                    x0=new_x0, y0=new_y0, z0=fit.z0,
                    vx=new_vx, vy=new_vy, vz=new_vz,
                    bounce_t_ms=t_b_s * 1000.0,
                    rms_m=fit.rms_m,
                    notes=list(fit.notes) + [
                        f"image-bounce anchor t={t_b_s*1000:.0f}ms "
                        f"world=({anchor[0]:.2f},{anchor[1]:.2f})"
                    ],
                )

    bounce_index: int | None = None
    impact_index: int | None = None
    smoothed = list(raw)

    if fit is not None and len(raw) >= 4:
        # Replace observations with smoothed projectile values; observations
        # are noisy (depth-from-size has ~10 % noise) but the fit is smooth.
        t0_ms = raw[0].t_ms
        smoothed = []
        for p in raw:
            ts = (p.t_ms - t0_ms) / 1000.0
            if fit.bounce_t_ms is not None and ts >= fit.bounce_t_ms / 1000.0:
                t_b = fit.bounce_t_ms / 1000.0
                vz_at_b = fit.vz - GRAVITY_MS2 * t_b
                vz_post = -COEFFICIENT_OF_RESTITUTION_Z * vz_at_b
                tp = ts - t_b
                x_s = (fit.x0 + fit.vx * t_b) + fit.vx * tp
                y_s = (fit.y0 + fit.vy * t_b) + fit.vy * tp
                z_s = max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp * tp)
            else:
                x_s = fit.x0 + fit.vx * ts
                y_s = fit.y0 + fit.vy * ts
                z_s = max(0.0, fit.z0 + fit.vz * ts - 0.5 * GRAVITY_MS2 * ts * ts)
            # Confidence weighted by raw observation conf and inverse-residual.
            resid = math.sqrt((p.x_m - x_s) ** 2 + (p.y_m - y_s) ** 2 + (p.z_m - z_s) ** 2)
            tightness = max(0.05, 1.0 - resid / max(0.5, fit.rms_m * 3.0))
            conf = float(min(1.0, 0.4 * p.confidence + 0.6 * tightness))
            smoothed.append(WorldPoint(
                t_ms=p.t_ms, x_m=x_s, y_m=y_s, z_m=z_s,
                confidence=conf, depth_m=p.depth_m, radius_px=p.radius_px,
            ))

        # Bounce index: closest observation to bounce_t_ms (if any).
        if fit.bounce_t_ms is not None:
            target_t = t0_ms + fit.bounce_t_ms
            bounce_index = int(np.argmin([abs(p.t_ms - target_t) for p in smoothed]))
        # Impact = stump-plane intersection: where world X reaches striker
        # crease (X=0) or bowler crease (X=pitch_length).  Use whichever
        # the ball is moving toward.
        x_first = smoothed[0].x_m
        x_last = smoothed[-1].x_m
        target_x = 0.0 if x_last < x_first else pitch_length_m
        impact_index = int(np.argmin([abs(p.x_m - target_x) for p in smoothed]))

    return Reconstruction(
        pose=pose,
        world_points=smoothed,
        fit=fit,
        bounce_index=bounce_index,
        impact_index=impact_index,
    )


def predict_path_to_stumps(
    fit: ProjectileFit,
    *,
    impact_t_ms: float,
    target_x_m: float,
    n_steps: int = 18,
) -> list[tuple[float, float, float, float]]:
    """Forward-extrapolate the projectile from impact to the stump plane.

    Returns a list of (t_ms_relative_to_fit_origin, x, y, z) — useful for
    drawing the predicted continuation of the trajectory in the 3D viewer.
    """
    impact_s = impact_t_ms / 1000.0

    # Determine velocities at the impact moment (after bounce if applicable).
    if fit.bounce_t_ms is not None and impact_s > fit.bounce_t_ms / 1000.0:
        t_b = fit.bounce_t_ms / 1000.0
        vz_at_b = fit.vz - GRAVITY_MS2 * t_b
        vz_post_at_bounce = -COEFFICIENT_OF_RESTITUTION_Z * vz_at_b
        # State at impact:
        tp_at_impact = impact_s - t_b
        x_imp = (fit.x0 + fit.vx * t_b) + fit.vx * tp_at_impact
        y_imp = (fit.y0 + fit.vy * t_b) + fit.vy * tp_at_impact
        z_imp = max(0.0, vz_post_at_bounce * tp_at_impact - 0.5 * GRAVITY_MS2 * tp_at_impact ** 2)
        vz_at_imp = vz_post_at_bounce - GRAVITY_MS2 * tp_at_impact
    else:
        x_imp = fit.x0 + fit.vx * impact_s
        y_imp = fit.y0 + fit.vy * impact_s
        z_imp = max(0.0, fit.z0 + fit.vz * impact_s - 0.5 * GRAVITY_MS2 * impact_s ** 2)
        vz_at_imp = fit.vz - GRAVITY_MS2 * impact_s

    # Time from impact to target_x, assuming vx unchanged.
    if abs(fit.vx) < 1e-3:
        return []
    dt_to_stumps = (target_x_m - x_imp) / fit.vx
    if dt_to_stumps < 0 or dt_to_stumps > 2.0:
        # Stumps are behind the ball or far away; skip.
        return []

    out: list[tuple[float, float, float, float]] = []
    for i in range(1, n_steps + 1):
        s = i / n_steps
        tp = dt_to_stumps * s
        x = x_imp + fit.vx * tp
        y = y_imp + fit.vy * tp
        z = max(0.0, z_imp + vz_at_imp * tp - 0.5 * GRAVITY_MS2 * tp ** 2)
        out.append((float(impact_t_ms + tp * 1000.0), x, y, z))
    return out


def build_overlay_px(
    *,
    pose: CameraPose,
    fit: ProjectileFit,
    t0_ms: int,
    impact_t_rel_ms: float,
    predicted_path: list[tuple[float, float, float, float]],
    pitch_length_m: float,
    stump_height_m: float = DEFAULT_STUMP_HEIGHT_M,
    bounce: tuple[float, float, float, float] | None = None,  # (t_ms_abs, x, y, z)
    impact: tuple[float, float, float, float] | None = None,  # (t_ms_abs, x, y, z)
    corridor_half_m: float = 0.18,  # half-width of the stump-line channel on the ground
    n_steps: int = 48,
) -> dict:
    """Project the reconstructed trajectory into image pixels for the video overlay.

    The server owns the camera pose, so it draws the Hawk-Eye path in the
    analysed frame's pixel space here; the client then renders it directly over
    the source video without re-implementing the projection. The flight segment
    is sampled densely from the *fit* (so it is smooth and complete through the
    bounce even where individual frames were missed) and the predicted segment
    continues it to the stump plane.

    Returns pixel-space polylines and markers; every coordinate is in the same
    frame space as ``track.image_points`` and ``image_size``.
    """
    params = np.array([fit.x0, fit.y0, fit.z0, fit.vx, fit.vy, fit.vz], dtype=float)
    has_bounce = fit.bounce_t_ms is not None
    t_b = fit.bounce_t_ms / 1000.0 if has_bounce else None

    def proj(x: float, y: float, z: float) -> dict | None:
        p = _project_world(pose, x, y, z)
        if p is None:
            return None
        return {"u": round(float(p[0]), 2), "v": round(float(p[1]), 2)}

    path: list[dict] = []
    impact_s = max(0.0, float(impact_t_rel_ms) / 1000.0)
    steps = max(2, n_steps)
    if impact_s > 1e-3:
        for i in range(steps + 1):
            ts = impact_s * i / steps
            x, y, z = _projectile_at(params, ts, has_bounce=has_bounce, t_b=t_b)
            pt = proj(x, y, z)
            if pt is not None:
                path.append({"t_ms": int(t0_ms + ts * 1000.0), "phase": "flight", **pt})
    for (tp, x, y, z) in predicted_path:
        pt = proj(x, y, z)
        if pt is not None:
            path.append({"t_ms": int(t0_ms + tp), "phase": "predicted", **pt})

    def marker(ev: tuple[float, float, float, float] | None) -> dict | None:
        if ev is None:
            return None
        pt = proj(ev[1], ev[2], ev[3])
        return None if pt is None else {"t_ms": int(ev[0]), **pt}

    def stump_pair(x: float) -> dict | None:
        base = proj(x, 0.0, 0.0)
        top = proj(x, 0.0, stump_height_m)
        return None if (base is None or top is None) else {"base": base, "top": top}

    # Pitch corridor: the on-stumps channel on the ground, drawn from the
    # striker stumps up the pitch. A ground rectangle in perspective gives the
    # broadcast "tramline" band that shows the line of the delivery.
    corridor = [
        proj(0.0, -corridor_half_m, 0.0),
        proj(0.0, corridor_half_m, 0.0),
        proj(pitch_length_m, corridor_half_m, 0.0),
        proj(pitch_length_m, -corridor_half_m, 0.0),
    ]
    corridor_px = corridor if all(c is not None for c in corridor) else None

    return {
        "path_px": path,
        "bounce_px": marker(bounce),
        "impact_px": marker(impact),
        "stumps_px": {"striker": stump_pair(0.0), "bowler": stump_pair(pitch_length_m)},
        "corridor_px": corridor_px,
    }
