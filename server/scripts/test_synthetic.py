"""Synthetic-trajectory verification of the 3D reconstruction math.

We bypass detection entirely.  Instead:
1. Pick a known camera pose (estimated from test.mp4 hardcoded calibration).
2. Define a known ball trajectory in world coords (release from bowler end at
   2.0m height, lands ~5m before striker, continues toward stumps).
3. Project the trajectory through the camera to image coords + apparent radius.
4. Add Gaussian pixel noise + radius noise.
5. Run reconstruct_trajectory() and compare recovered world trajectory
   against the ground truth.

If RMS world error < 0.20 m, the reconstruction math is good.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.reconstruction import (  # noqa: E402
    BALL_RADIUS_M,
    GRAVITY_MS2,
    detection_to_world,
    estimate_intrinsics,
    fit_projectile,
    reconstruct_trajectory,
    solve_camera_pose,
)


# Match debug_pipeline.py
TEST_MP4_CORNERS_PX = [
    (240.0, 625.0),    # striker-left
    (350.0, 625.0),    # striker-right
    (445.0, 1290.0),   # bowler-right
    (130.0, 1290.0),   # bowler-left
]
TEST_MP4_BOWLER_STUMP_BASE_PX = (270.0, 870.0)
TEST_MP4_STRIKER_STUMP_BASE_PX = (290.0, 625.0)

PITCH_LENGTH_M = 20.12
PITCH_WIDTH_M = 3.05


def project_world_to_image(pose, x_m, y_m, z_m):
    """Pinhole projection of a 3D world point through the camera."""
    p_world = np.array([[x_m], [y_m], [z_m]], dtype=np.float64)
    p_cam = pose.R @ p_world + pose.tvec.reshape(3, 1)
    if p_cam[2, 0] <= 0.001:
        return None, None
    u = pose.fx * (p_cam[0, 0] / p_cam[2, 0]) + pose.cx
    v = pose.fy * (p_cam[1, 0] / p_cam[2, 0]) + pose.cy
    # Apparent ball radius in pixels at this depth.
    depth = float(p_cam[2, 0])
    r_px = pose.fx * BALL_RADIUS_M / depth
    return (float(u), float(v), float(r_px)), depth


def make_synthetic_pose(image_w=1080, image_h=1920):
    """Construct a known umpire-POV pose, bypassing PnP.

    Camera at (21, 0, 1.7) — ~1 m behind bowler crease at human height.
    Looking down the pitch toward (0, 0, 0.5).
    """
    from app.pipeline.reconstruction import CameraPose, estimate_intrinsics

    K = estimate_intrinsics(image_w, image_h)
    cam_pos_world = np.array([21.0, 0.0, 1.7], dtype=np.float64)
    look_at = np.array([0.0, 0.0, 0.5], dtype=np.float64)
    forward = look_at - cam_pos_world
    forward /= np.linalg.norm(forward)
    world_up = np.array([0.0, 0.0, 1.0])
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right)
    cam_up = np.cross(right, forward)
    # OpenCV camera frame: X right, Y down, Z forward
    cam_x = right
    cam_y = -cam_up
    cam_z = forward
    R_world_from_cam = np.column_stack([cam_x, cam_y, cam_z])
    R = R_world_from_cam.T  # world->camera
    tvec = (-R @ cam_pos_world.reshape(3, 1))
    rvec, _ = cv2.Rodrigues(R)
    return CameraPose(
        K=K, rvec=rvec, tvec=tvec, R=R, R_inv=R.T,
        cam_center_world=cam_pos_world.reshape(3, 1),
        fx=float(K[0, 0]), fy=float(K[1, 1]),
        cx=float(K[0, 2]), cy=float(K[1, 2]),
        reproj_error_px=0.0,
        notes=["synthetic ground-truth pose"],
    )


def main() -> int:
    pose = make_synthetic_pose()
    print(f"Synthetic pose: cam at {pose.cam_center_world.flatten()}")

    # Ground-truth trajectory: bowled from bowler end (X=20.12) at release
    # height 2.0m, slight off-stump line.  Bounces at X=4m.
    rng = np.random.default_rng(42)

    # Pre-bounce projectile.
    X0, Y0, Z0 = 19.5, 0.10, 2.05
    Vx, Vy, Vz = -25.0, -0.10, 1.0  # m/s, ball moving toward striker (decreasing X)
    t_bounce_s = 0.55  # ball reaches the ground at this time (single segment fit)

    def true_pos(t_s):
        if t_s <= t_bounce_s:
            x = X0 + Vx * t_s
            y = Y0 + Vy * t_s
            z = max(0.0, Z0 + Vz * t_s - 0.5 * GRAVITY_MS2 * t_s ** 2)
            return x, y, z
        # Post-bounce: vz reflected with restitution 0.55
        vz_at_b = Vz - GRAVITY_MS2 * t_bounce_s
        vz_post = -0.55 * vz_at_b
        tp = t_s - t_bounce_s
        x_b = X0 + Vx * t_bounce_s
        y_b = Y0 + Vy * t_bounce_s
        x = x_b + Vx * tp
        y = y_b + Vy * tp
        z = max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp ** 2)
        return x, y, z

    detections: list[tuple[int, float, float, float, float]] = []
    truth_world: list[tuple[float, float, float, float]] = []

    sample_dt_ms = 33  # 30 fps
    for i in range(30):  # 30 frames covering ~1.0 s of flight
        t_ms = i * sample_dt_ms
        t_s = t_ms / 1000.0
        x, y, z = true_pos(t_s)
        if x < 0.5 or x > PITCH_LENGTH_M + 1.0:
            continue  # ball already past stumps or pre-release
        truth_world.append((t_ms, x, y, z))
        proj, depth = project_world_to_image(pose, x, y, z)
        if proj is None:
            continue
        u, v, r = proj
        # Add realistic noise.
        u += rng.normal(0, 1.5)
        v += rng.normal(0, 1.5)
        r += rng.normal(0, 0.4)  # radius noise ~10% at small sizes
        if r < 0.5:
            continue
        detections.append((t_ms, u, v, r, 0.85))

    print(f"\nGenerated {len(detections)} synthetic detections from {len(truth_world)} true points")

    # --- Reconstruct ---
    recon = reconstruct_trajectory(
        pose=pose, detections=detections,
        pitch_length_m=PITCH_LENGTH_M, pitch_width_m=PITCH_WIDTH_M,
    )
    if recon.fit is None:
        print("ERROR: projectile fit failed")
        return 1

    fit = recon.fit
    print(f"\nProjectile fit:")
    print(f"  X0={fit.x0:.2f}  Y0={fit.y0:.2f}  Z0={fit.z0:.2f}  (truth {X0:.2f},{Y0:.2f},{Z0:.2f})")
    print(f"  Vx={fit.vx:.2f}  Vy={fit.vy:.2f}  Vz={fit.vz:.2f}  (truth {Vx:.2f},{Vy:.2f},{Vz:.2f})")
    print(f"  bounce_t_ms={fit.bounce_t_ms}  (truth {t_bounce_s*1000:.0f})")
    print(f"  rms_m={fit.rms_m:.3f}")
    print(f"  notes={fit.notes}")

    # --- LBW-relevant accuracy metrics ---
    # Recovered Y/Z at the striker stump line (X=0).
    fit = recon.fit
    t_at_stump = fit.x0 / abs(fit.vx)
    y_at_stump_rec = fit.y0 + fit.vy * t_at_stump
    # Z at stump uses post-bounce kinematics if applicable.
    if fit.bounce_t_ms is not None and t_at_stump > fit.bounce_t_ms / 1000.0:
        t_b = fit.bounce_t_ms / 1000.0
        vz_at_b = fit.vz - GRAVITY_MS2 * t_b
        vz_post = -0.55 * vz_at_b
        tp = t_at_stump - t_b
        z_at_stump_rec = max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp * tp)
    else:
        z_at_stump_rec = max(0.0, fit.z0 + fit.vz * t_at_stump - 0.5 * GRAVITY_MS2 * t_at_stump ** 2)

    # Truth at X=0.
    t_truth_at_stump = X0 / abs(Vx)
    y_at_stump_true = Y0 + Vy * t_truth_at_stump
    if t_truth_at_stump > t_bounce_s:
        vz_at_b = Vz - GRAVITY_MS2 * t_bounce_s
        vz_post = -0.55 * vz_at_b
        tp = t_truth_at_stump - t_bounce_s
        z_at_stump_true = max(0.0, vz_post * tp - 0.5 * GRAVITY_MS2 * tp * tp)
    else:
        z_at_stump_true = max(0.0, Z0 + Vz * t_truth_at_stump - 0.5 * GRAVITY_MS2 * t_truth_at_stump ** 2)

    # Bounce location.
    if fit.bounce_t_ms is not None:
        tb = fit.bounce_t_ms / 1000.0
        bounce_x_rec = fit.x0 + fit.vx * tb
        bounce_y_rec = fit.y0 + fit.vy * tb
    else:
        bounce_x_rec = bounce_y_rec = float("nan")
    bounce_x_true = X0 + Vx * t_bounce_s
    bounce_y_true = Y0 + Vy * t_bounce_s

    print(f"\n--- LBW-relevant accuracy ---")
    print(f"  bounce X: rec={bounce_x_rec:.3f}m  truth={bounce_x_true:.3f}m  err={abs(bounce_x_rec-bounce_x_true)*1000:.0f}mm")
    print(f"  bounce Y: rec={bounce_y_rec:.3f}m  truth={bounce_y_true:.3f}m  err={abs(bounce_y_rec-bounce_y_true)*1000:.0f}mm")
    print(f"  stumps Y: rec={y_at_stump_rec:.4f}m truth={y_at_stump_true:.4f}m err={abs(y_at_stump_rec-y_at_stump_true)*1000:.0f}mm")
    print(f"  stumps Z: rec={z_at_stump_rec:.3f}m  truth={z_at_stump_true:.3f}m  err={abs(z_at_stump_rec-z_at_stump_true)*1000:.0f}mm")

    # Targets: bounce X <300mm, bounce Y <50mm, stumps Y <50mm, stumps Z <100mm.
    bx_err = abs(bounce_x_rec - bounce_x_true) * 1000
    by_err = abs(bounce_y_rec - bounce_y_true) * 1000
    sy_err = abs(y_at_stump_rec - y_at_stump_true) * 1000
    sz_err = abs(z_at_stump_rec - z_at_stump_true) * 1000

    failures = []
    if bx_err > 300: failures.append(f"bounce X {bx_err:.0f}mm > 300mm")
    if by_err > 50:  failures.append(f"bounce Y {by_err:.0f}mm > 50mm")
    if sy_err > 50:  failures.append(f"stumps Y {sy_err:.0f}mm > 50mm")
    if sz_err > 100: failures.append(f"stumps Z {sz_err:.0f}mm > 100mm")

    if not failures:
        print(f"\n PASS (all LBW-relevant errors within target)")
        return 0
    print(f"\n FAIL: {', '.join(failures)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
