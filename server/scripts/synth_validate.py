"""Synthetic LBW validation harness.

Generates a realistic umpire-POV cricket video for several known scenarios
(out / not-out / umpire's call / outside-leg) and runs the production
pipeline against each. Each scenario uses a medium-pace delivery (~32 m/s)
so the ball bounces exactly once before reaching the stump line.

Outputs:
- dump/validation/results.txt           summary table
- dump/validation/<scenario>/result.json complete pipeline output
- dump/validation/<scenario>/frame0.jpg first frame for visual reference
- dump/validation/<scenario>/payload.json viewer payload (for hawkeye.js)

The script is intentionally a one-shot harness; no side effects beyond the
listed outputs.
"""

from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.process_job import run_pipeline


# ---------------------------------------------------------------------------
# Scene config (fixed across scenarios)
# ---------------------------------------------------------------------------
W, H = 1080, 1920
FX = FY = 900.0
CX, CY = W / 2.0, H / 2.0
H_FOV_DEG = 2.0 * math.degrees(math.atan((W / 2.0) / FX))

PITCH_LEN = 20.12
PITCH_WID = 3.05
HALF_W = PITCH_WID / 2.0

CAM_WORLD = np.array([-3.5, 0.0, 1.8])
LOOK_AT = np.array([10.0, 0.0, 0.0])

FPS = 60
DUR_S = 1.3                 # enough for a medium-pace delivery + extrapolation
N_FRAMES = int(FPS * DUR_S)

BALL_RADIUS_M = 0.036
G = 9.81
RESTITUTION = 0.55

OUT_ROOT = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/validation")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_K_SYNTH = np.array([[FX, 0, CX], [0, FY, CY], [0, 0, 1]], dtype=np.float64)
_DIST_SYNTH = np.zeros((4, 1), dtype=np.float64)


