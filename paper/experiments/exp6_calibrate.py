"""Calibrate the stated uncertainty on exp6's World B deliveries, with every number held out.

Two steps, both fitted only on training folds and applied to the fold they did not see:
  1. Vertical bias (GUM 3.2.4: correct a known systematic effect and carry the correction's
     own uncertainty). The mean z error is fitted as b(x_b) = a + c x_b by least
     squares, subtracted, and u_b(x_b) from the fit's covariance is added to sigma.
     sigma_mod is then refitted on the corrected errors in exp6's chosen form.
  2. Empirical coverage factors by five-fold split-conformal: k68 and k95 are the conformal
     quantiles of |e - b| / sigma over the four training folds, where each training score is
     itself out of fold (inner four-fold split), so the factors never see their own data.
The reported result is then y_c = y - b, u = k68 sigma and U95 = k95 sigma.

Uses exp6's fold assignment, so sigma_cal stays as exp6 computed it. Writes
raw/exp6_calibrated.csv (one row per delivery) and raw/exp6_calibrated.json.

    python exp6_calibrate.py      # needs raw/exp6_worldb.csv and raw/exp6_model_error.json; seconds
"""
from __future__ import annotations

import csv
import json
import math
import os

import numpy as np
from scipy.stats import beta

from exp6_coverage import FORMS, SEED, fit_form
from uq import OUT, QTY, save_json

BIAS_Q = ("z",)          # the only measurand with a clear systematic error (exp6: -18 mm, 4.8 standard errors)
LEVELS = (("68", 0.6827), ("95", 0.95))


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def conformal_q(scores, p):
    """Split-conformal quantile: the ceil((n+1)p)-th smallest score."""
    s = np.sort(scores)
    j = min(len(s), int(math.ceil((len(s) + 1) * p))) - 1
    return float(s[j])


def cp_interval(x, n, conf=0.95):
    a = (1 - conf) / 2
    lo = 0.0 if x == 0 else float(beta.ppf(a, x, n - x + 1))
    hi = 1.0 if x == n else float(beta.ppf(1 - a, x + 1, n - x))
    return lo, hi


def fit(r, s2, x, form, bias):
    """Bias line (a, c, covariance) and sigma_mod parameters from training data."""
    p0 = fit_form(form, r, s2, x)
    if not bias:
        return None, p0
    # ordinary least squares, so the line removes the mean error itself; heavy tails make the
    # inverse-variance weighted line chase the short, precise deliveries instead
    A = np.c_[np.ones_like(x), x]
    inv = np.linalg.inv(A.T @ A)
    coef = inv @ (A.T @ r)
    e = r - A @ coef
    cov = inv @ (A.T @ (A * (e ** 2)[:, None])) @ inv * len(r) / max(1, len(r) - 2)   # HC1 sandwich, errors are heteroscedastic
    bl = (coef, cov)
    rc = r - A @ coef
    p = fit_form(form, rc, s2 + ub2(bl, x), x)
    return bl, p


def ub2(bl, x):
    if bl is None:
        return np.zeros_like(x)
    A = np.c_[np.ones_like(x), x]
    return np.einsum("ij,jk,ik->i", A, bl[1], A)


def apply(bl, p, form, s2, x):
    b = np.zeros_like(x) if bl is None else np.c_[np.ones_like(x), x] @ bl[0]
    return b, np.sqrt(s2 + ub2(bl, x) + FORMS[form](p, x) ** 2)


def oof_scores(r, s2, x, folds, form, bias):
    """|e - b| / sigma for every point, each from a fit that did not see it."""
    sc = np.empty_like(r)
    for g in np.unique(folds):
        tr, te = folds != g, folds == g
        bl, p = fit(r[tr], s2[tr], x[tr], form, bias)
        b, s = apply(bl, p, form, s2[te], x[te])
        sc[te] = np.abs(r[te] - b) / s
    return sc


