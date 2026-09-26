"""The README's accuracy table: the app's own calibration, ball finder, fit and call on synthetic detections.

Each row is 150 random deliveries at 60 Hz with 1 px detection noise, swing, and air drag drawn per ball
(Cd 0.35 to 0.55, air 1.0 to 1.225 kg/m3) that the model doesn't know. The stump marks are off by 0 to 4 px.

Usage:  server/.venv/bin/python paper/experiments/bench_app.py
"""
import math
import os
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "..", "server")]
import synth  # noqa: E402
from synth import (PITCH_LENGTH_M, PITCH_WIDTH_M, STUMP_HEIGHT_M, STUMP_OUTER_HALF_M, Camera,  # noqa: E402
                   observe, random_delivery, truth_verdict)
from app.pipeline.calibration import solve_camera_pose  # noqa: E402
from app.pipeline.decision import decide  # noqa: E402
from app.pipeline.process_job import MAX_FIT_RMS_PX, MIN_TAP_SD_PX, UNCERTAINTY_K, _calibration_spread  # noqa: E402
from app.pipeline.reconstruction import bounce_sigma, position_sigma, predict_stump_plane, reconstruct  # noqa: E402
from app.pipeline.trajectory import find_ball  # noqa: E402

N = 150
CAMERAS = {"bowler": Camera(end="bowler", back_m=2.8, height_m=1.7),
           "batter": Camera(end="striker", back_m=2.8, height_m=1.7)}
CELLS = [(cam, tap) for cam in CAMERAS for tap in (0.0, 1.0, 2.0, 4.0)]


def call(cam: Camera, pose, taps, dets) -> str:
    """What process_job would say about these detections, with the impact at the last tracked point."""
    track = find_ball(pose, [(round(t * 1000), [{"x": u, "y": v, "radius_px": r, "confidence": w}])
                             for t, u, v, r, w in dets])
    if track is None:
        return "no_verdict"
    t0 = track.points[0]["t_ms"]
    d4 = [((p["t_ms"] - t0) / 1000.0, p["u"], p["v"], max(0.05, p["confidence"])) for p in track.points]
    rec = reconstruct(pose, d4, track.model)
    pred = None if rec is None or rec.rms_px > MAX_FIT_RMS_PX else predict_stump_plane(rec)
    if pred is None:
        return "no_verdict"
    tr = rec.trajectory
    t_last = d4[-1][0]
    sp = _calibration_spread(taps, (cam.width, cam.height), PITCH_LENGTH_M, PITCH_WIDTH_M,
                             max(pose.reproj_error_px, MIN_TAP_SD_PX), d4, rec, t_last)
    if sp is None:
        return "no_verdict"
    sy, sz = math.hypot(pred.sigma_y, sp[3]), math.hypot(pred.sigma_z, sp[4])
    s_pitch = math.hypot(bounce_sigma(rec)[1], sp[0])
    s_impact = math.hypot(position_sigma(rec, t_last)[1], sp[2])
    used = [sy, sz, s_impact] + ([s_pitch] if tr.bounce_observed else [])
    if not all(map(math.isfinite, used)) or math.hypot(sy, sz) > STUMP_HEIGHT_M:
        return "no_verdict"
    impact = tr.position(np.array([t_last]))[0]
    return decide(leg_sign=1.0, pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=s_pitch,
                  impact_y=float(impact[1]), impact_sigma=s_impact,
                  stump_y=pred.y, stump_z=pred.z, sigma_y=sy, sigma_z=sz, k=UNCERTAINTY_K).decision


def run(cell) -> str:
    name, tap = cell
    cam = CAMERAS[name]
    rng, air = np.random.default_rng(7), np.random.default_rng(99)
    pose_true = cam.pose()
    w, h = STUMP_OUTER_HALF_M, STUMP_HEIGHT_M
    corners = [(-w, h), (w, h), (w, 0.0), (-w, 0.0)]
    su, sv, _ = pose_true.project(np.array([(0.0, a, b) for a, b in corners] + [(PITCH_LENGTH_M, a, b) for a, b in corners]))
    rows = []
    while len(rows) < N:
        d = random_delivery(rng, physics=True)
        synth.DRAG_K = 0.5 * air.uniform(1.0, 1.225) * air.uniform(0.35, 0.55) * math.pi * synth.BALL_RADIUS_M ** 2 / synth.BALL_MASS
        try:
            truth = synth.fly(d)
        except ValueError:
            continue
        taps = [(float(a + rng.normal(0, tap)), float(b + rng.normal(0, tap))) for a, b in zip(su, sv)]
        pose = solve_camera_pose(image_size=(cam.width, cam.height), stump_quads_px=taps, pitch_length_m=PITCH_LENGTH_M)
        dets = observe(truth, pose_true, fps=60.0, noise_px=1.0, radius_noise=0.10, dropout=0.05, rng=rng)
        if len(dets) >= 6:
            rows.append((truth_verdict(truth), call(cam, pose, taps, dets)))
    right = sum(g == v for g, v in rows)
    wrong_out = [g for g, v in rows if v == "out" and g != "out"]
    return (f"behind the {name:6s} marks {tap:.0f} px off: {right / N:.0%} right, {len(wrong_out)} wrongly out "
            f"({wrong_out.count('umpires_call')} of them umpire's call), {sum(v == 'no_verdict' for _, v in rows)} no call")


if __name__ == "__main__":
    with Pool(min(len(CELLS), os.cpu_count() or 1)) as pool:
        for line in pool.imap(run, CELLS):
            print(line, flush=True)
