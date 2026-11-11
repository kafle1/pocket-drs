"""Calibrate the stated uncertainty on exp6's World B deliveries, with every number held out.

For each camera end and measurand (lateral ones leg-side signed), fitted only on training folds
and applied to the fold they did not see:
  1. Bias (GUM 3.2.4: correct a known systematic effect and carry the correction's own
     uncertainty): either none, or b(x_b) = a + c x_b by least squares, subtracted, with u_b(x_b)
     from the fit's covariance added to sigma.
  2. Model error sigma_mod(x_b) on the corrected errors, in one of uncertainty.MODEL_FORMS.
     The bias choice and the form are picked together inside the training data by four-fold
     held-out likelihood (exp6_coverage.model_error), so a bias stays only where it wins held out.
  3. Coverage factors k68 and k95 by split conformal, separately for each third of the training
     bounce distances (Mondrian conformal), so a short bounce, where the model term is small, gets
     the factor its own band needs. Each training score is itself out of fold (inner four-fold
     split), so the factors never see their own data.
The reported result is y_c = y - b, u = k68 sigma and U95 = k95 sigma.

Uses exp6's fold assignment, so sigma_cal stays as exp6 computed it. A delivery whose sigma_cal
is unbounded (a perturbed solve failed) gets umpire's call in the app and is left out here. Writes
raw/exp6_calibrated.csv (one row per delivery), raw/exp6_calibrated.json, and the rule fitted on all
deliveries to raw/exp6_rule.json, which exp7 ships with its guard factor.

    python exp6_calibrate.py      # needs raw/exp6_worldb.csv; seconds
"""
from __future__ import annotations

import csv
import math
import os

import numpy as np
from scipy.stats import beta

from exp6_coverage import SEED, line_at, model_error, nll
from uq import OUT, QTY, save_json
from app.pipeline.uncertainty import MODEL_FORMS, factors

LEVELS = (("68", 0.6827), ("95", 0.95))
BANDS = 3


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


def fit(r, s2, x, bias=None):
    """(bias line or None, model-error form, its parameters), chosen by inner held-out likelihood
    from this data alone; bias True or False forces that choice."""
    inner = np.arange(len(r)) % 4
    fits = [model_error(r, s2, x, inner, b) for b in ((False, True) if bias is None else (bias,))]
    form, _, p, _, bl = min(fits, key=lambda f: f[1][f[0]])
    return bl, form, p


def apply(model, s2, x):
    bl, form, p = model
    b, u = line_at(bl, x)
    return b, np.sqrt(s2 + u + MODEL_FORMS[form](p, x) ** 2)


def oof_scores(r, s2, x, folds, bias=None):
    """|e - b| / sigma for every point, each from a fit that did not see it."""
    sc = np.empty_like(r)
    for g in np.unique(folds):
        tr, te = folds != g, folds == g
        b, s = apply(fit(r[tr], s2[tr], x[tr], bias), s2[te], x[te])
        sc[te] = np.abs(r[te] - b) / s
    return sc


def bands(x, scores):
    """Mondrian factors: band edges at the thirds of x, k68 and k95 from each band's own scores."""
    edges = list(np.quantile(x, [i / BANDS for i in range(1, BANDS)]))
    out, lo = [], -np.inf
    for hi in edges + [None]:
        sel = (x > lo) & (x <= (np.inf if hi is None else hi))
        out.append(dict(x_b_max=None if hi is None else float(hi),
                        **{f"k{lv}": conformal_q(scores[sel], p) for lv, p in LEVELS}))
        lo = np.inf if hi is None else hi
    return out


