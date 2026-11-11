"""Experiment 5: JCGM 101 Monte Carlo propagation through the full nonlinear solver.

Every input of the exp4 budget is drawn from its PDF at once (taps, ball centres, frame
times, frame phase, frame-rate metadata, rolling shutter, lens distortion, pitch and wicket
dimensions, bails, restitution, drag, swing, seam, friction),
and each trial runs the app's calibration solve and the bounce-anchored fit. The output is
the crossing error (estimate - truth). Frames carry their own timestamps, as the fixed app
now labels them: the submitted 17 ms request grid was a bug with its own exp4 row, not an
uncertainty, so it is left out here and from u_c. The linear (JCGM 100) result is y = the mean error at nominal inputs over the frame
phase and u_c = the RSS of the other exp4 rows; its 95 %
interval is y +- 1.96 u_c. Validation follows JCGM 101 section 8: d_low and d_high must
both be at most delta, the numerical tolerance of u_c written to two significant digits.

Representative delivery: the adaptive procedure of JCGM 101 7.9 (batches of 10^4, at
least two, stop when twice the standard deviation of every batch statistic is within the
tolerance, or when --max-batches is reached; either way the count is written out).
Subset: the first --subset deliveries of the exp4 sample, a fixed number of trials each.

    python exp5_mc.py                  # needs raw/exp4_budget_rep.csv and exp4_budget_dist.csv
    python exp5_mc.py --quick
"""
from __future__ import annotations

import argparse
import csv
import math
import multiprocessing as mp
import os
import time

import numpy as np

from uq import (Effects, fly, REF_CAM, QTY, RATE_TEST5, taps, solve, observe, truth_q, estimate, qvec, replace,
                OUT, save_json, CalibrationError)
from exp4_budget import REP, FPS, T, TAP_PX, CENTRE_PX, JITTER_S, DEG, SEED as SEED4, err, phases
from synth import random_delivery

SEED = 505
M_BATCH = 10_000


def draw_trial(args):
    """One Monte Carlo trial: every input drawn, full solve + fit, error vector (m) and the pipeline sigma."""
    d, idx, seed = args
    import cv2; cv2.setNumThreads(1)
    rng = np.random.default_rng([seed, idx])
    U = rng.uniform
    eff = Effects(tap_px=TAP_PX, noise_px=CENTRE_PX, jitter_s=JITTER_S, fps=FPS,
                  rate_ratio=U(RATE_TEST5, 1.0), rs_s=U(-0.030, 0.030), distortion=U(-0.01, 0.01),
                  dL=U(-0.05, 0.05), dW=U(-0.10, 0.10), dH=U(-0.01, 0.01), dw=U(-0.0025, 0.0025), top_tap=U(0.0, 0.0127))
    dd = replace(d, restitution=U(0.40, 0.70), drag=True, cd=U(0.35, 0.55), cs=U(-0.30, 0.30), friction=U(0.05, 0.20))
    seam = U(-2.0, 2.0)
    v0 = 0.3 + U(0.0, T)
    nan = np.full(8, np.nan)
    try:
        pre = fly(dd, dt=5e-4)
        i = max(2, int(np.searchsorted(pre.states[:, 0], pre.contact_t)))
        vx = abs(pre.states[i - 1, 1] - pre.states[i - 2, 1]) / (pre.states[i - 1, 0] - pre.states[i - 2, 0])
        tr = fly(replace(dd, turn_ms=math.tan(seam * DEG) * (1.0 - dd.friction) * vx), dt=5e-4)
    except ValueError:
        return nan
    pt = REF_CAM.pose()
    xy = taps(pt, eff, rng)
    try:
        pose = solve(pt, xy)
    except CalibrationError:
        return nan
    est = estimate(pose, observe(tr, pt, eff, rng, v0=v0))
    if est is None:
        return nan
    tq = truth_q(tr)
    t = np.array([np.nan if tq[k] is None else tq[k] for k in QTY])
    return np.concatenate([qvec(est) - t, [np.nan if est["s_" + k] is None else est["s_" + k] for k in QTY]])


