#!/usr/bin/env python
"""Experiment 3: real hand-held net clips.

No metric ground truth exists for these, so two things are measured that do not need it:
the pipeline's output with its own stated uncertainty, and its repeatability. For the
repeatability test each clip is analysed three times: on all sampled frames, on the even
frames only and on the odd frames only. Two half-rate analyses see disjoint detections of
the same delivery; the spread between their stump-plane predictions is an empirical
precision that can be compared with the propagated sigma.

Usage:  server/.venv/bin/python paper/experiments/exp3_real.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = Path(HERE).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "scripts"))
from app.pipeline.process_job import run_pipeline   # noqa: E402
from real_clip import CLIPS, build_request           # noqa: E402

OUT = os.path.join(HERE, "raw")
os.makedirs(OUT, exist_ok=True)

def run(name, req, parity):
    """parity: None for every frame, 0 or 1 to keep only even or odd sampled frames."""
    req = json.loads(json.dumps(req))
    if parity is not None:
        fps = int(req["tracking"]["sample_fps"])
        # sample at half rate, offset by one frame for the odd set
        req["tracking"]["sample_fps"] = fps // 2
        req["segment"]["start_ms"] = int(req["segment"]["start_ms"]) + (parity * 1000 // fps)
    art = Path(tempfile.mkdtemp(prefix=f"pdrs_real_{name}_"))
    out = run_pipeline(video_path=ROOT / f"{name}.mp4", request_json=req, artifacts_dir=art, progress=None).result
    lbw = out.get("lbw") or {}
    pred = lbw.get("prediction") or {}
    ev = out.get("events") or {}
    model = (out.get("world_trajectory") or {}).get("model") or {}
    residual = out["diagnostics"].get("fit_rms_px")
    return dict(clip=name, frames="all" if parity is None else ("even" if parity == 0 else "odd"),
                reproj_px=round(out["calibration"]["quality"]["reproj_error_px"], 2),
                n_track=len(out["track"]["image_points"]),
                length_m=round(out["calibration"]["pose"]["pitch_length_m"], 1),
                discard_px=None if residual is None else round(residual, 1),
                verdict=lbw.get("decision"), reason=lbw.get("reason"),
                y_cm=None if pred.get("y_at_stumps_m") is None else round(pred["y_at_stumps_m"] * 100, 1),
                z_cm=None if pred.get("z_at_stumps_m") is None else round(pred["z_at_stumps_m"] * 100, 1),
                sigma_y_cm=None if pred.get("sigma_y_m") is None else round(pred["sigma_y_m"] * 100, 1),
                sigma_z_cm=None if pred.get("sigma_z_m") is None else round(pred["sigma_z_m"] * 100, 1),
                bounce_x_m=None if not ev.get("bounce") or ev["bounce"].get("x_m") is None else round(ev["bounce"]["x_m"], 2),
                bounce_y_cm=None if not ev.get("bounce") or ev["bounce"].get("y_m") is None else round(ev["bounce"]["y_m"] * 100, 1),
                bounce_observed=model.get("bounce_observed"),
                restitution=None if model.get("restitution") is None else round(model["restitution"], 2),
                speed_kmh=(out.get("metrics") or {}).get("speed_kmh"),
                warnings=" | ".join(out["diagnostics"]["warnings"])[:200])


def main():
    rows = []
    for name in CLIPS:
        req = build_request(name)
        for parity in (None, 0, 1):
            try:
                r = run(name, req, parity)
            except Exception as e:                    # noqa: BLE001
                r = dict(clip=name, frames="all" if parity is None else parity, verdict="error", reason=str(e)[:120])
            rows.append(r)
            print({k: v for k, v in r.items() if k != "warnings"}, flush=True)
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in rows[0], k))
    with open(os.path.join(OUT, "exp3_real.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader(); w.writerows(rows)
    # repeatability: spread between the two half-rate analyses against the stated sigma
    for name in CLIPS:
        halves = [r for r in rows if r["clip"] == name and r["frames"] in ("even", "odd") and r.get("y_cm") is not None]
        full = next((r for r in rows if r["clip"] == name and r["frames"] == "all"), None)
        if len(halves) == 2 and full:
            dy = abs(halves[0]["y_cm"] - halves[1]["y_cm"]); dz = abs(halves[0]["z_cm"] - halves[1]["z_cm"])
            print(f"{name}: even/odd spread y={dy:.1f} cm z={dz:.1f} cm  vs stated sigma y={full['sigma_y_cm']} z={full['sigma_z_cm']}")
    print("wrote exp3_real.csv")


if __name__ == "__main__":
    main()
