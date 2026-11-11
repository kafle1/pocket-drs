"""Experiment 4: a JCGM 100 uncertainty budget for the stump-plane crossing.

For one representative delivery, and then for a sample of random ones, every input the
estimator takes on trust gets a row: its standard uncertainty u(x), the sensitivity c of
the crossing to it, and its contribution u_i to the lateral and vertical crossing.

  vector inputs (taps, ball centres, frame times): u_i = sigma * ||J||, J by one-sided
      differences of the full calibration + fit, step = sigma.
  distributed inputs (rolling shutter, lens distortion, frame rate, pitch and wicket
      dimensions, bails, flight physics): u_i = RMS over the input's distribution of the
      change in error from the estimator's nominal assumption, by Gauss-Legendre
      quadrature and averaged over frame phases. An uncorrected offset therefore counts in
      full (JCGM 100 F.2.4.5). c is the least-squares slope of that change.
  physics rows compare errors (estimate - truth), since the truth moves with the physics.

    python exp4_budget.py            # representative delivery + 100 random deliveries
    python exp4_budget.py --quick    # 10 random deliveries
"""
from __future__ import annotations

import argparse
import csv
import math
import multiprocessing as mp
import os
import time
from functools import lru_cache

import numpy as np

from uq import (Effects, Delivery, fly, REF_CAM, QTY, RATE_TEST5, taps, solve, observe, truth_q, estimate,
                qvec, forced_split, replace, OUT, save_json, CalibrationError)
from app.pipeline import reconstruction as recon
from synth import random_delivery

SEED = 404
REP = Delivery(speed_kmh=120.0, length_m=6.0, line_m=-0.10)   # good length on the off-stump line
FPS = 60.0
T = 1.0 / FPS
TAP_PX, CENTRE_PX, JITTER_S = 2.0, 1.0, 5e-4
DEG = math.pi / 180

# (name, where, field, lo, hi, nominal, type note). where: eff = Effects field, dlv = Delivery field
DIST_ROWS = [
    ("frame rate 59.80 vs 60 Hz", "eff", "rate_ratio", RATE_TEST5, 1.0, 1.0,
     "B: container rate over timestamp rate, U[0.99673, 1] (test5.mp4)"),
    ("rolling shutter, uncorrected", "eff", "rs_s", -0.030, 0.030, 0.0,
     "B: readout 0-30 ms, either direction (assumed)"),
    ("lens distortion", "eff", "distortion", -0.01, 0.01, 0.0,
     "B: +-1 % radial at the corner (assumed)"),
    ("pitch length L", "eff", "dL", -0.05, 0.05, 0.0, "B: +-5 cm marking, rectangular"),
    ("stump height H", "eff", "dH", -0.01, 0.01, 0.0, "B: +-1 cm set depth"),
    ("wicket half-width w", "eff", "dw", -0.0025, 0.0025, 0.0, "B: +-2.5 mm stump spacing"),
    ("bails tapped as top", "eff", "top_tap", 0.0, 0.0127, 0.0, "B: 0-1.27 cm, Law 8.3.1, uncorrected"),
    ("restitution e", "dlv", "restitution", 0.40, 0.70, 0.55, "B: model, U[0.40, 0.70] (James et al. 2004 pitch range)"),
    ("drag Cd", "dlv", "cd", 0.35, 0.55, 0.0, "B: model, U[0.35, 0.55] (Mehta 2005), not modelled"),
    ("swing Cs", "dlv", "cs", -0.30, 0.30, 0.0, "B: model, U[-0.3, 0.3] (Mehta 2005), not modelled"),
    ("seam deviation", "dlv", "seam", -2.0, 2.0, 0.0, "B: model, U[-2, 2] deg off the seam"),
    ("friction at contact", "dlv", "friction", 0.05, 0.20, 0.10, "B: model, U[0.05, 0.20] speed loss"),
]


@lru_cache(maxsize=None)
def truth_of(d: Delivery):
    return fly(d, dt=5e-4)


@lru_cache(maxsize=None)
def pose_of(key):
    eff = Effects(**dict(key))
    return solve(REF_CAM.pose(), taps(REF_CAM.pose(), eff, None))


def geo_key(eff):
    return tuple((k, getattr(eff, k)) for k in ("dL", "dH", "dw", "top_tap", "distortion"))


def apply(d: Delivery, field, x):
    """Delivery with one physics input set. Seam is an angle turned into a lateral kick."""
    if field == "cd":
        return replace(d, drag=x > 0, cd=x if x > 0 else d.cd)
    if field == "seam":
        tr = truth_of(d)
        i = max(2, int(np.searchsorted(tr.states[:, 0], tr.contact_t)))      # last two states before contact
        vx = abs(tr.states[i - 1, 1] - tr.states[i - 2, 1]) / (tr.states[i - 1, 0] - tr.states[i - 2, 0])
        return replace(d, turn_ms=math.tan(x * DEG) * (1.0 - d.friction) * vx)
    return replace(d, **{field: x})


