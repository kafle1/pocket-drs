#!/usr/bin/env python
"""How close the shipped estimator comes to the Cramer-Rao bound, and where it loses.

Part A (model-matched). Deliveries drawn from the solver's own model family: two drag-free
parabolas joined at a contact 3.6 cm up, exact frame instants at 60 fps, the reference
striker-end camera, Gaussian pixel noise. For every noise draw five estimators run on the
same detections:
    solver   reconstruction.reconstruct + predict_stump_plane, exactly as shipped
    rob_pri  a replica of the bounce fit (soft_l1, f_scale 2 px, the three priors, same
             bounds) started from the truth, so branch choice and start-up are removed
    lin_pri  the same with a plain squared loss
    ml       squared loss, no priors: the maximum-likelihood estimator
and the empirical variance is set against the CRLB of crlb.py. Each estimator is also set
against its own first-order prediction (sandwich variance and prior bias), which is how
the loss is attributed. A second pass solves the pose from twelve noisy taps (2 px) for
every draw, as the app does, and compares with the joint and two-step bounds.

Part B (the paper's setting). Random deliveries of Experiment 1's reference cell (physics
on and off, 60 fps, 1 px, 5% dropout, 2 px taps), where the stated sigma and a plug-in
bound evaluated at the fitted parameters are compared with the actual error.

Seeded (SeedSequence 20260925, one child per task), so results do not depend on workers.
Usage:  <venv>/bin/python paper/theory/efficiency.py [--quick] [--workers 10]
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import csv
import json
import math
import multiprocessing as mp
import sys
import time

import numpy as np
from scipy import integrate, stats
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crlb import (OUT, CAMERAS, PRIOR, truth_theta, positions, frame_times, setup, bounds,   # noqa: E402
                  dp_dtheta, pixel_jac, measurand_grad, lin_bound)
from synth import Delivery, calibration_taps, fly, observe, random_delivery                 # noqa: E402
from app.pipeline.reconstruction import (reconstruct, predict_stump_plane, _stump_plane_point,  # noqa: E402
                                         _theta_of, RESTITUTION_PRIOR, RESTITUTION_BOUNDS)
from app.pipeline.calibration import CalibrationError                                      # noqa: E402

QUICK = "--quick" in sys.argv
WORKERS = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 10
M = 40 if QUICK else 400          # noise draws per configuration
CHUNK = 20 if QUICK else 50
N_B = 60 if QUICK else 400        # deliveries per Part B cell
F_SCALE = 2.0
C_PRI = np.array([RESTITUTION_PRIOR / 0.15, 0.0, 0.0])   # PRIOR @ theta - C_PRI = the solver's prior rows
POSE = CAMERAS["striker_ref"].pose()
ESTS = ["solver", "rob_pri", "lin_pri", "ml", "ml_free"]


def configs():
    out = []
    for s in (90, 120, 145):
        for L in (2.5, 4.0, 6.0, 8.0):
            out.append(dict(name=f"s{s}_L{L:g}", speed=s, length=L, friction=0.10, sigma=1.0, cal=False))
    for s in (90, 120, 145):
        for L in (2.5, 4.0, 6.0, 8.0):
            out.append(dict(name=f"s{s}_L{L:g}_cal", speed=s, length=L, friction=0.10, sigma=1.0, cal=True))
    for L in (2.5, 4.0, 6.0):   # no pace loss at contact, so the pace prior is centred on the truth
        out.append(dict(name=f"s120_L{L:g}_f0", speed=120, length=L, friction=0.0, sigma=1.0, cal=False))
    for sg in (0.5, 2.0, 3.0):
        out.append(dict(name=f"s120_L6_n{sg:g}", speed=120, length=6.0, friction=0.10, sigma=sg, cal=False))
    return out


def delivery(c):
    return Delivery(speed_kmh=c["speed"], length_m=c["length"], line_m=0.2, friction=c["friction"])


# --------------------------------------------------------------------------- #
# Estimators
# --------------------------------------------------------------------------- #

def fit_replica(pose, t, u, v, theta0, loss, priors, bounded=True):
    """The solver's bounce fit (reconstruction._fit_bounce) with the loss and priors switchable."""
    def res(th):
        uu, vv, _ = pose.project(positions(th, t))
        parts = [u - uu, v - vv]
        if priors:
            parts.append(PRIOR @ th - C_PRI)
        return np.concatenate(parts)

    lower = np.array([t.min(), -10.0, -3.0, -60.0, -15.0, -25.0, -60.0, -15.0, RESTITUTION_BOUNDS[0]])
    upper = np.array([t.max(), 35.0, 3.0, 60.0, 15.0, -0.05, 60.0, 15.0, RESTITUTION_BOUNDS[1]])
    x0 = np.clip(theta0, lower + 1e-6, upper - 1e-6)
    if not bounded:
        lower, upper = -np.inf, np.inf
    sol = least_squares(res, x0, bounds=(lower, upper), loss=loss, f_scale=F_SCALE,
                        max_nfev=400, xtol=1e-10, ftol=1e-10)
    dof = max(1, 2 * len(t) - 9)
    cov = float(np.sum(sol.fun ** 2)) / dof * np.linalg.pinv(sol.jac.T @ sol.jac)
    return sol.x, cov, bool(np.any(sol.active_mask != 0))


