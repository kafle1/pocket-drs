#!/usr/bin/env python
"""Side checks quoted in CRLB-NOTES.md that crlb.py does not write out.

1. Conditioning against frame spacing h = 1/fps for the minimal frame counts, in general
   position and in the degenerate in-plane geometry, and how it recovers off the plane.
   Also which crossing component is estimable in each (N-, N+) cell.
2. Proposition 3: with g = 0 the null vector of a camera at contact height is the central
   scaling about the camera centre; gravity breaks it.
3. Depth: how much of the crossing bound comes from error along the camera ray.
4. The analytic null direction with one post-contact frame, and the in-plane rule with a camera
   that is not mirror-symmetric about the delivery plane.
Deterministic (no noise draws). Usage:  <venv>/bin/python paper/theory/checks.py
"""
import math
import os
import sys

from dataclasses import replace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crlb import (OUT, CAMERAS, G, RB, Camera, Delivery, truth_theta, positions, frame_times, setup,  # noqa: E402
                  dp_dtheta, pixel_jac, measurand_grad_analytic, lin_bound, _frames_around)
from synth import grid                                                                            # noqa: E402
from app.pipeline.reconstruction import _stump_plane_point                                        # noqa: E402

GEN = Delivery(speed_kmh=120, length_m=6.0, line_m=0.3, release_y=-0.3, turn_ms=0.8)
INPLANE = Delivery(speed_kmh=120, length_m=6.0, line_m=0.0, release_y=0.0)
FPS = (120, 240, 480, 960, 1920)


def smin_rel(th, pose, fps, a, b, g=G):
    t = _frames_around(th, pose, fps, a, b)
    J = pixel_jac(pose, positions(th, t, g), dp_dtheta(th, t, g))
    sig, r, sv = lin_bound(J, measurand_grad_analytic(th, g))
    return sv[-1] / sv[0], r, bool(np.all(np.isfinite(sig)))


def conditioning(log):
    log("1. relative smallest singular value (columns scaled) against fps; slope of log smin on log h")
    for name, d, cam in (("general", GEN, CAMERAS["striker_side"]), ("in_plane", INPLANE, CAMERAS["striker_ref"])):
        th = truth_theta(d)
        for a, b in ((2, 3), (3, 2), (2, 4), (4, 2), (3, 3)):
            s = np.array([smin_rel(th, cam.pose(), f, a, b)[0] for f in FPS])
            slope = np.polyfit(np.log(1.0 / np.array(FPS, float)), np.log(s), 1)[0]
            log(f"  {name:8s} ({a},{b}) " + " ".join(f"{x:.2e}" for x in s) + f"  slope {slope:.2f}")
    th = truth_theta(INPLANE)
    for off in (0.0, 0.01, 0.03, 0.1, 0.3, 1.0):
        pose = Camera(end="striker", back_m=2.8, height_m=1.7, offset_m=off).pose()
        log(f"  offset {off:4.2f} m at 240 fps: " + " ".join(
            f"({a},{b}) {smin_rel(th, pose, 240, a, b)[0]:.1e}" for a, b in ((2, 3), (3, 2), (2, 4), (3, 3))))


def components(log):
    log("1b. which crossing component has a finite bound (y* z*), rows N- = 0..5, columns N+ = 0..5, 240 fps")
    for name, d, cam in (("general", GEN, CAMERAS["striker_side"]), ("in_plane", INPLANE, CAMERAS["striker_ref"])):
        th, pose = truth_theta(d), cam.pose()
        log(f"  {name}")
        for a in range(6):
            cells = []
            for b in range(6):
                t = _frames_around(th, pose, 240.0, a, b)
                if len(t) == 0:
                    cells.append("..")
                    continue
                sig = lin_bound(pixel_jac(pose, positions(th, t), dp_dtheta(th, t)), measurand_grad_analytic(th))[0]
                cells.append("".join("Y" if np.isfinite(x) else "-" for x in sig))
            log(f"    N-={a}  " + "  ".join(cells))


def scaling(log):
    log("2. camera height and g, general-position delivery, 240 fps")
    th = truth_theta(GEN)
    for h in (RB, 0.2, 1.7):
        pose = Camera(end="striker", back_m=2.8, height_m=h, offset_m=1.5).pose()
        for g in (G, 0.0):
            for a, b in ((3, 3), (5, 5)):
                s, r, est = smin_rel(th, pose, 240, a, b, g)
                log(f"  height {h:.3f} g {g:4.2f} ({a},{b}) rank {r} smin {s:.2e} crossing estimable {est}")
    pose = Camera(end="striker", back_m=2.8, height_m=RB, offset_m=1.5).pose()
    c = pose.centre_world
    t = _frames_around(th, pose, 240.0, 5, 5)
    # d/dlambda of p -> c + lambda (p - c): contact moves along its ray, velocities scale, t_b and e stay
    d = np.array([0.0, th[1] - c[0], th[2] - c[1], th[3], th[4], th[5], th[6], th[7], 0.0])
    for g in (0.0, G):
        J = pixel_jac(pose, positions(th, t, g), dp_dtheta(th, t, g))
        log(f"  camera at contact height, g {g:4.2f}: |J d| / (|J| |d|) = "
            f"{np.linalg.norm(J @ d) / (np.linalg.norm(J, 2) * np.linalg.norm(d)):.2e}")


