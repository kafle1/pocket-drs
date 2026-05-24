"""End-to-end production-pipeline test for test3.mp4.

Runs the EXACT server pipeline the app calls (``run_pipeline`` ->
``process_job``) on the real indoor-net clip ``test3.mp4`` with its recovered
calibration taps, verifies the ball is tracked through the whole chain
(calibrate -> auto/YOLO detect -> RANSAC trajectory -> gravity-constrained 3D
-> LBW -> overlay), and renders the FullTrack-style broadcast overlay onto the
video.

Nothing here re-implements the pipeline: detection, association, pose,
reconstruction and the pixel overlay all come from ``app.pipeline``. This file
only feeds the request and draws the returned ``overlay`` payload onto frames.

Run:    server/.venv/bin/python server/scripts/test3_e2e.py
Out:    dump/validation/test3/{result.json, test3_tracked.mp4, test3_sample.png}
Exit 0 only if the ball is tracked end-to-end and the overlay is produced.
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

VIDEO = ROOT / "test3.mp4"
WEIGHTS = ROOT / "server" / "models" / "cricket_ball.pt"
OUT = ROOT / "dump" / "validation" / "test3"
OUT.mkdir(parents=True, exist_ok=True)

# Recovered test3 calibration taps (normalised 0..1 over the 1080x1920 frame).
# Each stump set is the bounding rectangle of the three-stump cluster
# (TL, TR, BR, BL) — the same 4-corner taps the production calibration UI
# emits via ``stump_quads_norm``. Half-cluster widths in normalised image
# units: striker (far) ≈ 0.011, bowler (near) ≈ 0.048 — eyeballed from
# the first frame and consistent with the perspective.
STRIKER_QUAD = [
    (0.5048, 0.4816),  # TL
    (0.5272, 0.4816),  # TR
    (0.5272, 0.5429),  # BR
    (0.5048, 0.5429),  # BL
]
BOWLER_QUAD = [
    (0.4185, 0.6304),  # TL
    (0.5165, 0.6304),  # TR
    (0.5165, 0.8409),  # BR
    (0.4185, 0.8409),  # BL
]
CORNERS_NORM = [  # striker-left, striker-right, bowler-right, bowler-left
    (0.324, 0.521), (0.704, 0.521), (0.787, 0.911), (0.185, 0.911),
]


def build_request() -> dict:
    """The same request shape analyze_screen sends: whole clip, detector=auto."""
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
            # test3.mp4 was filmed on a zoomed-in phone (~37° horizontal
            # FOV). The pitch-corner taps in this fixture are eyeballed
            # rather than precisely measured, so they disagree with the
            # stump geometry under any single FOV — the joint solver
            # would then drop them and the stumps-only fallback has a
            # (FOV × length) degeneracy. Pinning the real FOV lets the
            # solver recover the correct ~12 m length and ~60 km/h speed
            # deterministically. The production app does not need this
            # override: real users tap the actual turf corners, which
            # disambiguate FOV on their own.
            "h_fov_deg": 37.0,
            "pitch_dimensions_m": {"width": 3.05},
            "pitch_corners_norm": [{"x": x, "y": y} for x, y in CORNERS_NORM],
            "stump_quads_norm": [
                {"x": x, "y": y} for x, y in STRIKER_QUAD + BOWLER_QUAD
            ],
        },
    }


# --------------------------------------------------------------------------- #
# Rendering — draws the returned overlay payload (pixels already projected
# server-side; no camera maths happens here).
# --------------------------------------------------------------------------- #
RED = (60, 60, 235)
GOLD = (60, 200, 245)
BLUE = (235, 170, 60)
WHITE = (255, 255, 255)

def render_three_d_viewer(result: dict) -> None:
    """Emit the same Three.js HTML the /v1/jobs/{id}/three-d endpoint serves.

    Uses the shared ``app.three_d_viewer.render_html`` helper so the
    diagnostic script and the production endpoint can't drift.
    """
    from app.three_d_viewer import render_html
    out = OUT / "test3_3d.html"
    out.write_text(render_html(result))
    print(f"  wrote {out.name}")


def _dashed(img, a, b, color, thick=3, dash=18, gap=12):
    a = np.array(a, float)
    b = np.array(b, float)
    length = float(np.hypot(*(b - a)))
    if length < 1:
        return
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


def render_3d(result: dict) -> None:
    """3D Hawk-Eye trajectory plot, oblique umpire-ish angle.

    Modelled on the report's ``test3_3d_path`` figure (oblique scatter with
    ground shadow + drop lines + time-coloured points) but rebuilt around
    the cricket geometry: real pitch quad, both sets of stumps, the in-line
    LBW corridor between them, bounce + impact markers, and the bounce-
    aware predicted continuation as a dashed line to the stump plane.

    A single 3D axes — the previous "umpire POV looking straight down x"
    compressed the trajectory into a vertical sliver because the pitch is
    6 m long and only 3 m wide, so the eye had nothing to read against.
    An oblique angle restores depth.
    """
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

    # Pitch surface — two-tone so the strip reads as a real pitch with a
    # darker centre band rather than a flat green slab.
    pitch_quad = [(0, -half_w, 0), (0, half_w, 0), (L, half_w, 0), (L, -half_w, 0)]
    ax.add_collection3d(Poly3DCollection(
        [pitch_quad], facecolor="#1f4a2c", alpha=0.95, edgecolor="#4f9b66"))

    # In-line LBW corridor: the lateral band between the two outermost
    # stumps (±0.114 + ball radius), running the whole length of the
    # pitch. A ball that pitches OR impacts inside this band is "in line"
    # for the LBW; outside it is automatic not out. Drawn brighter than
    # the pitch and raised 1 mm so it sits cleanly on top.
    corr_half = STUMP_DX + 0.036  # outer-stump half + ball radius
    corr_quad = [(0, -corr_half, 0.002), (0, corr_half, 0.002),
                 (L, corr_half, 0.002), (L, -corr_half, 0.002)]
    ax.add_collection3d(Poly3DCollection(
        [corr_quad], facecolor="#f5c14b", alpha=0.45, edgecolor="#ffd166"))

    # Popping creases at 1.22 m from each stump line — the "pitching area"
    # markings batters use to read length. Two thin yellow lines across
    # the pitch keep the geometry recognisable as cricket, not generic 3D.
    POPPING_CREASE_M = 1.22
    for cx in (POPPING_CREASE_M, L - POPPING_CREASE_M):
        ax.plot([cx, cx], [-half_w, half_w], [0.003, 0.003],
                color="#ffd166", linewidth=1.5, alpha=0.7)
    # Stump-to-stump centerline so the pitching-area band reads as the
    # bowler's intended line.
    ax.plot([0, L], [0, 0], [0.003, 0.003],
            color="#f0e6b2", linewidth=1.0, alpha=0.35, linestyle=":")

    # Striker (far, prominent) and bowler (near, faint) stumps. Bails on
    # top so the stumps read as a wicket, not three sticks. Drawn last
    # over the corridor so they pop visually.
    BAIL_Z = H_STUMP + 0.012
    for x_end, col, lw, alpha in (
        (0.0, "#ffd166", 4.5, 1.0),
        (L,   "#cdd3dc", 2.8, 0.55),
    ):
        for dy in (-STUMP_DX, 0.0, STUMP_DX):
            ax.plot([x_end, x_end], [dy, dy], [0, H_STUMP],
                    color=col, linewidth=lw, alpha=alpha,
                    solid_capstyle="round", zorder=7)
        # Bails: two short horizontal sticks linking adjacent stumps.
        ax.plot([x_end, x_end], [-STUMP_DX, 0.0], [BAIL_Z, BAIL_Z],
                color=col, linewidth=max(1.5, lw - 1.8), alpha=alpha, zorder=7)
        ax.plot([x_end, x_end], [0.0, STUMP_DX], [BAIL_Z, BAIL_Z],
                color=col, linewidth=max(1.5, lw - 1.8), alpha=alpha, zorder=7)

    if pts:
        xs_t = [p["x"] for p in pts]
        ys_t = [p["y"] for p in pts]
        zs_t = [max(0.01, p["z"]) for p in pts]
        # Ground shadow + vertical drop lines so the eye can read depth
        # against the pitch surface (Hawk-Eye-style helper geometry).
        ax.plot(xs_t, ys_t, [0.004] * len(xs_t),
                color="#9aa0a6", linewidth=1.2, linestyle=":", alpha=0.6,
                zorder=5)
        for xs_i, ys_i, zs_i in zip(xs_t[::2], ys_t[::2], zs_t[::2]):
            ax.plot([xs_i, xs_i], [ys_i, ys_i], [0.004, zs_i],
                    color="#9aa0a6", linewidth=0.7, alpha=0.35,
                    zorder=5)
        ax.plot(xs_t, ys_t, zs_t,
                color="#ff4a4a", linewidth=4.0, label="tracked", zorder=8)
        ts_t = np.linspace(0.0, 1.0, len(xs_t))
        ax.scatter(xs_t, ys_t, zs_t, c=ts_t, cmap="plasma", s=22,
                   edgecolor="#0d1117", linewidth=0.4, depthshade=False,
                   zorder=8)

    # Predicted continuation — stops at the stump plane (server-enforced)
    # so the dashed line terminates exactly where the LBW intersection is.
    # Pre-pend the impact point so the dashes flow out of the tracked arc.
    if pred:
        pred_xs = [p["x"] for p in pred]
        pred_ys = [p["y"] for p in pred]
        pred_zs = [max(0.015, p["z"]) for p in pred]
        if impact.get("x_m") is not None:
            pred_xs = [impact["x_m"]] + pred_xs
            pred_ys = [impact["y_m"]] + pred_ys
            pred_zs = [max(0.015, impact.get("z_m", 0.0))] + pred_zs
        ax.plot(pred_xs, pred_ys, pred_zs, color="#ffd700",
                linewidth=4.0, linestyle="--", dashes=(4, 2),
                label="predicted", zorder=9)
        # Predicted ground shadow so the LBW corridor crossing is readable.
        ax.plot(pred_xs, pred_ys, [0.004] * len(pred_xs),
                color="#ffd700", linewidth=1.0, linestyle=":", alpha=0.45,
                zorder=5)

    # Pitching point: where the ball lands. Drawn as a flat tinted disc on
    # the pitch (a small filled circle marker reads as a disc when viewed
    # from this elevation) plus a vertical wick so the eye picks it up
    # against the corridor band.
    if bounce.get("x_m") is not None:
        bx, by = float(bounce["x_m"]), float(bounce["y_m"])
        ax.scatter([bx], [by], [0.005],
                   marker="o", s=150, color="#22d3ee",
                   edgecolor="#0d1117", linewidth=1.4,
                   label="pitching", depthshade=False, zorder=11)
        ax.plot([bx, bx], [by, by], [0.005, 0.35],
                color="#22d3ee", linewidth=1.2, alpha=0.55, zorder=11)

    if impact.get("x_m") is not None:
        ax.scatter([impact["x_m"]], [impact["y_m"]], [impact["z_m"]],
                   marker="X", s=140, color="#fbbf24",
                   edgecolor="#0d1117", linewidth=1.4,
                   label="impact", depthshade=False, zorder=11)

    # Oblique umpire-side angle: standing behind the bowler stumps but
    # off-centre so we see the pitch length as a real strip, not a sliver.
    # elev=18 / azim=-58 is close to the broadcast Hawk-Eye reference
    # angle and matches the report's ``test3_3d_path`` figure.
    ax.view_init(elev=18, azim=-58)
    ax.set_xlim(-0.3, L + 0.3)
    ax.set_ylim(-half_w - 0.2, half_w + 0.2)
    ax.set_zlim(0, max(2.0, max((p["z"] for p in pts), default=1.0) + 0.4))
    try:
        ax.set_box_aspect((L + 0.6, W + 0.4, 1.6))
    except AttributeError:
        pass

    # Keep faint axis ticks so absolute scale is readable, but tone them
    # down to broadcast-graphic level (the corridor / stumps carry the
    # geometry).
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_facecolor("#0d1117")
        axis.pane.set_edgecolor("#1f2933")
        axis.line.set_color("#1f2933")
    ax.tick_params(colors="#5b6473", labelsize=8)
    ax.set_xlabel("x  along pitch (m)", color="#9aa0a6", fontsize=9, labelpad=2)
    ax.set_ylabel("y  across (m)",      color="#9aa0a6", fontsize=9, labelpad=2)
    ax.set_zlabel("z  height (m)",       color="#9aa0a6", fontsize=9, labelpad=2)
    ax.grid(False)

    dec = (lbw.get("decision") or "?").upper().replace("_", " ")
    verdict_col = {
        "OUT": "#ef4444",
        "UMPIRES CALL": "#fbbf24",
        "NOT OUT": "#22c55e",
    }.get(dec, "#dde3eb")
    pred_y_at = (lbw.get("prediction") or {}).get("y_at_stumps_m")
    pred_z_at = (lbw.get("prediction") or {}).get("z_at_stumps_m")
    chip_lines = [dec]
    if pred_y_at is not None and pred_z_at is not None:
        chip_lines.append(
            f"y={pred_y_at*100:+.0f}cm  z={pred_z_at*100:.0f}cm")
    fig.text(0.04, 0.96, "\n".join(chip_lines), color=verdict_col,
             fontsize=18, fontweight="bold", va="top",
             bbox=dict(facecolor="#161b22", edgecolor=verdict_col,
                       boxstyle="round,pad=0.5"))

    fig.text(0.96, 0.96, f"{metrics.get('speed_kmh', 0):.0f} km/h",
             color="#dde3eb", fontsize=11, ha="right", va="top")

    ax.legend(loc="lower left", facecolor="#161b22", edgecolor="#30363d",
              labelcolor="#dde3eb", framealpha=0.9, fontsize=9)

    out = OUT / "test3_3d.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  wrote {out.name}")


def _anchored_prediction_px(
    raw_pts: list[dict],
    overlay_predicted: list[dict],
) -> list[tuple[int, int]]:
    """Anchor the projected world-prediction at the last visible image point.

    The server projects the bounce-aware fit's predicted continuation onto
    the image and stops it at the stump plane (target_x). Drawing that
    payload as-is can leave a small jump between the last tracked pixel
    and the first predicted pixel because the fit is not a perfect match
    for the measured track. We translate the whole predicted polyline by
    the residual between those two endpoints, so the dashes flow smoothly
    out of the tracked arc while still terminating exactly at the
    predicted stump-plane intersection (offset by the same residual,
    which is a few pixels at most).
    """
    if not overlay_predicted or not raw_pts:
        return []
    last = raw_pts[-1]
    first = overlay_predicted[0]
    du = float(last["u"]) - float(first["u"])
    dv = float(last["v"]) - float(first["v"])
    return [
        (int(round(float(p["u"]) + du)), int(round(float(p["v"]) + dv)))
        for p in overlay_predicted
    ]


def render(result: dict) -> None:
    ov = result.get("overlay") or {}
    path = ov.get("path_px") or []
    if not path:
        raise SystemExit("no overlay path to render")
    metrics = result.get("metrics") or {}
    lbw = result.get("lbw") or {}
    pitch_rect = ov.get("pitch_rect_px") or []
    corridor = ov.get("corridor_px") or []
    stumps = ov.get("stumps_px") or {}

    # Tracked (RED, solid) = what the detector actually saw, i.e. the full
    # measured flight from release to bat. Predicted (BLUE, dashed) = the
    # post-measurement continuation extrapolated to the stump plane and a
    # short distance past it, so the projected line is at least as long as
    # the measured one and clearly answers "where would the ball have
    # gone?".
    flight = [(p["u"], p["v"]) for p in path if p.get("phase") == "flight"]
    predicted = [(p["u"], p["v"]) for p in path if p.get("phase") == "predicted"]
    raw_pts = sorted(result.get("track", {}).get("image_points") or [],
                     key=lambda p: p["t_ms"])
    flight_t = [p["t_ms"] for p in raw_pts]

    cap = cv2.VideoCapture(str(VIDEO))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Render window: from a few frames before release through a few frames
    # after the last tracked observation. We stop at the bat — the post-bat
    # ball is the deflection, which is the umpire's business, not the
    # bowler's — and let the dashed predicted line carry the eye to the
    # stumps.
    t_lo = flight_t[0] if flight_t else path[0]["t_ms"]
    t_hi = flight_t[-1] if flight_t else path[-1]["t_ms"]
    f_lo = max(0, int(t_lo / 1000.0 * fps) - 6)
    f_hi = min(total - 1, int(t_hi / 1000.0 * fps) + 6)

    writer = cv2.VideoWriter(str(OUT / "test3_tracked.mp4"),
                             cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    rect = np.array([[c["u"], c["v"]] for c in pitch_rect], np.int32) if pitch_rect else None
    corr = (np.array([[c["u"], c["v"]] for c in corridor], np.int32)
            if len(corridor) >= 3 else None)
    sample_saved = False

    for f in range(f_lo, f_hi + 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            break
        t_now = f / fps * 1000.0

        # Dim the scene so the broadcast graphics read clearly.
        frame = (frame * 0.62).astype(np.uint8)

        # Calibration overlay: pitch outline + the in-line LBW corridor
        # ("pitching area" — between the two outermost stumps plus ball
        # radius). The corridor is filled translucent so it doesn't drown
        # the live frame; the outline gives it a defined edge.
        if rect is not None and len(rect) >= 3:
            cv2.polylines(frame, [rect], True, BLUE, 2, cv2.LINE_AA)
        if corr is not None:
            tint = frame.copy()
            cv2.fillPoly(tint, [corr], GOLD)
            frame = cv2.addWeighted(tint, 0.22, frame, 0.78, 0)
            cv2.polylines(frame, [corr], True, GOLD, 2, cv2.LINE_AA)

        # Both stump sets, drawn as full three-stump wickets so the user can
        # confirm calibration aligns with the actual stumps in the frame.
        for key, col, width_px in (("striker", GOLD, 4), ("bowler", WHITE, 3)):
            st = stumps.get(key) or {}
            if not (st.get("base") and st.get("top")):
                continue
            bu, bv = float(st["base"]["u"]), float(st["base"]["v"])
            tu, tv = float(st["top"]["u"]), float(st["top"]["v"])
            spread_px = max(6.0, abs(tu - bu) + 0.20 * abs(bv - tv))
            for off in (-spread_px, 0.0, spread_px):
                b = (int(bu + off), int(bv))
                tp = (int(tu + off), int(tv))
                cv2.line(frame, b, tp, col, width_px, cv2.LINE_AA)
                cv2.circle(frame, tp, max(3, width_px - 1), col, -1, cv2.LINE_AA)

        # Tracked flight (solid red) — release through bounce to bat impact.
        # Dashed BLUE continuation = predicted post-impact path, extended
        # linearly off the last two predicted samples only as far as the
        # striker stump base line so the dashes actually reach the wickets
        # (server's predicted_path stops at the world stump plane, which
        # can be a few px short of the rendered stump base).
        if len(flight) >= 2:
            poly = np.array([(int(x), int(y)) for x, y in flight], np.int32)
            cv2.polylines(frame, [poly], False, RED, 5, cv2.LINE_AA)
        if predicted:
            tail = (int(flight[-1][0]), int(flight[-1][1])) if flight else (int(predicted[0][0]), int(predicted[0][1]))
            chain = [tail] + [(int(x), int(y)) for x, y in predicted]
            striker_base = (stumps.get("striker") or {}).get("base")
            if striker_base and len(chain) >= 2:
                a2, b2 = chain[-2], chain[-1]
                stump_v = float(striker_base["v"])
                dv = b2[1] - a2[1]
                if abs(dv) > 1e-3:
                    s = (stump_v - b2[1]) / dv
                    if 0.0 < s < 6.0:
                        ex = (int(round(b2[0] + (b2[0] - a2[0]) * s)),
                              int(round(b2[1] + dv * s)))
                        chain.append(ex)
            for a, b in zip(chain, chain[1:]):
                _dashed(frame, a, b, BLUE, thick=5, dash=18, gap=12)
            end = chain[-1]
            cv2.circle(frame, end, 8, BLUE, -1, cv2.LINE_AA)
            cv2.circle(frame, end, 8, (20, 20, 20), 2, cv2.LINE_AA)

        # Moving ball riding the raw track at the current playback time,
        # held at the bat impact afterwards so the cursor does not vanish.
        ball = min(raw_pts, key=lambda p: abs(p["t_ms"] - t_now))
        cv2.circle(frame, (int(ball["u"]), int(ball["v"])), 11, WHITE, -1, cv2.LINE_AA)
        cv2.circle(frame, (int(ball["u"]), int(ball["v"])), 11, RED, 2, cv2.LINE_AA)

        # Single SPEED card + decision chip. The km/h reading is the
        # release speed |v0| derived from the bounce-aware projectile fit.
        _card(frame, 24, 24, 170, 78, "SPEED",
              f"{metrics.get('speed_kmh', 0):.0f} km/h")
        dec = (lbw.get("decision") or "n/a").upper().replace("_", " ")
        cv2.rectangle(frame, (24, 112), (24 + 16 * len(dec) + 28, 150), (24, 24, 24), -1)
        cv2.putText(frame, dec, (38, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.85, GOLD, 2, cv2.LINE_AA)

        writer.write(frame)
        if not sample_saved and t_now >= t_lo + 0.5 * (t_hi - t_lo):
            cv2.imwrite(str(OUT / "test3_sample.png"), frame)
            sample_saved = True

    writer.release()
    cap.release()
    if not sample_saved:  # short window — keep the last frame as the sample
        pass
    print(f"  wrote test3_tracked.mp4 ({f_hi - f_lo + 1} frames) + test3_sample.png")


def main() -> int:
    if not VIDEO.exists():
        print(f"FAIL: {VIDEO} missing")
        return 1
    req = build_request()
    art = Path(tempfile.mkdtemp(prefix="test3_e2e_"))
    out = run_pipeline(video_path=VIDEO, request_json=req, artifacts_dir=art, progress=None)
    result = out.result

    track = result.get("track") or {}
    pts = track.get("image_points") or []
    cal = (result.get("calibration") or {}).get("quality") or {}
    lbw = result.get("lbw") or {}
    metrics = result.get("metrics") or {}
    ov = result.get("overlay") or {}
    diag = result.get("diagnostics") or {}

    print("=" * 64)
    print("PocketDRS production pipeline — test3.mp4 end-to-end")
    print("=" * 64)
    print(f"calibration : reproj={cal.get('reproj_error_px', float('nan')):.2f}px  "
          f"score={cal.get('score', 0):.2f}  notes={cal.get('notes')}")
    print(f"ball track  : {len(pts)} image points  inliers={track.get('inliers')}")
    if pts:
        us = [p['u'] for p in pts]; vs = [p['v'] for p in pts]
        print(f"            : t {pts[0]['t_ms']}->{pts[-1]['t_ms']}ms  "
              f"u {min(us):.0f}..{max(us):.0f}  v {min(vs):.0f}..{max(vs):.0f}")
    print(f"3D world    : {len(result.get('world_trajectory') or [])} points")
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
