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
             Ribnick et al. (2009), fitted across the whole track, bounce included
  unanchored the same split as anchored, but a free six-parameter parabola either side of it
             (the side fits _anchor_candidates already makes), so the only thing missing
             is the contact pinned to the ground plane

Every cell sees the same deliveries: delivery i draws its trajectory, tap noise and detection
noise from its own streams seeded by (seed, i), so sweep rows differ only in the factor swept
(common random numbers) and the output does not depend on the worker count. --ablation runs the calibration ablations instead (focal length
handed to the solver, pitch length left free, a 70 degree camera) into exp1_ablation.csv.

Usage:  server/.venv/bin/python paper/experiments/exp1_geometry.py [--quick] [--ablation] [--workers 8]
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import csv
import json
import multiprocessing as mp
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from synth import (Camera, calibration_taps, fly, observe, random_delivery,   # noqa: E402
                   truth_verdict)
from app.pipeline.reconstruction import (reconstruct, predict_stump_plane, bounce_sigma, position_sigma,  # noqa: E402
                                         _linear_parabola, _fit_flight, flight_trajectory,
                                         _flight_covariance, Reconstruction, Trajectory, find_bounce_split,
                                         _numeric_jacobian, GRAVITY, BALL_RADIUS_M, LEATHER)
from app.pipeline.decision import decide                                                # noqa: E402
from app.pipeline.calibration import CalibrationError                                   # noqa: E402

cv2.setNumThreads(1)

OUT = os.path.join(HERE, "raw")
os.makedirs(OUT, exist_ok=True)
QUICK = "--quick" in sys.argv
ABLATION = "--ablation" in sys.argv
WORKERS = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else max(1, (os.cpu_count() or 2) - 1)
N = 60 if QUICK else 400
# solver arguments per calibration variant; None means hand it the true focal length
CALIB = {"app": {}, "pin_fov": None, "free_length": {"pitch_length_m": None}}

BASE = dict(fps=60.0, noise_px=1.0, radius_noise=0.10, dropout=0.05, tap_px=2.0, physics=True)
K_SHIPPED = 1.0
K_VALUES = (0.0, 0.5, 1.0, 1.5, 2.0)
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
    return Reconstruction(flight_trajectory(theta), _flight_covariance(theta, cov6), rms, [])


def _side_fit(pose, side):
    """Free parabola on one side of the split, timed from that side's first frame so the
    solver's bounds on the start position stay physical."""
    if len(side) < 3:
        return None
    ts = side[0][0]
    local = [(d[0] - ts, *d[1:]) for d in side]
    th0 = _linear_parabola(pose, local)
    fit = None if th0 is None else _fit_flight(pose, local, th0, f_scale=2.0, radius_weight=0.3)
    return None if fit is None else (*fit, ts)


def _unanchored_params(th12, ts_pre, ts_post, t_split):
    """Two free parabolas (pre, post; each x0,y0,z0,vx,vy,vz at its side's first frame) in
    the bounce parameterisation: the contact is where the post arc meets z = R, earlier root."""
    pre, post = th12[:6], th12[6:]
    a, b, c = -0.5 * GRAVITY, post[5], post[2] - BALL_RADIUS_M
    disc = b * b - 4 * a * c
    tau = min((-b + sgn * np.sqrt(disc)) / (2 * a) for sgn in (1.0, -1.0)) if disc >= 0 else t_split - ts_post
    t_b = ts_post + tau
    x_b, y_b = post[0] + post[3] * tau, post[1] + post[4] * tau
    v_post = np.array([post[3], post[4], post[5] - GRAVITY * tau])
    tp = t_b - ts_pre
    v_pre = np.array([pre[3], pre[4], pre[5] - GRAVITY * tp])
    e = -v_post[2] / v_pre[2] if v_pre[2] < -0.05 and v_post[2] > 0 else LEATHER.restitution[1]
    return np.array([t_b, x_b, y_b, *v_pre, v_post[0], v_post[1], e])