def stats(e):
    """mean, u, and the probabilistically symmetric 95 % interval of one output."""
    e = e[np.isfinite(e)]
    return np.array([e.mean(), e.std(ddof=1), np.percentile(e, 2.5), np.percentile(e, 97.5)])


def tolerance(u):
    """JCGM 101 7.9.2: delta = 0.5 * 10^l for u written with two significant digits."""
    l = math.floor(math.log10(abs(u))) - 1
    return 0.5 * 10 ** l


def validate(y, uc, e):
    s = stats(e)
    Up = 1.96 * uc
    dl, dh = abs(y - Up - s[2]), abs(y + Up - s[3])
    delta = tolerance(uc)
    return dict(y_gum=y, u_c=uc, gum_low=y - Up, gum_high=y + Up, mc_mean=s[0], mc_u=s[1], mc_low=s[2], mc_high=s[3],
                delta=delta, d_low=dl, d_high=dh, valid=bool(dl <= delta and dh <= delta))


def y_gum(d, n_phase=8):
    """Linear estimate of the error: nominal inputs, averaged over the frame phase."""
    from uq import Effects as E
    return np.nanmean([err(d, E(fps=FPS), v0) for v0 in phases(n_phase)], axis=0)


SAMPLER_ROW = "submitted frame sampler"


def _f(x):
    return None if x in (None, "", "None", "nan") else float(x)


