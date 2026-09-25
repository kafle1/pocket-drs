"""Experiment 8: unmodelled physics one effect at a time, and sensitivity to the taps.

Part 1, physics. 200 deliveries drawn once (speed 60-150 km/h, length 1-10 m, line
+-0.6 m, release height 1.8-2.3 m). The baseline is the estimator's own model: no drag,
no swing, restitution 0.55, friction 0.10, no turn. Each row switches on one effect at a
literature magnitude, on the same deliveries, taps, frame phase and noise seeds:
  drag           Cd 0.35 / 0.45 / 0.55            (Mehta 2005 gives ~0.4 to 0.5 for a new ball)
  swing          side-force Cs 0.1 / 0.2 / 0.3     (Mehta 2005: up to ~0.3), sign drawn per delivery
  seam           1 / 2 / 3 deg off the pitch       (assumed; sign drawn per delivery)
  spin           speed 70-95 km/h, turn 0 / 3 / 6 deg (assumed; 0 deg is the slow-ball baseline)
  restitution    0.40 / 0.70 / U[0.40, 0.70]      (James et al. 2004 pitch range)
  friction       0.20
  combined pace  Cd U[.35,.55], Cs U[-.3,.3], seam U[-2,2] deg, e U[.4,.7], friction U[.05,.2]
Measurement effects are exp1's (1 px centres, 10 % radius, 5 % dropout, 2 px taps, 60 fps)
plus 0.5 ms frame-time jitter, frames labelled with their own timestamps. sigma_cal is
computed once per delivery on the baseline (uq.cal_sigma) and sigma_mod comes from exp6's
cross-validated model applied at each fit's own bounce distance.

Part 2, taps. The first 300 deliveries of exp6's World B, reproduced exactly (same taps,
same detections; the unperturbed estimate is checked against exp6's). Every tap is moved
by d = 2, 5, 10 px in a random direction, or all twelve by +-d px in v (a consistent
high or low tap). Reported: how far the stump-plane point moves and how many verdicts
flip, under the shipped rule (sigma_fit, k = 1) and under the full sigma with the k
chosen in exp7 at 1 % and 5 %.

    python exp8_physics.py                 # both parts, then the summary
    python exp8_physics.py --part physics  # or taps; --summary-only re-reads the CSVs
"""
from __future__ import annotations

import argparse
import csv
import math
import multiprocessing as mp
import os
import time

import numpy as np

from uq import (Effects, Delivery, fly, REF_CAM, QTY, taps, solve, observe, truth_q, estimate, cal_sigma,
                replace, OUT, save_json, load_json, verdict, CalibrationError)
from synth import random_delivery

SEED = 808
N_PHYS = 200
N_TAPS = 300
TAP_PX = 2.0
DEG = math.pi / 180
EFF = Effects(tap_px=TAP_PX, noise_px=1.0, radius_noise=0.10, dropout=0.05, fps=60.0, jitter_s=5e-4)
ROWS = ["baseline", "drag Cd 0.35", "drag Cd 0.45", "drag Cd 0.55", "swing Cs 0.1", "swing Cs 0.2", "swing Cs 0.3",
        "seam 1 deg", "seam 2 deg", "seam 3 deg", "spin 0 deg", "spin 3 deg", "spin 6 deg",
        "restitution 0.40", "restitution 0.70", "restitution U[0.40,0.70]", "friction 0.20", "combined pace"]
TAP_CASES = [("random", 2.0), ("random", 5.0), ("random", 10.0),
             ("v shift", 2.0), ("v shift", -2.0), ("v shift", 5.0), ("v shift", -5.0), ("v shift", 10.0), ("v shift", -10.0)]


def base(i):
    """Delivery i's geometry and its per-delivery draws, identical on every call."""
    rng = np.random.default_rng([SEED, i])
    d = replace(random_delivery(rng, physics=False), restitution=0.55)
    U = rng.uniform
    sign = lambda: 1.0 if rng.random() < 0.5 else -1.0         # noqa: E731
    draws = dict(s_swing=sign(), s_seam=sign(), s_turn=sign(), spin_kmh=U(70, 95), e_u=U(0.40, 0.70),
                 cd=U(0.35, 0.55), cs=U(-0.3, 0.3), seam=U(-2.0, 2.0), e=U(0.40, 0.70), fr=U(0.05, 0.20),
                 v0=0.3 + U(0.0, 1.0 / EFF.fps))
    return d, draws