def main():
    rows = []
    with open(os.path.join(OUT, "exp6_worldb.csv"), newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["ok"] == "True" and r["bounce"] == "True"]
    forms6 = json.load(open(os.path.join(OUT, "exp6_model_error.json")))["forms"]
    folds = np.random.default_rng(SEED).permutation(len(rows)) % 5      # exp6's folds, same order
    out = [dict(i=int(r["i"])) for r in rows]
    summary = dict(n=len(rows), seed=SEED, bias_measurands=list(BIAS_Q), measurands={})
    for q in QTY:
        idx = np.array([j for j, r in enumerate(rows) if fnum(r[f"err_{q}"]) is not None])
        g = lambda k: np.array([fnum(rows[j][f"{k}_{q}"]) or 0.0 for j in idx])
        r_, sf, sc = g("err"), g("sfit"), g("scal")
        s2 = sf ** 2 + sc ** 2
        x = np.array([max(fnum(rows[j]["x_b"]), 0.0) for j in idx])
        f_, form, bias = folds[idx], forms6[q]["chosen"], q in BIAS_Q
        b_all, s_all, k_fold = np.zeros_like(r_), np.zeros_like(r_), []
        cover = {lv: np.zeros(len(r_), bool) for lv, _ in LEVELS}
        for f in range(5):
            tr, te = f_ != f, f_ == f
            ks = oof_scores(r_[tr], s2[tr], x[tr], f_[tr], form, bias)
            k = {lv: conformal_q(ks, p) for lv, p in LEVELS}
            bl, p = fit(r_[tr], s2[tr], x[tr], form, bias)
            b, s = apply(bl, p, form, s2[te], x[te])
            b_all[te], s_all[te] = b, s
            for lv, _ in LEVELS:
                cover[lv][te] = np.abs(r_[te] - b) <= k[lv] * s
            k_fold.append(k)
            for j, jj in enumerate(np.where(te)[0]):
                o = out[idx[jj]]
                o[f"bias_{q}"] = float(b[j]); o[f"sigma_{q}"] = float(s[j])
                o[f"u_{q}"] = k["68"] * float(s[j]); o[f"U95_{q}"] = k["95"] * float(s[j])
                o[f"err_corr_{q}"] = float(r_[jj] - b[j])
        n = len(r_)
        ent = dict(n=n, form=form, bias=bias,
                   k_fold={lv: [kf[lv] for kf in k_fold] for lv, _ in LEVELS},
                   mean_err_before_mm=float(np.mean(r_) * 1000), mean_err_after_mm=float(np.mean(r_ - b_all) * 1000),
                   se_mean_mm=float(np.std(r_, ddof=1) / math.sqrt(n) * 1000))
        for lv, p in LEVELS:
            c = int(cover[lv].sum())
            lo, hi = cp_interval(c, n)
            ent[f"cover_{lv}"] = dict(pct=100 * c / n, lo=100 * lo, hi=100 * hi, nominal=100 * p, covered=c)
        # the factors and bias line the app would ship: fitted on all data, scores out of fold
        ks = oof_scores(r_, s2, x, f_, form, bias)
        ent["k_all"] = {lv: conformal_q(ks, p) for lv, p in LEVELS}
        bl, p = fit(r_, s2, x, form, bias)
        ent["sigma_mod_params_m"] = [float(math.exp(v)) for v in p]
        if bl is not None:
            ent["bias_line"] = dict(a_mm=float(bl[0][0] * 1000), c_mm_per_m=float(bl[0][1] * 1000),
                                    u_a_mm=float(math.sqrt(bl[1][0, 0]) * 1000), u_c_mm_per_m=float(math.sqrt(bl[1][1, 1]) * 1000),
                                    median_u_b_mm=float(np.median(np.sqrt(ub2(bl, x))) * 1000),
                                    coef_m=[float(v) for v in bl[0]], cov_m2=bl[1].tolist())
        ent["median_u_mm"] = float(np.median([out[j][f"u_{q}"] for j in idx]) * 1000)
        ent["median_U95_mm"] = float(np.median([out[j][f"U95_{q}"] for j in idx]) * 1000)
        if q in ("y", "z"):
            # does the remaining misfit track swing? if not, a swing term would not help
            sw = np.array([abs(fnum(rows[j]["swing_ms2"])) for j in idx])
            sws = np.array([fnum(rows[j]["swing_ms2"]) for j in idx])
            full = np.sqrt(s2 + np.array([fnum(rows[j][f"smod_{q}"]) for j in idx]) ** 2)
            ent["corr_ratio_abs_swing"] = float(np.corrcoef(np.abs(r_) / full, sw)[0, 1])
            ent["r2_err_swing"] = float(np.corrcoef(r_, sws)[0, 1] ** 2)
        summary["measurands"][q] = ent
    fields = list(dict.fromkeys(k for o in out for k in o))
    with open(os.path.join(OUT, "exp6_calibrated.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(out)
    save_json("exp6_calibrated.json", summary)
    for q, e in summary["measurands"].items():
        print(q, f"mean {e['mean_err_before_mm']:+.1f} -> {e['mean_err_after_mm']:+.1f} mm",
              {lv: f"{e[f'cover_{lv}']['pct']:.1f} [{e[f'cover_{lv}']['lo']:.1f}, {e[f'cover_{lv}']['hi']:.1f}]" for lv, _ in LEVELS},
              "k_all", {k: round(v, 2) for k, v in e["k_all"].items()}, e.get("bias_line", ""))


if __name__ == "__main__":
    main()
