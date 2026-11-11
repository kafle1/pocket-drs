"""Experiment 7: the umpire's-call guard band as a JCGM 106 decision rule.

Runs on exp6's World B deliveries (raw/exp6_worldb.csv, anchored fits that saw the bounce).
For every guard factor k on a 0.05 grid the tool verdict decide(k) is compared with the
ICC rule applied to the true path (k = 0, sigma = 0), under three 1-sigma sets:
  fit          the pipeline's own covariance, as shipped
  fit+cal      plus tap noise through the calibration (exp6 sigma_cal)
  full         plus the cross-validated model error (exp6 sigma_mod, out of fold)
  calibrated   exp6_calibrate: bias removed from each estimate, sigma scaled so its Gaussian
               95 % interval is the held-out conformal U95 (U95 / 1.96), the conservative
               choice when the tails are heavier than Gaussian

Specific risk (JCGM 106 clause 9.3, flat prior, independent Gaussian errors per test):
  false out      = P(some test clearly fails on the true path | the estimate), for OUT calls
  missed out     = P(every test fully passes on the true path | the estimate), for NOT OUT calls
Global risk (clause 9.4) is counted directly against the known truth: joint rate over all
deliveries and the rate among OUT calls, with a Clopper-Pearson 95 % upper limit.

k is chosen from a maximum specific false-out risk alpha in {1 %, 5 %}: the smallest grid k
from which every OUT call on the grid has specific risk <= alpha. The closed-form bounds
are printed next to it: 1 - Phi(k) = alpha for one binding test, and
1 - Phi(k)^4 = alpha when all four tests sit on their boundaries at once.

The calibrated set's k at alpha = 5 % is added as guard_k to exp6_calibrate's rule
(raw/exp6_rule.json), and the whole rule is written to the app's file (uncertainty.RULE_PATH).

    python exp7_risk.py      # needs raw/exp6_worldb.csv and exp6_calibrate's output; takes seconds
"""
from __future__ import annotations

import csv
import json
import math
import os
import time

import numpy as np
from scipy.stats import beta, norm

from uq import QTY, OUT, verdict, specific_risk, save_json, load_json
from app.pipeline.uncertainty import RULE_PATH

K_GRID = np.round(np.arange(0.0, 3.0001, 0.05), 2)
ALPHAS = (0.01, 0.05)
GUARD_ALPHA = "0.05"
SETS = ("fit", "fit+cal", "full", "calibrated")


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def load_cal():
    with open(os.path.join(OUT, "exp6_calibrated.csv"), newline="") as fh:
        return {int(r["i"]): r for r in csv.DictReader(fh)}