def crossing(theta, cov):
    p = _stump_plane_point(theta, 0.0, True)
    if not np.all(np.isfinite(p[:3])):
        return None
    Gm = measurand_grad(theta)
    S = Gm @ cov @ Gm.T
    return float(p[1]), float(p[2]), math.sqrt(max(S[0, 0], 0.0)), math.sqrt(max(S[1, 1], 0.0))


def on_frame(t_b, t):
    """True when the fitted contact sits on a frame instant, where the model has a kink in t_b."""
    return bool(np.min(np.abs(t - t_b)) < 1e-7)


def stated_by_formula(pose, t_shift, u, v, theta):
    """Rebuild the solver's covariance by hand: s^2 pinv(Jw^T Jw), rows scaled by
    (1 + (r/2)^2)^-0.75 (scipy's soft_l1 scaling), priors included, s^2 over 2N - 9."""
    P = positions(theta, t_shift)
    uu, vv, _ = pose.project(P)
    r = np.concatenate([u - uu, v - vv, PRIOR @ theta - C_PRI])
    J = np.vstack([pixel_jac(pose, P, dp_dtheta(theta, t_shift)), PRIOR])
    w = (1.0 + (r / F_SCALE) ** 2) ** -0.75
    Jw = J * w[:, None]
    s2 = float(np.sum(r ** 2)) / max(1, 2 * len(t_shift) - 9)
    return crossing(theta, s2 * np.linalg.pinv(Jw.T @ Jw))


# --------------------------------------------------------------------------- #
# Part A worker
# --------------------------------------------------------------------------- #

def task_a(args):
    ci, c, n, seed = args
    rng = np.random.default_rng(seed)
    th = truth_theta(delivery(c))
    t = frame_times(th, POSE, 60.0)
    u0, v0, dep = POSE.project(positions(th, t))
    rad = POSE.fx * 0.036 / dep
    rows = []
    for _ in range(n):
        pose = POSE
        if c["cal"]:
            try:
                pose, _, _ = calibration_taps(POSE, noise_px=2.0, rng=rng)
            except CalibrationError:
                rows.append(dict(ci=ci, cal_fail=True))
                continue
        u = u0 + rng.normal(0, c["sigma"], len(t))
        v = v0 + rng.normal(0, c["sigma"], len(t))
        row = dict(ci=ci)
        dets = [(float(a), float(b), float(cc), float(rr), 1.0) for a, b, cc, rr in zip(t, u, v, rad)]
        try:   # one odd draw must not kill a long run; solver_n < draws shows it
            rec = reconstruct(pose, dets)
            pred = predict_stump_plane(rec) if rec is not None else None
            if pred is not None:
                row.update(solver_y=pred.y, solver_z=pred.z, solver_sy=pred.sigma_y, solver_sz=pred.sigma_z,
                           solver_anchored=bool(rec.trajectory.bounce_observed),
                           solver_zero_sd=bool(pred.sigma_y <= 0 or pred.sigma_z <= 0),
                           solver_extra_bounce=bool(pred.extra_bounces > 0))
                if rec.trajectory.bounce_observed:
                    ths = _theta_of(rec.trajectory)
                    row["solver_kink"] = on_frame(ths[0], t - t[0])
                    chk = stated_by_formula(pose, t - t[0], u, v, ths)
                    if row["solver_zero_sd"]:   # a stated sigma of exactly 0 happens; keep the fit for the audit
                        row["solver_zero_theta"] = ths.tolist()
                    elif chk is not None:
                        row["cov_check"] = max(abs(chk[2] / pred.sigma_y - 1), abs(chk[3] / pred.sigma_z - 1))
        except Exception as exc:
            row["solver_error"] = repr(exc)
        for name, loss, pri, bnd in (("rob_pri", "soft_l1", True, True), ("lin_pri", "linear", True, True),
                                     ("ml", "linear", False, True), ("ml_free", "linear", False, False)):
            if c["cal"] and name not in ("ml",):
                continue
            try:
                x, cov, active = fit_replica(pose, t, u, v, th, loss, pri, bnd)
                cr = crossing(x, cov)
            except Exception:
                continue
            if cr is not None:
                row.update({f"{name}_y": cr[0], f"{name}_z": cr[1], f"{name}_sy": cr[2], f"{name}_sz": cr[3],
                            f"{name}_active": active, f"{name}_kink": on_frame(x[0], t)})
        rows.append(row)
    return rows