def look_at_R(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    world_up = np.array([0.0, 0.0, 1.0])
    right = np.cross(world_up, forward)
    right = right / np.linalg.norm(right)
    down = np.cross(forward, right)
    return np.stack([right, down, forward], axis=0)


def world_to_pixel(R: np.ndarray, t: np.ndarray, X: np.ndarray) -> tuple[float, float, float]:
    rvec, _ = cv2.Rodrigues(R)
    proj, _ = cv2.projectPoints(X.reshape(1, 1, 3), rvec, t.reshape(3, 1), _K_SYNTH, _DIST_SYNTH)
    Xc = R @ X.reshape(3) + t.reshape(3)
    return float(proj[0, 0, 0]), float(proj[0, 0, 1]), float(Xc[2])


# ---------------------------------------------------------------------------
# Ball simulation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    expected_decision: str
    # Release state: position (x_m, y_m, z_m), velocity (vx, vy, vz) m/s.
    p0: tuple[float, float, float]
    v0: tuple[float, float, float]


def simulate_ball(p0: np.ndarray, v0: np.ndarray) -> list[tuple[float, np.ndarray]]:
    dt = 1.0 / FPS
    states: list[tuple[float, np.ndarray]] = []
    p, v = p0.copy(), v0.copy()
    t = 0.0
    for _ in range(N_FRAMES):
        states.append((t, p.copy()))
        v_next = v + np.array([0.0, 0.0, -G]) * dt
        p_next = p + v_next * dt
        if p_next[2] <= BALL_RADIUS_M and v_next[2] < 0:
            v_next[2] = -RESTITUTION * v_next[2]
            p_next[2] = BALL_RADIUS_M + (BALL_RADIUS_M - p_next[2])
        p, v = p_next, v_next
        # Stop when ball has crossed the stump line.
        if p[0] < -0.5:
            states.append((t + dt, p.copy()))
            break
        t += dt
    return states


def find_first_bounce(states: list[tuple[float, np.ndarray]]) -> int:
    """Index of first frame after vertical-velocity reversal (ground bounce).

    A 25 m/s ball moves > 40 cm per 60-fps frame, so the on-ground sample is
    typically skipped. Detect by sign change in dz/dt instead of z threshold.
    """
    for i in range(1, len(states) - 1):
        dz_prev = states[i][1][2] - states[i - 1][1][2]
        dz_next = states[i + 1][1][2] - states[i][1][2]
        if dz_prev < 0 and dz_next > 0:
            return i
    return len(states) // 2


def find_stump_crossing(states: list[tuple[float, np.ndarray]]) -> int:
    """Index where ball x crosses 0 (striker stump line)."""
    for i in range(1, len(states)):
        if states[i][1][0] <= 0.0:
            return i
    return len(states) - 1


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_scene(out_path: Path, states: list[tuple[float, np.ndarray]]) -> list[tuple[float, float]]:
    R = look_at_R(CAM_WORLD, LOOK_AT)
    t = (-R @ CAM_WORLD).reshape(3)
    corners_world = [
        np.array([0.0,         -HALF_W, 0.0]),
        np.array([0.0,          HALF_W, 0.0]),
        np.array([PITCH_LEN,    HALF_W, 0.0]),
        np.array([PITCH_LEN,   -HALF_W, 0.0]),
    ]
    corners_px = [world_to_pixel(R, t, c)[:2] for c in corners_world]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, FPS, (W, H))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter failed")

    pitch_poly = np.array([world_to_pixel(R, t, c)[:2] for c in corners_world], dtype=np.int32)

    for _, p in states[:N_FRAMES]:
        frame = np.full((H, W, 3), (60, 110, 70), dtype=np.uint8)  # grass
        cv2.fillPoly(frame, [pitch_poly], (70, 110, 160))           # dirt
        for x_m in (1.22, PITCH_LEN - 1.22):
            a = world_to_pixel(R, t, np.array([x_m, -HALF_W, 0.0]))[:2]
            b = world_to_pixel(R, t, np.array([x_m,  HALF_W, 0.0]))[:2]
            cv2.line(frame, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (240, 240, 240), 2)
        u, v, depth = world_to_pixel(R, t, p)
        if math.isfinite(u) and depth > 0:
            r_px = max(2.0, FX * BALL_RADIUS_M / depth)
            cv2.circle(frame, (int(u), int(v)), int(round(r_px)), (40, 40, 220), -1, lineType=cv2.LINE_AA)
            cv2.circle(frame, (int(u - r_px * 0.3), int(v - r_px * 0.3)),
                       max(1, int(r_px * 0.3)), (80, 90, 240), -1, lineType=cv2.LINE_AA)
        writer.write(frame)
    writer.release()
    return [(float(u), float(v)) for u, v in corners_px]


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

WICKET_HALF = 0.114             # 11.4 cm half-width of three stumps
WICKET_GUARD = WICKET_HALF + BALL_RADIUS_M
STUMP_TOP = 0.711
LEG_LIMIT = WICKET_HALF + 0.114  # one full stump width outside leg


def _predict_stump_state(p0, v0) -> tuple[float, float, float] | None:
    """Forward-simulate to x=0 and report (bounce_x, y_at_stumps, z_at_stumps)."""
    states = simulate_ball(np.array(p0), np.array(v0))
    if not states:
        return None
    bounce_idx = find_first_bounce(states)
    bounce_x = states[bounce_idx][1][0]
    last = next((s for s in states if s[1][0] <= 0.0), states[-1])
    return float(bounce_x), float(last[1][1]), float(last[1][2])


