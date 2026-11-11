#!/usr/bin/env python
"""False detections: does a large round object the learned detector fires on reach the verdict?

Renders 8 deliveries of the exp2 grid (all truly not out), runs the production job on each, and
adds one fake 90 px box at confidence 0.95 to the learned detector's output on a run of frames:

  clean    no fake box
  static   fixed near the bottom edge, on the middle half of the frames
  drift    sliding 6 px a frame along the bottom edge, on the middle 3/5 of the frames
  top      fixed near the top edge, on the middle half of the frames

The rendered clips and injected boxes are the only inputs; no real clip is used, so no limit of
the false-detection filter is tuned on the exp3 clips.

Usage:  $PY false_dets.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO / "server"), str(HERE)]
import app.pipeline.process_job as pj                  # noqa: E402
from app.pipeline.reconstruction import BALL_RADIUS_M  # noqa: E402
from synth import Camera, fly, grid, truth_verdict     # noqa: E402
from render import render                              # noqa: E402

WEIGHTS = REPO / "server" / "models" / "cricket_ball.pt"
if not WEIGHTS.exists():
    sys.exit(f"needs the learned detector's weights at {WEIGHTS}")
SCENARIOS = ("clean", "static", "drift", "top")
PICKS = (0, 13, 26, 39, 52, 65, 78, 91)
FAKE_R = 90.0
ctx: dict = {}
log: list = []


def fake_for(scen, k, n):
    """The fake box centre on the k-th of n frames, or None."""
    if scen == "static" and n // 4 <= k < n // 4 + n // 2:
        return 540.0, 1800.0
    if scen == "drift" and n // 5 <= k < n // 5 + (3 * n) // 5:
        return 300.0 + 6.0 * (k - n // 5), 1750.0
    if scen == "top" and n // 4 <= k < n // 4 + n // 2:
        return 540.0, 120.0
    return None


class FakeYolo(pj.YoloDetector):
    def detect(self, frame):
        dets = super().detect(frame)
        f = fake_for(ctx["scen"], ctx["k"], ctx["n"])
        ctx["k"] += 1
        if f is not None:
            dets.insert(0, {"x": f[0], "y": f[1], "radius_px": FAKE_R, "confidence": 0.95, "source": "fake"})
        return dets


pj.YoloDetector = FakeYolo
_orig_track = pj._track


def rec_track(frames, times_ms, detector, *a):
    ctx.update(k=0, n=len(frames), det=type(detector).__name__, times=list(times_ms), call=0)
    out = _orig_track(frames, times_ms, detector, *a)
    ctx["tracks"].append((ctx["det"], out))
    return out


pj._track = rec_track
_orig_drop = pj.drop_impossible


def rec_drop(dets, pose, fps):
    kept = _orig_drop(dets, pose, fps)
    log.append((ctx["times"][ctx["call"]], dets, kept))
    ctx["call"] += 1
    return kept


pj.drop_impossible = rec_drop


def one(clip, req, truth, pose, scen, i):
    log.clear()
    ctx.update(scen=scen, tracks=[])
    out = pj.run_pipeline(video_path=clip, request_json=req, artifacts_dir=Path(tempfile.mkdtemp(prefix="fd_")),
                          progress=None).result
    st = truth.states
    dt = st[1, 0] - st[0, 0]

    def truth_px(t_ms):
        j = int(round(t_ms / 1000.0 / dt))
        if not 0 <= j < len(st):
            return None
        q = pose.project_one(*st[j, 1:4])
        return None if q is None else (q[0], q[1], pose.fx * BALL_RADIUS_M / q[2])

    # a detection is the ball when it sits within its own smear of the true centre
    n = dict(ball=0, ball_dropped=0, fake=0, fake_dropped=0, other=0, other_dropped=0)
    for t, raw, kept in log:
        tp = truth_px(t)
        kept_ids = {id(k) for k in kept}
        for d in raw:
            kind = "fake" if d.get("source") == "fake" else (
                "ball" if tp is not None and np.hypot(d["x"] - tp[0], d["y"] - tp[1]) <= max(10.0, 3.0 * tp[2]) else "other")
            n[kind] += 1
            n[kind + "_dropped"] += id(d) not in kept_ids
    pts = (out.get("track") or {}).get("image_points") or []
    pred = (out.get("lbw") or {}).get("prediction") or {}
    chosen = next((name for name, o in ctx["tracks"] if o is not None
                   and any(p["t_ms"] == o.points[0]["t_ms"] and p["u"] == o.points[0]["u"] for p in pts)), None)
    note = (out["diagnostics"]["warnings"] or [""])[0]
    err = lambda k, a: None if pred.get(k) is None else round(abs(pred[k] - truth.stumps[a]) * 100, 2)
    row = dict(scenario=scen, i=i, truth=truth_verdict(truth), verdict=(out.get("lbw") or {}).get("decision"),
               track_from=chosen, n_track=len(pts), fake_in_track=sum(1 for p in pts if p["radius_px"] == FAKE_R),
               y_err_cm=err("y_at_stumps_m", 1), z_err_cm=err("z_at_stumps_m", 2),
               **{f"{k}_dets": n[k] for k in ("ball", "fake", "other")},
               **{f"{k}_dropped": n[k + "_dropped"] for k in ("ball", "fake", "other")},
               note=note[:80])
    print(json.dumps(row), flush=True)
    return row


def main():
    cam = Camera(end="striker", back_m=2.8, height_m=1.7)
    pose = cam.pose()
    rng = np.random.default_rng(7)
    clips = Path(tempfile.mkdtemp(prefix="fd_clips_"))
    jobs = []
    for i, d in enumerate(grid()):
        if i > max(PICKS):
            break
        truth = fly(d)
        noise = [(rng.normal(0, 2.0), rng.normal(0, 2.0)) for _ in range(12)]
        if i not in PICKS:
            continue
        clip = clips / f"striker_ref_{i:03d}.mp4"
        cal = render(truth, cam, clip, fps=60.0)
        n_frames = cal.pop("n_frames")
        cal["pitch_corners_px"] = [{"x": p["x"] + nx, "y": p["y"] + ny} for p, (nx, ny) in zip(cal["pitch_corners_px"], noise[:4])]
        cal["stump_quads_px"] = [{"x": p["x"] + nx, "y": p["y"] + ny} for p, (nx, ny) in zip(cal["stump_quads_px"], noise[4:])]
        req = {"segment": {"start_ms": 0, "end_ms": int(1000 * (n_frames - 1) / 60.0)}, 
               "tracking": {"sample_fps": 60, "max_frames": n_frames, "ball_color": "red"},
               "calibration": cal, "batsman_handedness": "right"}
        jobs.append((clip, req, truth, i))
    rows = [one(clip, req, truth, pose, scen, i) for scen in SCENARIOS for clip, req, truth, i in jobs]
    with open(HERE / "raw" / "false_dets_filtered.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {s: {"correct": sum(r["verdict"] == r["truth"] for r in rows if r["scenario"] == s),
                   "clips": sum(r["scenario"] == s for r in rows),
                   "fake_in_track": sum(r["fake_in_track"] for r in rows if r["scenario"] == s)} for s in SCENARIOS}
    meta = dict(picks=PICKS, fake_radius_px=FAKE_R,
                weights_sha1=hashlib.sha1(WEIGHTS.read_bytes()).hexdigest(), summary=summary)
    (HERE / "raw" / "false_dets_filtered.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
