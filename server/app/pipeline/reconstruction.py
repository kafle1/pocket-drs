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
    if radius_px < 0.5:
        raise ValueError("Detection radius too small for depth estimation")
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

    `params` = [x0, y0, z0, vx, vy, vz].  When has_bounce is True and t_s >= t_b,
    we reflect Vz at the bounce time with the given restitution.
    """
    x0, y0, z0, vx, vy, vz = params
    if has_bounce and t_b is not None and t_s >= t_b:
        vz_at_b = vz - GRAVITY_MS2 * t_b
        vz_post = -restitution * vz_at_b
        tp = t_s - t_b
        x = (x0 + vx * t_b) + vx * tp
        y = (y0 + vy * t_b) + vy * tp
        z = max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp * tp)
    else:
        x = x0 + vx * t_s
        y = y0 + vy * t_s
        z = max(0.0, z0 + vz * t_s - 0.5 * GRAVITY_MS2 * t_s * t_s)
    return x, y, z


def _bundle_adjust_trajectory(
    *,
    pose: CameraPose,
    detections: list[tuple[int, float, float, float, float]],
    seed: ProjectileFit,
    radius_weight: float = 8.0,
) -> ProjectileFit | None:
    """Refine the 6 trajectory parameters by minimising pixel + radius residuals.

    Pixel residuals dominate (3 pixel units = 1 unit weight); radius residual
    has its own weight because radius noise is multiplicative and only
    informative at close depths.

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
        return np.asarray(out, dtype=float)

    x0_arr = np.array([seed.x0, seed.y0, seed.z0, seed.vx, seed.vy, seed.vz], dtype=float)

    try:
        sol = least_squares(
            residuals, x0_arr,
            method="lm",
            max_nfev=200,
            xtol=1e-8, ftol=1e-8,
        )
    except Exception:
        return None

    p = sol.x
    rms_pixels = float(np.sqrt(np.mean(sol.fun ** 2)))
    notes = list(seed.notes) + [f"bundle-adj rms_resid={rms_pixels:.3f}", f"nfev={sol.nfev}"]

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
) -> ProjectileFit:
    """Grid-search bounce time and bundle-adjust each candidate; return best."""
    if not detections:
        return seed_no_bounce
    t0_ms = detections[0][0]
    duration_s = (detections[-1][0] - t0_ms) / 1000.0
    if duration_s < 0.20 or len(detections) < 6:
        return _bundle_adjust_trajectory(pose=pose, detections=detections, seed=seed_no_bounce) or seed_no_bounce

    best = _bundle_adjust_trajectory(pose=pose, detections=detections, seed=seed_no_bounce) or seed_no_bounce

    for t_b_s in np.linspace(0.20 * duration_s, 0.80 * duration_s, 12):
        seeded = ProjectileFit(
            x0=seed_no_bounce.x0, y0=seed_no_bounce.y0, z0=seed_no_bounce.z0,
            vx=seed_no_bounce.vx, vy=seed_no_bounce.vy, vz=seed_no_bounce.vz,
            bounce_t_ms=float(t_b_s * 1000.0),
            rms_m=seed_no_bounce.rms_m,
            notes=list(seed_no_bounce.notes),
        )
        candidate = _bundle_adjust_trajectory(pose=pose, detections=detections, seed=seeded)
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

    fit_seed = fit_projectile(raw, pitch_length_m=pitch_length_m)

    # Bundle-adjust against the original pixel observations.  This dramatically
    # reduces sensitivity to depth-from-size noise: pixel positions are accurate
    # to ~1-2 px regardless of distance, while raw depth estimates are noisy at
    # the far end where the ball is small.
    fit: ProjectileFit | None = None
    if fit_seed is not None and len(detections) >= 6:
        fit = _search_bounce_then_bundle(
            pose=pose,
            detections=[d for d in detections if d[3] >= 0.5],
            seed_no_bounce=fit_seed,
        )
    else:
        fit = fit_seed

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
