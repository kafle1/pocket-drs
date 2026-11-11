"""Experiment 6: why the pipeline's 1-sigma under-covers, and what honest coverage needs.

World B = exp1's randomised deliveries and unmodelled physics (drag with Cd drawn from
[0.35, 0.55], pre-pitch swing, friction and turn at contact, varying restitution), exp1's
tracker noise (1 px, 10 % radius, 5 % dropout), 2 px taps, plus every measurement effect
of exp4 drawn from its PDF: rolling-shutter readout, lens distortion, frame-time jitter,
frame-rate metadata, pitch and wicket dimensions, bails. Frames carry their own
timestamps here; the app's sampler, fixed and as submitted, is a separate configuration.
Delivery i is filmed from the striker's end when i is even and the bowler's end when odd, and
faces a left-hander when i // 2 is odd. The deliveries are symmetric across the pitch, so a
left-hander's are a right-hander's mirrored; the lateral measurands (pitch_y, impact_y, y) are
kept leg-side signed, which makes them the same quantity for either hand and either end.

Per delivery the error of each measurand is kept with three 1-sigma terms:
  sigma_fit  the pipeline's own covariance (centre scatter only)
  sigma_cal  tap noise pushed through the calibration solve and the fit, the app's way
             (uq.cal_sigma: tap noise implied by the pose residual); failed solves are counted
  sigma_mod  model error, fitted by maximum likelihood with 5-fold cross-validation; the
             form (constant, proportional to the bounce distance x_b, or both in
             quadrature) is chosen by held-out likelihood, and every delivery gets the
             value from the fold that did not see it.
Coverage is |error| <= k sigma at k = 1 and 1.96, on anchored fits that saw the bounce,
as in exp1.

Sweeps on the first 200 deliveries, everything else as drawn: rolling-shutter readout
{0, 5, 10, 16, 30} ms in both directions, uncorrected and corrected; and the frame sampler
(timestamps; the fixed app, nearest frame to each 60 Hz request by its own timestamp; or the
submitted 17 ms grid labelled with the requested time) against frame-rate metadata (true or
59.80/60).
sigma_cal and sigma_mod are carried over from the main run for the same delivery.

    python exp6_coverage.py            # 1200 deliveries, 200 in each sweep configuration
    python exp6_coverage.py --quick    # 60 deliveries, 30 in the sweeps
"""
from __future__ import annotations

import argparse
import csv
import math
import multiprocessing as mp
import os
import time

import numpy as np
from scipy.optimize import minimize

from uq import (Effects, fly, CAMS, QTY, RATE_TEST5, taps, solve, observe, truth_q, estimate, cal_sigma,
                replace, OUT, save_json, CalibrationError)
from synth import random_delivery
from app.pipeline.reconstruction import find_bounce_split
from app.pipeline.uncertainty import LATERAL, MODEL_FORMS

SEED = 606
TAP_PX = 2.0
RS_SWEEP = [0.0, 0.005, 0.010, 0.016, 0.030]
SAMPLERS = [("timestamps", "exact", 1.0), ("timestamps, 59.80 metadata", "exact", RATE_TEST5),
            ("fixed sampler", "fixed", 1.0), ("fixed sampler, 59.80 metadata", "fixed", RATE_TEST5),
            ("submitted 17 ms grid", "submitted", 1.0), ("submitted 17 ms grid, 59.80 metadata", "submitted", RATE_TEST5)]


def draw(i):
    """Delivery i of World B and its effects, the same on every call."""
    rng = np.random.default_rng([SEED, i])
    U = rng.uniform
    d = replace(random_delivery(rng, physics=True), cd=U(0.35, 0.55))
    eff = Effects(tap_px=TAP_PX, noise_px=1.0, radius_noise=0.10, dropout=0.05, fps=60.0, jitter_s=5e-4,
                  rate_ratio=U(RATE_TEST5, 1.0), rs_s=U(-0.030, 0.030), distortion=U(-0.01, 0.01),
                  dL=U(-0.05, 0.05), dW=U(-0.10, 0.10), dH=U(-0.01, 0.01), dw=U(-0.0025, 0.0025),
                  top_tap=U(0.0, 0.0127))
    return d, eff, rng


