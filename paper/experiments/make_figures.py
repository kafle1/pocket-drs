#!/usr/bin/env python
"""Every figure in the manuscript, from the raw result files.

Usage:  server/.venv/bin/python paper/experiments/make_figures.py
"""
import csv
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import numpy as np                # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
FIGS = os.path.join(os.path.dirname(HERE), "figures")
os.makedirs(FIGS, exist_ok=True)
plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.labelsize": 8.5, "axes.titlesize": 8.5,
    "legend.fontsize": 7.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 300,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
BLUE, ORANGE, GREY, RED = "#1b4965", "#e8a33d", "#6c757d", "#c1666b"


def load(name):
    with open(os.path.join(RAW, name), newline="") as fh:
        return list(csv.DictReader(fh))


def fl(r, k):
    v = r.get(k, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def nanmed(xs):
    xs = [x for x in xs if not math.isnan(x)]
    return float(np.median(xs)) if xs else float("nan")


def fig_geometry():
    """Side view of the model: two parabolas, the contact point on the ground and the camera."""
    fig, ax = plt.subplots(figsize=(3.4, 1.9))
    g, R = 9.81, 0.036
    xb, tb = 6.0, 0.0
    v_pre = np.array([-30.0, -4.5]); v_post = np.array([-27.0, 2.5])
    t = np.linspace(-0.42, 0.0, 60)
    ax.plot(xb + v_pre[0] * t, R + v_pre[1] * t - 0.5 * g * t ** 2, color=BLUE, lw=1.4)
    t = np.linspace(0.0, 0.2, 40)
    ax.plot(xb + v_post[0] * t, R + v_post[1] * t - 0.5 * g * t ** 2, color=BLUE, lw=1.4)
    ax.plot([xb], [R], "o", color=ORANGE, ms=5, zorder=5)
    ax.annotate("contact $(x_b, y_b, R)$ at $t_b$", (xb, R), (xb + 1.5, 0.75), fontsize=7, arrowprops=dict(arrowstyle="-", lw=0.6))
    ax.plot([0, 0], [0, 0.711], color="k", lw=2)
    ax.plot([20.12, 20.12], [0, 0.711], color="k", lw=2)
    ax.plot([1.22, 1.22], [0, 0.3], color=GREY, lw=0.8, ls="--")
    ax.text(1.22, 0.33, "crease", fontsize=6.5, ha="center", color=GREY)
    ax.plot([-2.8], [1.7], "s", color=RED, ms=5)
    ax.text(-2.6, 1.85, "phone", fontsize=7, color=RED)
    for xx in (xb + v_pre[0] * (-0.3), xb + v_pre[0] * (-0.15), xb + v_post[0] * 0.12):
        pass
    ax.text(xb + v_pre[0] * (-0.3) + 0.3, 1.55, r"$\mathbf{v}^-$", color=BLUE, fontsize=8)
    ax.text(xb + v_post[0] * 0.14 - 0.4, 0.42, r"$\mathbf{v}^+$", color=BLUE, fontsize=8)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xlim(-3.5, 21); ax.set_ylim(-0.1, 2.4)
    ax.set_xlabel("$x$ along the pitch (m)"); ax.set_ylabel("$z$ (m)")
    ax.set_aspect("auto"); ax.grid(False)
    fig.savefig(os.path.join(FIGS, "geometry.pdf")); plt.close(fig)


def fig_sweeps():
    g = load("exp1_geometry.csv")
    sweeps = [("noise_px", "Pixel noise (px)", [0.0, 0.5, 1.0, 2.0, 3.0, 5.0]),
              ("fps", "Frame rate (Hz)", [30.0, 60.0, 120.0, 240.0]),
              ("tap_px", "Tap noise (px)", [0.0, 2.0, 4.0, 8.0, 12.0]),
              ("dropout", "Dropped frames", [0.0, 0.1, 0.25, 0.4])]
    fig, axes = plt.subplots(2, 4, figsize=(7.1, 3.4), sharey="row")
    for j, (key, label, vals) in enumerate(sweeps):
        for est, col, mk in (("anchored", BLUE, "o"), ("parabola", ORANGE, "s")):
            ag, my, mz = [], [], []
            for v in vals:
                rs = [r for r in g if r["sweep"] == f"{key}={v}" and r["estimator"] == est]
                ag.append(100.0 * sum(1 for r in rs if r["verdict"] == r["truth"]) / max(1, len(rs)))
                ok = [r for r in rs if r["ok"] == "True"]
                my.append(nanmed([fl(r, "y_err_cm") for r in ok])); mz.append(nanmed([fl(r, "z_err_cm") for r in ok]))
            axes[0, j].plot(vals, ag, marker=mk, ms=3, color=col, label="anchored" if est == "anchored" else "single parabola")
            axes[1, j].plot(vals, my, marker=mk, ms=3, color=col, label=f"lateral $y$")
            axes[1, j].plot(vals, mz, marker=mk, ms=3, color=col, ls="--", label=f"vertical $z$")
        axes[1, j].set_xlabel(label)
        if key == "fps":
            from matplotlib.ticker import NullFormatter, FixedLocator, FixedFormatter
            for ax in (axes[0, j], axes[1, j]):
                ax.set_xscale("log")
                ax.xaxis.set_major_locator(FixedLocator(vals)); ax.xaxis.set_major_formatter(FixedFormatter([f"{int(v)}" for v in vals]))
                ax.xaxis.set_minor_locator(FixedLocator([])); ax.xaxis.set_minor_formatter(NullFormatter())
        axes[1, j].set_yscale("log")
    axes[0, 0].set_ylabel("Verdict agreement (%)"); axes[1, 0].set_ylabel("Median stump-plane error (cm)")
    axes[0, 0].set_ylim(0, 100)
    axes[0, 0].legend(frameon=False, loc="lower left")
    h, l = axes[1, 0].get_legend_handles_labels()
    axes[1, 3].legend([h[0], h[1]], ["lateral $y$", "vertical $z$"], frameon=False, loc="lower right", handlelength=1.8)
    fig.subplots_adjust(hspace=0.35, wspace=0.12)
    fig.savefig(os.path.join(FIGS, "sweeps.pdf")); plt.close(fig)


def fig_coverage():
    g = [r for r in load("exp1_geometry.csv") if r["estimator"] == "anchored" and r["ok"] == "True" and r["bounce_observed"] == "True"]
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.2))
    for ax, c, name in ((axes[0], "y", "lateral $y$"), (axes[1], "z", "vertical $z$")):
        ratio = np.array([fl(r, f"{c}_err_cm") / max(fl(r, f"sigma_{c}_cm"), 1e-3) for r in g])
        ratio = ratio[np.isfinite(ratio)]
        xs = np.linspace(0, 4, 200)
        emp = [np.mean(ratio <= x) for x in xs]
        ax.plot(xs, emp, color=BLUE, lw=1.4, label="observed")
        from math import erf
        ax.plot(xs, [erf(x / math.sqrt(2)) for x in xs], color=GREY, ls="--", lw=1, label="Gaussian")
        ax.set_xlabel(f"$|$error$| / \\sigma$, {name}"); ax.set_ylabel("Fraction of deliveries")
        ax.set_ylim(0, 1.02); ax.set_xlim(0, 4)
        ax.legend(frameon=False, loc="lower right")
    fig.subplots_adjust(wspace=0.3)
    fig.savefig(os.path.join(FIGS, "coverage.pdf")); plt.close(fig)