def with_turn(d: Delivery, deg: float) -> Delivery:
    """Add a lateral kick at contact that turns the ground track by deg."""
    if deg == 0:
        return d
    st = fly(d, dt=5e-4)
    i = max(2, int(np.searchsorted(st.states[:, 0], st.contact_t)))
    vx = abs(st.states[i - 1, 1] - st.states[i - 2, 1]) / (st.states[i - 1, 0] - st.states[i - 2, 0])
    return replace(d, turn_ms=math.tan(deg * DEG) * (1.0 - d.friction) * vx)


def row_delivery(d: Delivery, w: dict, row: str) -> Delivery:
    if row.startswith("drag"):
        return replace(d, drag=True, cd=float(row.split()[-1]))
    if row.startswith("swing"):
        return replace(d, cs=w["s_swing"] * float(row.split()[-1]))
    if row.startswith("seam"):
        return with_turn(d, w["s_seam"] * float(row.split()[1]))
    if row.startswith("spin"):
        return with_turn(replace(d, speed_kmh=w["spin_kmh"]), w["s_turn"] * float(row.split()[1]))
    if row == "restitution U[0.40,0.70]":
        return replace(d, restitution=w["e_u"])
    if row.startswith("restitution"):
        return replace(d, restitution=float(row.split()[-1]))
    if row.startswith("friction"):
        return replace(d, friction=float(row.split()[-1]))
    if row == "combined pace":
        return with_turn(replace(d, drag=True, cd=w["cd"], cs=w["cs"], restitution=w["e"], friction=w["fr"]), w["seam"])
    return d


def phys_job(args):
    i, row = args
    import cv2; cv2.setNumThreads(1)
    d0, w = base(i)
    out = dict(part="physics", i=i, row=row, ok=False, bounce=False)
    try:
        d = row_delivery(d0, w, row)
        tr = fly(d, dt=5e-4)
    except ValueError:
        return out
    pt = REF_CAM.pose()
    xy = taps(pt, EFF, np.random.default_rng([SEED, i, 1]))
    try:
        pose = solve(pt, xy)
    except CalibrationError:
        return out
    dets = observe(tr, pt, EFF, np.random.default_rng([SEED, i, 2]), v0=w["v0"])
    est = estimate(pose, dets)
    tq = truth_q(tr)
    out.update({f"truth_{q}": tq[q] for q in QTY})
    out["speed_kmh"] = d.speed_kmh
    if est is None:
        return out
    out.update(ok=True, bounce=est["bounce"], x_b=est["x_b"])
    for q in QTY:
        out[f"est_{q}"] = est[q]
        out[f"sfit_{q}"] = est["s_" + q]
    if row == "baseline":
        sc = cal_sigma(pt, xy, dets, np.array([np.nan if est[q] is None else est[q] for q in QTY]), TAP_PX)
        out.update({f"scal_{q}": float(v) for q, v in zip(QTY, sc)})
    return out


def tap_job(i):
    """exp6 World B delivery i, unperturbed and under every tap case."""
    import cv2; cv2.setNumThreads(1)
    from exp6_coverage import draw
    d, eff, rng = draw(i)
    res = []
    try:
        tr = fly(d, dt=5e-4)
    except ValueError:
        return res
    pt = REF_CAM.pose()
    xy = taps(pt, eff, rng)
    try:
        pose = solve(pt, xy)
    except CalibrationError:
        return res
    dets = observe(tr, pt, eff, rng)
    cases = [("none", 0.0, xy)]
    for kind, dpx in TAP_CASES:
        if kind == "random":
            phi = np.random.default_rng([SEED + 1, i, int(dpx)]).uniform(0, 2 * math.pi, len(xy))
            cases.append((kind, dpx, xy + dpx * np.column_stack([np.cos(phi), np.sin(phi)])))
        else:
            cases.append((kind, dpx, xy + np.array([0.0, dpx])))
    for kind, dpx, z in cases:
        row = dict(part="taps", i=i, case=kind, d_px=dpx, ok=False)
        try:
            est = estimate(solve(pt, z), dets)
        except CalibrationError:
            est = None
        if est is not None:
            row.update(ok=True, bounce=est["bounce"], x_b=est["x_b"])
            for q in QTY:
                row[f"est_{q}"] = est[q]
                row[f"sfit_{q}"] = est["s_" + q]
        res.append(row)
    return res


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #

def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def read(name):
    with open(os.path.join(OUT, name), newline="") as fh:
        return list(csv.DictReader(fh))