def _expected_decision(p0, v0) -> str:
    """Closed-form ground-truth label based on the analytical simulation.

    Mirrors the pipeline's LBW logic so we can grade decisions against the
    *known* underlying physics, not against the noisy reconstruction.
    """
    pred = _predict_stump_state(p0, v0)
    if pred is None:
        return "not_out"
    bounce_x, y_stumps, z_stumps = pred
    # Pitched outside leg → not_out regardless of trajectory after pitching.
    bounce_y = p0[1] + v0[1] * (p0[0] - bounce_x) / max(abs(v0[0]), 1e-3)
    if bounce_y < -LEG_LIMIT:
        return "not_out"
    # ICC half-ball overlap rule: the ball centre within one ball-radius of
    # a stump edge produces an umpire's call. We use the strict ICC band
    # here so that ground truth reflects the formal DRS specification.
    UMP_BAND = BALL_RADIUS_M  # 3.6 cm
    # Outside guard horizontally.
    if abs(y_stumps) > WICKET_GUARD:
        if abs(y_stumps) - WICKET_GUARD <= UMP_BAND:
            return "umpires_call"
        return "not_out"
    # Above the stumps.
    if z_stumps > STUMP_TOP + BALL_RADIUS_M:
        if z_stumps - (STUMP_TOP + BALL_RADIUS_M) <= UMP_BAND:
            return "umpires_call"
        return "not_out"
    if z_stumps < 0:
        return "not_out"
    # Hits stumps: umpire's call when grazing any edge.
    margin = min(
        WICKET_GUARD - abs(y_stumps),
        (STUMP_TOP + BALL_RADIUS_M) - z_stumps,
        z_stumps,
    )
    return "umpires_call" if margin <= UMP_BAND else "out"


# Realistic delivery mix: clear deliveries dominate, close calls are rare.
# Three speed bands (slow spin / medium pace / fast pace) × multiple lines
# spanning wide-of-off through outside-leg, plus distinct length variations.
_SPEEDS = [-18.0, -24.0, -30.0]
_RELEASE_Z = 2.0


def _gen_scenarios() -> list[Scenario]:
    out: list[Scenario] = []
    # Wide range of release y across the realistic distribution.
    lines = [
        # Clearly wide of off — NOT OUT
        (+0.65, +0.00, "wide_off"),
        (+0.55, -0.10, "off_drifting_in"),
        # Off stump line — OUT
        (+0.10, -0.10, "off_stump_line"),
        # Middle stump line — OUT
        (+0.00, +0.00, "middle_stump"),
        (-0.05, +0.05, "middle_clip"),
        # Leg stump line — OUT
        (-0.10, +0.10, "leg_stump_line"),
        # Pitched on leg margin — UMPIRE'S CALL
        (-0.20, +0.05, "leg_marginal"),
        # Outside leg — NOT OUT
        (-0.40, +0.00, "outside_leg"),
        (-0.55, -0.05, "well_outside_leg"),
        # Down-leg slanting — NOT OUT
        (-0.05, -0.30, "going_down_leg"),
        # Going wide-off — NOT OUT
        (+0.05, +0.30, "going_wide_off"),
    ]
    vz_options = [-2.5, -3.0]
    for vx in _SPEEDS:
        for y0, vy, label in lines:
            for vz in vz_options:
                p0 = (19.0, y0, _RELEASE_Z)
                v0 = (vx, vy, vz)
                exp = _expected_decision(p0, v0)
                name = f"v{int(-vx)}_{label}_vz{int(-vz*10)}_{exp}"
                out.append(Scenario(
                    name=name,
                    description=f"{label} speed={-vx:.0f}m/s",
                    expected_decision=exp,
                    p0=p0,
                    v0=v0,
                ))
    return out


SCENARIOS: list[Scenario] = _gen_scenarios()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def build_viewer_payload(result: dict) -> dict | None:
    wt = result.get("world_trajectory")
    if not wt:
        return None
    points = [{"x": p["x"], "y": p["y"], "z": p["z"]} for p in wt["points_m"]]
    for p in wt.get("predicted_to_stumps_m", []):
        points.append({"x": p["x"], "y": p["y"], "z": p["z"]})
    times = [p["t_ms"] for p in wt["points_m"]]
    ev = result.get("events") or {}
    def _near(t: int | None) -> int:
        if t is None or not times:
            return 0
        return min(range(len(times)), key=lambda i: abs(times[i] - t))
    return {
        "points": points,
        "bounceIndex": _near((ev.get("bounce") or {}).get("t_ms")),
        "impactIndex": _near((ev.get("impact") or {}).get("t_ms")),
        "decision": (result.get("lbw") or {}).get("decision"),
    }