def fig_kcurve():
    g = [r for r in load("exp1_geometry.csv") if r["estimator"] == "anchored"]
    keys = [("verdict_k0", 0.0), ("verdict_k0.5", 0.5), ("verdict", 1.0), ("verdict_k1.5", 1.5), ("verdict_k2", 2.0)]
    keys = [(k, v) for k, v in keys if k in g[0]]
    n = len(g)
    fo = [100.0 * sum(1 for r in g if r[k] == "out" and r["truth"] == "not_out") / sum(1 for r in g if r["truth"] == "not_out") for k, _ in keys]
    mo = [100.0 * sum(1 for r in g if r[k] == "not_out" and r["truth"] == "out") / max(1, sum(1 for r in g if r["truth"] == "out")) for k, _ in keys]
    um = [100.0 * sum(1 for r in g if r[k] == "umpires_call") / n for k, _ in keys]
    fig, ax = plt.subplots(figsize=(3.4, 2.2))
    ks = [v for _, v in keys]
    ax.plot(ks, fo, marker="o", ms=3.5, color=RED, label="false out (% of not-out)")
    ax.plot(ks, mo, marker="s", ms=3.5, color=ORANGE, label="missed out (% of out)")
    ax.set_ylabel("Error rate (%)"); ax.set_xlabel("Band widening $k$ (multiples of $\\sigma$)")
    ax2 = ax.twinx()
    ax2.plot(ks, um, marker="^", ms=3.5, color=BLUE, label="umpire's call (% of all)")
    ax2.set_ylabel("Umpire's call (%)"); ax2.grid(False); ax2.spines["top"].set_visible(False)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper center", fontsize=6.5)
    fig.savefig(os.path.join(FIGS, "kcurve.pdf")); plt.close(fig)