def unanchored_estimate(pose, dets) -> Reconstruction | None:
    """Same split as the anchored fit, no anchor. Without a usable split, too few frames
    after it, or a fit that diverges, it falls back to the single parabola."""
    dets = sorted(dets)
    t0 = dets[0][0]
    dets = [(d[0] - t0, *d[1:]) for d in dets]
    split = find_bounce_split(dets)
    fits = None
    if split is not None:
        k, t_split = split[0], split[1]
        f_pre, f_post = _side_fit(pose, dets[:k]), _side_fit(pose, dets[k:])
        if f_pre is not None and f_post is not None:
            fits = (f_pre, f_post, t_split)
    if fits is None:
        return parabola_estimate(pose, [(d[0] + t0, *d[1:]) for d in dets])
    (th_pre, c_pre, rms_pre, ts_pre), (th_post, c_post, rms_post, ts_post), t_split = fits
    th12 = np.concatenate([th_pre, th_post])
    th9 = _unanchored_params(th12, ts_pre, ts_post, t_split)
    # a contact off the pitch or outside the track is a diverged fit; fall back, as a careful
    # unanchored method would, rather than score it
    if (not np.all(np.isfinite(th9)) or not (-2.0 <= th9[1] <= pose.pitch_length_m + 2.0)
            or abs(th9[2]) > 2.0 or not (dets[0][0] <= th9[0] <= dets[-1][0])):
        return parabola_estimate(pose, [(d[0] + t0, *d[1:]) for d in dets])
    cov12 = np.zeros((12, 12)); cov12[:6, :6] = c_pre; cov12[6:, 6:] = c_post
    J = _numeric_jacobian(lambda th: _unanchored_params(th, ts_pre, ts_post, t_split), th12)
    v_pre = th9[3:6]
    tr = Trajectory(float(th9[0]), float(th9[1]), float(th9[2]), v_pre,
                    np.array([th9[6], th9[7], -th9[8] * v_pre[2]]), True)
    return Reconstruction(tr, J @ cov12 @ J.T, max(rms_pre, rms_post), [])


def evaluate(rec, truth, t_last):
    """Errors and verdict for one reconstruction; impact is read at the last detection (t_last, in
    the fit's time base), as the app does."""
    pred = predict_stump_plane(rec) if rec is not None else None
    if pred is None:
        return dict(ok=False, verdict="no_verdict", **{f"verdict_k{kk:g}": "no_verdict" for kk in K_VALUES if kk != K_SHIPPED},
                    bounce_observed=None, y_err_mm=None, z_err_mm=None, sigma_y_mm=None, sigma_z_mm=None,
                    contact_x_err_mm=None, contact_y_err_mm=None, speed_err_kmh=None, rms_px=None,
                    restitution=None, est_y_mm=None, est_z_mm=None, est_pitch_y_mm=None, pitch_sigma_mm=None,
                    est_impact_y_mm=None, impact_sigma_mm=None)
    tr = rec.trajectory
    _, sy = bounce_sigma(rec)
    impact = tr.position(np.array([t_last]))[0]
    impact_sigma = position_sigma(rec, t_last)[1]
    # the verdict at the shipped band widening and at the others, for the operating curve
    verdicts = {}
    for kk in K_VALUES:
        verdicts[kk] = decide(leg_sign=1.0,
                              pitch_y=float(tr.y_b) if tr.bounce_observed else None, pitch_sigma=sy,
                              impact_y=float(impact[1]), impact_sigma=impact_sigma,
                              stump_y=pred.y, stump_z=pred.z, sigma_y=pred.sigma_y, sigma_z=pred.sigma_z, k=kk).decision
    by_k = {f"verdict_k{kk:g}": v for kk, v in verdicts.items() if kk != K_SHIPPED}
    cx = np.nan if not np.isfinite(truth.contact[0]) else abs(tr.x_b - truth.contact[0]) * 1000
    cy = np.nan if not np.isfinite(truth.contact[0]) else abs(tr.y_b - truth.contact[1]) * 1000
    speed = float(np.linalg.norm(tr.velocity(0.0))) * 3.6
    return dict(ok=True, verdict=verdicts[K_SHIPPED], **by_k, bounce_observed=tr.bounce_observed,
                y_err_mm=abs(pred.y - truth.stumps[1]) * 1000, z_err_mm=abs(pred.z - truth.stumps[2]) * 1000,
                sigma_y_mm=pred.sigma_y * 1000, sigma_z_mm=pred.sigma_z * 1000,
                contact_x_err_mm=cx, contact_y_err_mm=cy,
                speed_err_kmh=abs(speed - truth.release_speed_kmh), rms_px=rec.rms_px,
                restitution=tr.restitution, est_y_mm=pred.y * 1000, est_z_mm=pred.z * 1000,
                est_pitch_y_mm=tr.y_b * 1000 if tr.bounce_observed else None, pitch_sigma_mm=sy * 1000,
                est_impact_y_mm=impact[1] * 1000, impact_sigma_mm=impact_sigma * 1000)