def main():
    with open(os.path.join(OUT, "exp6_worldb.csv"), newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["ok"] == "True" and r["bounce"] == "True"]
    folds = np.random.default_rng(SEED).permutation(len(rows)) % 5      # exp6's folds, same order
    out = [dict(i=int(r["i"]), end=r["end"]) for r in rows]
    summary = dict(n=len(rows), seed=SEED, bands=BANDS, ends={})
    rule = {}
    for end in ("striker", "bowler"):
        summary["ends"][end], rule[end] = {}, {}
        for q in QTY:
            idx = np.array([j for j, r in enumerate(rows) if r["end"] == end and fnum(r[f"err_{q}"]) is not None
                            and fnum(r[f"scal_{q}"]) is not None])
            g = lambda k: np.array([fnum(rows[j][f"{k}_{q}"]) for j in idx])
            r_, sf, sc = g("err"), g("sfit"), g("scal")
            s2 = sf ** 2 + sc ** 2
            x = np.array([max(fnum(rows[j]["x_b"]), 0.0) for j in idx])
            f_ = folds[idx]
            b_all, s_all, forms_fold, bias_fold = np.zeros_like(r_), np.zeros_like(r_), [], []
            k_test = {lv: np.zeros_like(r_) for lv, _ in LEVELS}
            for f in range(5):
                tr, te = f_ != f, f_ == f
                bs = dict(factors=bands(x[tr], oof_scores(r_[tr], s2[tr], x[tr], f_[tr])))
                model = fit(r_[tr], s2[tr], x[tr])
                b, s = apply(model, s2[te], x[te])
                b_all[te], s_all[te] = b, s
                for k, (lv, _) in enumerate(LEVELS):
                    k_test[lv][te] = [factors(bs, v)[k] for v in x[te]]
                forms_fold.append(model[1]); bias_fold.append(model[0] is not None)
                for j, jj in enumerate(np.where(te)[0]):
                    o = out[idx[jj]]
                    o[f"bias_{q}"] = float(b[j]); o[f"sigma_{q}"] = float(s[j])
                    o[f"u_{q}"] = float(k_test["68"][jj] * s[j]); o[f"U95_{q}"] = float(k_test["95"][jj] * s[j])
            n = len(r_)
            a = np.abs(r_ - b_all)
            third = np.quantile(x, [1 / 3, 2 / 3])
            tert = np.digitize(x, third)
            ent = dict(n=n, cal_unbounded=sum(r["end"] == end and fnum(r[f"err_{q}"]) is not None for r in rows) - n,
                       forms_fold=forms_fold, bias_fold=bias_fold,
                       mean_err_before_mm=float(np.mean(r_) * 1000), mean_err_after_mm=float(np.mean(r_ - b_all) * 1000),
                       se_mean_mm=float(np.std(r_, ddof=1) / math.sqrt(n) * 1000),
                       x_b_thirds_m=[float(v) for v in third],
                       U95_below_gauss_fitcal_pct=float(100 * np.mean(k_test["95"] * s_all < 1.96 * np.sqrt(s2))),
                       # held out, beyond 1.645 (w95 / 1.96) on each side: 5 % each if that sigma is Gaussian
                       exceed_hi_pct=float(100 * np.mean(r_ - b_all > 1.645 * k_test["95"] * s_all / 1.96)),
                       exceed_lo_pct=float(100 * np.mean(r_ - b_all < -1.645 * k_test["95"] * s_all / 1.96)))
            for lv, p in LEVELS:
                cov = a <= k_test[lv] * s_all
                c = int(cov.sum()); lo, hi = cp_interval(c, n)
                ent[f"cover_{lv}"] = dict(pct=100 * c / n, lo=100 * lo, hi=100 * hi, nominal=100 * p, covered=c)
                ent[f"cover_{lv}_by_third"] = []
                for t in range(3):
                    sel = tert == t
                    ct, nt = int(cov[sel].sum()), int(sel.sum())
                    lo, hi = cp_interval(ct, nt)
                    ent[f"cover_{lv}_by_third"].append(dict(n=nt, pct=100 * ct / nt, lo=100 * lo, hi=100 * hi))
            # the rule the app ships: bias or none by the five folds' summed held-out likelihood, refitted on
            # all of this end's deliveries, factors from out-of-fold scores
            held = {}
            for bias in (False, True):
                ms = [(f_ == f, apply(fit(r_[f_ != f], s2[f_ != f], x[f_ != f], bias), s2[f_ == f], x[f_ == f])) for f in range(5)]
                held["line" if bias else "none"] = sum(nll(r_[te] - b, s ** 2, 0.0) for te, (b, s) in ms)
            bias = held["line"] < held["none"]
            ent["bias_heldout_nll"] = held
            bl, form, p = fit(r_, s2, x, bias)
            rule[end][q] = dict(form=form, params_m=p, x_b_max=float(x.max()), factors=bands(x, oof_scores(r_, s2, x, f_, bias)),
                                bias=None if bl is None else dict(coef_m=bl[0].tolist(), cov_m2=bl[1].tolist()))
            ent["rule"] = rule[end][q]
            ent["bias_line"] = None if bl is None else dict(
                a_mm=float(bl[0][0] * 1000), c_mm_per_m=float(bl[0][1] * 1000),
                u_a_mm=float(math.sqrt(bl[1][0, 0]) * 1000), u_c_mm_per_m=float(math.sqrt(bl[1][1, 1]) * 1000),
                median_u_b_mm=float(np.median(np.sqrt(line_at(bl, x)[1])) * 1000))
            ent["median_u_mm"] = float(np.median([out[j][f"u_{q}"] for j in idx]) * 1000)
            ent["median_U95_mm"] = float(np.median([out[j][f"U95_{q}"] for j in idx]) * 1000)
            if q in ("y", "z"):
                # does the remaining misfit track swing? if not, a swing term would not help
                # swing is world-signed; the lateral error is leg-side signed, so sign swing the same way
                sws = np.array([fnum(rows[j]["swing_ms2"]) * (fnum(rows[j]["leg"]) if q == "y" else 1.0) for j in idx])
                ent["corr_ratio_abs_swing"] = float(np.corrcoef(a / s_all, np.abs(sws))[0, 1])
                ent["r2_err_swing"] = float(np.corrcoef(r_, sws)[0, 1] ** 2)
            summary["ends"][end][q] = ent
    fields = list(dict.fromkeys(k for o in out for k in o))
    with open(os.path.join(OUT, "exp6_calibrated.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(out)
    save_json("exp6_calibrated.json", summary)
    save_json("exp6_rule.json", rule)      # exp7 adds the guard factor and ships it
    for end, qs in summary["ends"].items():
        for q, e in qs.items():
            print(end, q, f"mean {e['mean_err_before_mm']:+.1f} -> {e['mean_err_after_mm']:+.1f} mm",
                  {lv: f"{e[f'cover_{lv}']['pct']:.1f} [{e[f'cover_{lv}']['lo']:.1f}, {e[f'cover_{lv}']['hi']:.1f}]" for lv, _ in LEVELS},
                  "by third 95:", [round(t["pct"], 1) for t in e["cover_95_by_third"]],
                  "rule", e["rule"]["form"], "bias" if e["rule"]["bias"] else "no bias",
                  [(b["x_b_max"] and round(b["x_b_max"], 2), round(b["k95"], 2)) for b in e["rule"]["factors"]])


if __name__ == "__main__":
    main()