def fig_cameras():
    g = load("exp1_geometry.csv")
    cams = ["striker_low", "striker_ref", "striker_high", "striker_side", "bowler_ref", "bowler_side"]
    lab = ["S low", "S ref", "S high", "S side", "B ref", "B side"]
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.2))
    x = np.arange(len(cams))
    for est, col, off in (("anchored", BLUE, -0.18), ("parabola", ORANGE, 0.18)):
        ag, my, mz = [], [], []
        for c in cams:
            rs = [r for r in g if r["sweep"] == f"camera={c}" and r["estimator"] == est]
            ag.append(100.0 * sum(1 for r in rs if r["verdict"] == r["truth"]) / max(1, len(rs)))
            ok = [r for r in rs if r["ok"] == "True"]
            my.append(nanmed([fl(r, "y_err_cm") for r in ok])); mz.append(nanmed([fl(r, "z_err_cm") for r in ok]))
        axes[0].bar(x + off, ag, width=0.36, color=col, label="anchored" if est == "anchored" else "single parabola")
        axes[1].bar(x + off, my, width=0.36, color=col, alpha=0.9)
        axes[1].bar(x + off, mz, width=0.36, color="none", edgecolor=col, lw=1.0)
    axes[0].set_xticks(x); axes[0].set_xticklabels(lab); axes[0].set_ylabel("Verdict agreement (%)"); axes[0].set_ylim(0, 100)
    axes[0].legend(frameon=False, loc="lower left")
    axes[1].set_xticks(x); axes[1].set_xticklabels(lab); axes[1].set_ylabel("Median error (cm): $y$ filled, $z$ outline")
    axes[1].set_yscale("log")
    fig.subplots_adjust(wspace=0.3)
    fig.savefig(os.path.join(FIGS, "cameras.pdf")); plt.close(fig)


def fig_rendered():
    e = load("exp2_rendered_striker_ref.csv")
    lengths = sorted({fl(r, "length_m") for r in e}); lines = sorted({fl(r, "line_m") for r in e})
    grid = np.zeros((len(lines), len(lengths)))
    for i, ln in enumerate(lines):
        for j, lg in enumerate(lengths):
            rs = [r for r in e if fl(r, "length_m") == lg and fl(r, "line_m") == ln]
            grid[i, j] = 100.0 * sum(1 for r in rs if r["verdict"] == r["truth"]) / max(1, len(rs))
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.4))
    im = axes[0].imshow(grid, cmap="Blues", vmin=0, vmax=100, aspect="auto", origin="lower")
    axes[0].set_xticks(range(len(lengths))); axes[0].set_xticklabels([f"{l:g}" for l in lengths])
    axes[0].set_yticks(range(len(lines))); axes[0].set_yticklabels([f"{l:+.1f}" for l in lines])
    axes[0].set_xlabel("Pitching length (m)"); axes[0].set_ylabel("Line (m, + leg)"); axes[0].grid(False)
    for i in range(len(lines)):
        for j in range(len(lengths)):
            axes[0].text(j, i, f"{grid[i, j]:.0f}", ha="center", va="center", fontsize=7, color="white" if grid[i, j] > 60 else "black")
    fig.colorbar(im, ax=axes[0], fraction=0.046, pad=0.03, label="Agreement (%)")
    ok = [r for r in e if r.get("y_err_cm") not in ("", None)]
    cols = {"not_out": GREY, "out": RED, "umpires_call": ORANGE}
    for cls, c in cols.items():
        rs = [r for r in ok if r["verdict"] == cls]
        axes[1].scatter([fl(r, "y_err_cm") for r in rs], [fl(r, "z_err_cm") for r in rs], s=12, color=c,
                        label={"not_out": "not out", "out": "out", "umpires_call": "umpire's call"}[cls], alpha=0.85, edgecolors="none")
    axes[1].set_xlabel("Lateral error $|y|$ (cm)"); axes[1].set_ylabel("Vertical error $|z|$ (cm)")
    axes[1].set_xscale("symlog", linthresh=1); axes[1].set_yscale("symlog", linthresh=1)
    axes[1].legend(frameon=False, title="returned verdict", fontsize=6.5, title_fontsize=6.5)
    fig.subplots_adjust(wspace=0.35)
    fig.savefig(os.path.join(FIGS, "rendered.pdf")); plt.close(fig)


if __name__ == "__main__":
    for fn in (fig_geometry, fig_sweeps, fig_coverage, fig_kcurve, fig_cameras, fig_rendered):
        fn(); print("ok", fn.__name__)
    print("figures written to", FIGS)