def err(d: Delivery, eff: Effects, v0: float, dets=None, pose=None) -> np.ndarray:
    """Estimate minus truth for the four measurands, noise-free unless dets are given."""
    tr = truth_of(d)
    try:
        pose = pose or pose_of(geo_key(eff))
    except CalibrationError:
        return np.full(4, np.nan)
    if dets is None:
        dets = observe(tr, REF_CAM.pose(), eff, None, v0=v0)
    tq = truth_q(tr)
    t = np.array([np.nan if tq[k] is None else tq[k] for k in QTY])
    return qvec(estimate(pose, dets)) - t


def phases(n):
    return [0.3 + (j + 0.5) / n * T for j in range(n)]


def gl_nodes(lo, hi, n):
    x, w = np.polynomial.legendre.leggauss(n)
    return 0.5 * (hi - lo) * x + 0.5 * (hi + lo), w / 2


def row_job(args):
    """One budget row for one delivery -> dict of u(x), c and u_i per measurand."""
    d, row, n_phase, n_node, seed = args
    import cv2; cv2.setNumThreads(1)
    eff0 = Effects(fps=FPS)
    ph = phases(n_phase)
    base = {v0: err(d, eff0, v0) for v0 in ph}
    out = dict(row=row)
    if row == "calibration taps":
        v0 = ph[0]
        dets = observe(truth_of(d), REF_CAM.pose(), eff0, None, v0=v0)
        xy = taps(REF_CAM.pose(), eff0, None).reshape(-1)
        J = []
        for i in range(xy.size):
            z = xy.copy(); z[i] += TAP_PX
            try:
                pose = solve(REF_CAM.pose(), z.reshape(-1, 2))
            except CalibrationError:
                continue
            J.append((err(d, eff0, v0, dets, pose) - base[v0]) / TAP_PX)
        J = np.array(J)
        out.update(ux=TAP_PX, unit="px", c=np.sqrt(np.nansum(J ** 2, axis=0)), n_eval=len(J))
        out["ui"] = TAP_PX * out["c"]
        return out
    if row in ("ball centre", "frame-time jitter"):
        v0 = ph[0]
        dets = observe(truth_of(d), REF_CAM.pose(), eff0, None, v0=v0)
        h = CENTRE_PX if row == "ball centre" else JITTER_S
        cols = (1, 2) if row == "ball centre" else (0,)
        J = []
        for i in range(len(dets)):
            for c in cols:
                dd = list(dets); r = list(dd[i]); r[c] += h; dd[i] = tuple(r)
                J.append((err(d, eff0, v0, dd) - base[v0]) / h)
        J = np.array(J)
        out.update(ux=h * (1000 if row != "ball centre" else 1), unit="px" if row == "ball centre" else "ms",
                   c=np.sqrt(np.nansum(J ** 2, axis=0)) / (1 if row == "ball centre" else 1000), n_eval=len(J))
        out["ui"] = out["c"] * out["ux"]
        return out
    if row == "frame phase":
        e = np.array(list(base.values()))
        out.update(ux=T / math.sqrt(12) * 1000, unit="ms", ui=np.nanstd(e, axis=0), n_eval=len(e))
        out["c"] = out["ui"] / out["ux"]
        out["bias"] = np.nanmean(e, axis=0)
        return out
    if row == "submitted frame sampler":
        dlt = np.array([err(d, replace(eff0, sampler="submitted", sample_fps=60.0), v0) - base[v0] for v0 in ph])
        out.update(ux=float("nan"), unit="", ui=np.sqrt(np.nanmean(dlt ** 2, axis=0)), c=np.full(4, np.nan),
                   bias=np.nanmean(dlt, axis=0), n_eval=len(dlt))
        return out
    if row == "bounce split":
        rng = np.random.default_rng(seed)
        v0 = ph[0]
        dets = observe(truth_of(d), REF_CAM.pose(), eff0, None, v0=v0)
        s0 = recon.find_bounce_split(dets)
        if s0 is None:
            out.update(ux=float("nan"), unit="", ui=np.full(4, np.nan), c=np.full(4, np.nan), n_eval=0)
            return out
        shifts = []
        for _ in range(20):
            noisy = [(t, u + rng.normal(0, CENTRE_PX), v + rng.normal(0, CENTRE_PX), r, w) for t, u, v, r, w in dets]
            s = recon.find_bounce_split(noisy)
            shifts.append(0 if s is None else s[0] - s0[0])
        shifts = np.array(shifts)
        dl = {}
        for sh in (-1, 1):
            with forced_split(sh):
                dl[sh] = err(d, eff0, v0, dets) - base[v0]
        p_m, p_p = np.mean(shifts < 0), np.mean(shifts > 0)
        out.update(ux=float(np.mean(shifts != 0)), unit="P(k moves)",
                   ui=np.sqrt(p_m * dl[-1] ** 2 + p_p * dl[1] ** 2), c=np.full(4, np.nan),
                   n_eval=22, shift_counts={int(k): int(np.sum(shifts == k)) for k in np.unique(shifts)},
                   delta_minus=dl[-1], delta_plus=dl[1])
        return out
    name, where, field, lo, hi, x0, _ = next(r for r in DIST_ROWS if r[0] == row)
    xs, ws = gl_nodes(lo, hi, n_node)
    dlt = np.zeros((len(ph), len(xs), 4))
    for a, v0 in enumerate(ph):
        for b, x in enumerate(xs):
            if where == "eff":
                dlt[a, b] = err(d, replace(eff0, **{field: float(x)}), v0) - base[v0]
            else:
                dd = apply(d, field, float(x))
                try:
                    truth_of(dd)
                except ValueError:
                    dlt[a, b] = np.nan; continue
                dlt[a, b] = err(dd, eff0, v0) - base[v0]
    W = ws[None, :, None] / len(ph)
    ok = np.isfinite(dlt)
    wsum = np.sum(np.where(ok, W, 0), axis=(0, 1))
    ms = np.sum(np.where(ok, W * dlt ** 2, 0), axis=(0, 1)) / np.maximum(wsum, 1e-12)
    mean = np.sum(np.where(ok, W * dlt, 0), axis=(0, 1)) / np.maximum(wsum, 1e-12)
    dx = xs - x0
    ux = math.sqrt(float(np.sum(ws * dx ** 2)))
    slope = np.array([np.polyfit(np.tile(dx, len(ph))[ok[:, :, q].reshape(-1)],
                                 dlt[:, :, q].reshape(-1)[ok[:, :, q].reshape(-1)], 1)[0]
                      if ok[:, :, q].sum() > 2 else np.nan for q in range(4)])
    out.update(ux=ux, unit=field, ui=np.sqrt(ms), c=slope, bias=mean, n_eval=int(ok[:, :, 0].sum()))
    return out