def budget_uc(path, key):
    """u_c (m) without the sampler row: from the rep table, or per delivery from the dist table."""
    with open(os.path.join(OUT, path)) as fh:
        rows = list(csv.DictReader(fh))
    if key is None:
        return {q: math.sqrt(sum(_f(r[f"u_{q}_mm"]) ** 2 for r in rows
                                 if r["row"] != SAMPLER_ROW and _f(r[f"u_{q}_mm"]) is not None)) / 1000
                for q in ("y", "z")}
    out = []
    for r in rows:
        names = {c.split("|")[0] for c in r if "|" in c and not c.startswith("u_c")}
        out.append({q: math.sqrt(sum(_f(r[f"{n}|{q}"]) ** 2 for n in names
                                     if n != SAMPLER_ROW and _f(r[f"{n}|{q}"]) is not None)) / 1000
                    for q in ("y", "z")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--max-batches", type=int, default=3)
    ap.add_argument("--subset", type=int, default=10)
    ap.add_argument("--subset-trials", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    m_batch = 500 if a.quick else M_BATCH
    n_sub, m_sub = (2, 100) if a.quick else (a.subset, a.subset_trials)
    t0 = time.time()
    uc_rep = budget_uc("exp4_budget_rep.csv", None)
    dist_rows = budget_uc("exp4_budget_dist.csv", "dist")

    # the exp4 sample, regenerated from its seed
    rng = np.random.default_rng(SEED4)
    dlv = []
    from exp4_budget import truth_of
    while len(dlv) < len(dist_rows):
        d = replace(random_delivery(rng, physics=False), restitution=0.55)
        try:
            tr = truth_of(d)
        except ValueError:
            continue
        if np.isfinite(tr.contact[0]):
            dlv.append(d)

    out = {}
    with mp.get_context("spawn").Pool(a.workers) as pool:
        yg = pool.map(y_gum, [REP] + dlv[:n_sub])
        # representative delivery, adaptive
        batches, hist = [], []
        idx = 0
        while True:
            res = np.array(pool.map(draw_trial, [(REP, i, SEED) for i in range(idx, idx + m_batch)], chunksize=20))
            idx += m_batch
            batches.append(res)
            h = len(batches)
            per = np.array([[stats(b[:, 2 + k]) for k in range(2)] for b in batches])     # h x 2 x 4
            if h >= 2:
                s = per.std(axis=0, ddof=1) / math.sqrt(h)
                allres = np.vstack(batches)
                tol = np.array([tolerance(np.nanstd(allres[:, 2 + k], ddof=1)) for k in range(2)])
                hist.append(dict(h=h, M=idx, two_s_mm=(2 * s * 1000).round(4).tolist(), delta_mm=(tol * 1000).tolist()))
                print(f"batch {h}: M={idx} 2s(mm)={np.round(2 * s * 1000, 3).tolist()} delta(mm)={tol * 1000}", flush=True)
                if np.all(2 * s <= tol[:, None]) or h >= a.max_batches:
                    stable = bool(np.all(2 * s <= tol[:, None]))
                    break
        allres = np.vstack(batches)
        fails = int(np.sum(~np.isfinite(allres[:, 2])))
        rep = {q: validate(float(yg[0][2 + k]), uc_rep[q], allres[:, 2 + k]) for k, q in enumerate(("y", "z"))}
        rep["pipeline_sigma_median_mm"] = dict(zip(QTY, (np.nanmedian(allres[:, 4:], axis=0) * 1000).round(3).tolist()))
        rep["mc_u_all_mm"] = dict(zip(QTY, (np.nanstd(allres[:, :4], axis=0, ddof=1) * 1000).round(3).tolist()))
        out["representative"] = dict(M=int(idx), batches=len(batches), batch_size=m_batch, failed_trials=fails,
                                     adaptive_stable=stable, history=hist, **rep)
        with open(os.path.join(OUT, "exp5_mc_rep.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([f"err_{q}_m" for q in QTY] + [f"sigma_{q}_m" for q in QTY])
            w.writerows(np.round(allres, 7).tolist())
        t_rep = time.time() - t0
        # subset, fixed M
        sub = []
        with open(os.path.join(OUT, "exp5_mc_subset.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["delivery"] + [f"err_{q}_m" for q in QTY] + [f"sigma_{q}_m" for q in QTY])
            for j, d in enumerate(dlv[:n_sub]):
                res = np.array(pool.map(draw_trial, [(d, i, SEED + 1 + j) for i in range(m_sub)], chunksize=20))
                w.writerows([[j] + r for r in np.round(res, 7).tolist()])
                row = dist_rows[j]
                entry = dict(id=j, speed_kmh=d.speed_kmh, length_m=d.length_m, line_m=d.line_m,
                             failed_trials=int(np.sum(~np.isfinite(res[:, 2]))))
                for k, q in enumerate(("y", "z")):
                    uc = row[q]
                    if not uc or not np.isfinite(yg[j + 1][2 + k]) or np.sum(np.isfinite(res[:, 2 + k])) < 10:
                        entry[q] = None; continue
                    entry[q] = validate(float(yg[j + 1][2 + k]), uc, res[:, 2 + k])
                sub.append(entry)
                print(f"subset {j}: " + ", ".join(f"{q} u_mc/u_c={e[q]['mc_u'] / e[q]['u_c']:.2f} valid={e[q]['valid']}"
                                                   for e in [entry] for q in ("y", "z") if e[q]), flush=True)
    out["subset"] = dict(n=len(sub), trials_each=m_sub, adaptive=False, deliveries=sub,
                         valid_y=sum(1 for e in sub if e["y"] and e["y"]["valid"]),
                         valid_z=sum(1 for e in sub if e["z"] and e["z"]["valid"]),
                         ratio_u_y=[round(e["y"]["mc_u"] / e["y"]["u_c"], 3) for e in sub if e["y"]],
                         ratio_u_z=[round(e["z"]["mc_u"] / e["z"]["u_c"], 3) for e in sub if e["z"]])
    out.update(seed=SEED, workers=a.workers, seconds_representative=round(t_rep, 1), seconds=round(time.time() - t0, 1))
    save_json("exp5_mc.json", out)
    r = out["representative"]
    for q in ("y", "z"):
        e = r[q]
        print(f"{q}: GUM {e['y_gum'] * 1000:.2f} +- {1.96 * e['u_c'] * 1000:.2f} mm  MC mean {e['mc_mean'] * 1000:.2f} "
              f"u {e['mc_u'] * 1000:.2f} [{e['mc_low'] * 1000:.2f}, {e['mc_high'] * 1000:.2f}]  "
              f"d_low {e['d_low'] * 1000:.2f} d_high {e['d_high'] * 1000:.2f} delta {e['delta'] * 1000:.2f} valid {e['valid']}")
    print(f"M={r['M']} stable={r['adaptive_stable']} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
