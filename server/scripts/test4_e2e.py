"""End-to-end production-pipeline test for test4.mp4 (indoor net, wide angle).

Mirror of test3_e2e.py with calibration retuned for test4 — a different
indoor-net delivery shot from the umpire-bowler end with the bowler in the
foreground (big yellow stumps near, batsman + striker stumps far). Same
production pipeline, same rendering primitives.

Run:    server/.venv/bin/python server/scripts/test4_e2e.py
Out:    dump/validation/test4/{result.json, test4_tracked.mp4, test4_sample.png}
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs")
sys.path.insert(0, str(ROOT / "server"))

from app.pipeline.process_job import run_pipeline  # noqa: E402

VIDEO = ROOT / "test4.mp4"
WEIGHTS = ROOT / "server" / "models" / "cricket_ball.pt"
OUT = ROOT / "dump" / "validation" / "test4"
OUT.mkdir(parents=True, exist_ok=True)

# Recovered test4 calibration taps (normalised over 1080x1920 frame).
# Camera sits at the bowler's end with the bowler in the foreground; the
# bowler's own stumps are the big yellow set near the bottom of the frame
# (image y ~1187–1568), and the striker's stumps are the small far set
# next to the batsman (image y ~928–1046). Measured off the first frame
# via yellow-mask connected components, not eyeballed.
STRIKER_QUAD = [           # small far stumps (image y ~928–1046)
    (0.509, 0.483),  # TL
    (0.552, 0.483),  # TR
    (0.552, 0.545),  # BR
    (0.509, 0.545),  # BL
]
BOWLER_QUAD = [            # big near stumps (image y ~1187–1568)
    (0.452, 0.618),  # TL
    (0.574, 0.618),  # TR
    (0.574, 0.817),  # BR
    (0.452, 0.817),  # BL
]
CORNERS_NORM = [           # striker-left, striker-right, bowler-right, bowler-left
    (0.398, 0.532), (0.591, 0.532), (0.833, 0.982), (0.160, 0.982),
]


def build_request() -> dict:
    """Same request shape as the production analyze flow."""
    return {
        "segment": {"start_ms": 0, "end_ms": 600000},
        "video": {"rotation_deg": 0},
        "tracking": {
            "sample_fps": 60,
            "max_frames": 180,
            "ball_color": "red",
            "detector": "auto",
            "yolo_weights": str(WEIGHTS),
        },
        "calibration": {
            "mode": "taps",
            # The joint auto-solver lands on 28° (telephoto) here, which
            # gives low reprojection error but collapses depth-from-ball-
            # radius downstream and the 3D fit rejects with "trajectory fit
            # error > 1 m". Pin the long-axis FOV to the phone's actual
            # main lens (~70° vertical for ~67° horizontal at 9:16) so the
            # depth recovery matches the camera that recorded the clip.
            "h_fov_deg": 45.0,
            "pitch_dimensions_m": {"width": 3.05},
            "pitch_corners_norm": [{"x": x, "y": y} for x, y in CORNERS_NORM],
            "stump_quads_norm": [
                {"x": x, "y": y} for x, y in STRIKER_QUAD + BOWLER_QUAD
            ],
        },
    }


# --------------------------------------------------------------------------- #
# Rendering — reuses the test3_e2e overlay primitives.
# --------------------------------------------------------------------------- #
RED = (60, 60, 235)
GOLD = (60, 200, 245)
BLUE = (235, 170, 60)
WHITE = (255, 255, 255)


def _dashed(img, a, b, color, thick=3, dash=18, gap=12):
    a = np.array(a, float); b = np.array(b, float)
    length = float(np.hypot(*(b - a)))
    if length < 1: return
    step = dash + gap
    n = int(length // step) + 1
    d = (b - a) / length
    for i in range(n):
        s = a + d * (i * step)
        e = a + d * min(i * step + dash, length)
        cv2.line(img, tuple(s.astype(int)), tuple(e.astype(int)), color, thick, cv2.LINE_AA)


def _card(img, x, y, w, h, title, value):
    sub = img[y:y + h, x:x + w].copy()
    cv2.rectangle(sub, (0, 0), (w, h), (28, 28, 28), -1)
    img[y:y + h, x:x + w] = cv2.addWeighted(sub, 0.78, img[y:y + h, x:x + w], 0.22, 0)
    cv2.rectangle(img, (x, y), (x + w, y + h), (90, 90, 90), 1, cv2.LINE_AA)
    cv2.putText(img, title, (x + 12, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.putText(img, value, (x + 12, y + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, WHITE, 2, cv2.LINE_AA)


def render_three_d_viewer(result: dict) -> None:
    from app.three_d_viewer import render_html
    (OUT / "test4_3d.html").write_text(render_html(result))
    print("  wrote test4_3d.html")


def render_3d(result: dict) -> None:
    """3D Hawk-Eye plot — same look as test3, retitled for test4."""
    world_pts = result.get("world_trajectory") or {}
    pts = world_pts.get("points_m") or []
    pred = world_pts.get("predicted_to_stumps_m") or []
    events = result.get("events") or {}
    bounce = events.get("bounce") or {}
    impact = events.get("impact") or {}
    metrics = result.get("metrics") or {}
    lbw = result.get("lbw") or {}

    L = max([p["x"] for p in pts] + [6.3])
    W = 3.05
    half_w = W / 2.0
    H_STUMP = 0.711
    STUMP_DX = 0.114

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    fig = plt.figure(figsize=(12, 8), facecolor="#0d1117")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#0d1117")

    pitch_quad = [(0, -half_w, 0), (0, half_w, 0), (L, half_w, 0), (L, -half_w, 0)]
    ax.add_collection3d(Poly3DCollection([pitch_quad], facecolor="#1f4a2c", alpha=0.95, edgecolor="#4f9b66"))

    corr_half = STUMP_DX + 0.036
    corr_quad = [(0, -corr_half, 0.002), (0, corr_half, 0.002), (L, corr_half, 0.002), (L, -corr_half, 0.002)]
    ax.add_collection3d(Poly3DCollection([corr_quad], facecolor="#f5c14b", alpha=0.45, edgecolor="#ffd166"))

    POPPING = 1.22
    for cx in (POPPING, L - POPPING):
        ax.plot([cx, cx], [-half_w, half_w], [0.003, 0.003], color="#ffd166", linewidth=1.5, alpha=0.7)
    ax.plot([0, L], [0, 0], [0.003, 0.003], color="#f0e6b2", linewidth=1.0, alpha=0.35, linestyle=":")

    BAIL_Z = H_STUMP + 0.012
    for x_end, col, lw, alpha in ((0.0, "#ffd166", 4.5, 1.0), (L, "#cdd3dc", 2.8, 0.55)):
        for dy in (-STUMP_DX, 0.0, STUMP_DX):
            ax.plot([x_end, x_end], [dy, dy], [0, H_STUMP], color=col, linewidth=lw, alpha=alpha, solid_capstyle="round", zorder=7)
        ax.plot([x_end, x_end], [-STUMP_DX, 0.0], [BAIL_Z, BAIL_Z], color=col, linewidth=max(1.5, lw - 1.8), alpha=alpha, zorder=7)
        ax.plot([x_end, x_end], [0.0, STUMP_DX], [BAIL_Z, BAIL_Z], color=col, linewidth=max(1.5, lw - 1.8), alpha=alpha, zorder=7)

    if pts:
        xs_t = [p["x"] for p in pts]; ys_t = [p["y"] for p in pts]; zs_t = [max(0.01, p["z"]) for p in pts]
        ax.plot(xs_t, ys_t, [0.004] * len(xs_t), color="#9aa0a6", linewidth=1.2, linestyle=":", alpha=0.6, zorder=5)
        for xs_i, ys_i, zs_i in zip(xs_t[::2], ys_t[::2], zs_t[::2]):
            ax.plot([xs_i, xs_i], [ys_i, ys_i], [0.004, zs_i], color="#9aa0a6", linewidth=0.7, alpha=0.35, zorder=5)
        ax.plot(xs_t, ys_t, zs_t, color="#ff4a4a", linewidth=4.0, label="tracked", zorder=8)
        ts_t = np.linspace(0.0, 1.0, len(xs_t))
        ax.scatter(xs_t, ys_t, zs_t, c=ts_t, cmap="plasma", s=22, edgecolor="#0d1117", linewidth=0.4, depthshade=False, zorder=8)

    if pred:
        pxs = [p["x"] for p in pred]; pys = [p["y"] for p in pred]; pzs = [max(0.015, p["z"]) for p in pred]
        if impact.get("x_m") is not None:
            pxs = [impact["x_m"]] + pxs; pys = [impact["y_m"]] + pys
            pzs = [max(0.015, impact.get("z_m", 0.0))] + pzs
        ax.plot(pxs, pys, pzs, color="#ffd700", linewidth=4.0, linestyle="--", dashes=(4, 2), label="predicted", zorder=9)
        ax.plot(pxs, pys, [0.004] * len(pxs), color="#ffd700", linewidth=1.0, linestyle=":", alpha=0.45, zorder=5)

    if bounce.get("x_m") is not None:
        bx, by = float(bounce["x_m"]), float(bounce["y_m"])
        ax.scatter([bx], [by], [0.005], marker="o", s=150, color="#22d3ee", edgecolor="#0d1117", linewidth=1.4, label="pitching", depthshade=False, zorder=11)
        ax.plot([bx, bx], [by, by], [0.005, 0.35], color="#22d3ee", linewidth=1.2, alpha=0.55, zorder=11)

    if impact.get("x_m") is not None:
        ax.scatter([impact["x_m"]], [impact["y_m"]], [impact["z_m"]], marker="X", s=140, color="#fbbf24", edgecolor="#0d1117", linewidth=1.4, label="impact", depthshade=False, zorder=11)

    ax.view_init(elev=18, azim=-58)
    ax.set_xlim(-0.3, L + 0.3); ax.set_ylim(-half_w - 0.2, half_w + 0.2)
    ax.set_zlim(0, max(2.0, max((p["z"] for p in pts), default=1.0) + 0.4))
    try:
        ax.set_box_aspect((L + 0.6, W + 0.4, 1.6))
    except AttributeError:
        pass
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_facecolor("#0d1117"); axis.pane.set_edgecolor("#1f2933"); axis.line.set_color("#1f2933")
    ax.tick_params(colors="#5b6473", labelsize=8)
    ax.set_xlabel("x  along pitch (m)", color="#9aa0a6", fontsize=9, labelpad=2)
    ax.set_ylabel("y  across (m)",      color="#9aa0a6", fontsize=9, labelpad=2)
    ax.set_zlabel("z  height (m)",       color="#9aa0a6", fontsize=9, labelpad=2)
    ax.grid(False)

    dec = (lbw.get("decision") or "?").upper().replace("_", " ")
    verdict_col = {"OUT": "#ef4444", "UMPIRES CALL": "#fbbf24", "NOT OUT": "#22c55e"}.get(dec, "#dde3eb")
    pred_y = (lbw.get("prediction") or {}).get("y_at_stumps_m")
    pred_z = (lbw.get("prediction") or {}).get("z_at_stumps_m")
    chip = [dec]
    if pred_y is not None and pred_z is not None:
        chip.append(f"y={pred_y*100:+.0f}cm  z={pred_z*100:.0f}cm")
    fig.text(0.04, 0.96, "\n".join(chip), color=verdict_col, fontsize=18, fontweight="bold", va="top",
             bbox=dict(facecolor="#161b22", edgecolor=verdict_col, boxstyle="round,pad=0.5"))
    fig.text(0.96, 0.96, f"{metrics.get('speed_kmh', 0):.0f} km/h", color="#dde3eb", fontsize=11, ha="right", va="top")
    ax.legend(loc="lower left", facecolor="#161b22", edgecolor="#30363d", labelcolor="#dde3eb", framealpha=0.9, fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT / "test4_3d.png", dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("  wrote test4_3d.png")


def _anchored_prediction_px(raw_pts, overlay_predicted):
    if not overlay_predicted or not raw_pts: return []
    last = raw_pts[-1]; first = overlay_predicted[0]
    du = float(last["u"]) - float(first["u"]); dv = float(last["v"]) - float(first["v"])
    return [(int(round(float(p["u"]) + du)), int(round(float(p["v"]) + dv))) for p in overlay_predicted]


def _impact_cutoff_ms(result: dict) -> int | None:
    """Time (ms) at which the ball loses its projectile identity — i.e. it
    contacts the batsman, bat, pad or stumps and direction-changes. After
    this point the detector may still latch on to the deflected ball, but
    those samples belong to a new trajectory; the Hawk-Eye overlay should
    stop drawing the *measured* arc here and let the dashed prediction
    carry the line on to the stumps instead.
    """
    impact = ((result.get("events") or {}).get("impact") or {})
    t = impact.get("t_ms")
    return int(t) if t is not None else None


def render(result: dict) -> None:
    ov = result.get("overlay") or {}
    path = ov.get("path_px") or []
    if not path:
        raise SystemExit("no overlay path to render")
    metrics = result.get("metrics") or {}; lbw = result.get("lbw") or {}
    pitch_rect = ov.get("pitch_rect_px") or []
    corridor = ov.get("corridor_px") or []
    stumps = ov.get("stumps_px") or {}

    raw_pts_all = sorted(result.get("track", {}).get("image_points") or [], key=lambda p: p["t_ms"])
    impact_t = _impact_cutoff_ms(result)
    raw_pts = [p for p in raw_pts_all if impact_t is None or p["t_ms"] <= impact_t]
    flight = [(p["u"], p["v"]) for p in raw_pts]
    flight_t = [p["t_ms"] for p in raw_pts]
    overlay_predicted = [pp for pp in path if pp.get("phase") == "predicted"]
    predicted = _anchored_prediction_px(raw_pts, overlay_predicted)

    cap = cv2.VideoCapture(str(VIDEO))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    full_t = [p["t_ms"] for p in raw_pts_all]
    t_lo = full_t[0] if full_t else path[0]["t_ms"]
    t_hi = full_t[-1] if full_t else path[-1]["t_ms"]
    f_lo = max(0, int(t_lo / 1000.0 * fps) - 6)
    f_hi = min(total - 1, int(t_hi / 1000.0 * fps) + 6)

    writer = cv2.VideoWriter(str(OUT / "test4_tracked.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    rect = np.array([[c["u"], c["v"]] for c in pitch_rect], np.int32) if pitch_rect else None
    corr = np.array([[c["u"], c["v"]] for c in corridor], np.int32) if len(corridor) >= 3 else None
    sample_saved = False

    for f in range(f_lo, f_hi + 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok: break
        t_now = f / fps * 1000.0
        frame = (frame * 0.62).astype(np.uint8)

        if rect is not None and len(rect) >= 3:
            cv2.polylines(frame, [rect], True, BLUE, 2, cv2.LINE_AA)
        if corr is not None:
            tint = frame.copy(); cv2.fillPoly(tint, [corr], GOLD)
            frame = cv2.addWeighted(tint, 0.22, frame, 0.78, 0)
            cv2.polylines(frame, [corr], True, GOLD, 2, cv2.LINE_AA)

        for key, col, lw in (("striker", GOLD, 4), ("bowler", WHITE, 3)):
            st = stumps.get(key) or {}
            if not (st.get("base") and st.get("top")): continue
            bu, bv = float(st["base"]["u"]), float(st["base"]["v"])
            tu, tv = float(st["top"]["u"]), float(st["top"]["v"])
            spread = max(6.0, abs(tu - bu) + 0.20 * abs(bv - tv))
            for off in (-spread, 0.0, spread):
                b = (int(bu + off), int(bv)); tp = (int(tu + off), int(tv))
                cv2.line(frame, b, tp, col, lw, cv2.LINE_AA)
                cv2.circle(frame, tp, max(3, lw - 1), col, -1, cv2.LINE_AA)

        if len(flight) >= 2:
            poly = np.array([(int(x), int(y)) for x, y in flight], np.int32)
            cv2.polylines(frame, [poly], False, RED, 5, cv2.LINE_AA)
        if predicted:
            tail = (int(flight[-1][0]), int(flight[-1][1])) if flight else predicted[0]
            chain = [tail, *predicted]
            for a, b in zip(chain, chain[1:]):
                _dashed(frame, a, b, RED, thick=4, dash=14, gap=10)

        # Ball marker tracks every detected position (including post-impact
        # deflection frames) so the moving dot still follows the ball; the
        # static red flight line above is the one that stops at impact.
        ball = min(raw_pts_all, key=lambda p: abs(p["t_ms"] - t_now))
        cv2.circle(frame, (int(ball["u"]), int(ball["v"])), 11, WHITE, -1, cv2.LINE_AA)
        cv2.circle(frame, (int(ball["u"]), int(ball["v"])), 11, RED, 2, cv2.LINE_AA)

        _card(frame, 24, 24, 170, 78, "SPEED", f"{metrics.get('speed_kmh', 0):.0f} km/h")
        dec = (lbw.get("decision") or "n/a").upper().replace("_", " ")
        cv2.rectangle(frame, (24, 112), (24 + 16 * len(dec) + 28, 150), (24, 24, 24), -1)
        cv2.putText(frame, dec, (38, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.85, GOLD, 2, cv2.LINE_AA)

        writer.write(frame)
        if not sample_saved and t_now >= t_lo + 0.5 * (t_hi - t_lo):
            cv2.imwrite(str(OUT / "test4_sample.png"), frame); sample_saved = True

    writer.release(); cap.release()
    print(f"  wrote test4_tracked.mp4 ({f_hi - f_lo + 1} frames) + test4_sample.png")


def main() -> int:
    if not VIDEO.exists():
        print(f"FAIL: {VIDEO} missing"); return 1
    req = build_request()
    art = Path(tempfile.mkdtemp(prefix="test4_e2e_"))
    out = run_pipeline(video_path=VIDEO, request_json=req, artifacts_dir=art, progress=None)
    result = out.result

    track = result.get("track") or {}; pts = track.get("image_points") or []
    cal = (result.get("calibration") or {}).get("quality") or {}
    lbw = result.get("lbw") or {}; metrics = result.get("metrics") or {}
    ov = result.get("overlay") or {}; diag = result.get("diagnostics") or {}

    print("=" * 64)
    print("PocketDRS production pipeline — test4.mp4 end-to-end")
    print("=" * 64)
    print(f"calibration : reproj={cal.get('reproj_error_px', float('nan')):.2f}px  "
          f"score={cal.get('score', 0):.2f}  notes={cal.get('notes')}")
    print(f"ball track  : {len(pts)} image points  inliers={track.get('inliers')}")
    if pts:
        us = [p['u'] for p in pts]; vs = [p['v'] for p in pts]
        print(f"            : t {pts[0]['t_ms']}->{pts[-1]['t_ms']}ms  "
              f"u {min(us):.0f}..{max(us):.0f}  v {min(vs):.0f}..{max(vs):.0f}")
    print(f"3D world    : {len((result.get('world_trajectory') or {}).get('points_m') or [])} points")
    print(f"metrics     : speed={metrics.get('speed_kmh')} km/h ({metrics.get('speed_mph')} mph)")
    print(f"LBW         : {lbw.get('decision')}  ({lbw.get('reason')})")
    print(f"overlay     : path={len(ov.get('path_px') or [])}  corridor={len(ov.get('corridor_px') or [])}  "
          f"impact={'yes' if ov.get('impact_px') else 'no'}  bounce={'yes' if ov.get('bounce_px') else 'no'}")
    for w in diag.get("warnings") or []:
        print(f"warning     : {w}")

    (OUT / "result.json").write_text(json.dumps(result, indent=2))

    ok = len(pts) >= 6 and bool(ov.get("path_px"))
    if not ok:
        print("\nFAIL: ball not tracked end-to-end")
        return 1

    print("\nrendering overlay ...")
    render(result)
    print("emitting Three.js viewer ...")
    render_three_d_viewer(result)
    print("rendering 3D view ...")
    render_3d(result)
    print("\nPASS: ball tracked full end-to-end; overlay rendered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
