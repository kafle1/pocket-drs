#!/usr/bin/env python
"""Experiment 1: reconstruction accuracy under controlled measurement error.

Random deliveries are projected through a known camera, corrupted with detection noise,
and handed to the estimator. Because the generating trajectory is known exactly, every
error is absolute. The sweep separates the effects a real clip mixes together: pixel
noise on the ball centre, frame rate, calibration tap error, dropped frames, the camera's
position, and physical effects the estimator does not model (drag, swing, friction, spin).

Two estimators run on identical detections:
  anchored   the bounce-anchored two-parabola fit (this paper)
  parabola   the single gravity parabola with the apparent-size cue, in the line of
             Ribnick et al. (2009), which is what a monocular method without a contact
             constraint can do

Usage:  server/.venv/bin/python paper/experiments/exp1_geometry.py [--quick]
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from synth import (Camera, Delivery, calibration_taps, fly, observe, random_delivery,   # noqa: E402
                   truth_verdict, CREASE_X)
from app.pipeline.reconstruction import (reconstruct, predict_stump_plane, bounce_sigma,  # noqa: E402
                                         _linear_parabola, _fit_flight, _flight_as_trajectory,
                                         _flight_covariance, Reconstruction)
from app.pipeline.decision import decide                                                # noqa: E402

OUT = os.path.join(HERE, "raw")
os.makedirs(OUT, exist_ok=True)
QUICK = "--quick" in sys.argv
N = 60 if QUICK else 400

BASE = dict(fps=60.0, noise_px=1.0, radius_noise=0.10, dropout=0.05, tap_px=2.0, physics=True)
SWEEPS = {
    "noise_px": [0.0, 0.5, 1.0, 2.0, 3.0, 5.0],
    "fps": [30.0, 60.0, 120.0, 240.0],
    "tap_px": [0.0, 2.0, 4.0, 8.0, 12.0],
    "dropout": [0.0, 0.1, 0.25, 0.4],
    "physics": [False, True],
}
CAMERAS = {
    "striker_low": Camera(end="striker", back_m=2.8, height_m=1.2),
    "striker_ref": Camera(end="striker", back_m=2.8, height_m=1.7),
    "striker_high": Camera(end="striker", back_m=4.0, height_m=2.6),
    "striker_side": Camera(end="striker", back_m=2.8, height_m=1.7, offset_m=1.5),
    "bowler_ref": Camera(end="bowler", back_m=2.8, height_m=1.7),
    "bowler_side": Camera(end="bowler", back_m=4.0, height_m=2.0, offset_m=2.0),
}


def parabola_estimate(pose, dets) -> Reconstruction | None:
    dets = sorted(dets)
    t0 = dets[0][0]
    dets = [(d[0] - t0, *d[1:]) for d in dets]
    th0 = _linear_parabola(pose, dets)
    if th0 is None:
        return None
    fit = _fit_flight(pose, dets, th0, f_scale=2.0, radius_weight=0.3)
    if fit is None:
        return None
    theta, cov6, rms = fit
    return Reconstruction(_flight_as_trajectory(theta, pose), _flight_covariance(theta, cov6, pose),
                          rms, len(dets), 0, [])


def evaluate(rec, truth, pose, k=1.0):
    """Errors and verdict for one reconstruction."""
    pred = predict_stump_plane(rec) if rec is not None else None
    if pred is None:
        return dict(ok=False, verdict="no_verdict", **{f"verdict_k{kk:g}": "no_verdict" for kk in (0.0, 0.5, 1.5, 2.0)})
    tr = rec.trajectory
    sx, sy = bounce_sigma(rec)
    crease = tr.position(np.array([tr.t_b + (CREASE_X - tr.x_b) / tr.v_post[0]]))[0] if abs(tr.v_post[0]) > 1e-6 else None
    v = decide(leg_sign=1.0,
               pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=sy,
               impact_y=float(crease[1]) if crease is not None else None, impact_sigma=pred.sigma_y,
               stump_y=pred.y, stump_z=pred.z, sigma_y=pred.sigma_y, sigma_z=pred.sigma_z, k=k)
    # the same decision at other widenings of the uncertainty band, for the operating curve
    by_k = {}
    for kk in (0.0, 0.5, 1.5, 2.0):
        by_k[f"verdict_k{kk:g}"] = decide(leg_sign=1.0,
                                          pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=sy,
                                          impact_y=float(crease[1]) if crease is not None else None, impact_sigma=pred.sigma_y,
                                          stump_y=pred.y, stump_z=pred.z, sigma_y=pred.sigma_y, sigma_z=pred.sigma_z, k=kk).decision
    cx = np.nan if not np.isfinite(truth.contact[0]) else abs(tr.x_b - truth.contact[0]) * 100
    cy = np.nan if not np.isfinite(truth.contact[0]) else abs(tr.y_b - truth.contact[1]) * 100
    speed = float(np.linalg.norm(tr.velocity(0.0))) * 3.6
    return dict(ok=True, verdict=v.decision, **by_k, bounce_observed=tr.bounce_observed,
                y_err_cm=abs(pred.y - truth.stumps[1]) * 100, z_err_cm=abs(pred.z - truth.stumps[2]) * 100,
                sigma_y_cm=pred.sigma_y * 100, sigma_z_cm=pred.sigma_z * 100,
                contact_x_err_cm=cx, contact_y_err_cm=cy,
                speed_err_kmh=abs(speed - truth.release_speed_kmh), rms_px=rec.rms_px,
                restitution=tr.restitution)


def run_cell(name, cam_name, cfg, n, seed):
    rng = np.random.default_rng(seed)
    cam = CAMERAS[cam_name]
    pose_true = cam.pose()
    rows = []
    for i in range(n):
        d = random_delivery(rng, physics=cfg["physics"])
        try:
            truth = fly(d)
        except ValueError:
            continue
        if cfg["tap_px"] > 0:
            pose, _, _ = calibration_taps(pose_true, noise_px=cfg["tap_px"], rng=rng)
        else:
            pose = pose_true
        dets = observe(truth, pose_true, fps=cfg["fps"], noise_px=cfg["noise_px"],
                       radius_noise=cfg["radius_noise"], dropout=cfg["dropout"], rng=rng)
        if len(dets) < 6:
            continue
        gt = truth_verdict(truth)
        base = dict(sweep=name, camera=cam_name, **{k: cfg[k] for k in BASE}, i=i,
                    speed_kmh=round(d.speed_kmh, 1), length_m=round(d.length_m, 2), line_m=round(d.line_m, 3),
                    restitution_true=round(d.restitution, 3), n_dets=len(dets), truth=gt,
                    calib_reproj_px=round(pose.reproj_error_px, 2))
        for est_name, rec in (("anchored", reconstruct(pose, dets)), ("parabola", parabola_estimate(pose, dets))):
            r = evaluate(rec, truth, pose)
            rows.append(dict(base, estimator=est_name, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}))
    return rows


def main():
    t_start = time.time()
    rows = []
    seed = 0
    # one-factor sweeps around the reference camera
    for key, values in SWEEPS.items():
        for val in values:
            cfg = dict(BASE); cfg[key] = val
            seed += 1
            cell = run_cell(f"{key}={val}", "striker_ref", cfg, N, seed)
            rows.extend(cell)
            _report(cell)
    # camera placements at the reference noise
    for cam_name in CAMERAS:
        seed += 1
        cell = run_cell(f"camera={cam_name}", cam_name, dict(BASE), N, seed)
        rows.extend(cell)
        _report(cell)

    with open(os.path.join(OUT, "exp1_geometry.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(OUT, "exp1_config.json"), "w") as fh:
        json.dump({"n_per_cell": N, "base": BASE, "sweeps": SWEEPS,
                   "cameras": {k: v.__dict__ for k, v in CAMERAS.items()},
                   "seconds": round(time.time() - t_start, 1)}, fh, indent=2)
    print(f"wrote {len(rows)} rows to raw/exp1_geometry.csv in {time.time() - t_start:.0f}s")


def _report(cell):
    if not cell:
        return
    name, cam = cell[0]["sweep"], cell[0]["camera"]
    for est in ("anchored", "parabola"):
        rs = [r for r in cell if r["estimator"] == est]
        ok = [r for r in rs if r["ok"]]
        agree = sum(1 for r in rs if r["verdict"] == r["truth"])
        false_out = sum(1 for r in rs if r["verdict"] == "out" and r["truth"] != "out")
        ump = sum(1 for r in rs if r["verdict"] == "umpires_call")
        y = np.median([r["y_err_cm"] for r in ok]) if ok else float("nan")
        z = np.median([r["z_err_cm"] for r in ok]) if ok else float("nan")
        print(f"{name:<22s} {cam:<13s} {est:<9s} n={len(rs):3d} ok={len(ok):3d} "
              f"agree={agree/len(rs)*100:5.1f}% false_out={false_out:2d} ump={ump:3d} "
              f"median y={y:5.1f}cm z={z:5.1f}cm", flush=True)


if __name__ == "__main__":
    main()