def run_one(scenario: Scenario) -> dict:
    out_dir = OUT_ROOT / scenario.name
    out_dir.mkdir(parents=True, exist_ok=True)
    art = Path(tempfile.mkdtemp(prefix=f"synth_{scenario.name}_"))

    states = simulate_ball(np.array(scenario.p0), np.array(scenario.v0))
    bounce_idx = find_first_bounce(states)
    impact_idx = find_stump_crossing(states)
    bounce_gt = states[bounce_idx]
    impact_gt = states[impact_idx]

    video = art / "synth.mp4"
    corners = render_scene(video, states)

    req = {
        "segment": {"start_ms": 0, "end_ms": int(1000 * (N_FRAMES - 1) / FPS)},
        "calibration": {
            "mode": "taps",
            "pitch_corners_px": [{"x": u, "y": v} for (u, v) in corners],
            "pitch_dimensions_m": {"length": PITCH_LEN, "width": PITCH_WID},
            "h_fov_deg": H_FOV_DEG,
        },
        "tracking": {"sample_fps": FPS, "max_frames": N_FRAMES, "ball_color": "red"},
    }

    out = run_pipeline(video_path=video, request_json=req, artifacts_dir=art, progress=None)
    r = out.result

    payload = build_viewer_payload(r)
    (out_dir / "result.json").write_text(json.dumps(r, indent=2, default=str))
    if payload is not None:
        (out_dir / "payload.json").write_text(json.dumps(payload))

    cap = cv2.VideoCapture(str(video))
    ok, f0 = cap.read()
    if ok:
        cv2.imwrite(str(out_dir / "frame0.jpg"), f0)
    cap.release()

    cal = r["calibration"]
    track = r["track"]
    ev = r.get("events") or {}
    lbw = r.get("lbw") or {}

    bounce_err = impact_err = None
    if ev.get("bounce") and ev["bounce"].get("x_m") is not None:
        b = ev["bounce"]
        bounce_err = math.hypot(b["x_m"] - bounce_gt[1][0], b["y_m"] - bounce_gt[1][1])
    if ev.get("impact") and ev["impact"].get("x_m") is not None:
        i = ev["impact"]
        impact_err = math.sqrt(
            (i["x_m"] - impact_gt[1][0]) ** 2
            + (i["y_m"] - impact_gt[1][1]) ** 2
            + ((i.get("z_m") or 0.0) - impact_gt[1][2]) ** 2
        )

    return {
        "name": scenario.name,
        "description": scenario.description,
        "expected": scenario.expected_decision,
        "release_x": scenario.p0[0],
        "release_y": scenario.p0[1],
        "release_v": scenario.v0,
        "ground_truth_bounce_m": [round(float(x), 3) for x in bounce_gt[1]],
        "ground_truth_impact_m": [round(float(x), 3) for x in impact_gt[1]],
        "reproj_px": round(cal["quality"]["reproj_error_px"], 2),
        "cam_center_m": [round(c, 3) for c in cal["pose"]["cam_center_world_m"]],
        "candidates": track["candidates_total"],
        "inliers": track["inliers"],
        "rms_px": round(track["rms_px"], 2),
        "world_points": len(r.get("world_trajectory", {}).get("points_m", []) if r.get("world_trajectory") else []),
        "recovered_bounce_xy_m": (
            [round(ev["bounce"]["x_m"], 3), round(ev["bounce"]["y_m"], 3)]
            if ev.get("bounce") and ev["bounce"].get("x_m") is not None else None
        ),
        "recovered_impact_m": (
            [round(ev["impact"]["x_m"], 3), round(ev["impact"]["y_m"], 3), round(ev["impact"].get("z_m") or 0.0, 3)]
            if ev.get("impact") and ev["impact"].get("x_m") is not None else None
        ),
        "bounce_err_cm": round(bounce_err * 100, 1) if bounce_err is not None else None,
        "impact_err_cm": round(impact_err * 100, 1) if impact_err is not None else None,
        "decision": lbw.get("decision"),
        "reason": lbw.get("reason"),
        "warnings": r["diagnostics"]["warnings"],
    }


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for i, sc in enumerate(SCENARIOS, 1):
        print(f"[{i:2d}/{len(SCENARIOS)}] {sc.name}")
        try:
            r = run_one(sc)
            results.append(r)
            tag = "OK " if r["decision"] == r["expected"] else "MISS"
            print(f"   {tag} decision={r['decision']} expected={r['expected']} "
                  f"track={r['inliers']}/{r['candidates']} "
                  f"impact_err={r['impact_err_cm']}cm")
        except Exception as e:  # noqa: BLE001
            results.append({"name": sc.name, "error": str(e), "expected": sc.expected_decision})
            print(f"   ERR  {e}")

    summary_path = OUT_ROOT / "results.txt"
    matches = 0
    by_class: dict[str, dict[str, int]] = {}
    with summary_path.open("w") as f:
        f.write(f"PocketDRS synthetic LBW validation — {len(results)} scenarios\n")
        f.write("=" * 72 + "\n\n")
        f.write(f"{'#':>3}  {'name':<35} {'exp':<14} {'got':<14} {'imp_err_cm':>10} match\n")
        f.write("-" * 80 + "\n")
        for i, r in enumerate(results, 1):
            if "error" in r:
                f.write(f"{i:>3}  {r['name']:<35} {r['expected']:<14} ERROR: {r['error']}\n")
                continue
            ok = r["decision"] == r["expected"]
            matches += ok
            by_class.setdefault(r["expected"], {"n": 0, "ok": 0})
            by_class[r["expected"]]["n"] += 1
            by_class[r["expected"]]["ok"] += int(ok)
            f.write(f"{i:>3}  {r['name']:<35} {r['expected']:<14} {r['decision'] or '-':<14} "
                    f"{r['impact_err_cm'] if r['impact_err_cm'] is not None else '-':>10}  "
                    f"{'OK' if ok else 'miss'}\n")
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"Overall decision match: {matches}/{len(results)} "
                f"({100*matches/len(results):.1f}%)\n\n")
        for cls, st in by_class.items():
            f.write(f"  {cls:<14} {st['ok']}/{st['n']} ({100*st['ok']/st['n']:.1f}%)\n")
        # Also stash detailed track/recon diagnostics for the deep dive.
        f.write("\n\nDetailed diagnostics\n")
        f.write("=" * 72 + "\n")
        for r in results:
            if "error" in r:
                continue
            f.write(f"\n[{r['name']}]\n")
            f.write(f"  reason  : {r['reason']}\n")
            f.write(f"  reproj  : {r['reproj_px']}px cam={r['cam_center_m']}\n")
            f.write(f"  track   : {r['inliers']}/{r['candidates']} rms={r['rms_px']}px world={r['world_points']}\n")
            f.write(f"  bounce  : gt={r['ground_truth_bounce_m']} reco={r['recovered_bounce_xy_m']} err={r['bounce_err_cm']}cm\n")
            f.write(f"  impact  : gt={r['ground_truth_impact_m']} reco={r['recovered_impact_m']} err={r['impact_err_cm']}cm\n")
    print()
    print(f"Summary written to {summary_path}")
    print(f"Overall match: {matches}/{len(results)} ({100*matches/len(results):.1f}%)")
    for cls, st in by_class.items():
        print(f"  {cls}: {st['ok']}/{st['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
