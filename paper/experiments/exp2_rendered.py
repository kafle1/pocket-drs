#!/usr/bin/env python
"""Experiment 2: the full pipeline, detector included, on rendered deliveries with known truth.

Experiment 1 feeds the estimator ideal detections with controlled noise. This one renders
each delivery of the 100-delivery grid to a 60 frame/s portrait clip, hands the clip and the
tapped marks to the production job exactly as the app would, and scores the verdict the
pipeline returns against the ground truth. Detection and association errors are therefore
included. Tap positions are perturbed by 2 px so the calibration is not handed the truth.

Usage:  server/.venv/bin/python paper/experiments/exp2_rendered.py [--quick] [--camera striker_ref]
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from synth import Camera, fly, grid, truth_verdict, CREASE_X   # noqa: E402
from render import render                                       # noqa: E402
from app.pipeline.process_job import run_pipeline              # noqa: E402

OUT = os.path.join(HERE, "raw")
os.makedirs(OUT, exist_ok=True)
CLIPS = Path(os.environ.get("POCKET_DRS_CLIPS", os.path.join(HERE, "clips")))
CLIPS.mkdir(parents=True, exist_ok=True)
QUICK = "--quick" in sys.argv
CAM_NAME = sys.argv[sys.argv.index("--camera") + 1] if "--camera" in sys.argv else "striker_ref"
CAMERAS = {"striker_ref": Camera(end="striker", back_m=2.8, height_m=1.7),
           "bowler_ref": Camera(end="bowler", back_m=2.8, height_m=1.7)}
FPS = 60.0
TAP_PX = 2.0


def main():
    t_start = time.time()
    rng = np.random.default_rng(7)
    cam = CAMERAS[CAM_NAME]
    deliveries = grid()
    if QUICK:
        deliveries = deliveries[::12]
    rows = []
    for i, d in enumerate(deliveries):
        truth = fly(d)
        clip = CLIPS / f"{CAM_NAME}_{i:03d}.mp4"
        cal = render(truth, cam, clip, fps=FPS)
        n_frames = cal.pop("n_frames")
        for key in ("pitch_corners_px", "stump_quads_px"):
            cal[key] = [{"x": p["x"] + rng.normal(0, TAP_PX), "y": p["y"] + rng.normal(0, TAP_PX)} for p in cal[key]]
        req = {"segment": {"start_ms": 0, "end_ms": int(1000 * (n_frames - 1) / FPS)},
               "video": {"rotation_deg": 0},
               "tracking": {"sample_fps": int(FPS), "max_frames": n_frames, "ball_color": "red", "detector": "auto"},
               "calibration": cal, "batsman_handedness": "right"}
        art = Path(tempfile.mkdtemp(prefix="pdrs_exp2_"))
        row = dict(i=i, camera=CAM_NAME, speed_kmh=d.speed_kmh, length_m=d.length_m, line_m=d.line_m,
                   truth=truth_verdict(truth), truth_y_cm=round(truth.stumps[1] * 100, 2),
                   truth_z_cm=round(truth.stumps[2] * 100, 2), n_frames=n_frames)
        try:
            out = run_pipeline(video_path=clip, request_json=req, artifacts_dir=art, progress=None).result
        except Exception as e:                       # noqa: BLE001
            rows.append(dict(row, verdict="error", error=str(e)[:120]))
            print(f"[{i + 1:3d}/{len(deliveries)}] {d.speed_kmh:.0f} km/h L={d.length_m} y={d.line_m:+.2f}  ERROR {e}", flush=True)
            continue
        lbw = out.get("lbw") or {}
        pred = lbw.get("prediction") or {}
        ev = (out.get("events") or {}).get("bounce") or {}
        track = out.get("track") or {}
        verdict = lbw.get("decision") or "no_verdict"
        y, z = pred.get("y_at_stumps_m"), pred.get("z_at_stumps_m")
        rows.append(dict(row, verdict=verdict, n_track=len(track.get("image_points") or []),
                         reproj_px=round(out["calibration"]["quality"]["reproj_error_px"], 2),
                         y_err_cm=None if y is None else round(abs(y - truth.stumps[1]) * 100, 2),
                         z_err_cm=None if z is None else round(abs(z - truth.stumps[2]) * 100, 2),
                         sigma_y_cm=None if pred.get("sigma_y_m") is None else round(pred["sigma_y_m"] * 100, 2),
                         sigma_z_cm=None if pred.get("sigma_z_m") is None else round(pred["sigma_z_m"] * 100, 2),
                         contact_x_err_cm=None if ev.get("x_m") is None else round(abs(ev["x_m"] - truth.contact[0]) * 100, 2),
                         contact_y_err_cm=None if ev.get("y_m") is None else round(abs(ev["y_m"] - truth.contact[1]) * 100, 2),
                         speed_err_kmh=None if not out.get("metrics") else round(abs(out["metrics"]["speed_kmh"] - truth.release_speed_kmh), 1),
                         warnings=" | ".join(out["diagnostics"]["warnings"])[:200]))
        r = rows[-1]
        print(f"[{i + 1:3d}/{len(deliveries)}] {d.speed_kmh:.0f} km/h L={d.length_m} y={d.line_m:+.2f}  "
              f"truth={r['truth']:<12} got={verdict:<12} y={r['y_err_cm']} z={r['z_err_cm']} track={r['n_track']}", flush=True)

    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in rows[0], k))
    with open(os.path.join(OUT, f"exp2_rendered_{CAM_NAME}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader(); w.writerows(rows)
    agree = sum(1 for r in rows if r["verdict"] == r["truth"])
    false_out = sum(1 for r in rows if r["verdict"] == "out" and r["truth"] != "out")
    print(f"agreement {agree}/{len(rows)}  false out {false_out}  ({time.time() - t_start:.0f}s)")
    with open(os.path.join(OUT, f"exp2_config_{CAM_NAME}.json"), "w") as fh:
        json.dump({"camera": CAMERAS[CAM_NAME].__dict__, "fps": FPS, "tap_px": TAP_PX, "n": len(rows),
                   "seconds": round(time.time() - t_start, 1)}, fh, indent=2)


if __name__ == "__main__":
    main()
