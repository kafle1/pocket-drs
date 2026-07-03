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
    # Measured post-bounce horizontal velocity (m/s).  A real delivery changes
    # both direction (seam / spin) and speed (friction) off the pitch, so the
    # post-bounce arc is fitted independently and its lateral/longitudinal
    # velocity stored here.  ``None`` means "no independent post-bounce
    # evidence" — evaluators then carry the pre-bounce horizontal velocity
    # through the bounce (the old behaviour).  ``vz_post`` likewise overrides
    # the restitution-derived rebound speed when measured directly.
    vx_post: float | None = None
    vy_post: float | None = None
    vz_post: float | None = None


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

    `h_fov_deg` is the sensor's wide-direction field of view (typical phone
    main cameras are 60–75°). The sensor's wide direction always maps to the
    image's *long* axis: in landscape that is the image width, in portrait it
    is the image height. Using the long axis here keeps fx consistent across
    orientations and removes a ~1.8× depth-scale bias that the previous
    width-based formula introduced for portrait clips.

    Errors here translate ~linearly into depth bias, which is correctable
    later by re-projecting the calibration marks; large bias surfaces as a
    high reprojection error rather than corrupting the geometry silently.
    """
    if not (1.0 < float(h_fov_deg) < 179.0):
        raise CalibrationError(
            f"h_fov_deg must be in (1, 179) degrees, got {h_fov_deg}"
        )
    long_axis_px = float(max(image_width, image_height))
    fx = (long_axis_px / 2.0) / math.tan(math.radians(h_fov_deg) / 2.0)
    fy = fx  # square pixels assumption (true for all modern phones)
    cx = image_width / 2.0
    cy = image_height / 2.0
    K = np.array([
        [fx, 0.0, cx],
        [0.0, fy, cy],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    return K



STUMP_LATERAL_DX_M = 0.114    # half-distance from middle stump to leg/off stump
STUMP_HALF_WIDTH_M = 0.018    # half-thickness of a stump
STUMP_OUTER_HALF_M = STUMP_LATERAL_DX_M + STUMP_HALF_WIDTH_M  # ≈0.132 m


def solve_camera_pose_from_stumps(
    *,
    image_size: tuple[int, int],                                 # (width, height)
    stump_quads_px: list[tuple[float, float]],                   # 8: striker_TL..BL, bowler_TL..BL
    pitch_corners_px: list[tuple[float, float]] | None = None,   # 4: SL, SR, BR, BL
    pitch_width_m: float = 3.05,
    stump_height_m: float = DEFAULT_STUMP_HEIGHT_M,
    h_fov_deg: float | None = None,
    known_length_m: float | None = None,
    length_min_m: float = 2.0,
    length_max_m: float = 26.0,
) -> tuple[CameraPose, float]:
    """Recover the camera pose AND the pitch length from the marked points.

    Inputs:
      * ``stump_quads_px`` — 8 image points, the bounding rectangle of each
        end's three-stump cluster in tap order TL, TR, BR, BL: striker first,
        bowler second. Two stumps' worth of corners over a known 0.711 m
        height + ≈0.264 m width pins the metric scale.
      * ``pitch_corners_px`` (optional but strongly recommended) — 4 turf
        corners (striker-L, striker-R, bowler-R, bowler-L). They sit off
        the stump plane so they break the (FOV × length) degeneracy that
        stumps alone would have.

    Auto-fits camera FOV (28°–86°) and pitch length unless the caller pins
    either. When the corners disagree with the stumps under any tried FOV
    the corner fit is dropped and the stumps-only result is returned.
    """
    if cv2 is None:
        raise CalibrationError("OpenCV required for camera pose")
    if len(stump_quads_px) != 8:
        raise CalibrationError("Need exactly 8 stump quad points (4 per side)")
    if pitch_corners_px is not None and len(pitch_corners_px) != 4:
        raise CalibrationError("Need exactly 4 pitch corners (or none)")

    width, height = image_size
    dist = np.zeros((4, 1), dtype=np.float64)

    stump_img = np.array(stump_quads_px, dtype=np.float64)
    # Per-side object template applied at X=0 (striker) and X=L (bowler).
    # OUTER half-width includes the stump radius so the rectangle hugs the
    # real outer edge the user tapped.
    OUTER = STUMP_OUTER_HALF_M
    side_template = [
        (-OUTER, stump_height_m),  # TL
        (+OUTER, stump_height_m),  # TR
        (+OUTER, 0.0),             # BR
        (-OUTER, 0.0),             # BL
    ]
    corner_img = (
        np.array(pitch_corners_px, dtype=np.float64)
        if pitch_corners_px is not None else None
    )
    half_w = float(pitch_width_m) / 2.0

    def _solve_at(K: np.ndarray, length: float, use_corners: bool) -> tuple | None:
        L = float(length)
        striker_obj = [(0.0, dy, dz) for (dy, dz) in side_template]
        bowler_obj = [(L, dy, dz) for (dy, dz) in side_template]
        stump_obj = np.array(striker_obj + bowler_obj, dtype=np.float64)
        if use_corners and corner_img is not None:
            # Pitch corners: striker-left, striker-right, bowler-right, bowler-left.
            # Y sign matches the calibration UI's tap convention.
            corner_obj = np.array(
                [(0.0, -half_w, 0.0), (0.0,  half_w, 0.0),
                 (L,    half_w, 0.0), (L,   -half_w, 0.0)],
                dtype=np.float64,
            )
            obj = np.concatenate([stump_obj, corner_obj], axis=0)
            img = np.concatenate([stump_img, corner_img], axis=0)
        else:
            obj = stump_obj
            img = stump_img
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_SQPNP)
        if not ok:
            return None
        R, _ = cv2.Rodrigues(rvec)
        R_inv = R.T
        cam = -R_inv @ tvec.reshape(3, 1)
        if float(cam[2, 0]) <= 0.0:
            return None
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
        proj = proj.reshape(-1, 2)
        reproj = float(np.sqrt(np.mean(np.sum((proj - img) ** 2, axis=1))))
        if not math.isfinite(reproj):
            return None
        return (reproj, L, rvec, tvec, R, R_inv, cam, K)

    fov_candidates: list[float]
    if h_fov_deg is not None:
        fov_candidates = [float(h_fov_deg)]
    else:
        # Covers phone telephoto (~28°) through ultra-wide (~86°) at ~6°
        # steps. Reprojection error is smooth in FOV at this scale, so 10
        # samples land us within 2-3° of the true focal length — fine
        # enough for downstream PnP and bundle adjustment.
        fov_candidates = [28.0, 34.0, 40.0, 46.0, 52.0, 58.0, 64.0, 70.0, 78.0, 86.0]

    length_locked = (
        known_length_m is not None
        and length_min_m <= float(known_length_m) <= length_max_m
    )
    if length_locked:
        length_candidates = [float(known_length_m)]
    else:
        # 0.05 m steps give length to about half a stump width — finer than
        # the reprojection minimum is meaningful at this noise level.
        n_steps = max(2, int(round((length_max_m - length_min_m) / 0.05)) + 1)
        length_candidates = [float(v) for v in np.linspace(length_min_m, length_max_m, n_steps)]

    def _sweep(use_corners: bool) -> tuple | None:
        best_local = None
        best_fov_local = None
        for fov in fov_candidates:
            K_local = estimate_intrinsics(width, height, h_fov_deg=fov)
            for length in length_candidates:
                cand = _solve_at(K_local, length, use_corners=use_corners)
                if cand is None:
                    continue
                if best_local is None or cand[0] < best_local[0]:
                    best_local = cand
                    best_fov_local = fov
        return (best_local, best_fov_local) if best_local is not None else None

    # Primary: fuse stumps + pitch corners — the corners sit off the stump
    # plane, so they break the (FOV × length) degeneracy stumps-only has.
    primary = _sweep(use_corners=corner_img is not None) if corner_img is not None else None

    # Fallback: stumps-only. Used both as a consistency check for the primary
    # solve and as the answer when the corner taps disagree with the stump
    # geometry (which means the corner taps are off — the stumps anchor the
    # metric scale via their known height, so we trust them).
    stumps_only = _sweep(use_corners=False)

    used_corners = False
    if primary is not None and stumps_only is not None:
        prim_best, prim_fov = primary
        so_best, so_fov = stumps_only
        # Tolerance scales with frame width — at 1080p, 6 px is the noise
        # floor of a precise tap. The corners disambiguate only if they
        # don't blow the joint reprojection wide open relative to the
        # stumps-only fit at the same (or any) FOV.
        joint_acceptable_px = max(6.0, 0.012 * width)
        if prim_best[0] <= max(joint_acceptable_px, so_best[0] * 2.0 + 3.0):
            best = prim_best
            best_fov = prim_fov
            used_corners = True
        else:
            best = so_best
            best_fov = so_fov
    elif primary is not None:
        best, best_fov = primary
        used_corners = True
    elif stumps_only is not None:
        best, best_fov = stumps_only
    else:
        best, best_fov = None, None

    if best is None:
        raise CalibrationError(
            "Stump calibration is degenerate — re-mark the stump bases and tops."
        )

    reproj, length, rvec, tvec, R, R_inv, cam, K = best
    source = "user-supplied" if length_locked else "geometry-fit"
    notes = [
        "stump-anchored pose" if not used_corners else "stump+corner pose",
        f"length={length:.2f} m ({source})",
        f"reproj={reproj:.2f} px",
        f"fov={best_fov:.0f} deg ({'user-supplied' if h_fov_deg is not None else 'auto-fit'})",
        f"cam_height={float(cam[2, 0]):.2f} m",
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
    ray = _backproject_ray(pose, u, v)  # unit ray, camera frame, optical axis = +z
    # `depth` is the optical-axis (camera-Z) distance from depth-from-size, not a
    # Euclidean range. Scale the ray so its z-component equals `depth`; using the
    # unit ray directly places off-axis balls too close by sqrt(1 + x^2 + y^2)
    # (0 at frame centre, ~15-20% at the edge). ray[2] = 1/||[x, y, 1]|| lies in
    # (0, 1] for any real pixel, so the divide is safe (== 1 at image centre).
    point_cam = (ray / ray[2]) * depth
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
        # Trust the independently-fitted post-bounce HORIZONTAL velocity only
        # when that arc is well-determined: enough points and a residual no
        # worse than the pre-bounce arc, with a physical cricket speed range.
        # When it qualifies we keep the *measured* post-bounce direction and
        # speed — that is the seam/spin deviation and the friction slow-down off
        # the pitch that a real DRS must reproduce and the restitution model
        # cannot.  The VERTICAL rebound stays restitution-derived: it is well
        # modelled, and replacing it with the raw post-fit vz adds depth-noise
        # without adding information (verified to worsen height accuracy).  A
        # short or noisy post arc leaves the fields None, so the evaluator
        # carries the pre-bounce velocity through (the old behaviour) rather
        # than inventing a sideways kick.
        post_trust = (
            len(post) >= 4
            and math.isfinite(post_fit.vx)
            and math.isfinite(post_fit.vy)
            and post_rms <= max(2.5, 1.5 * pre_rms)
            and 3.0 <= abs(post_fit.vx) <= 50.0
            and abs(post_fit.vy) <= 8.0
        )
        best_rms_px = combined_rms
        notes = [
            "bounce-aware linear solve (Ribnick 2009)",
            f"t_b={t_b_s*1000:.0f}ms pre_rms={pre_rms:.2f}px post_rms={post_rms:.2f}px",
        ]
        if post_trust:
            notes.append(
                f"measured post-bounce horiz v=({post_fit.vx:.1f},{post_fit.vy:.2f}) m/s"
            )
        best = ProjectileFit(
            x0=pre_fit.x0, y0=pre_fit.y0, z0=pre_fit.z0,
            vx=pre_fit.vx, vy=pre_fit.vy, vz=vz_pre,
            bounce_t_ms=float(t_b_s * 1000.0),
            rms_m=0.0,
            notes=notes,
            vx_post=post_fit.vx if post_trust else None,
            vy_post=post_fit.vy if post_trust else None,
            vz_post=None,  # vertical rebound stays restitution-derived
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


def _bounce_eval(
    fit: ProjectileFit,
) -> tuple[float, float, float, float, float, float] | None:
    """Single source of truth for a fit's bounce geometry.

    Returns ``(t_b_s, xb, yb, vx_post, vy_post, vz_post)`` or ``None`` when the
    fit has no bounce.  The bounce time is the solver's ``bounce_t_ms`` — the
    point where the pre/post arcs were split — and z is taken to be 0 there by
    construction (the ball is on the ground at the pitch contact).  Anchoring on
    that single time and feeding it to the flight overlay, the forward
    prediction AND the smoothing pass is what removes the old kink: those three
    previously evaluated the bounce with two different conventions.  (The
    production reconstruction is the gravity-constrained *linear* solver, whose
    stored ``vz`` is back-derived to satisfy restitution at this exact time, so
    re-deriving a "physical" ground-touch time from it is both circular and
    numerically unstable — measured.)  Horizontal post-bounce velocity is the
    measured value when the bounce-aware solver recovered it, else the
    pre-bounce velocity carried through; vertical rebound is restitution-derived
    from the pre-bounce descent (or the measured value when explicitly stored).
    """
    if fit.bounce_t_ms is None:
        return None
    t_b = max(fit.bounce_t_ms / 1000.0, 0.0)
    xb = fit.x0 + fit.vx * t_b
    yb = fit.y0 + fit.vy * t_b
    vx_post = fit.vx_post if fit.vx_post is not None else fit.vx
    vy_post = fit.vy_post if fit.vy_post is not None else fit.vy
    if fit.vz_post is not None:
        vz_post = fit.vz_post
    else:
        vz_post = -COEFFICIENT_OF_RESTITUTION_Z * (fit.vz - GRAVITY_MS2 * t_b)
    return (t_b, xb, yb, vx_post, vy_post, vz_post)


def _eval_fit_at(fit: ProjectileFit, t_s: float) -> tuple[float, float, float]:
    """Evaluate the bounce-aware projectile position at time ``t_s``.

    The one evaluator shared by the flight overlay, the forward prediction and
    the smoothing pass, so all three render the identical physical trajectory
    (including any measured post-bounce deviation).
    """
    be = _bounce_eval(fit)
    if be is not None and t_s >= be[0]:
        t_g, xb, yb, vxp, vyp, vzp = be
        tp = t_s - t_g
        x = xb + vxp * tp
        y = yb + vyp * tp
        z = max(0.0, vzp * tp - 0.5 * GRAVITY_MS2 * tp * tp)
        return x, y, z
    x = fit.x0 + fit.vx * t_s
    y = fit.y0 + fit.vy * t_s
    z = max(0.0, fit.z0 + fit.vz * t_s - 0.5 * GRAVITY_MS2 * t_s * t_s)
    return x, y, z


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
                    vx_post=bl_fit.vx_post,
                    vy_post=bl_fit.vy_post,
                    vz_post=bl_fit.vz_post,
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
    # re-anchor the trajectory. The image v-peak (largest pixel y) is the
    # only event that flips the ball's vertical image motion downward →
    # upward, so it pin-points the pitch-contact frame even when the
    # bounce-aware linear solver has too few post-bounce points to fit (a
    # bounce in the last ~10% of the tracked arc, common on short clips).
    # We override the fit only when it does not already commit to a bounce.
    needs_bounce_anchor = (
        detections and len(detections) >= 8
        and (fit is None or fit.bounce_t_ms is None)
    )
    if needs_bounce_anchor:
        sorted_dets = sorted(detections, key=lambda d: d[0])
        vs = np.array([d[2] for d in sorted_dets], dtype=float)
        ts = np.array([d[0] for d in sorted_dets], dtype=float)
        # Bounce frame = the strict local maximum of v (image y grows
        # downward, so peak v is the closest the ball gets to the pitch).
        # Operate on raw v, not a smoothed copy: a 3-tap smoothing flattens
        # the peak and tends to push neighbour values within a pixel of the
        # peak, defeating a strict ">" comparison. We require the very next
        # frame to lift off again so an isolated detection drop-out does not
        # masquerade as a bounce, and keep the latest qualifying peak so a
        # bounce that lands near the end of the tracked arc is preferred
        # over an earlier ambiguous dip.
        bounce_local_idx: int | None = None
        v_jitter_px = 2.0
        for i in range(1, len(vs) - 1):
            if vs[i] > vs[i - 1] + v_jitter_px and vs[i] > vs[i + 1] + v_jitter_px:
                bounce_local_idx = i
        if bounce_local_idx is not None:
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
                # Release-height anchor: back-project the first detection at
                # an assumed release height. 1.8 m is the typical bowling-
                # arm release for slow / medium / spin deliveries; using the
                # earlier 2.0 m guess placed the release world-point a metre
                # in FRONT of the bowler crease for short indoor-net clips,
                # which collapsed the geometric vx to ~6 m/s and produced
                # the under-reported 22 km/h "ball speed".
                u0, v0 = float(sorted_dets[0][1]), float(sorted_dets[0][2])
                rel = backproject_to_ground(pose, u0, v0, z_target=1.8)
                new_y0 = float(anchor[1]) - fit.vy * t_b_s
                new_vx = fit.vx
                new_vy = fit.vy
                # Accept the geometric vx if it lies in a plausible cricket
                # range. The lower bound was 10 m/s, which rejected spin /
                # net-bowling speeds (28-35 km/h) and silently left vx at
                # the linear solver's miscalibrated guess. 5 m/s ≈ 18 km/h
                # is the floor for any deliberate delivery.
                if rel is not None and t_b_s > 0.05:
                    cand_vx = (float(anchor[0]) - float(rel[0])) / t_b_s
                    cand_vy = (float(anchor[1]) - float(rel[1])) / t_b_s
                    if 5.0 < abs(cand_vx) < 50.0:
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
            # Same shared evaluator the overlay and prediction use, so the
            # smoothed world points lie on the identical bounce-aware arc.
            x_s, y_s, z_s = _eval_fit_at(fit, ts)
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
    n_steps: int = 24,
) -> list[tuple[float, float, float, float]]:
    """Forward-extrapolate the projectile from impact to the stump plane.

    Uses the shared bounce-aware evaluator (:func:`_eval_fit_at`) so the
    predicted segment continues the flight overlay seamlessly: pre-bounce
    dynamics when the impact falls before the pitch point, otherwise the
    measured (or restitution-derived) post-bounce branch — which is what
    carries any real seam/spin deviation off the pitch into the forecast.
    Returns ``(t_ms_rel_to_fit_origin, x, y, z)`` tuples — the overlay
    builder's contract.
    """
    impact_s = impact_t_ms / 1000.0
    x_imp, y_imp, z_imp = _eval_fit_at(fit, impact_s)

    # Horizontal velocity that governs the continuation, and the vertical speed
    # at impact: post-bounce values when the impact is past the pitch point,
    # pre-bounce otherwise.  Pulling both from the same _bounce_eval the
    # evaluator used guarantees the forecast leaves the impact point along the
    # exact tangent of the drawn flight arc (no kink at the hand-off).
    be = _bounce_eval(fit)
    if be is not None and impact_s >= be[0]:
        t_g, _xb, _yb, vx_eff, vy_eff, vz_post = be
        vz_at_imp = vz_post - GRAVITY_MS2 * (impact_s - t_g)
    else:
        vx_eff, vy_eff = fit.vx, fit.vy
        vz_at_imp = fit.vz - GRAVITY_MS2 * impact_s

    if abs(vx_eff) < 1e-3:
        return []
    dt_to_stumps = (target_x_m - x_imp) / vx_eff
    # Cap the horizon: a multi-second dt means a near-degenerate horizontal
    # speed, not a real delivery.  Clamp instead of dropping the path so a
    # genuinely slow ball still gets a forecast.
    if dt_to_stumps > 3.0:
        dt_to_stumps = 3.0
    # If the ball has already crossed the stump plane at impact (DRS late
    # interception cases), show a short forward continuation so the user
    # still sees the predicted direction past the bat.
    if dt_to_stumps < 0:
        dt_to_stumps = 0.2

    out: list[tuple[float, float, float, float]] = []
    for i in range(1, n_steps + 1):
        s = i / n_steps
        tp = dt_to_stumps * s
        x = x_imp + vx_eff * tp
        y = y_imp + vy_eff * tp
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
    pitch_width_m: float = 3.05,
    stump_height_m: float = DEFAULT_STUMP_HEIGHT_M,
    bounce: tuple[float, float, float, float] | None = None,  # (t_ms_abs, x, y, z)
    impact: tuple[float, float, float, float] | None = None,  # (t_ms_abs, x, y, z)
    corridor_half_m: float = 0.18,  # half-width of the stump-line channel on the ground
    n_steps: int = 48,
    image_points: list[dict] | None = None,
) -> dict:
    """Project the reconstructed trajectory into image pixels for the video overlay.

    The server owns the camera pose, so it draws the Hawk-Eye path in the
    analysed frame's pixel space here; the client then renders it directly over
    the source video without re-implementing the projection.

    The flight segment (release -> impact) is drawn through the *observed* ball
    positions (``image_points``) whenever they are available: those pixels sit
    on the real ball, so the drawn line follows it exactly regardless of how
    tight the monocular 3-D lift came out. Only when no detections are supplied
    do we fall back to reprojecting the 3-D fit (which drifts off the ball on a
    loose, near-end-on reconstruction). The predicted segment always continues
    from the 3-D forward integration to the stump plane.

    Returns pixel-space polylines and markers; every coordinate is in the same
    frame space as ``track.image_points`` and ``image_size``.
    """
    def proj(x: float, y: float, z: float) -> dict | None:
        p = _project_world(pose, x, y, z)
        if p is None:
            return None
        return {"u": round(float(p[0]), 2), "v": round(float(p[1]), 2)}

    path: list[dict] = []
    impact_s = max(0.0, float(impact_t_rel_ms) / 1000.0)
    steps = max(2, n_steps)
    obs = sorted(image_points or [], key=lambda p: p.get("t_ms", 0))
    if obs:
        # Trace the measured ball through the flight. Detections already run to
        # the interception (they carry the extension past the RANSAC arc), so
        # this is the true release->impact curve on the ball.
        clean: list[tuple[int, float, float]] = []
        for p in obs:
            try:
                clean.append((int(p["t_ms"]), float(p["u"]), float(p["v"])))
            except (KeyError, TypeError, ValueError):
                continue
        # A dim or near-end-on clip yields the odd detection that jumps to
        # background clutter for a single frame. A 3-point median on (u,v)
        # removes those single-sample spikes while leaving an already-smooth
        # arc unchanged and preserving the endpoints (release and impact).
        n = len(clean)
        for i, (t, u, v) in enumerate(clean):
            if 0 < i < n - 1:
                u = sorted((clean[i - 1][1], u, clean[i + 1][1]))[1]
                v = sorted((clean[i - 1][2], v, clean[i + 1][2]))[1]
            path.append({"t_ms": t, "phase": "flight",
                         "u": round(u, 2), "v": round(v, 2)})
    elif impact_s > 1e-3:
        for i in range(steps + 1):
            ts = impact_s * i / steps
            x, y, z = _eval_fit_at(fit, ts)
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

    # Full pitch surface polygon — the visible playing strip from striker to
    # bowler ends at the full pitch width. Distinct from the LBW corridor so
    # clients can render the broadcast pitch outline as well as the corridor.
    half_w = float(pitch_width_m) / 2.0
    pitch_rect = [
        proj(0.0, -half_w, 0.0),
        proj(0.0,  half_w, 0.0),
        proj(pitch_length_m,  half_w, 0.0),
        proj(pitch_length_m, -half_w, 0.0),
    ]
    pitch_rect_px = pitch_rect if all(p is not None for p in pitch_rect) else None

    # Stump-to-stump centerline on the ground (the bowling axis), drawn so
    # clients can show the "wickets-to-wickets" line at a glance even when
    # the trajectory is short or the corridor band is hard to see.
    centerline_segments = max(8, int(round(pitch_length_m)) * 2)
    centerline: list[dict] = []
    for i in range(centerline_segments + 1):
        x_m = pitch_length_m * i / centerline_segments
        p = proj(x_m, 0.0, 0.0)
        if p is not None:
            centerline.append(p)
    centerline_px = centerline if len(centerline) >= 2 else None

    return {
        "path_px": path,
        "bounce_px": marker(bounce),
        "impact_px": marker(impact),
        "stumps_px": {"striker": stump_pair(0.0), "bowler": stump_pair(pitch_length_m)},
        "corridor_px": corridor_px,
        "pitch_rect_px": pitch_rect_px,
        "centerline_px": centerline_px,
    }