def depth(log):
    log("3. depth: medians over the 100-delivery grid, 60 fps, 1 px, deliveries with N- >= 2 and N+ >= 3")
    for cname in ("striker_ref", "striker_low", "striker_high", "striker_side", "bowler_ref", "bowler_side"):
        pose = CAMERAS[cname].pose()
        out = []
        for d in grid():
            th = truth_theta(d)
            S = setup(th, pose, frame_times(th, pose, 60.0))
            if S["n_pre"] < 2 or S["n_post"] < 3:
                continue
            Fi = np.linalg.pinv(S["J"].T @ S["J"])
            ts = _stump_plane_point(th, 0.0, True)[0]
            Dp = dp_dtheta(th, np.array([ts]))[0]
            Cp = Dp @ Fi @ Dp.T                       # position covariance at the crossing time
            vx, vy = th[6], th[7]
            vz = -th[8] * th[5] - G * (ts - th[0])
            A = np.array([[-vy / vx, 1, 0], [-vz / vx, 0, 1]])   # plane section: dm = A dp(t*)
            Cg = S["G"] @ Fi @ S["G"].T
            r = positions(th, np.array([ts]))[0] - pose.centre_world
            r /= np.linalg.norm(r)
            sig_rho = math.sqrt(r @ Cp @ r)
            dep = A @ r * sig_rho                     # the along-ray part alone
            Pn = np.eye(3) - np.outer(r, r)
            Cperp = A @ Pn @ Cp @ Pn @ A.T            # the across-ray part alone
            out.append((100 * sig_rho, 100 * abs(dep[0]), 100 * abs(dep[1]), 100 * math.sqrt(Cperp[0, 0]),
                        100 * math.sqrt(Cperp[1, 1]), 100 * math.sqrt(Cg[0, 0]), 100 * math.sqrt(Cg[1, 1]),
                        r[2] / r[0], vz / vx, np.linalg.norm(positions(th, np.array([ts]))[0] - pose.centre_world)))
        o = np.median(np.array(out), axis=0)
        log(f"  {cname:12s} n {len(out):3d} range {o[9]:5.1f} m  depth sd {o[0]:6.1f} cm | along-ray only y,z "
            f"{o[1]:5.2f} {o[2]:6.2f} | across-ray only y,z {o[3]:5.2f} {o[4]:5.2f} | bound y,z {o[5]:5.2f} "
            f"{o[6]:6.2f} | dz/dx ray {o[7]:+.3f} path {o[8]:+.3f}")


def null_direction(log):
    log("4. one post-contact frame: the analytic null direction d1 (dv+ = r1/tau1) and the crossing shift it causes")
    th = truth_theta(GEN)
    pose = CAMERAS["striker_side"].pose()
    ts = -th[1] / th[6]
    vz = -th[8] * th[5] - G * ts
    A = np.array([[-th[7] / th[6], 1, 0], [-vz / th[6], 0, 1]])
    for a in (3, 5):
        t = _frames_around(th, pose, 240.0, a, 1)
        t1 = t[t >= th[0]][0]
        r = positions(th, np.array([t1]))[0] - pose.centre_world
        r /= np.linalg.norm(r)
        tau1 = t1 - th[0]
        d = np.zeros(9)
        d[6], d[7] = r[0] / tau1, r[1] / tau1
        d[8] = -(r[2] / tau1) / th[5]          # vz+ = -e vz-, so with vz- fixed de = -dvz+ / vz-
        J = pixel_jac(pose, positions(th, t), dp_dtheta(th, t))
        sig, r_, _ = lin_bound(J, measurand_grad_analytic(th))
        pred = ts / tau1 * (A @ r)
        got = measurand_grad_analytic(th) @ d
        log(f"  N- {a} N+ 1: |J d1|/(|J| |d1|) {np.linalg.norm(J @ d) / (np.linalg.norm(J, 2) * np.linalg.norm(d)):.1e}, "
            f"rank {r_}, finite y* z* {np.isfinite(sig).tolist()}, crossing shift per unit d1 "
            f"{got[0]:+.4f}/{got[1]:+.4f} m, predicted (tau*/tau1) A r1 {pred[0]:+.4f}/{pred[1]:+.4f} m")
    # in-plane rule without mirror symmetry: yaw and roll the reference camera about its own centre
    th = truth_theta(INPLANE)
    pose = CAMERAS["striker_ref"].pose()
    ang = math.radians(8.0)
    Qy = np.array([[math.cos(ang), 0, math.sin(ang)], [0, 1, 0], [-math.sin(ang), 0, math.cos(ang)]])
    Qz = np.array([[math.cos(ang), -math.sin(ang), 0], [math.sin(ang), math.cos(ang), 0], [0, 0, 1]])
    Q = Qz @ Qy
    tilted = replace(pose, R=Q @ pose.R, t=Q @ pose.t)
    log(f"  in-plane, camera yawed and rolled 8 deg about its centre (centre moved "
        f"{np.linalg.norm(tilted.centre_world - pose.centre_world):.1e} m); finite y* z* at 240 fps")
    for a in range(6):
        cells = []
        for b in range(6):
            t = _frames_around(th, pose, 240.0, a, b)
            if len(t) == 0:
                cells.append("..")
                continue
            sig = lin_bound(pixel_jac(tilted, positions(th, t), dp_dtheta(th, t)), measurand_grad_analytic(th))[0]
            cells.append("".join("Y" if np.isfinite(x) else "-" for x in sig))
        log(f"    N-={a}  " + "  ".join(cells))


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = []

    def log(s):
        print(s, flush=True)
        lines.append(s)

    conditioning(log)
    components(log)
    scaling(log)
    depth(log)
    null_direction(log)
    with open(os.path.join(OUT, "checks_log.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
