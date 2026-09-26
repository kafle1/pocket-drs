"""Experiment 9: frame rate, and what the app's frame sampler does at each rate.

150 deliveries from exp1's physics world (drag, swing, friction, turn, restitution 0.4-0.7),
1 px centres, 10 % radius, 5 % dropout, 2 px taps, 0.5 ms frame-time jitter, reference
camera. Each delivery is replayed at 30, 60, 120 and 240 fps with the same taps and the
same release time in the video, under four samplers:
  timestamps       every frame, labelled with its own time
  fixed @60        process_job asks for a frame every 1000/60 ms and gets the nearest frame,
                   labelled with its own timestamp; the app sends 60 whatever the video rate
  fixed @fps       the same loop with sample_fps set to the video's own rate
  submitted @60    the code at submission: a request every round(1000/60) = 17 ms, each
                   labelled with the requested time
Reported: stump-plane error, 1-sigma coverage of the pipeline's own sigma, agreement and
umpire's-call rate at the shipped k = 1.

    python exp9_fps.py
"""
from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import time

import numpy as np

from uq import (Effects, fly, REF_CAM, QTY, taps, solve, observe, truth_q, estimate, replace, OUT, save_json,
                verdict, CalibrationError)
from synth import random_delivery

SEED = 909
N = 150
FPS = (30.0, 60.0, 120.0, 240.0)
SAMPLERS = (("timestamps", "exact", 0.0), ("fixed @60", "fixed", 60.0), ("fixed @fps", "fixed", None),
            ("submitted @60", "submitted", 60.0))
EFF = Effects(tap_px=2.0, noise_px=1.0, radius_noise=0.10, dropout=0.05, jitter_s=5e-4)


def job(args):
    i, fps, name = args
    import cv2; cv2.setNumThreads(1)
    rng = np.random.default_rng([SEED, i])
    d = random_delivery(rng, physics=True)
    v0 = 0.3 + rng.uniform(0.0, 1.0 / 30.0)
    smp, sfps = next((s, f) for n, s, f in SAMPLERS if n == name)
    eff = replace(EFF, fps=fps, sampler=smp, sample_fps=fps if sfps is None else sfps)
    row = dict(i=i, fps=fps, sampler=name, ok=False, bounce=False)
    try:
        tr = fly(d, dt=5e-4)
    except ValueError:
        return row
    pt = REF_CAM.pose()
    xy = taps(pt, eff, np.random.default_rng([SEED, i, 1]))
    try:
        pose = solve(pt, xy)
    except CalibrationError:
        return row
    dets = observe(tr, pt, eff, np.random.default_rng([SEED, i, 2, int(fps)]), v0=v0)
    est = estimate(pose, dets)
    tq = truth_q(tr)
    row.update({f"truth_{q}": tq[q] for q in QTY})
    row["n_dets"] = len(dets)
    if est is None:
        return row
    row.update(ok=True, bounce=est["bounce"])
    for q in QTY:
        row[f"est_{q}"] = est[q]
        row[f"sfit_{q}"] = est["s_" + q]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    t0 = time.time()
    jobs = [(i, f, n) for f in FPS for n, _, _ in SAMPLERS for i in range(N)]
    with mp.get_context("spawn").Pool(a.workers) as pool:
        rows = pool.map(job, jobs, chunksize=2)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(OUT, "exp9_fps.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    zero = {q: 0.0 for q in QTY}
    cells = {}
    for f in FPS:
        for n, _, _ in SAMPLERS:
            rr = [r for r in rows if r["fps"] == f and r["sampler"] == n and r["ok"] and r["bounce"]
                  and r.get("est_y") is not None and r.get("est_crease_y") is not None]
            ent = dict(n=len(rr), median_dets=float(np.median([r["n_dets"] for r in rows if r["fps"] == f and r["sampler"] == n
                                                               and "n_dets" in r])))
            for q in ("y", "z"):
                e = np.array([r[f"est_{q}"] - r[f"truth_{q}"] for r in rr])
                s = np.array([r[f"sfit_{q}"] for r in rr])
                ent[q] = dict(median_abs_mm=float(np.median(np.abs(e)) * 1000), p90_abs_mm=float(np.percentile(np.abs(e), 90) * 1000),
                              mean_mm=float(np.mean(e) * 1000), cov1_fit=float(100 * np.mean(np.abs(e) <= s)))
            v = [(verdict({q: r[f"est_{q}"] for q in QTY}, {q: r[f"sfit_{q}"] for q in QTY}, 1.0),
                  verdict({q: r[f"truth_{q}"] for q in QTY}, zero, 0.0)) for r in rr]
            ent["agree_pct"] = 100 * float(np.mean([x == y for x, y in v])) if v else None
            ent["ump_pct"] = 100 * float(np.mean([x == "umpires_call" for x, _ in v])) if v else None
            cells[f"{f:g}|{n}"] = ent
    save_json("exp9_fps.json", dict(seed=SEED, n=N, cells=cells, workers=a.workers, seconds=round(time.time() - t0, 1)))
    for key, ent in cells.items():
        print(f"{key:22s} n={ent['n']:3d} dets {ent['median_dets']:5.0f} y {ent['y']['median_abs_mm']:6.1f} mm "
              f"z {ent['z']['median_abs_mm']:6.1f} mm cov {ent['y']['cov1_fit']:3.0f}/{ent['z']['cov1_fit']:3.0f} "
              f"agree {ent['agree_pct']:.1f} ump {ent['ump_pct']:.1f}")
    print(f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