def end_hand(i):
    """Camera end and the batter's leg sign (+1 right-handed, -1 left) of delivery i."""
    return ("striker", "bowler")[i % 2], (1.0, -1.0)[(i // 2) % 2]


def run(args):
    """One delivery under World B, optionally with effect overrides. with_cal adds sigma_cal."""
    i, over, with_cal = args
    import cv2; cv2.setNumThreads(1)
    d, eff, rng = draw(i)
    eff = replace(eff, **over)
    end, leg = end_hand(i)
    row = dict(i=i, end=end, leg=leg, speed_kmh=d.speed_kmh, length_m=d.length_m, line_m=d.line_m, cd=d.cd, swing_ms2=d.swing_ms2,
               turn_ms=d.turn_ms, restitution=d.restitution, friction=d.friction, rs_s=eff.rs_s,
               rs_correct_s=eff.rs_correct_s, distortion=eff.distortion, rate_ratio=eff.rate_ratio, sampler=eff.sampler,
               ok=False, bounce=False)
    try:
        tr = fly(d, dt=5e-4)
    except ValueError:
        return row
    pt = CAMS[end].pose()
    xy = taps(pt, eff, rng)
    try:
        pose = solve(pt, xy)
    except CalibrationError:
        return row
    dets = observe(tr, pt, eff, rng)
    row["split"] = find_bounce_split(sorted(dets)) is not None      # a bounce seen in the image
    est = estimate(pose, dets)
    tq = truth_q(tr)
    tq = {q: v * leg if q in LATERAL and v is not None else v for q, v in tq.items()}
    for q in QTY:
        row[f"truth_{q}"] = tq[q]
    if est is None:
        return row
    st = tr.states
    j = max(2, int(np.searchsorted(st[:, 0], tr.contact_t))) if np.isfinite(tr.contact_t) else None
    vy_pre = None if j is None else (st[j - 1, 2] - st[j - 2, 2]) / (st[j - 1, 0] - st[j - 2, 0])
    row.update(ok=True, bounce=est["bounce"], x_b=est["x_b"], rms_px=est["rms_px"], fov_deg=pose.fov_deg,
               tap_sigma_px=pose.tap_sigma_px, est_e=est["e"], est_dvy=est["dvy"],
               true_dvy=None if vy_pre is None else d.turn_ms - d.friction * vy_pre)
    for q in QTY:
        est[q] = est[q] * leg if q in LATERAL and est[q] is not None else est[q]
        row[f"est_{q}"] = est[q]
        row[f"err_{q}"] = None if est[q] is None or tq[q] is None else est[q] - tq[q]
        row[f"sfit_{q}"] = est["s_" + q]
    if with_cal:
        sc, row["cal_failed"] = cal_sigma(pt, pose, xy, dets, est)
        for k, q in enumerate(QTY):
            row[f"scal_{q}"] = float(sc[k])
    return row


# --------------------------------------------------------------------------- #
# model error by cross-validated maximum likelihood
# --------------------------------------------------------------------------- #

# the app's forms (uncertainty.MODEL_FORMS), searched over log parameters
FORMS = {k: (lambda f: lambda p, x: f(np.exp(p), x))(f) for k, f in MODEL_FORMS.items()}
NPAR = {"constant": 1, "proportional to x_b": 1, "constant + proportional": 2}


def nll(r, s2, m):
    v = np.maximum(s2 + m ** 2, 1e-12)
    return 0.5 * float(np.sum(np.log(2 * math.pi * v) + r ** 2 / v))


def fit_form(form, r, s2, x):
    f = FORMS[form]
    x0 = [math.log(max(np.std(r), 1e-4))] + ([math.log(max(np.std(r), 1e-4) / 5)] if NPAR[form] == 2 else [])
    res = minimize(lambda p: nll(r, s2, f(p, x)), x0, method="Nelder-Mead", options=dict(xatol=1e-4, fatol=1e-6))
    return res.x


def bias_line(r, x):
    """Least-squares line a + c x_b through the errors and its HC1 sandwich covariance (the errors
    are heteroscedastic). Unweighted, so the line removes the mean error itself."""
    A = np.c_[np.ones_like(x), x]
    inv = np.linalg.inv(A.T @ A)
    coef = inv @ (A.T @ r)
    e = r - A @ coef
    return coef, inv @ (A.T @ (A * (e ** 2)[:, None])) @ inv * len(r) / max(1, len(r) - 2)


def line_at(bl, x):
    """Bias b(x_b) and its variance u_b^2; zero for no bias line."""
    if bl is None:
        return np.zeros_like(x), np.zeros_like(x)
    A = np.c_[np.ones_like(x), x]
    return A @ bl[0], np.einsum("ij,jk,ik->i", A, bl[1], A)


def model_error(r, s2, x, folds, bias=False):
    """Held-out log-likelihood per form, the chosen form, its full-data parameters (metres), the
    out-of-fold sigma_mod for every point, and the full-data bias line (None without bias). With
    bias, each fold fits its own line on its training part first."""
    held = {}
    oof = {}
    for form in FORMS:
        tot, m = 0.0, np.zeros_like(r)
        for f in range(folds.max() + 1):
            tr, te = folds != f, folds == f
            bl = bias_line(r[tr], x[tr]) if bias else None
            (b_tr, u_tr), (b_te, u_te) = line_at(bl, x[tr]), line_at(bl, x[te])
            p = fit_form(form, r[tr] - b_tr, s2[tr] + u_tr, x[tr])
            m[te] = FORMS[form](p, x[te])
            tot += nll(r[te] - b_te, s2[te] + u_te, m[te])
        held[form], oof[form] = tot, m
    best = min(held, key=held.get)
    bl = bias_line(r, x) if bias else None
    b, u = line_at(bl, x)
    p = fit_form(best, r - b, s2 + u, x)
    return best, held, [float(math.exp(v)) for v in p], oof[best], bl


def coverage(r, s):
    a = np.abs(r) / np.maximum(s, 1e-9)
    return dict(one=float(100 * np.mean(a <= 1.0)), p95=float(100 * np.mean(a <= 1.96)), n=int(a.size),
                median_ratio=float(np.median(a)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--n-sweep", type=int, default=200)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    n, n_sw = (60, 30) if a.quick else (a.n, min(a.n_sweep, a.n))
    t0 = time.time()
    sweep_cfg = [("rs", 0.0, False)] + [("rs", s * r, c) for r in RS_SWEEP[1:] for s in (1, -1) for c in (False, True)]
    jobs_sw = []
    for kind, rho, corr in sweep_cfg:
        over = dict(rs_s=rho, rs_correct_s=rho if corr else 0.0)
        jobs_sw += [(("rs", rho, corr), (i, over, False)) for i in range(n_sw)]
    for name, smp, ratio in SAMPLERS:
        over = dict(sampler=smp, sample_fps=60.0, rate_ratio=ratio)
        jobs_sw += [(("sampler", name), (i, over, False)) for i in range(n_sw)]
    with mp.get_context("spawn").Pool(a.workers) as pool:
        main_rows = pool.map(run, [(i, {}, True) for i in range(n)], chunksize=2)
        t_main = time.time() - t0
        print(f"main: {sum(r['ok'] for r in main_rows)}/{n} fitted in {t_main:.0f} s", flush=True)
        sw_rows = pool.map(run, [j[1] for j in jobs_sw], chunksize=4)
    for (key, _), r in zip(jobs_sw, sw_rows):
        r["config"] = "|".join(str(k) for k in key)

    # model error per measurand on anchored fits that saw the bounce
    use = [r for r in main_rows if r["ok"] and r["bounce"]]
    folds = np.random.default_rng(SEED).permutation(len(use)) % 5
    summary = dict(n=n, fitted=sum(r["ok"] for r in main_rows), bounce_observed=len(use), forms={}, coverage={})
    for q in QTY:
        # a failed perturbed solve leaves sigma_cal unbounded (umpire's call in the app); nothing to fit there
        idx = [j for j, r in enumerate(use) if r.get(f"err_{q}") is not None and math.isfinite(r[f"scal_{q}"])]
        r_ = np.array([use[j][f"err_{q}"] for j in idx])
        sf = np.array([use[j][f"sfit_{q}"] for j in idx])
        sc = np.array([use[j][f"scal_{q}"] for j in idx])
        xb = np.array([max(use[j]["x_b"], 0.0) for j in idx])
        best, held, par, oof, _ = model_error(r_, sf ** 2 + sc ** 2, xb, folds[idx])
        for j, m in zip(idx, oof):
            use[j][f"smod_{q}"] = float(m)
        summary["forms"][q] = dict(chosen=best, cal_unbounded=sum(r.get(f"err_{q}") is not None for r in use) - len(idx),
                                   params_m=par, heldout_nll={k: round(v, 2) for k, v in held.items()},
                                   mean_err_mm=float(np.mean(r_) * 1000), median_abs_err_mm=float(np.median(np.abs(r_)) * 1000),
                                   median_sigma_fit_mm=float(np.median(sf) * 1000), median_sigma_cal_mm=float(np.median(sc) * 1000),
                                   median_sigma_mod_mm=float(np.median(oof) * 1000))
        summary["coverage"][q] = {"fit only (as shipped)": coverage(r_, sf),
                                  "fit + calibration": coverage(r_, np.sqrt(sf ** 2 + sc ** 2)),
                                  "fit + calibration + model": coverage(r_, np.sqrt(sf ** 2 + sc ** 2 + oof ** 2))}
    fields = list(dict.fromkeys(k for r in main_rows for k in r))
    with open(os.path.join(OUT, "exp6_worldb.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(main_rows)

    # sweeps, with sigma_cal and sigma_mod carried over from the main run
    carry = {r["i"]: r for r in use}
    sweeps = {}
    for key in dict.fromkeys(r["config"] for r in sw_rows):
        rows = [r for r in sw_rows if r["config"] == key and r["ok"] and r["bounce"] and r["i"] in carry]
        ent = dict(n=len(rows))
        for q in ("y", "z"):
            rr = [(r[f"err_{q}"], r[f"sfit_{q}"], carry[r["i"]].get(f"scal_{q}"), carry[r["i"]].get(f"smod_{q}"))
                  for r in rows if r.get(f"err_{q}") is not None and carry[r["i"]].get(f"smod_{q}") is not None]
            if not rr:
                continue
            e, sf, sc, sm = map(np.array, zip(*rr))
            ent[q] = dict(median_abs_mm=float(np.median(np.abs(e)) * 1000), p90_abs_mm=float(np.percentile(np.abs(e), 90) * 1000),
                          mean_mm=float(np.mean(e) * 1000), cov_fit=coverage(e, sf),
                          cov_full=coverage(e, np.sqrt(sf ** 2 + sc ** 2 + sm ** 2)))
        sweeps[key] = ent
    fields = list(dict.fromkeys(k for r in sw_rows for k in r))
    with open(os.path.join(OUT, "exp6_sweeps.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(sw_rows)
    summary.update(sweeps=sweeps, n_sweep=n_sw, seed=SEED, workers=a.workers, seconds_main=round(t_main, 1),
                   seconds=round(time.time() - t0, 1),
                   world="exp1 physics with Cd U[0.35,0.55]; 1 px centres, 10 % radius, 5 % dropout, 2 px taps; "
                         "jitter 0.5 ms; rate U[0.99673,1]; rolling shutter U[-30,30] ms; distortion U[-1,1] %; "
                         "dL +-5 cm, dW +-10 cm, dH +-1 cm, dw +-2.5 mm, bails U[0,1.27] cm; both camera ends, both hands; "
                         "frames labelled with their own timestamps")
    save_json("exp6_model_error.json", summary)
    for q in ("y", "z"):
        c = summary["coverage"][q]
        print(q, summary["forms"][q]["chosen"], [round(v * 1000, 2) for v in summary["forms"][q]["params_m"]],
              {k: (round(v["one"], 1), round(v["p95"], 1)) for k, v in c.items()})
    for key, ent in sweeps.items():
        print(f"{key:<45s} n={ent['n']:3d} " + " ".join(
            f"{q}: med {ent[q]['median_abs_mm']:.1f} mm cov {ent[q]['cov_full']['one']:.0f}/{ent[q]['cov_full']['p95']:.0f}"
            for q in ("y", "z") if q in ent))
    print(f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
