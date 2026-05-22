"""Full case-study analysis of test3.mp4 for the PocketDRS final report.

Pipeline reused (not re-implemented):
  - YoloBallDetector  -> per-frame cricket-ball candidates
  - find_ball_trajectory -> RANSAC constant-acceleration association (the same
    static-clutter suppression + parabolic fit the production server runs)

Then we render report figures:
  1. test3_path_overlay.png   full 2D ball path (release -> batsman) on one frame
  2. test3_ghost_trail.png    Hawk-Eye style multi-position ghost trail
  3. test3_montage.png        release / mid-flight / arrival frames, ball circled
  4. test3_pixel_track.png    u-v pixel trajectory, time-coloured, radius profile
  5. test3_3d_path.png        camera-relative 3D arc (depth-from-apparent-size)
  6. summary.json / analysis.md

Detection is cached to dets_all.json so reruns of the rendering are instant.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs")
sys.path.insert(0, str(ROOT / "server"))

from app.pipeline.reconstruction import estimate_intrinsics
from app.pipeline.tracking import YoloBallDetector
from app.pipeline.trajectory import find_ball_trajectory
from app.pipeline.video import VideoReader

VIDEO = ROOT / "test3.mp4"
WEIGHTS = ROOT / "server" / "models" / "cricket_ball.pt"
OUT = ROOT / "dump" / "validation" / "test3"
OUT.mkdir(parents=True, exist_ok=True)

BALL_RADIUS_M = 0.036  # regulation cricket ball, ~22.4 cm circumference


# --------------------------------------------------------------------------- #
# Stage A — per-frame detection (cached)
# --------------------------------------------------------------------------- #
def detect_all(meta) -> list[dict]:
    cache = OUT / "dets_all.json"
    if cache.exists():
        print(f"[A] loading cached detections {cache.name}")
        return json.loads(cache.read_text())

    print("[A] running YOLO over every frame ...")
    det = YoloBallDetector(str(WEIGHTS), conf=0.15, imgsz=1280)
    reader = VideoReader(str(VIDEO))
    fps = meta.fps if meta.fps > 0 else 60.0
    n = meta.frame_count if meta.frame_count > 0 else 290
    out = []
    for idx in range(n):
        t_ms = int(round(idx / fps * 1000.0))
        try:
            frame = reader.frame_at_ms(t_ms)
        except Exception as exc:
            print(f"    truncated at frame {idx}: {exc}")
            break
        dets = det.detect(frame)
        out.append({
            "frame": idx,
            "t_ms": t_ms,
            "dets": [
                {"x": round(d["x"], 2), "y": round(d["y"], 2),
                 "radius_px": round(d["radius_px"], 2),
                 "confidence": round(d["confidence"], 4)}
                for d in dets
            ],
        })
    reader.close()
    cache.write_text(json.dumps(out))
    print(f"[A] cached {len(out)} frames")
    return out


# --------------------------------------------------------------------------- #
# Stage B — trajectory association (RANSAC)
# --------------------------------------------------------------------------- #
def fit_trajectory(dets_all, meta, frame_lo=None, frame_hi=None):
    diag = math.hypot(meta.width if hasattr(meta, "width") else 1080,
                      meta.height if hasattr(meta, "height") else 1920)
    by_frame = []
    for rec in dets_all:
        if frame_lo is not None and rec["frame"] < frame_lo:
            continue
        if frame_hi is not None and rec["frame"] > frame_hi:
            continue
        by_frame.append((rec["t_ms"], rec["dets"]))
    fit = find_ball_trajectory(by_frame, image_diagonal_px=diag, min_inliers=6)
    return fit


def extend_to_release(pts, dets_all, *, back_frames=12, radius_px=45.0):
    """Prepend earlier detections that lie on the back-extrapolated arc.

    The RANSAC seed locks onto the densest contiguous run; the first few
    out-of-hand frames (lower confidence, partial occlusion by the bowler's
    arm) can fall outside that run. We fit u(t), v(t) to the recovered arc,
    extrapolate backwards, and accept any earlier candidate within radius_px
    of the predicted position — i.e. real detections that match the same
    physical flight, recovering the true point of release.
    """
    from app.pipeline.trajectory import TrajectoryPoint

    t0 = pts[0].t_ms
    t = np.array([p.t_ms for p in pts], dtype=float)
    u = np.array([p.x_px for p in pts], dtype=float)
    v = np.array([p.y_px for p in pts], dtype=float)
    cu = np.polyfit(t, u, 2)
    cv = np.polyfit(t, v, 2)

    first_frame = min(rec["frame"] for rec in dets_all if rec["t_ms"] == t0)
    by_idx = {rec["frame"]: rec for rec in dets_all}
    added = []
    for f in range(first_frame - 1, max(0, first_frame - 1 - back_frames), -1):
        rec = by_idx.get(f)
        if not rec or not rec["dets"]:
            continue
        tm = rec["t_ms"]
        pu, pv = np.polyval(cu, tm), np.polyval(cv, tm)
        best, bd = None, radius_px ** 2
        for d in rec["dets"]:
            dd = (d["x"] - pu) ** 2 + (d["y"] - pv) ** 2
            if dd < bd:
                bd, best = dd, d
        if best is not None:
            added.append(TrajectoryPoint(
                t_ms=tm, x_px=float(best["x"]), y_px=float(best["y"]),
                radius_px=float(best["radius_px"]), confidence=float(best["confidence"]),
            ))
    if added:
        added.sort(key=lambda p: p.t_ms)
        print(f"    extended release back {len(added)} frame(s): "
              f"now starts t={added[0].t_ms}ms (was {t0}ms)")
        return added + pts
    return pts


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #
def grab_frame(t_ms: int) -> np.ndarray:
    reader = VideoReader(str(VIDEO))
    f = reader.frame_at_ms(t_ms)
    reader.close()
    return f


def time_color(frac: float):
    """Green (release) -> yellow -> red (arrival). BGR."""
    frac = max(0.0, min(1.0, frac))
    if frac < 0.5:
        g = 220
        r = int(2 * frac * 220)
    else:
        g = int(220 * (1 - (frac - 0.5) * 2))
        r = 220
    return (40, g, r)


def render_path_overlay(pts, bg_t_ms):
    frame = grab_frame(bg_t_ms)
    out = frame.copy()
    n = len(pts)
    # connecting line
    for i in range(1, n):
        a = (int(pts[i - 1].x_px), int(pts[i - 1].y_px))
        b = (int(pts[i].x_px), int(pts[i].y_px))
        cv2.line(out, a, b, time_color(i / max(1, n - 1)), 3, cv2.LINE_AA)
    # markers
    for i, p in enumerate(pts):
        c = (int(p.x_px), int(p.y_px))
        cv2.circle(out, c, max(5, int(p.radius_px)), time_color(i / max(1, n - 1)), 2, cv2.LINE_AA)
        cv2.circle(out, c, 2, (255, 255, 255), -1)
    # release + arrival labels
    r0 = pts[0]; r1 = pts[-1]
    cv2.circle(out, (int(r0.x_px), int(r0.y_px)), 16, (60, 255, 60), 3)
    cv2.putText(out, "RELEASE", (int(r0.x_px) + 20, int(r0.y_px) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 255, 60), 2)
    cv2.circle(out, (int(r1.x_px), int(r1.y_px)), 16, (60, 60, 255), 3)
    cv2.putText(out, "ARRIVAL", (int(r1.x_px) + 20, int(r1.y_px) + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 60, 255), 2)
    # Clean caption banner at the bottom (avoids the clip's burned-in text).
    H = out.shape[0]
    band = out.copy()
    cv2.rectangle(band, (0, H - 110), (out.shape[1], H), (0, 0, 0), -1)
    out = cv2.addWeighted(band, 0.55, out, 0.45, 0)
    cv2.putText(out, "PocketDRS  -  tracked ball path (test3.mp4)", (24, H - 66),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
    flight = pts[-1].t_ms - pts[0].t_ms
    cv2.putText(out, f"{n} positions  |  60 fps  |  {flight} ms flight  |  YOLO + RANSAC",
                (24, H - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 255, 200), 2, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "test3_path_overlay.png"), out)
    print("  wrote test3_path_overlay.png")


def render_ghost_trail(pts):
    """Alpha-composite the ball patch from each frame onto one background."""
    bg = grab_frame(pts[len(pts) // 2].t_ms).copy()
    canvas = bg.astype(np.float32)
    for i, p in enumerate(pts):
        f = grab_frame(p.t_ms)
        u, v = int(p.x_px), int(p.y_px)
        r = max(8, int(p.radius_px) + 6)
        x0, x1 = max(0, u - r), min(f.shape[1], u + r)
        y0, y1 = max(0, v - r), min(f.shape[0], v + r)
        if x1 <= x0 or y1 <= y0:
            continue
        patch = f[y0:y1, x0:x1].astype(np.float32)
        alpha = 0.35 + 0.65 * (i / max(1, len(pts) - 1))  # fade older positions
        canvas[y0:y1, x0:x1] = (1 - alpha) * canvas[y0:y1, x0:x1] + alpha * patch
    out = canvas.astype(np.uint8)
    # overlay the fit line on top
    for i in range(1, len(pts)):
        a = (int(pts[i - 1].x_px), int(pts[i - 1].y_px))
        b = (int(pts[i].x_px), int(pts[i].y_px))
        cv2.line(out, a, b, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(out, "Ball trail (real frames composited)", (24, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "test3_ghost_trail.png"), out)
    print("  wrote test3_ghost_trail.png")


def render_montage(pts):
    idxs = [0, len(pts) // 2, len(pts) - 1]
    labels = ["RELEASE", "MID-FLIGHT", "ARRIVAL"]
    panels = []
    for j, k in enumerate(idxs):
        p = pts[k]
        f = grab_frame(p.t_ms).copy()
        u, v = int(p.x_px), int(p.y_px)
        cv2.circle(f, (u, v), max(18, int(p.radius_px) + 8), (0, 255, 255), 3)
        cv2.line(f, (u - 40, v), (u + 40, v), (0, 255, 255), 1)
        cv2.line(f, (u, v - 40), (u, v + 40), (0, 255, 255), 1)
        cv2.putText(f, labels[j], (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 255), 3)
        cv2.putText(f, f"t={p.t_ms}ms  r={p.radius_px:.0f}px", (24, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        panels.append(cv2.resize(f, (480, 853)))
    cv2.imwrite(str(OUT / "test3_montage.png"), cv2.hconcat(panels))
    print("  wrote test3_montage.png")


def render_pixel_track(pts):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    u = np.array([p.x_px for p in pts])
    v = np.array([p.y_px for p in pts])
    t = np.array([p.t_ms for p in pts]) - pts[0].t_ms
    r = np.array([p.radius_px for p in pts])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6))
    sc = ax1.scatter(u, v, c=t, cmap="viridis", s=60, zorder=3, edgecolor="k", linewidth=0.4)
    ax1.plot(u, v, "-", color="0.6", lw=1, zorder=1)
    ax1.invert_yaxis()
    ax1.set_xlabel("image u (px)")
    ax1.set_ylabel("image v (px)")
    ax1.set_title("Ball pixel trajectory (release → arrival)")
    ax1.set_xlim(0, 1080); ax1.set_ylim(1920, 0)
    ax1.set_aspect("equal", adjustable="box")
    cb = fig.colorbar(sc, ax=ax1); cb.set_label("time since release (ms)")

    ax2.plot(t, r, "o-", color="crimson")
    ax2.set_xlabel("time since release (ms)")
    ax2.set_ylabel("ball apparent radius (px)")
    ax2.set_title("Apparent size profile (depth cue)")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "test3_pixel_track.png", dpi=130)
    plt.close(fig)
    print("  wrote test3_pixel_track.png")


def reconstruct_3d(pts, meta):
    """Camera-relative metric arc via depth-from-apparent-size."""
    K = estimate_intrinsics(meta.width, meta.height, h_fov_deg=67.0)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    P = []  # (t_s, forward, lateral, height)
    for p in pts:
        if p.radius_px < 1:
            continue
        Z = fx * BALL_RADIUS_M / p.radius_px            # depth (forward)
        Xc = (p.x_px - cx) * Z / fx                       # right
        Yc = (p.y_px - cy) * Z / fy                       # down
        P.append((p.t_ms / 1000.0, Z, Xc, -Yc))          # forward, lateral, up
    P = np.array(P)
    return P, (fx, fy, cx, cy)


def render_3d(P):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D  # noqa

    t = P[:, 0] - P[0, 0]
    fwd, lat, up = P[:, 1], P[:, 2], P[:, 3]

    # least-squares kinematic fit (quadratic in t) per axis -> smooth arc
    def qfit(y):
        c = np.polyfit(t, y, 2)
        ts = np.linspace(t.min(), t.max(), 120)
        return ts, np.polyval(c, ts), c
    ts, fwd_s, _ = qfit(fwd)
    _, lat_s, _ = qfit(lat)
    _, up_s, cz = qfit(up)

    fig = plt.figure(figsize=(13, 9))
    ax = fig.add_subplot(111, projection="3d")
    # ground plane
    gx = np.linspace(fwd.min() - 0.2, fwd.max() + 0.2, 2)
    gy = np.linspace(lat.min() - 0.3, lat.max() + 0.3, 2)
    GX, GY = np.meshgrid(gx, gy)
    ax.plot_surface(GX, GY, np.zeros_like(GX), alpha=0.10, color="green")
    # vertical drop lines (point -> ground) for depth perception
    for i in range(0, len(fwd), 2):
        ax.plot([fwd[i], fwd[i]], [lat[i], lat[i]], [up[i], 0],
                color="0.7", lw=0.6, alpha=0.6)
    # ground shadow of arc
    ax.plot(fwd_s, lat_s, np.zeros_like(fwd_s), "--", color="0.5", lw=1.2,
            label="ground shadow")
    # the smooth fitted arc
    ax.plot(fwd_s, lat_s, up_s, "-", color="orange", lw=3, label="fitted arc")
    # raw 3D points
    sc = ax.scatter(fwd, lat, up, c=t, cmap="viridis", s=55, depthshade=True,
                    edgecolor="k", linewidth=0.3)
    # camera + endpoints
    ax.scatter([0], [0], [0], marker="^", s=160, color="red")
    ax.text(0, 0, 0.06, "camera", color="red", fontsize=10)
    ax.scatter([fwd[0]], [lat[0]], [up[0]], s=130, color="lime",
               edgecolor="k", label="release", zorder=5)
    ax.scatter([fwd[-1]], [lat[-1]], [up[-1]], s=130, color="red",
               edgecolor="k", label="arrival", zorder=5)

    ax.set_xlabel("forward / depth from camera (m)")
    ax.set_ylabel("lateral (m)")
    ax.set_zlabel("height above optical axis (m)")
    ax.set_title("PocketDRS 3D ball path  (camera-relative, depth-from-apparent-size)\n"
                 f"release depth {fwd[0]:.2f} m  ->  arrival depth {fwd[-1]:.2f} m   "
                 f"|  monocular scale (single camera)", fontsize=11)
    ax.view_init(elev=16, azim=-62)
    fig.colorbar(sc, ax=ax, shrink=0.5, pad=0.02, label="time since release (s)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "test3_3d_path.png", dpi=130)
    # second view (top-down)
    ax.view_init(elev=82, azim=-90)
    ax.set_title("PocketDRS 3D ball path — top-down (depth vs lateral)", fontsize=11)
    fig.savefig(OUT / "test3_3d_path_topdown.png", dpi=130)
    plt.close(fig)
    print("  wrote test3_3d_path.png + test3_3d_path_topdown.png")


def main() -> int:
    reader = VideoReader(str(VIDEO))
    meta = reader.meta
    reader.close()
    # attach dims
    class M:
        fps = meta.fps; frame_count = meta.frame_count
        duration_ms = meta.duration_ms; width = 1080; height = 1920
    meta = M()

    dets_all = detect_all(meta)

    # Primary delivery window discovered from the raw track (frames ~31-65).
    fit = fit_trajectory(dets_all, meta, frame_lo=28, frame_hi=70)
    if fit is None:
        print("no trajectory in primary window; retrying whole clip")
        fit = fit_trajectory(dets_all, meta)
    if fit is None:
        print("FAILED: no ball trajectory found")
        return 1

    pts = sorted(fit.points, key=lambda p: p.t_ms)
    pts = extend_to_release(pts, dets_all)
    print(f"\n[B] trajectory: {fit.inliers} inliers / {fit.candidates_total} candidates, "
          f"rms={fit.rms_px:.2f}px")
    print(f"    release frame t={pts[0].t_ms}ms -> arrival t={pts[-1].t_ms}ms "
          f"({pts[-1].t_ms - pts[0].t_ms}ms flight)")
    span_u = max(p.x_px for p in pts) - min(p.x_px for p in pts)
    span_v = max(p.y_px for p in pts) - min(p.y_px for p in pts)
    print(f"    pixel span: {span_u:.0f} x {span_v:.0f} px")

    print("\n[C] rendering 2D figures ...")
    render_path_overlay(pts, bg_t_ms=pts[len(pts) // 2].t_ms)
    render_ghost_trail(pts)
    render_montage(pts)
    render_pixel_track(pts)

    print("\n[D] reconstruct + render 3D ...")
    P, intr = reconstruct_3d(pts, meta)
    render_3d(P)

    # ---- summary -------------------------------------------------------- #
    flight_ms = pts[-1].t_ms - pts[0].t_ms
    depth0 = float(P[0, 1]); depth1 = float(P[-1, 1])
    # 3D path length / flight time -> caveated average speed
    seg = np.diff(P[:, 1:4], axis=0)
    path_len_m = float(np.sum(np.linalg.norm(seg, axis=1)))
    flight_s = max(1e-3, (P[-1, 0] - P[0, 0]))
    speed_ms = path_len_m / flight_s
    speed_kmh = speed_ms * 3.6
    summary = {
        "video": "test3.mp4",
        "meta": {"fps": meta.fps, "frames": meta.frame_count,
                 "duration_ms": meta.duration_ms, "resolution": "1080x1920"},
        "detector": "YoloBallDetector (cricket_ball.pt)",
        "trajectory": {
            "inliers": fit.inliers,
            "candidates_total": fit.candidates_total,
            "rms_px": round(fit.rms_px, 2),
            "release_t_ms": pts[0].t_ms,
            "arrival_t_ms": pts[-1].t_ms,
            "flight_ms": flight_ms,
            "n_points": len(pts),
            "pixel_span_uv": [round(span_u), round(span_v)],
            "px_per_ms_x": round(fit.px_per_ms_x, 4),
            "px_per_ms_y": round(fit.px_per_ms_y, 4),
        },
        "depth_from_size": {
            "ball_radius_m": BALL_RADIUS_M,
            "intrinsics_fx_fy_cx_cy": [round(v, 1) for v in intr],
            "depth_release_m": round(depth0, 3),
            "depth_arrival_m": round(depth1, 3),
            "path_length_m": round(path_len_m, 3),
            "avg_speed_ms": round(speed_ms, 2),
            "avg_speed_kmh": round(speed_kmh, 1),
            "note": ("Monocular depth from apparent ball size; absolute metric "
                     "scale is single-camera-ambiguous and reflects this short "
                     "indoor coaching net. Arc SHAPE and 2D track are reliable; "
                     "speed is an order-of-magnitude estimate, not a calibrated "
                     "measurement."),
        },
        "points_px": [{"t_ms": p.t_ms, "u": round(p.x_px, 1), "v": round(p.y_px, 1),
                       "radius_px": round(p.radius_px, 1), "conf": round(p.confidence, 3)}
                      for p in pts],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote summary.json ({len(pts)} points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
