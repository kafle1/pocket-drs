"""One-shot synthetic validation of the PocketDRS pipeline.

Renders a realistic umpire-POV cricket scene with a known projectile, then
runs run_pipeline on it and compares recovered events against ground truth.

Throwaway script. Deleted after use.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.process_job import run_pipeline


# ---------------------------------------------------------------------------
# Scene config
# ---------------------------------------------------------------------------
W, H = 1080, 1920          # portrait phone frame
FX = FY = 900.0            # known synthetic intrinsics
CX, CY = W / 2.0, H / 2.0
H_FOV_DEG = 2.0 * math.degrees(math.atan((W / 2.0) / FX))  # back-derived

PITCH_LEN = 20.12
PITCH_WID = 3.05
HALF_W = PITCH_WID / 2.0

# Camera placed behind the striker, 1.8 m up, 3.5 m back from the crease,
# tilted slightly down to frame the pitch.
CAM_WORLD = np.array([-3.5, 0.0, 1.8])
LOOK_AT = np.array([10.0, 0.0, 0.0])  # mid-pitch ground point

FPS = 60
DUR_S = 2.4
N_FRAMES = int(FPS * DUR_S)

# Ball: from bowler end towards striker, bounces once.
BALL_RADIUS_M = 0.036
BALL_P0 = np.array([18.0, 0.05, 1.8])
BALL_V0 = np.array([-8.5, -0.02, -1.0])
G = 9.81
RESTITUTION = 0.55


def look_at_R(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    """World->camera rotation in OpenCV convention (+X right, +Y down, +Z forward).

    OpenCV's camera frame is *left-handed* when expressed in a right-handed
    world frame: cross(camera_X_in_world, camera_Y_in_world) = -camera_Z_in_world.
    To produce a valid SE(3) transform we negate the camera-Y row so the
    composite rotation has det=+1 and Rodrigues round-trips correctly.
    """
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    world_up = np.array([0.0, 0.0, 1.0])
    right = np.cross(world_up, forward)
    right = right / np.linalg.norm(right)
    # OpenCV's right-handed camera frame (+X right, +Y down, +Z forward)
    # requires cross(right, down_in_world) = forward, giving det(R) = +1.
    down = np.cross(forward, right)
    R = np.stack([right, down, forward], axis=0)
    return R


_K_SYNTH = np.array([[FX, 0.0, CX], [0.0, FY, CY], [0.0, 0.0, 1.0]], dtype=np.float64)
_DIST_SYNTH = np.zeros((4, 1), dtype=np.float64)


def world_to_pixel(R: np.ndarray, t: np.ndarray, X: np.ndarray) -> tuple[float, float, float]:
    """Project a world point via OpenCV. Returns (u, v, depth)."""
    rvec, _ = cv2.Rodrigues(R)
    proj, _ = cv2.projectPoints(X.reshape(1, 1, 3), rvec, t.reshape(3, 1), _K_SYNTH, _DIST_SYNTH)
    Xc = (R @ X.reshape(3) + t.reshape(3))
    return float(proj[0, 0, 0]), float(proj[0, 0, 1]), float(Xc[2])


def simulate_ball() -> list[tuple[float, np.ndarray]]:
    """Return [(t_s, world_xyz)] with bounce reflection at z=R."""
    dt = 1.0 / FPS
    states: list[tuple[float, np.ndarray]] = []
    p = BALL_P0.copy()
    v = BALL_V0.copy()
    t = 0.0
    for _ in range(N_FRAMES):
        states.append((t, p.copy()))
        # Symplectic Euler-ish integration with bounce check.
        v_next = v + np.array([0.0, 0.0, -G]) * dt
        p_next = p + v_next * dt
        if p_next[2] <= BALL_RADIUS_M and v_next[2] < 0:
            # Reflect at z = ball radius.
            v_next[2] = -RESTITUTION * v_next[2]
            p_next[2] = BALL_RADIUS_M + (BALL_RADIUS_M - p_next[2])
        p, v = p_next, v_next
        t += dt
    return states


def render_scene(out_path: Path) -> tuple[list[tuple[float, float]], list[tuple[float, np.ndarray]]]:
    """Render the synthetic video. Returns (pitch_corners_px, ball_states).

    OpenCV's right-handed camera frame with image-Y down combined with our
    right-handed world (Z up) yields a visually inverted image relative to a
    real handheld phone shot. We do NOT visually flip it: that would break
    the projection-to-PnP round-trip. The tracking ROI mask is orientation-
    adaptive so it still works on this configuration.
    """
    R = look_at_R(CAM_WORLD, LOOK_AT)
    t = (-R @ CAM_WORLD).reshape(3)

    # Pitch corners in CALIB UI ORDER: striker-left, striker-right, bowler-right, bowler-left.
    corners_world = [
        np.array([0.0,         -HALF_W, 0.0]),
        np.array([0.0,          HALF_W, 0.0]),
        np.array([PITCH_LEN,    HALF_W, 0.0]),
        np.array([PITCH_LEN,   -HALF_W, 0.0]),
    ]
    corners_px = [world_to_pixel(R, t, c)[:2] for c in corners_world]

    states = simulate_ball()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, FPS, (W, H))
    if not writer.isOpened():
        raise RuntimeError("cv2.VideoWriter failed to open")

    for _, p in states:
        frame = np.full((H, W, 3), (60, 110, 70), dtype=np.uint8)  # grass BGR

        # Pitch trapezoid filled (dirt colour).
        pts = np.array([world_to_pixel(R, t, c)[:2] for c in corners_world], dtype=np.int32)
        cv2.fillPoly(frame, [pts], (70, 110, 160))  # dirt-ish BGR

        # Crease lines.
        for x_m in (1.22, PITCH_LEN - 1.22):
            a = np.array([world_to_pixel(R, t, np.array([x_m, -HALF_W, 0.0]))[:2]], dtype=np.float32)
            b = np.array([world_to_pixel(R, t, np.array([x_m,  HALF_W, 0.0]))[:2]], dtype=np.float32)
            cv2.line(frame, tuple(np.int32(a[0])), tuple(np.int32(b[0])), (240, 240, 240), 2)

        # Ball: red, scaled by depth.
        u, v, depth = world_to_pixel(R, t, p)
        if math.isfinite(u) and depth > 0:
            r_px = max(2.0, FX * BALL_RADIUS_M / depth)
            cv2.circle(frame, (int(u), int(v)), int(round(r_px)), (40, 40, 220), -1, lineType=cv2.LINE_AA)
            # Subtle highlight for realism.
            cv2.circle(frame, (int(u - r_px * 0.3), int(v - r_px * 0.3)), max(1, int(r_px * 0.3)), (80, 90, 240), -1, lineType=cv2.LINE_AA)

        writer.write(frame)
    writer.release()
    return corners_px, states


def find_ground_truth_events(states: list[tuple[float, np.ndarray]]) -> tuple[tuple[float, np.ndarray], tuple[float, np.ndarray] | None]:
    """Find ground-truth bounce (first z-min after release) and impact (first crossing of x=0)."""
    bounce_idx = -1
    for i in range(1, len(states) - 1):
        z_prev = states[i - 1][1][2]
        z_now = states[i][1][2]
        z_next = states[i + 1][1][2]
        if z_now <= z_prev and z_now <= z_next and z_now <= 1.0 * BALL_RADIUS_M + 0.02:
            bounce_idx = i
            break
    bounce = states[bounce_idx] if bounce_idx >= 0 else states[len(states) // 2]

    impact = None
    for s in states:
        if s[1][0] <= 0.0:
            impact = s
            break
    return bounce, impact


def main() -> int:
    art = Path(tempfile.mkdtemp(prefix="synth_"))
    video_path = art / "synth.mp4"
    corners_px, states = render_scene(video_path)
    bounce_gt, impact_gt = find_ground_truth_events(states)

    req = {
        "segment": {"start_ms": 0, "end_ms": int(1000 * (N_FRAMES - 1) / FPS)},
        "calibration": {
            "mode": "taps",
            "pitch_corners_px": [{"x": u, "y": v} for (u, v) in corners_px],
            "pitch_dimensions_m": {"length": PITCH_LEN, "width": PITCH_WID},
            "h_fov_deg": H_FOV_DEG,
        },
        "tracking": {"sample_fps": FPS, "max_frames": N_FRAMES, "ball_color": "red"},
    }

    print(f"-- input  ----------------------------------")
    print(f"video       : {video_path}")
    print(f"frames      : {N_FRAMES}  ({DUR_S:.2f}s @ {FPS}fps)")
    print(f"h_fov_deg   : {H_FOV_DEG:.2f}")
    print(f"cam world   : {CAM_WORLD.tolist()}")
    print(f"corners px  : {[(round(u,1), round(v,1)) for (u,v) in corners_px]}")
    print(f"bounce gt   : t={bounce_gt[0]*1000:.0f}ms xyz={bounce_gt[1].round(3).tolist()}")
    if impact_gt is not None:
        print(f"impact gt   : t={impact_gt[0]*1000:.0f}ms xyz={impact_gt[1].round(3).tolist()}")

    out = run_pipeline(video_path=video_path, request_json=req, artifacts_dir=art, progress=None)
    r = out.result

    print()
    print(f"-- pipeline output ------------------------")
    cal = r["calibration"]
    print(f"reproj px   : {cal['quality']['reproj_error_px']:.2f}")
    print(f"cam center  : {[round(c, 3) for c in cal['pose']['cam_center_world_m']]}")
    print(f"track       : candidates={r['track']['candidates_total']} inliers={r['track']['inliers']} rms_px={r['track']['rms_px']:.2f}")
    wt = r.get("world_trajectory")
    if wt is None:
        print("world_trajectory: NONE — pipeline could not fit a 3D trajectory")
        ev = None
    else:
        print(f"world pts   : {len(wt['points_m'])}")
        ev = r.get("events")
        if ev:
            b = ev.get("bounce") or {}
            i = ev.get("impact") or {}
            print(f"bounce reco : t={b.get('t_ms')}ms xyz=({b.get('x_m')}, {b.get('y_m')}, ?)")
            print(f"impact reco : t={i.get('t_ms')}ms xyz=({i.get('x_m')}, {i.get('y_m')}, {i.get('z_m')})")
        lbw = r.get("lbw")
        if lbw:
            print(f"lbw         : {lbw.get('decision')} — {lbw.get('reason')}")

    # Comparison
    print()
    print(f"-- accuracy --------------------------------")
    bgt = bounce_gt[1]
    if ev and ev.get("bounce") and ev["bounce"].get("x_m") is not None:
        b = ev["bounce"]
        err = math.hypot(b["x_m"] - bgt[0], b["y_m"] - bgt[1])
        print(f"bounce xy err : {err*100:.1f} cm  (target < 50 cm)")
    else:
        print("bounce xy err : N/A — no recovered bounce")

    if impact_gt is not None and ev and ev.get("impact") and ev["impact"].get("x_m") is not None:
        i = ev["impact"]
        igt = impact_gt[1]
        err = math.hypot(i["x_m"] - igt[0], i["y_m"] - igt[1])
        if i.get("z_m") is not None:
            err = math.sqrt((i["x_m"] - igt[0]) ** 2 + (i["y_m"] - igt[1]) ** 2 + (i["z_m"] - igt[2]) ** 2)
        print(f"impact 3d err : {err*100:.1f} cm  (target < 50 cm)")
    else:
        print("impact 3d err : N/A — no recovered impact")

    # Save artifacts for the report.
    out_dir = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result_debug.json").write_text(json.dumps(r, indent=2, default=str))
    # Save first frame.
    cap = cv2.VideoCapture(str(video_path))
    ok, f0 = cap.read()
    if ok:
        cv2.imwrite(str(out_dir / "frame0.jpg"), f0)
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