def write(name, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def smod_fn():
    """exp6's chosen model-error form per measurand, as a function of x_b (metres)."""
    me = load_json("exp6_model_error.json")["forms"]
    def f(q, xb):
        p, form = me[q]["params_m"], me[q]["chosen"]
        xb = max(xb, 0.0)
        if form == "constant":
            return p[0]
        if form == "proportional to x_b":
            return p[0] * xb
        return math.hypot(p[0], p[1] * xb)
    return f


def chosen_k():
    try:
        ch = load_json("exp7_risk.json")["chosen"]["full"]
        return {a: ch[a]["k_specific"] for a in ("0.01", "0.05")}
    except (OSError, KeyError):
        return {}


def sigmas(r, scal, smod):
    sf = {q: fnum(r.get(f"sfit_{q}")) or 0.0 for q in QTY}
    xb = fnum(r.get("x_b")) or 0.0
    full = {q: math.sqrt(sf[q] ** 2 + (scal.get(q) or 0.0) ** 2 + smod(q, xb) ** 2) for q in QTY}
    return sf, full


def est_of(r):
    return {q: fnum(r.get(f"est_{q}")) for q in QTY}


def cov(e, s):
    a = np.abs(np.asarray(e)) / np.maximum(np.asarray(s), 1e-9)
    return float(100 * np.mean(a <= 1.0)), float(100 * np.mean(a <= 1.96))


def summarise_physics(ks):
    rows = read("exp8_physics.csv")
    smod = smod_fn()
    scal = {r["i"]: {q: fnum(r.get(f"scal_{q}")) for q in QTY} for r in rows if r["row"] == "baseline"}
    zero = {q: 0.0 for q in QTY}
    out = {}
    for name in ROWS:
        rr = [r for r in rows if r["row"] == name and r["ok"] == "True" and r["bounce"] == "True"
              and all(fnum(r.get(f"est_{q}")) is not None for q in ("crease_y", "y", "z"))]
        ent = dict(n=len(rr))
        agree = {"fit k=1": 0}
        agree.update({f"full k={ks[a]}": 0 for a in ks if ks[a] is not None})
        ump = dict.fromkeys(agree, 0)
        for q in ("pitch_y", "y", "z"):
            e, sf_, sfull = [], [], []
            for r in rr:
                est, tru = fnum(r.get(f"est_{q}")), fnum(r.get(f"truth_{q}"))
                if est is None or tru is None:
                    continue
                sf, full = sigmas(r, scal.get(r["i"], {}), smod)
                e.append(est - tru); sf_.append(sf[q]); sfull.append(full[q])
            if not e:
                continue
            ent[q] = dict(median_abs_mm=float(np.median(np.abs(e)) * 1000), p90_abs_mm=float(np.percentile(np.abs(e), 90) * 1000),
                          mean_mm=float(np.mean(e) * 1000), cov_fit=cov(e, sf_), cov_full=cov(e, sfull))
        for r in rr:
            tru = {q: fnum(r.get(f"truth_{q}")) for q in QTY}
            tv = verdict(tru, zero, 0.0)
            sf, full = sigmas(r, scal.get(r["i"], {}), smod)
            for key in agree:
                s, k = (sf, 1.0) if key == "fit k=1" else (full, float(key.split("=")[1]))
                v = verdict(est_of(r), s, k)
                agree[key] += v == tv
                ump[key] += v == "umpires_call"
        ent["agree_pct"] = {k: 100 * v / max(len(rr), 1) for k, v in agree.items()}
        ent["ump_pct"] = {k: 100 * v / max(len(rr), 1) for k, v in ump.items()}
        out[name] = ent
    return out


def summarise_taps(ks):
    rows = read("exp8_taps.csv")
    smod = smod_fn()
    ref = {r["i"]: r for r in read("exp6_worldb.csv")}
    scal = {i: {q: fnum(r.get(f"scal_{q}")) for q in QTY} for i, r in ref.items()}
    base = {r["i"]: r for r in rows if r["case"] == "none" and r["ok"] == "True"}
    # the unperturbed fit must be exp6's fit, bit for bit up to float printing
    mism = sum(1 for i, r in base.items() if i in ref and any(
        (fnum(r.get(f"est_{q}")) is None) != (fnum(ref[i].get(f"est_{q}")) is None) or
        (fnum(r.get(f"est_{q}")) is not None and abs(fnum(r[f"est_{q}"]) - fnum(ref[i][f"est_{q}"])) > 1e-9) for q in QTY))
    rules = {"fit k=1": None}
    rules.update({f"full k={ks[a]}": ks[a] for a in ks if ks[a] is not None})
    out = dict(n_deliveries=len(base), mismatch_vs_exp6=mism, cases={})
    for kind, dpx in TAP_CASES:
        key = f"{kind} {dpx:+g} px" if kind == "v shift" else f"{kind} {dpx:g} px"
        rr = [r for r in rows if r["case"] == kind and float(r["d_px"]) == dpx and r["i"] in base]
        dy, dz, dc, flips, fails = [], [], [], dict.fromkeys(rules, 0), 0
        hard = dict.fromkeys(rules, 0)
        for r in rr:
            b = base[r["i"]]
            if r["ok"] != "True" or fnum(r.get("est_y")) is None:
                fails += 1
                continue
            dy.append(abs(fnum(r["est_y"]) - fnum(b["est_y"]))); dz.append(abs(fnum(r["est_z"]) - fnum(b["est_z"])))
            dc.append(abs(fnum(r["est_crease_y"]) - fnum(b["est_crease_y"])))
            for name, k in rules.items():
                sb_fit, sb_full = sigmas(b, scal.get(r["i"], {}), smod)
                sr_fit, sr_full = sigmas(r, scal.get(r["i"], {}), smod)
                if k is None:
                    va, vb = verdict(est_of(r), sr_fit, 1.0), verdict(est_of(b), sb_fit, 1.0)
                else:
                    va, vb = verdict(est_of(r), sr_full, k), verdict(est_of(b), sb_full, k)
                flips[name] += va != vb
                hard[name] += {va, vb} == {"out", "not_out"}     # straight across, no umpire's call between
        n = len(rr) - fails
        out["cases"][key] = dict(n=n, failed=fails,
                                 median_dy_mm=float(np.median(dy) * 1000) if dy else None,
                                 p90_dy_mm=float(np.percentile(dy, 90) * 1000) if dy else None,
                                 median_dz_mm=float(np.median(dz) * 1000) if dz else None,
                                 p90_dz_mm=float(np.percentile(dz, 90) * 1000) if dz else None,
                                 median_dcrease_mm=float(np.median(dc) * 1000) if dc else None,
                                 flips={k: int(v) for k, v in flips.items()},
                                 out_notout_flips={k: int(v) for k, v in hard.items()},
                                 flip_pct={k: 100 * v / max(n, 1) for k, v in flips.items()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=("physics", "taps", "both"), default="both")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    t0 = time.time()
    secs = {}
    if not a.summary_only:
        with mp.get_context("spawn").Pool(a.workers) as pool:
            if a.part in ("physics", "both"):
                jobs = [(i, "baseline") for i in range(N_PHYS)] + [(i, r) for r in ROWS[1:] for i in range(N_PHYS)]
                rows = pool.map(phys_job, jobs, chunksize=1)
                write("exp8_physics.csv", rows)
                secs["physics"] = round(time.time() - t0, 1)
                print(f"physics: {sum(r['ok'] for r in rows)}/{len(rows)} fitted in {secs['physics']:.0f} s", flush=True)
            if a.part in ("taps", "both"):
                t1 = time.time()
                rows = [r for rs in pool.map(tap_job, range(N_TAPS), chunksize=1) for r in rs]
                write("exp8_taps.csv", rows)
                secs["taps"] = round(time.time() - t1, 1)
                print(f"taps: {len(rows)} fits in {secs['taps']:.0f} s", flush=True)
    ks = chosen_k()
    prev = {}
    try:
        prev = load_json("exp8_physics.json")
    except OSError:
        pass
    summary = dict(seed=SEED, n_physics=N_PHYS, n_taps=N_TAPS, k_from_exp7=ks,
                   seconds={**prev.get("seconds", {}), **secs})
    if os.path.exists(os.path.join(OUT, "exp8_physics.csv")):
        summary["physics"] = summarise_physics(ks)
    if os.path.exists(os.path.join(OUT, "exp8_taps.csv")):
        summary["taps"] = summarise_taps(ks)
    save_json("exp8_physics.json", summary)
    for name, ent in summary.get("physics", {}).items():
        print(f"{name:26s} n={ent['n']:3d} " + " ".join(
            f"{q}: {ent[q]['median_abs_mm']:6.1f} mm cov {ent[q]['cov_full'][0]:3.0f}/{ent[q]['cov_full'][1]:3.0f}"
            for q in ("y", "z") if q in ent) + "  agree " + " ".join(f"{v:.1f}" for v in ent["agree_pct"].values()))
    t = summary.get("taps")
    if t:
        print(f"taps: {t['n_deliveries']} deliveries, {t['mismatch_vs_exp6']} differ from exp6")
        for key, ent in t["cases"].items():
            print(f"{key:18s} n={ent['n']} dy {ent['median_dy_mm']:.1f}/{ent['p90_dy_mm']:.1f} mm "
                  f"dz {ent['median_dz_mm']:.1f}/{ent['p90_dz_mm']:.1f} mm flips {ent['flips']}")
    print(f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