def load_rows():
    rows = []
    cal = load_cal()
    with open(os.path.join(OUT, "exp6_worldb.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            if r["ok"] != "True" or r["bounce"] != "True":
                continue
            est = {q: fnum(r[f"est_{q}"]) for q in QTY}
            tru = {q: fnum(r[f"truth_{q}"]) for q in QTY}
            # no stump-plane crossing gives umpire's call or a clear fail, as in the app, so those rows stay
            if est["impact_y"] is None or any(tru[q] is None for q in ("impact_y", "y", "z")):
                continue
            sf = {q: fnum(r[f"sfit_{q}"]) or 0.0 for q in QTY}
            sc = {q: float(r.get(f"scal_{q}") or 0.0) for q in QTY}     # inf when a perturbed solve failed
            sm = {q: fnum(r.get(f"smod_{q}")) or 0.0 for q in QTY}
            sig = {"fit": sf,
                   "fit+cal": {q: float(np.hypot(sf[q], sc[q])) for q in QTY},
                   "full": {q: float(np.sqrt(sf[q] ** 2 + sc[q] ** 2 + sm[q] ** 2)) for q in QTY}}
            # exp6_calibrate leaves out a quantity whose sigma_cal is unbounded: no bias, infinite U95, as in the app
            c = {k: fnum(v) for k, v in cal[int(r["i"])].items()}
            sig["calibrated"] = {q: math.inf if c.get(f"U95_{q}") is None else c[f"U95_{q}"] / 1.96 for q in QTY}
            est_c = {q: None if est[q] is None else est[q] - (c.get(f"bias_{q}") or 0.0) for q in QTY}
            zero = {q: 0.0 for q in QTY}
            rows.append(dict(i=int(r["i"]), est=est, est_c=est_c, sig=sig, truth=verdict(tru, zero, 0.0)))
    return rows


def cp_upper(x, n, conf=0.95):
    """One-sided Clopper-Pearson upper limit on a binomial rate."""
    return 1.0 if n == 0 else float(beta.ppf(conf, x + 1, n - x)) if x < n else 1.0


def curve(rows, sset):
    out = []
    ek = "est_c" if sset == "calibrated" else "est"
    risks = [specific_risk(r[ek], r["sig"][sset]) for r in rows]
    n = len(rows)
    n_true_out = sum(r["truth"] == "out" for r in rows)
    n_true_no = sum(r["truth"] == "not_out" for r in rows)
    for k in K_GRID:
        v = [verdict(r[ek], r["sig"][sset], float(k)) for r in rows]
        t = [r["truth"] for r in rows]
        outs = [j for j, x in enumerate(v) if x == "out"]
        nots = [j for j, x in enumerate(v) if x == "not_out"]
        fo = sum(t[j] == "not_out" for j in outs)
        mo = sum(t[j] == "out" for j in nots)
        sp_fo = [risks[j][0] for j in outs]
        sp_mo = [risks[j][1] for j in nots]
        out.append(dict(
            sigma_set=sset, k=float(k), n=n,
            agree_pct=100 * float(np.mean([a == b for a, b in zip(v, t)])),
            out_pct=100 * len(outs) / n, ump_pct=100 * sum(x == "umpires_call" for x in v) / n,
            not_out_pct=100 * len(nots) / n,
            false_out=fo, false_out_joint_pct=100 * fo / n,
            false_out_among_out_pct=100 * fo / len(outs) if outs else 0.0,
            false_out_joint_cp95_pct=100 * cp_upper(fo, n),
            false_out_given_true_not_out_pct=100 * fo / n_true_no if n_true_no else 0.0,
            out_on_true_ump=sum(t[j] == "umpires_call" for j in outs),
            missed_out=mo, missed_out_joint_pct=100 * mo / n,
            missed_out_given_true_out_pct=100 * mo / n_true_out if n_true_out else 0.0,
            true_out_to_ump_pct=100 * sum(t[j] == "out" and v[j] == "umpires_call" for j in range(n)) / n_true_out
            if n_true_out else 0.0,
            true_out_called_out=sum(t[j] == "out" and v[j] == "out" for j in range(n)),
            max_specific_false_out_pct=100 * max(sp_fo) if sp_fo else 0.0,
            mean_specific_false_out_pct=100 * float(np.mean(sp_fo)) if sp_fo else 0.0,
            max_specific_missed_out_pct=100 * max(sp_mo) if sp_mo else 0.0,
            mean_specific_missed_out_pct=100 * float(np.mean(sp_mo)) if sp_mo else 0.0,
        ))
    return out


def smallest_k(rows, key, alpha_pct):
    """Smallest grid k from which rows[key] <= alpha for the rest of the grid."""
    ok = [r[key] <= alpha_pct + 1e-12 for r in rows]
    for j in range(len(rows)):
        if all(ok[j:]):
            return rows[j]["k"]
    return None


def at(rows, k):
    return min(rows, key=lambda r: abs(r["k"] - k))


def main():
    t0 = time.time()
    rows = load_rows()
    truth_mix = {c: sum(r["truth"] == c for r in rows) for c in ("out", "umpires_call", "not_out")}
    table = []
    for s in SETS:
        table += curve(rows, s)
    with open(os.path.join(OUT, "exp7_risk_curve.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader(); w.writerows(table)

    bounds = {f"{a:g}": dict(single_test=float(norm.ppf(1 - a)), four_tests=float(norm.ppf((1 - a) ** 0.25)))
              for a in ALPHAS}
    summary = dict(n=len(rows), truth_mix=truth_mix, k_grid=[float(K_GRID[0]), float(K_GRID[-1]), 0.05],
                   bounds=bounds, chosen={}, at_k={}, seconds=None)
    for s in SETS:
        cur = [r for r in table if r["sigma_set"] == s]
        ch = {}
        for a in ALPHAS:
            kk = smallest_k(cur, "max_specific_false_out_pct", 100 * a)
            kg = smallest_k(cur, "false_out_joint_pct", 100 * a)
            ch[f"{a:g}"] = dict(k_specific=kk, k_global_joint=kg,
                                at_k_specific=at(cur, kk) if kk is not None else None)
        summary["chosen"][s] = ch
        summary["at_k"][s] = {f"{k:g}": at(cur, k) for k in (0.0, 1.0, 1.645, 1.96, 2.0, 2.326, 2.5, 3.0)}
    guard_k = summary["chosen"]["calibrated"][GUARD_ALPHA]["k_specific"]
    if guard_k is None:
        raise SystemExit(f"no guard factor on the grid keeps the calibrated specific risk under {GUARD_ALPHA}")
    # the shipped rule: calibrated U95 / 1.96 at guard_k; its OUT calls are also scored with the uncalibrated full sigma
    summary["shipped"] = at([r for r in table if r["sigma_set"] == "calibrated"], guard_k)
    shipped_outs = [r for r in rows if verdict(r["est_c"], r["sig"]["calibrated"], guard_k) == "out"]
    sp = [specific_risk(r["est"], r["sig"]["full"])[0] for r in shipped_outs]
    summary["shipped"]["max_specific_false_out_full_sigma_pct"] = 100 * max(sp) if sp else 0.0
    summary["shipped"]["mean_specific_false_out_full_sigma_pct"] = 100 * float(np.mean(sp)) if sp else 0.0
    summary["shipped"]["outs_over_5pct_full_sigma"] = int(sum(x > 0.05 for x in sp))
    sp = [specific_risk(r["est_c"], r["sig"]["calibrated"])[0] for r in shipped_outs]
    summary["shipped"]["max_specific_false_out_cal_sigma_pct"] = 100 * max(sp) if sp else 0.0
    summary["shipped"]["outs_over_5pct_cal_sigma"] = int(sum(x > 0.05 for x in sp))
    # the former rule, fit sigma and k = 1, with its OUT calls scored under the calibrated U95 / 1.96
    sp = [specific_risk(r["est_c"], r["sig"]["calibrated"])[0] for r in rows if verdict(r["est"], r["sig"]["fit"], 1.0) == "out"]
    summary["former"] = dict(outs=len(sp), max_specific_false_out_cal_sigma_pct=100 * max(sp) if sp else 0.0,
                             outs_over_5pct_cal_sigma=int(sum(x > 0.05 for x in sp)))
    rule = load_json("exp6_rule.json")
    rule["guard_k"] = guard_k
    with open(RULE_PATH, "w") as fh:
        json.dump(rule, fh, indent=2)
    summary["seconds"] = round(time.time() - t0, 1)
    save_json("exp7_risk.json", summary)

    print(f"n={len(rows)} truth {truth_mix}")
    print("bounds", {a: {k: round(v, 3) for k, v in b.items()} for a, b in bounds.items()})
    for s in SETS:
        for a, c in summary["chosen"][s].items():
            r = c["at_k_specific"]
            tail = "" if r is None else (f" agree {r['agree_pct']:.1f}% ump {r['ump_pct']:.1f}% out {r['out_pct']:.1f}% "
                                         f"false out {r['false_out']} ({r['false_out_joint_pct']:.2f}%, cp95 "
                                         f"{r['false_out_joint_cp95_pct']:.2f}%) missed {r['missed_out']}")
            print(f"{s:8s} alpha {a:>4s}: k_spec {c['k_specific']} k_glob {c['k_global_joint']}{tail}")
    r = summary["shipped"]
    print(f"shipped (calibrated, k={guard_k}): agree {r['agree_pct']:.1f}% ump {r['ump_pct']:.1f}% false out {r['false_out']} "
          f"max spec {r['max_specific_false_out_pct']:.1f}% (full sigma {r['max_specific_false_out_full_sigma_pct']:.1f}%, "
          f"{r['outs_over_5pct_full_sigma']} outs over 5 %)")
    print(f"{summary['seconds']} s")


if __name__ == "__main__":
    main()