ROWS = (["calibration taps", "ball centre", "frame-time jitter", "frame phase", "submitted frame sampler",
         "bounce split"] + [r[0] for r in DIST_ROWS])
TYPE = {"calibration taps": "B: 2 px per coordinate (real clips: 2.05-10.55 px reprojection)",
        "ball centre": "B: 1 px per coordinate (assumed)",
        "frame-time jitter": "B: 0.5 ms per frame (assumed; PTS jitter measures the muxer only)",
        "frame phase": "B: release instant U[0, T] against the frame clock",
        "submitted frame sampler": "B: effect of the submitted 17 ms request grid (fixed since), RMS over phases",
        "bounce split": "A: split index from 20 noisy draws x effect of k+-1",
        **{r[0]: r[6] for r in DIST_ROWS}}


def pipeline_sigma(d, n, seed):
    """The pipeline's own 1-sigma and the observed scatter under 1 px centre noise alone."""
    rng = np.random.default_rng(seed)
    pose = pose_of(geo_key(Effects()))
    tr = truth_of(d)
    eff = Effects(fps=FPS, noise_px=CENTRE_PX)
    sig, errs = [], []
    for _ in range(n):
        est = estimate(pose, observe(tr, REF_CAM.pose(), eff, rng))
        if est is None:
            continue
        sig.append([est["s_" + k] for k in QTY]); errs.append(qvec(est))
    return np.median(np.array(sig), axis=0), np.std(np.array(errs), axis=0, ddof=1), len(sig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    n_dist = 10 if a.quick else a.n
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    dlv = []
    while len(dlv) < n_dist:
        d = replace(random_delivery(rng, physics=False), restitution=0.55)
        try:
            tr = truth_of(d)
        except ValueError:
            continue
        if np.isfinite(tr.contact[0]):
            dlv.append(d)
    jobs = [(REP, r, 8, 5, SEED + i) for i, r in enumerate(ROWS)]
    jobs += [(d, r, 2, 3, SEED + 1000 * (j + 1) + i) for j, d in enumerate(dlv) for i, r in enumerate(ROWS)]
    with mp.get_context("spawn").Pool(a.workers) as pool:
        sig_job = pool.apply_async(pipeline_sigma, (REP, 20, SEED))
        res = pool.map(row_job, jobs, chunksize=1)
        pipe_sig, pipe_sd, pipe_n = sig_job.get()

    def mm(x):
        return [round(float(v) * 1000, 3) if np.isfinite(v) else None for v in x]

    rep = res[:len(ROWS)]
    with open(os.path.join(OUT, "exp4_budget_rep.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "type", "u_x", "u_x_unit", "c_y", "c_z", "u_pitch_mm", "u_impact_mm", "u_y_mm",
                    "u_z_mm", "bias_y_mm", "bias_z_mm", "n_eval"])
        for r in rep:
            b = r.get("bias", np.full(4, np.nan))
            ui = mm(r["ui"])
            w.writerow([r["row"], TYPE[r["row"]], round(r["ux"], 6) if np.isfinite(r["ux"]) else "", r["unit"],
                        f"{r['c'][2]:.6g}", f"{r['c'][3]:.6g}", *ui, *mm(b)[2:], r["n_eval"]])
    U = np.array([r["ui"] for r in rep])
    uc = np.sqrt(np.nansum(U ** 2, axis=0))
    share = U ** 2 / np.maximum(uc ** 2, 1e-18)
    rows_dist = []
    for j, d in enumerate(dlv):
        rr = res[len(ROWS) * (j + 1): len(ROWS) * (j + 2)]
        Uj = np.array([r["ui"] for r in rr])
        rows_dist.append(dict(id=j, speed_kmh=round(d.speed_kmh, 2), length_m=round(d.length_m, 3),
                              line_m=round(d.line_m, 3), **{f"{r['row']}|{q}": mm(r["ui"])[k]
                                                            for r in rr for k, q in enumerate(QTY)},
                              **{f"u_c|{q}": mm(np.sqrt(np.nansum(Uj ** 2, axis=0)))[k] for k, q in enumerate(QTY)}))
    with open(os.path.join(OUT, "exp4_budget_dist.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_dist[0].keys()))
        w.writeheader(); w.writerows(rows_dist)
    summ = {}
    for k, q in enumerate(QTY):
        ucs = np.array([r[f"u_c|{q}"] for r in rows_dist if r[f"u_c|{q}"] is not None])
        dom = {}
        for r in rows_dist:
            vals = {row: r[f"{row}|{q}"] for row in ROWS if r[f"{row}|{q}"] is not None}
            if vals:
                top = max(vals, key=vals.get); dom[top] = dom.get(top, 0) + 1
        per_row = {row: dict(median=float(np.median([r[f"{row}|{q}"] for r in rows_dist if r[f"{row}|{q}"] is not None])),
                             p90=float(np.percentile([r[f"{row}|{q}"] for r in rows_dist if r[f"{row}|{q}"] is not None], 90)))
                   for row in ROWS if any(r[f"{row}|{q}"] is not None for r in rows_dist)}
        summ[q] = dict(n=int(ucs.size), u_c_median_mm=float(np.median(ucs)), u_c_p90_mm=float(np.percentile(ucs, 90)),
                       dominant=dict(sorted(dom.items(), key=lambda kv: -kv[1])), per_row=per_row)
    save_json("exp4_budget.json", dict(
        seed=SEED, representative=dict(speed_kmh=REP.speed_kmh, length_m=REP.length_m, line_m=REP.line_m,
                                       restitution=REP.restitution, fps=FPS, camera="striker_ref, 2.8 m back, 1.7 m up",
                                       phases=8, quadrature_nodes=5),
        u_c_mm=dict(zip(QTY, mm(uc))), share=dict(zip(QTY, [dict(zip(ROWS, np.round(s, 4).tolist())) for s in share.T])),
        pipeline_sigma_mm=dict(zip(QTY, mm(pipe_sig))), noise_only_scatter_mm=dict(zip(QTY, mm(pipe_sd))), pipeline_n=pipe_n,
        split=dict(counts=rep[ROWS.index("bounce split")].get("shift_counts"),
                   delta_minus_mm=mm(rep[ROWS.index("bounce split")].get("delta_minus", np.full(4, np.nan))),
                   delta_plus_mm=mm(rep[ROWS.index("bounce split")].get("delta_plus", np.full(4, np.nan)))),
        distribution=dict(n_deliveries=len(dlv), phases=2, quadrature_nodes=3, ranges="speed 60-150 km/h, length 1-10 m, "
                          "line +-0.6 m, release height 1.8-2.3 m, release y +-0.4 m, e 0.55", **summ),
        workers=a.workers, seconds=round(time.time() - t0, 1)))
    print(f"u_c (mm) pitch/impact/y/z: {mm(uc)}  pipeline sigma: {mm(pipe_sig)}  scatter: {mm(pipe_sd)}")
    for r, s in zip(rep, share):
        print(f"  {r['row']:<30s} u_y {mm(r['ui'])[2]!s:>8} u_z {mm(r['ui'])[3]!s:>8}  share z {s[3]:.3f}")
    print(f"distribution: {summ['y']['u_c_median_mm']:.2f}/{summ['z']['u_c_median_mm']:.2f} mm median, "
          f"dominant y {list(summ['y']['dominant'].items())[:2]}, z {list(summ['z']['dominant'].items())[:2]}; "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