def psi_moments(sigma, C=F_SCALE):
    """E[psi'] and E[psi^2] for scipy's soft_l1 (psi(r) = r / sqrt(1 + r^2/C^2)), r ~ N(0, sigma^2)."""
    pdf = lambda r: math.exp(-0.5 * (r / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
    a = integrate.quad(lambda r: (1 + (r / C) ** 2) ** -1.5 * pdf(r), -np.inf, np.inf)[0]
    b = integrate.quad(lambda r: r * r / (1 + (r / C) ** 2) * pdf(r), -np.inf, np.inf)[0]
    return a, b


def predictions(c):
    """First-order predictions at the truth: bounds, and for each estimator its variance and
    bias on (y*, z*) from the linearised estimating equation
        (a J^T J + P) d = J^T psi(noise) - Ap^T rp(theta),   P = Ap^T Ap,
    with a = E[psi'], b = E[psi^2] (a = 1, b = sigma^2 for the squared loss)."""
    th = truth_theta(delivery(c))
    t = frame_times(th, POSE, 60.0)
    S = setup(th, POSE, t)
    B = bounds(S, sigma=c["sigma"], sigma_tap=2.0)
    J, Gm = S["J"], S["G"]
    F = J.T @ J
    P = PRIOR.T @ PRIOR
    rp = PRIOR @ th - C_PRI
    a, b = psi_moments(c["sigma"])
    out = dict(name=c["name"], n=len(t), n_pre=S["n_pre"], n_post=S["n_post"],
               y_true=float(_stump_plane_point(th, 0.0, True)[1]), z_true=float(_stump_plane_point(th, 0.0, True)[2]),
               psi_a=a, psi_b=b, prior_resid=rp.tolist())
    for k, val in B.items():
        out[f"bound_{k}"] = val.tolist()
    for name, (aa, bb, pri) in dict(rob_pri=(a, b, True), lin_pri=(1.0, c["sigma"] ** 2, True),
                                    ml=(1.0, c["sigma"] ** 2, False)).items():
        H = aa * F + (P if pri else 0.0)
        D = np.sqrt(np.diag(H))
        try:
            if np.linalg.cond(H / np.outer(D, D)) > 1e12:   # unit-free singularity test
                raise np.linalg.LinAlgError
            Hi = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            out[f"pred_{name}_sd"] = [math.inf, math.inf]
            out[f"pred_{name}_bias"] = [0.0, 0.0]
            continue
        V = Gm @ Hi @ (bb * F) @ Hi @ Gm.T
        out[f"pred_{name}_sd"] = np.sqrt(np.diag(V)).tolist()
        out[f"pred_{name}_bias"] = (-(Gm @ Hi @ PRIOR.T @ rp) if pri else np.zeros(2)).tolist()
        if name == "rob_pri":   # what the solver states, to first order: s^2 (a F + P)^-1 with s^2 ~ sigma^2
            out["pred_stated_sd"] = np.sqrt(np.diag(c["sigma"] ** 2 * Gm @ Hi @ Gm.T)).tolist()
    return out


def summarise_a(c, pred, rows):
    rows = [r for r in rows if not r.get("cal_fail")]
    out = dict(pred)
    out["draws"] = len(rows)
    out["solver_errors"] = sorted({r["solver_error"] for r in rows if "solver_error" in r})[:5]
    out["solver_error_n"] = sum("solver_error" in r for r in rows)
    for e in ESTS:
        ok = [r for r in rows if f"{e}_y" in r]
        out[f"{e}_n"] = len(ok)
        if not ok:
            continue
        err = np.array([[r[f"{e}_y"] - pred["y_true"], r[f"{e}_z"] - pred["z_true"]] for r in ok])
        sd_st = np.array([[r[f"{e}_sy"], r[f"{e}_sz"]] for r in ok])
        mad = 1.4826 * np.median(np.abs(err - np.median(err, axis=0)), axis=0)
        m = len(ok)
        out[f"{e}_bias_cm"] = (100 * err.mean(axis=0)).tolist()
        out[f"{e}_sd_cm"] = (100 * err.std(axis=0, ddof=1)).tolist()
        out[f"{e}_madsd_cm"] = (100 * mad).tolist()
        out[f"{e}_rmse_cm"] = (100 * np.sqrt(np.mean(err ** 2, axis=0))).tolist()
        out[f"{e}_stated_rms_cm"] = (100 * np.sqrt(np.mean(sd_st ** 2, axis=0))).tolist()
        out[f"{e}_coverage"] = np.mean(np.abs(err) <= sd_st, axis=0).tolist()
        bnd = np.array(pred["bound_joint"] if c["cal"] else pred["bound_px"])
        out[f"{e}_below_bound"] = np.mean(sd_st < bnd, axis=0).tolist()
        var = err.var(axis=0, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            eff = bnd ** 2 / var
            lo = bnd ** 2 * (m - 1) / (var * stats.chi2.ppf(0.975, m - 1))
            hi = bnd ** 2 * (m - 1) / (var * stats.chi2.ppf(0.025, m - 1))
        out[f"{e}_eff"] = eff.tolist()
        out[f"{e}_eff_ci"] = [lo.tolist(), hi.tolist()]
        out[f"{e}_eff_mse"] = (bnd ** 2 / np.mean(err ** 2, axis=0)).tolist()
        out[f"{e}_eff_mad"] = (bnd ** 2 / mad ** 2).tolist()
        out[f"{e}_frac_gt5bound"] = np.mean(np.abs(err) > 5 * bnd, axis=0).tolist()
        if e == "solver":
            out["solver_anchored"] = float(np.mean([r["solver_anchored"] for r in ok]))
            # off a kink the hand-built covariance must match; on one, scipy's forward difference
            # takes the other one-sided derivative in t_b, so they legitimately differ
            chk = [r["cov_check"] for r in ok if "cov_check" in r and not r.get("solver_kink")]
            chk_k = [r["cov_check"] for r in ok if "cov_check" in r and r.get("solver_kink")]
            out["cov_check_max"] = float(max(chk)) if chk else None
            out["cov_check_median"] = float(np.median(chk)) if chk else None
            out["cov_check_kink_median"] = float(np.median(chk_k)) if chk_k else None
            out["solver_kink"] = float(np.mean([bool(r.get("solver_kink")) for r in ok]))
            out["solver_zero_sd"] = float(np.mean([r["solver_zero_sd"] for r in ok]))
            out["solver_extra_bounce"] = float(np.mean([r["solver_extra_bounce"] for r in ok]))
            out["solver_zero_theta"] = [r["solver_zero_theta"] for r in ok if "solver_zero_theta" in r][:5]
            kk = np.array([bool(r.get("solver_kink")) for r in ok])
            if kk.any() and (~kk).sum() > 2:
                out["solver_sd_cm_offkink"] = (100 * err[~kk].std(axis=0, ddof=1)).tolist()
        else:
            out[f"{e}_active"] = float(np.mean([r[f"{e}_active"] for r in ok]))
            out[f"{e}_kink"] = float(np.mean([r[f"{e}_kink"] for r in ok]))
    return out


# --------------------------------------------------------------------------- #
# Part B: the paper's reference cell
# --------------------------------------------------------------------------- #

def task_b(args):
    physics, n, seed = args
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        d = random_delivery(rng, physics=physics)
        try:
            truth = fly(d)
        except ValueError:
            continue
        try:
            pose, _, _ = calibration_taps(POSE, noise_px=2.0, rng=rng)
        except CalibrationError:
            continue
        dets = observe(truth, POSE, fps=60.0, noise_px=1.0, radius_noise=0.10, dropout=0.05, rng=rng)
        if len(dets) < 6:
            continue
        try:
            rec = reconstruct(pose, dets)
            pred = predict_stump_plane(rec) if rec is not None else None
            if pred is None or not rec.trajectory.bounce_observed:
                continue
            th = _theta_of(rec.trajectory)
            t = np.array([dd[0] for dd in dets]); t = t - t[0]
            B = bounds(setup(th, pose, t), sigma=1.0, sigma_tap=2.0)
        except Exception as exc:
            rows.append(dict(physics=physics, error=repr(exc)))
            continue
        row = dict(physics=physics, speed=d.speed_kmh, length=d.length_m,
                   ey=pred.y - truth.stumps[1], ez=pred.z - truth.stumps[2],
                   sy=pred.sigma_y, sz=pred.sigma_z, extra=int(pred.extra_bounces),
                   b_px_y=B["px"][0], b_px_z=B["px"][1], b_pri_y=B["px_pri"][0], b_pri_z=B["px_pri"][1],
                   b_2s_y=B["twostep"][0], b_2s_z=B["twostep"][1])
        if not physics:   # the truth is in the model family, so the bound at the truth exists too
            try:
                tht = truth_theta(d)
                tt = frame_times(tht, POSE, 60.0)
                Bt = bounds(setup(tht, POSE, tt), sigma=1.0, sigma_tap=2.0)
                row.update(bt_2s_y=Bt["twostep"][0], bt_2s_z=Bt["twostep"][1])
            except Exception:
                row.update(bt_2s_y=math.inf, bt_2s_z=math.inf)
        rows.append(row)
    return rows


def summarise_b(rows):
    out = {"errors": sorted({r["error"] for r in rows if "error" in r})[:5]}
    for physics in (False, True):
        out[f"error_n_{physics}"] = sum(r["physics"] == physics and "error" in r for r in rows)
        R = [r for r in rows if r["physics"] == physics and "error" not in r]
        if not R:
            continue
        s = dict(n=len(R))
        for ax in ("y", "z"):
            e = np.abs(np.array([r[f"e{ax}"] for r in R]))
            st = np.array([r[f"s{ax}"] for r in R])
            s[f"median_abs_err_cm_{ax}"] = float(100 * np.median(e))
            s[f"median_stated_cm_{ax}"] = float(100 * np.median(st))
            s[f"coverage_stated_{ax}"] = float(np.mean(e <= st))
            for key in ("px", "pri", "2s"):
                b = np.array([r[f"b_{key}_{ax}"] for r in R])
                fin = np.isfinite(b)
                s[f"median_bound_{key}_cm_{ax}"] = float(100 * np.median(np.where(fin, b, np.inf)))
                s[f"coverage_bound_{key}_{ax}"] = float(np.mean(e[fin] <= b[fin])) if fin.any() else None
                s[f"frac_stated_below_bound_{key}_{ax}"] = float(np.mean(st[fin] < b[fin])) if fin.any() else None
                s[f"median_stated_over_bound_{key}_{ax}"] = float(np.median(st[fin] / b[fin])) if fin.any() else None
            if not physics:
                bt = np.array([r[f"bt_2s_{ax}"] for r in R])
                fin = np.isfinite(bt)
                s[f"coverage_truthbound_2s_{ax}"] = float(np.mean(e[fin] <= bt[fin]))
                s[f"frac_stated_below_truthbound_2s_{ax}"] = float(np.mean(st[fin] < bt[fin]))
            # a normalised error of 1 means the error is the size of the bound
            b2 = np.array([r[f"b_2s_{ax}"] for r in R])
            fin = np.isfinite(b2)
            s[f"rms_err_over_bound_2s_{ax}"] = float(np.sqrt(np.mean((e[fin] / b2[fin]) ** 2)))
            s[f"median_err_over_bound_2s_{ax}"] = float(np.median(e[fin] / b2[fin]))
            s[f"median_err_over_stated_{ax}"] = float(np.median(e / st))
            s[f"mean_err_cm_{ax}"] = float(100 * np.mean([r[f"e{ax}"] for r in R]))
            s[f"frac_stated_zero_{ax}"] = float(np.mean(st <= 0))
        s["frac_extra_bounce"] = float(np.mean([r["extra"] > 0 for r in R]))
        out["physics_on" if physics else "physics_off"] = s
    return out


# --------------------------------------------------------------------------- #

def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    ss = np.random.SeedSequence(20260925)
    cfgs = configs()
    tasks_a = []
    for ci, c in enumerate(cfgs):
        for k in range(M // CHUNK):
            tasks_a.append((ci, c, CHUNK, None))
    tasks_b = [(ph, N_B // 10, None) for ph in (False, True) for _ in range(10)]
    seeds = ss.spawn(len(tasks_a) + len(tasks_b))
    tasks_a = [(a, b, n, int(s.generate_state(1)[0])) for (a, b, n, _), s in zip(tasks_a, seeds)]
    tasks_b = [(p, n, int(s.generate_state(1)[0])) for (p, n, _), s in zip(tasks_b, seeds[len(tasks_a):])]

    moments = {f"{C / sg:g}": dict(zip(("E_dpsi", "E_psi2"), psi_moments(sg))) for sg in (0.5, 1.0, 2.0, 3.0, 4.0)
               for C in (F_SCALE,)}
    for k, m in moments.items():
        m["efficiency"] = m["E_dpsi"] ** 2 * (2.0 / float(k)) ** 2 / m["E_psi2"]   # sigma = C / k
        m["stated_over_true_var"] = m["E_dpsi"] * (2.0 / float(k)) ** 2 / m["E_psi2"]

    with mp.Pool(WORKERS) as pool:
        res_a = pool.map(task_a, tasks_a, chunksize=1)
        if os.environ.get("EFF_RAW"):   # part A alone, in case part B dies
            import pickle
            with open(os.environ["EFF_RAW"] + ".a", "wb") as f:
                pickle.dump(res_a, f)
        res_b = pool.map(task_b, tasks_b, chunksize=1)
    rows_a = [r for chunk in res_a for r in chunk]
    rows_b = [r for chunk in res_b for r in chunk]
    if os.environ.get("EFF_RAW"):   # optional raw dump, so a summary bug does not cost the run
        import pickle
        with open(os.environ["EFF_RAW"], "wb") as f:
            pickle.dump((rows_a, rows_b), f)

    summ = []
    for ci, c in enumerate(cfgs):
        pred = predictions(c)
        s = summarise_a(c, pred, [r for r in rows_a if r["ci"] == ci])
        s.update(cal=c["cal"], sigma=c["sigma"], speed=c["speed"], length=c["length"], friction=c["friction"])
        summ.append(s)
    part_b = summarise_b(rows_b)

    with open(os.path.join(OUT, "efficiency_results.json"), "w") as f:
        json.dump(dict(M=M, seed=20260925, soft_l1_moments=moments, configs=summ, part_b=part_b,
                       runtime_s=round(time.time() - t0, 1)), f, indent=1)
    keys = ["name", "n", "n_pre", "n_post"]
    flat = []
    for s in summ:
        row = {k: s[k] for k in keys}
        for ax, i in (("y", 0), ("z", 1)):
            row[f"crlb_{ax}"] = round(100 * s["bound_joint" if s["cal"] else "bound_px"][i], 3)
            row[f"pri_{ax}"] = round(100 * s["bound_px_pri"][i], 3)
            for e in ESTS:
                if f"{e}_sd_cm" in s:
                    row[f"{e}_sd_{ax}"] = round(s[f"{e}_sd_cm"][i], 3)
                    row[f"{e}_bias_{ax}"] = round(s[f"{e}_bias_cm"][i], 3)
                    row[f"{e}_eff_{ax}"] = round(s[f"{e}_eff"][i], 3)
                    row[f"{e}_stated_{ax}"] = round(s[f"{e}_stated_rms_cm"][i], 3)
        row["anchored"] = s.get("solver_anchored")
        flat.append(row)
    with open(os.path.join(OUT, "efficiency_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in flat for k in r}, key=lambda k: (k not in keys, k)))
        w.writeheader()
        w.writerows(flat)
    with open(os.path.join(OUT, "efficiency_partb_rows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in rows_b for k in r}))
        w.writeheader()
        w.writerows(rows_b)   # rows with an "error" key are failed fits, kept so the count is visible
    print(f"done in {time.time() - t0:.0f} s: {len(rows_a)} part-A draws, {len(rows_b)} part-B deliveries")


if __name__ == "__main__":
    main()