def run_cell(name, cam_name, cfg, n, seed, cam=None):
    cam = cam or CAMERAS[cam_name]
    calib = cfg.get("calib", "app")
    pose_true = cam.pose()
    rows = []
    for i in range(n):
        # separate streams, so a factor that skips or adds draws (taps off, frame rate) cannot shift the others
        rng_d, rng_t, rng_o = (np.random.default_rng([seed, i, k]) for k in range(3))
        d = random_delivery(rng_d, physics=cfg["physics"])
        try:
            truth = fly(d)
        except ValueError:
            continue
        if cfg["tap_px"] > 0:
            kw = CALIB[calib] if CALIB[calib] is not None else {"fov_deg": cam.fov_deg}
            try:
                pose, _, _ = calibration_taps(pose_true, noise_px=cfg["tap_px"], rng=rng_t, **kw)
            except CalibrationError:
                pose = None
        else:
            pose = pose_true
        dets = observe(truth, pose_true, fps=cfg["fps"], noise_px=cfg["noise_px"],
                       radius_noise=cfg["radius_noise"], dropout=cfg["dropout"], rng=rng_o)
        if pose is None or len(dets) < 6:
            continue
        gt = truth_verdict(truth)
        base = dict(sweep=name, camera=cam_name, **{k: cfg[k] for k in BASE}, i=i,
                    speed_kmh=round(d.speed_kmh, 1), length_m=round(d.length_m, 2), line_m=round(d.line_m, 3),
                    restitution_true=round(d.restitution, 3), n_dets=len(dets), truth=gt,
                    calib_reproj_px=round(pose.reproj_error_px, 2), calib=calib,
                    calib_fov_deg=round(pose.fov_deg, 3), calib_focal_err_pct=round((pose.fx / pose_true.fx - 1) * 100, 3),
                    calib_length_m=round(pose.pitch_length_m, 3), calib_used_creases=pose.used_creases,
                    truth_y_mm=round(truth.stumps[1] * 1000, 3), truth_z_mm=round(truth.stumps[2] * 1000, 3),
                    truth_impact_y_mm=round(truth.crease[1] * 1000, 3),
                    truth_contact_x_m=round(float(truth.contact[0]), 4) if np.isfinite(truth.contact[0]) else None,
                    truth_contact_y_mm=round(float(truth.contact[1]) * 1000, 3) if np.isfinite(truth.contact[0]) else None)
        for est_name, rec in (("anchored", reconstruct(pose, dets)), ("parabola", parabola_estimate(pose, dets)),
                              ("unanchored", unanchored_estimate(pose, dets))):
            r = evaluate(rec, truth, dets[-1][0] - dets[0][0])
            rows.append(dict(base, estimator=est_name, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}))
    return rows


def _cell(args):
    return run_cell(*args)


def main():
    t_start = time.time()
    cells, seed = [], 1
    if ABLATION:
        # paired: the three calibrations see the same deliveries and the same tap noise
        for calib in CALIB:
            cells.append((f"calib={calib}", "striker_ref", dict(BASE, calib=calib), N, 101))
        fov70 = Camera(end="striker", back_m=2.8, height_m=1.7, fov_deg=70.0)
        for calib in ("app", "pin_fov"):
            cells.append((f"fov70 calib={calib}", "striker_fov70", dict(BASE, calib=calib), N, 102, fov70))
    else:
        # the reference once, then one-factor sweeps and camera placements around it; a sweep
        # value equal to the reference is that same run, not a second copy of it
        cells.append(("reference", "striker_ref", dict(BASE), N, seed))
        for key, values in SWEEPS.items():
            for val in values:
                if val != BASE[key]:
                    cfg = dict(BASE); cfg[key] = val
                    cells.append((f"{key}={val}", "striker_ref", cfg, N, seed))
        for cam_name in CAMERAS:
            if cam_name != "striker_ref":
                cells.append((f"camera={cam_name}", cam_name, dict(BASE), N, seed))
    rows = []
    with mp.get_context("spawn").Pool(WORKERS) as pool:
        for cell in pool.imap(_cell, cells):          # imap keeps the cell order
            rows.extend(cell)
            _report(cell)

    stem = "exp1_ablation" if ABLATION else "exp1_geometry"
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(OUT, f"{stem}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    cfg_name = "exp1_ablation_config.json" if ABLATION else "exp1_config.json"
    with open(os.path.join(OUT, cfg_name), "w") as fh:
        json.dump({"n_per_cell": N, "base": BASE, "sweeps": SWEEPS if not ABLATION else None,
                   "cells": [c[0] for c in cells],
                   "cameras": {k: v.__dict__ for k, v in CAMERAS.items()},
                   "workers": WORKERS, "seconds": round(time.time() - t_start, 1)}, fh, indent=2)
    print(f"wrote {len(rows)} rows to raw/{stem}.csv in {time.time() - t_start:.0f}s")


def _report(cell):
    if not cell:
        return
    name, cam = cell[0]["sweep"], cell[0]["camera"]
    for est in ("anchored", "parabola", "unanchored"):
        rs = [r for r in cell if r["estimator"] == est]
        ok = [r for r in rs if r["ok"]]
        agree = sum(1 for r in rs if r["verdict"] == r["truth"])
        false_out = sum(1 for r in rs if r["verdict"] == "out" and r["truth"] != "out")
        ump = sum(1 for r in rs if r["verdict"] == "umpires_call")
        y = np.median([r["y_err_mm"] for r in ok]) if ok else float("nan")
        z = np.median([r["z_err_mm"] for r in ok]) if ok else float("nan")
        print(f"{name:<22s} {cam:<13s} {est:<9s} n={len(rs):3d} ok={len(ok):3d} "
              f"agree={agree/len(rs)*100:5.1f}% false_out={false_out:2d} ump={ump:3d} "
              f"median y={y:5.0f}mm z={z:5.0f}mm", flush=True)


if __name__ == "__main__":
    main()
