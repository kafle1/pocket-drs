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
    fig, axes = plt.subplots(2, 4, figsize=(7.1, 2.7), sharey="row")
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
    axes[0, 0].set_ylabel("Agreement (%)"); axes[1, 0].set_ylabel("Median error (cm)")
    axes[0, 0].set_ylim(0, 100)
    axes[0, 0].legend(frameon=False, loc="lower left")
    h, l = axes[1, 0].get_legend_handles_labels()
    axes[1, 3].legend([h[0], h[1]], ["lateral $y$", "vertical $z$"], frameon=False, loc="lower right", handlelength=1.8)
    fig.subplots_adjust(hspace=0.35, wspace=0.12)
    fig.savefig(os.path.join(FIGS, "sweeps.pdf")); plt.close(fig)


def fig_coverage():
    g = [r for r in load("exp1_geometry.csv") if r["estimator"] == "anchored" and r["ok"] == "True" and r["bounce_observed"] == "True"]
    fig, axes = plt.subplots(1, 2, figsize=(3.4, 1.7))
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


if __name__ == "__main__":
    for fn in (fig_geometry, fig_sweeps, fig_coverage):
        fn(); print("ok", fn.__name__)
    print("figures written to", FIGS)
