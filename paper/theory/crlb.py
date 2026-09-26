#!/usr/bin/env python
"""Identifiability and Cramer-Rao bounds for the bounce-anchored monocular reconstruction.

The trajectory model, the camera and the stump-plane measurand are the solver's own
(server/app/pipeline/reconstruction.py and calibration.py), imported rather than rewritten.
Only the derivatives are written out by hand, and each one is checked against a finite
difference of the solver's code before anything is computed from it.

Noise model, as in the paper: independent Gaussian detection noise of sigma px on both pixel
coordinates of every ball detection, and independent Gaussian noise of sigma_tap px on each of
the twelve calibration taps (eight stump corners, four pitch corners). Focal length and pitch
length are known, as in Experiment 1; a variant also treats the focal length as unknown.

Usage:  python paper/theory/crlb.py        writes paper/theory/out/crlb_*.{json,csv}
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from dataclasses import replace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "experiments"))
from synth import Camera, Delivery, CREASE_X, _launch, grid                                   # noqa: E402
from app.pipeline.reconstruction import (_unpack, _stump_plane_point, _numeric_jacobian,     # noqa: E402
                                         GRAVITY, BALL_RADIUS_M)
from app.pipeline.calibration import (CameraPose, STUMP_HEIGHT_M, STUMP_OUTER_HALF_M,         # noqa: E402
                                      PITCH_LENGTH_M, PITCH_WIDTH_M)

OUT = os.path.join(HERE, "out")
G, RB = GRAVITY, BALL_RADIUS_M
NAMES = ["t_b", "x_b", "y_b", "vx-", "vy-", "vz-", "vx+", "vy+", "e"]

CAMERAS = {   # the six placements of Experiment 1
    "striker_low": Camera(end="striker", back_m=2.8, height_m=1.2),
    "striker_ref": Camera(end="striker", back_m=2.8, height_m=1.7),
    "striker_high": Camera(end="striker", back_m=4.0, height_m=2.6),
    "striker_side": Camera(end="striker", back_m=2.8, height_m=1.7, offset_m=1.5),
    "bowler_ref": Camera(end="bowler", back_m=2.8, height_m=1.7),
    "bowler_side": Camera(end="bowler", back_m=4.0, height_m=2.0, offset_m=2.0),
}

# the solver's three soft priors as residual rows (reconstruction._fit_bounce), in its units
PRIOR = np.zeros((3, 9))
PRIOR[0, 8] = 1 / 0.15
PRIOR[1, 6], PRIOR[1, 3] = 1 / 4.0, -1 / 4.0
PRIOR[2, 7], PRIOR[2, 4] = 1 / 2.0, -1 / 2.0


# --------------------------------------------------------------------------- #
# Truth in the solver's own model family
# --------------------------------------------------------------------------- #

def truth_theta(d: Delivery) -> np.ndarray:
    """theta for a drag-free, swing-free delivery, t_b from release. Same contact physics as
    synth.fly, so the generated path is exactly two of the solver's parabolas."""
    if d.drag or d.swing_ms2 != 0.0:
        raise ValueError("drag or swing is outside the solver's model")
    p0, v0 = _launch(d)
    tc = (v0[2] + math.sqrt(v0[2] ** 2 + 2 * G * (p0[2] - RB))) / G
    vpre = np.array([v0[0], v0[1], v0[2] - G * tc])
    vx1 = vpre[0] * (1 - d.friction)
    vy1 = vpre[1] * (1 - d.friction) + d.turn_ms
    return np.array([tc, p0[0] + v0[0] * tc, p0[1] + v0[1] * tc, *vpre, vx1, vy1, d.restitution])


def positions(theta: np.ndarray, t: np.ndarray, g: float = G, zb: float = RB) -> np.ndarray:
    """The solver's model with gravity and contact height as arguments, for the variants.
    For g = GRAVITY and zb = R this equals reconstruction.Trajectory.position (checked)."""
    t_b, x_b, y_b, vx0, vy0, vz0, vx1, vy1, e = theta[:9]
    tau = np.asarray(t, float) - t_b
    post = tau >= 0
    v = np.where(post[:, None], [vx1, vy1, -e * vz0], [vx0, vy0, vz0])
    p = np.array([x_b, y_b, zb])[None, :] + v * tau[:, None]
    p[:, 2] -= 0.5 * g * tau ** 2
    return p


def frame_times(theta: np.ndarray, pose: CameraPose, fps: float, phase: float = 0.0) -> np.ndarray:
    """Frame instants from release until the pad at the popping crease, keeping the frames in
    which the ball is in view, as synth.observe does."""
    ts = np.arange(phase, 3.0, 1.0 / fps)
    p = positions(theta, ts)
    gone = p[:, 0] <= CREASE_X
    k = int(np.argmax(gone)) if gone.any() else len(ts)
    ts, p = ts[:k], p[:k]
    u, v, dep = pose.project(p)
    ok = (dep > 0.5) & (u >= 0) & (u < 2 * pose.cx) & (v >= 0) & (v < 2 * pose.cy)
    return ts[ok]


# --------------------------------------------------------------------------- #
# Analytic derivatives
# --------------------------------------------------------------------------- #

def dp_dtheta(theta: np.ndarray, t: np.ndarray, g: float = G, zb_free: bool = False) -> np.ndarray:
    """(n, 3, 9) derivative of the world position; (n, 3, 10) with a free contact height."""
    t_b, x_b, y_b, vx0, vy0, vz0, vx1, vy1, e = theta[:9]
    tau = np.asarray(t, float) - t_b
    post = tau >= 0
    pre = ~post
    D = np.zeros((len(tau), 3, 10 if zb_free else 9))
    vel = np.where(post[:, None], [vx1, vy1, -e * vz0], [vx0, vy0, vz0]).astype(float)
    vel[:, 2] -= g * tau
    D[:, :, 0] = -vel
    D[:, 0, 1] = 1.0
    D[:, 1, 2] = 1.0
    D[pre, 0, 3] = tau[pre]
    D[pre, 1, 4] = tau[pre]
    D[pre, 2, 5] = tau[pre]
    D[post, 2, 5] = -e * tau[post]
    D[post, 0, 6] = tau[post]
    D[post, 1, 7] = tau[post]
    D[post, 2, 8] = -vz0 * tau[post]
    if zb_free:
        D[:, 2, 9] = 1.0
    return D


def _dpix_dpc(pose: CameraPose, P: np.ndarray):
    pc = P @ pose.R.T + pose.t
    x, y, z = pc.T
    f = pose.fx
    A = np.zeros((len(P), 2, 3))
    A[:, 0, 0] = f / z
    A[:, 0, 2] = -f * x / z ** 2
    A[:, 1, 1] = f / z
    A[:, 1, 2] = -f * y / z ** 2
    return A, pc


def pixel_jac(pose: CameraPose, P: np.ndarray, dP: np.ndarray) -> np.ndarray:
    """(2n, k) derivative of the stacked pixels [u_1..u_n, v_1..v_n], the solver's row order."""
    A, _ = _dpix_dpc(pose, P)
    J = np.einsum("nij,jk,nkl->nil", A, pose.R, dP)
    return np.vstack([J[:, 0, :], J[:, 1, :]])


def pose_jac(pose: CameraPose, P: np.ndarray, with_f: bool = False) -> np.ndarray:
    """(2n, 6 or 7) derivative of the pixels w.r.t. a pose perturbation R <- exp([w]x) R,
    t <- t + dt, and optionally the focal length (square pixels)."""
    A, pc = _dpix_dpc(pose, P)
    a = P @ pose.R.T
    n = len(P)
    dpc = np.zeros((n, 3, 6))
    dpc[:, 0, 1], dpc[:, 0, 2] = a[:, 2], -a[:, 1]
    dpc[:, 1, 0], dpc[:, 1, 2] = -a[:, 2], a[:, 0]
    dpc[:, 2, 0], dpc[:, 2, 1] = a[:, 1], -a[:, 0]
    dpc[:, :, 3:] = np.eye(3)
    J = np.einsum("nij,njk->nik", A, dpc)
    J = np.vstack([J[:, 0, :], J[:, 1, :]])
    if with_f:
        J = np.hstack([J, np.concatenate([pc[:, 0] / pc[:, 2], pc[:, 1] / pc[:, 2]])[:, None]])
    return J


def tap_points() -> np.ndarray:
    """The twelve marks of synth.calibration_taps: striker TL,TR,BR,BL, bowler TL,TR,BR,BL, corners."""
    w, h = STUMP_OUTER_HALF_M, STUMP_HEIGHT_M
    side = [(-w, h), (w, h), (w, 0.0), (-w, 0.0)]
    hw = PITCH_WIDTH_M / 2
    return np.array([(0.0, dy, dz) for dy, dz in side] + [(PITCH_LENGTH_M, dy, dz) for dy, dz in side]
                    + [(0.0, -hw, 0.0), (0.0, hw, 0.0), (PITCH_LENGTH_M, hw, 0.0), (PITCH_LENGTH_M, -hw, 0.0)])


def measurand_grad(theta: np.ndarray) -> np.ndarray:
    """(2, 9) gradient of (y*, z*), computed exactly as predict_stump_plane does."""
    return _numeric_jacobian(lambda th: _stump_plane_point(th, 0.0, True)[1:3], theta)


def measurand_grad_analytic(theta: np.ndarray, g: float = G, zb_free: bool = False) -> np.ndarray:
    """Closed form for a crossing with no second bounce; (2, 10) with a free contact height."""
    t_b, x_b, y_b, vx0, vy0, vz0, vx1, vy1, e = theta[:9]
    ts = -x_b / vx1
    dts = np.zeros(10 if zb_free else 9)
    dts[1], dts[6] = -1 / vx1, x_b / vx1 ** 2
    vz1 = -e * vz0
    Gm = np.zeros((2, len(dts)))
    Gm[0] = vy1 * dts
    Gm[0, 2] += 1.0
    Gm[0, 7] += ts
    Gm[1] = (vz1 - g * ts) * dts
    Gm[1, 5] += -e * ts
    Gm[1, 8] += -vz0 * ts
    if zb_free:
        Gm[1, 9] = 1.0
    return Gm


# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #

def lin_bound(A: np.ndarray, Gm: np.ndarray, rtol: float = 1e-10, want_M: bool = False):
    """Bound G F^+ G^T with F = A^T A (A whitened). Returns per-row sigma (inf where the
    function is not estimable, i.e. its gradient has a component in null(A)), the rank, and
    the column-scaled singular values; with want_M also the linear estimator rows M = G A^+,
    so the first-order estimation error is M times the whitened noise. Columns are scaled to
    unit norm first so the rank test does not depend on units (a bound is invariant to that)."""
    s_col = np.linalg.norm(A, axis=0)
    s_col[s_col == 0] = 1.0
    As, Gs = A / s_col, Gm / s_col
    U, s, Vt = np.linalg.svd(As, full_matrices=True)
    s_full = np.zeros(As.shape[1])
    s_full[:len(s)] = s
    r = int(np.sum(s_full > rtol * s_full[0])) if s_full[0] > 0 else 0
    V_r, V_n = Vt[:r].T, Vt[r:].T
    W = Gs @ V_r / s_full[:r]
    sig = np.sqrt(np.sum(W ** 2, axis=1))
    if V_n.shape[1]:
        leak = np.linalg.norm(Gs @ V_n, axis=1) / np.maximum(np.linalg.norm(Gs, axis=1), 1e-300)
        sig = np.where(leak > 1e-6, np.inf, sig)
    if want_M:
        return sig, r, s_full, W @ U[:, :r].T
    return sig, r, s_full


def setup(theta: np.ndarray, pose: CameraPose, t: np.ndarray):
    """Everything the bounds need at one configuration."""
    P = positions(theta, t)
    return dict(J=pixel_jac(pose, P, dp_dtheta(theta, t)), Jphi=pose_jac(pose, P), Jphif=pose_jac(pose, P, True),
                Jtap=pose_jac(pose, tap_points()), Jtapf=pose_jac(pose, tap_points(), True),
                G=measurand_grad(theta), n_pre=int(np.sum(t < theta[0])), n_post=int(np.sum(t >= theta[0])))


def bounds(S: dict, sigma: float = 1.0, sigma_tap: float = 2.0) -> dict:
    """1-sigma bounds on (y*, z*) in metres.

    px          classical CRLB, ball pixels only, camera known exactly
    px_pri      the same plus the solver's three priors as Gaussian information (local
                Bayesian bound; the solver's priors are stated at 1 px of pixel noise)
    joint       classical CRLB with the pose as a nuisance and the twelve taps as data
    joint_pri   joint plus the priors
    joint_f     joint with the focal length also unknown
    twostep     variance of a first-order plug-in estimator: pose from the taps alone, then
                the ball fit with that pose held fixed (what the pipeline does)
    """
    J, Jp, Jt, Gm = S["J"] / sigma, S["Jphi"] / sigma, S["Jtap"] / sigma_tap, S["G"]
    out = {}
    out["px"] = lin_bound(J, Gm)[0]
    out["px_pri"] = lin_bound(np.vstack([J, PRIOR]), Gm)[0]
    Z6, Z9 = np.zeros((len(Jt), 9)), np.zeros((3, 6))
    Afull = np.block([[J, Jp], [Z6, Jt]])
    Gpad = np.hstack([Gm, np.zeros((2, 6))])
    out["joint"] = lin_bound(Afull, Gpad)[0]
    out["joint_pri"] = lin_bound(np.vstack([Afull, np.hstack([PRIOR, Z9])]), Gpad)[0]
    Jpf, Jtf = S["Jphif"] / sigma, S["Jtapf"] / sigma_tap
    Af = np.block([[J, Jpf], [np.zeros((len(Jtf), 9)), Jtf]])
    out["joint_f"] = lin_bound(Af, np.hstack([Gm, np.zeros((2, 7))]))[0]
    # two-step (what the pipeline does): pose from the taps alone, dphi ~ N(0, (Jt^T Jt)^-1),
    # then the ball fit with that pose fixed, whose first-order error is M (n - Jp dphi)
    sig, _, _, M = lin_bound(J, Gm, want_M=True)
    MJ = M @ Jp
    ts = np.sqrt(np.sum(M ** 2, axis=1) + np.diag(MJ @ np.linalg.inv(Jt.T @ Jt) @ MJ.T))
    out["twostep"] = np.where(np.isfinite(sig), ts, np.inf)
    return out


def crossing_cov_px(S: dict, sigma: float = 1.0) -> np.ndarray:
    """2x2 CRLB covariance of (y*, z*), pixels only, camera known (None if singular)."""
    J = S["J"] / sigma
    F = J.T @ J
    try:
        return S["G"] @ np.linalg.inv(F) @ S["G"].T
    except np.linalg.LinAlgError:
        return None


def config_bounds(d: Delivery, cam: Camera, fps: float, sigma: float = 1.0, sigma_tap: float = 2.0,
                  phase: float = 0.0) -> dict | None:
    th = truth_theta(d)
    pose = cam.pose()
    t = frame_times(th, pose, fps, phase)
    if len(t) < 3:
        return None
    S = setup(th, pose, t)
    b = bounds(S, sigma, sigma_tap)
    row = dict(speed_kmh=d.speed_kmh, length_m=d.length_m, line_m=d.line_m, fps=fps, n=len(t),
               n_pre=S["n_pre"], n_post=S["n_post"], y_star=float(_stump_plane_point(th, 0.0, True)[1]),
               z_star=float(_stump_plane_point(th, 0.0, True)[2]))
    for k, v in b.items():
        row[f"{k}_y_cm"], row[f"{k}_z_cm"] = 100 * float(v[0]), 100 * float(v[1])
    return row


# --------------------------------------------------------------------------- #
# Checks and experiments
# --------------------------------------------------------------------------- #

def check_derivatives() -> dict:
    """Analytic derivatives against central differences of the solver's own code."""
    rng = np.random.default_rng(7)
    worst = dict(model=0.0, pose=0.0, focal=0.0, measurand=0.0, positions=0.0)
    for cam in CAMERAS.values():
        pose = cam.pose()
        for d in grid()[::7]:
            th = truth_theta(replace(d, turn_ms=float(rng.uniform(-1, 1))))
            t = frame_times(th, pose, 60.0)
            if len(t) < 4:
                continue
            P_solver = _unpack(th, True).position(t)
            worst["positions"] = max(worst["positions"], float(np.abs(P_solver - positions(th, t)).max()))

            def pix(theta):
                u, v, _ = pose.project(_unpack(theta, True).position(t))
                return np.concatenate([u, v])
            Jn = _numeric_jacobian(pix, th, rel=1e-7)
            Ja = pixel_jac(pose, positions(th, t), dp_dtheta(th, t))
            worst["model"] = max(worst["model"], float(np.abs(Jn - Ja).max() / np.abs(Ja).max()))

            import cv2

            def pix_pose(phi):
                R = cv2.Rodrigues(phi[:3])[0] @ pose.R
                K = pose.K.copy()
                if len(phi) == 7:
                    K[0, 0] = K[1, 1] = pose.fx + phi[6]
                q = CameraPose(K=K, R=R, t=pose.t + phi[3:6], reproj_error_px=0.0, fov_deg=0.0,
                               pitch_length_m=PITCH_LENGTH_M, pitch_width_m=PITCH_WIDTH_M, used_corners=True)
                u, v, _ = q.project(positions(th, t))
                return np.concatenate([u, v])
            Jpn = _numeric_jacobian(pix_pose, np.zeros(7), rel=1e-7)
            Jpa = pose_jac(pose, positions(th, t), with_f=True)
            worst["pose"] = max(worst["pose"], float(np.abs(Jpn[:, :6] - Jpa[:, :6]).max() / np.abs(Jpa[:, :6]).max()))
            worst["focal"] = max(worst["focal"], float(np.abs(Jpn[:, 6] - Jpa[:, 6]).max() / np.abs(Jpa[:, 6]).max()))
            Gn, Ga = measurand_grad(th), measurand_grad_analytic(th)
            if _stump_plane_point(th, 0.0, True)[3] == 0:
                worst["measurand"] = max(worst["measurand"], float(np.abs(Gn - Ga).max() / np.abs(Ga).max()))
    return worst


def _frames_around(theta, pose, fps, n_pre, n_post):
    """The last n_pre frames before contact and the first n_post after, at the given rate."""
    t = frame_times(theta, pose, fps)
    pre, post = t[t < theta[0]], t[t >= theta[0]]
    return np.concatenate([pre[len(pre) - n_pre:] if n_pre else pre[:0], post[:n_post]])


def identifiability_table(theta, pose, g=G, fps=240.0, nmax=5) -> list[dict]:
    """Rank of the pixel Jacobian (no priors) and estimability of y*, z*, for every
    (n_pre, n_post) up to nmax, for the anchored model (A), the anchored model with a free
    contact height (C), and a free six-parameter parabola fitted to the post-contact frames (B).
    Data are generated with the same g the model uses, so g = 0 asks whether the model is
    identifiable without gravity."""
    rows = []
    th = theta.copy()
    for n_pre in range(0, nmax + 1):
        for n_post in range(0, nmax + 1):
            t = _frames_around(th, pose, fps, n_pre, n_post)
            if len(t) == 0:
                continue
            P = positions(th, t, g)
            GA = measurand_grad_analytic(th, g)
            JA = pixel_jac(pose, P, dp_dtheta(th, t, g))
            sA, rA, svA = lin_bound(JA, GA)
            JC = pixel_jac(pose, P, dp_dtheta(th, t, g, zb_free=True))
            sC, rC, _ = lin_bound(JC, measurand_grad_analytic(th, g, zb_free=True))
            # B: post-contact frames only, parabola (x_b, y_b, z_b, vx+, vy+, vz+) at t_b
            tp = t[t >= th[0]]
            if len(tp):
                DC = dp_dtheta(th, tp, g, zb_free=True)
                idx = [1, 2, 9, 6, 7]
                DB = np.concatenate([DC[:, :, idx], np.zeros((len(tp), 3, 1))], axis=2)
                DB[:, 2, 5] = tp - th[0]                       # d/d vz+
                JB = pixel_jac(pose, positions(th, tp, g), DB)
                GC = measurand_grad_analytic(th, g, zb_free=True)
                GB = np.zeros((2, 6))
                GB[:, :5] = GC[:, idx]
                GB[1, 5] = -GC[1, 8] / th[5]                   # dz*/dvz+ = tau*
                sB, rB, _ = lin_bound(JB, GB)
            else:
                sB, rB = np.array([np.inf, np.inf]), 0
            rows.append(dict(n_pre=n_pre, n_post=n_post, rank_A=rA, est_A=bool(np.all(np.isfinite(sA))),
                             smin_A=float(svA[-1] / svA[0]), rank_C=rC, est_C=bool(np.all(np.isfinite(sC))),
                             rank_B=rB, est_B=bool(np.all(np.isfinite(sB)))))
    return rows


def _median(rows, key):
    """Median over the grid with a non-identifiable delivery counted as an infinite bound."""
    xs = [r[key] for r in rows if r is not None]
    return float(np.median(xs)) if xs else float("inf")


def _frac_inf(rows, key):
    xs = [r[key] for r in rows if r is not None]
    return float(np.mean([not np.isfinite(x) for x in xs])) if xs else float("nan")


KEYS = ["px", "px_pri", "joint", "joint_pri", "joint_f", "twostep"]


def summarise(rows) -> dict:
    ok = [r for r in rows if r is not None]
    s = dict(n=len(ok), median_frames=float(np.median([r["n"] for r in ok])),
             median_post=float(np.median([r["n_post"] for r in ok])))
    for k in KEYS:
        for ax in "yz":
            s[f"{k}_{ax}_cm"] = round(_median(ok, f"{k}_{ax}_cm"), 3)
            s[f"{k}_{ax}_inf"] = round(_frac_inf(ok, f"{k}_{ax}_cm"), 3)
    return s


def write_csv(path, rows):
    rows = [r for r in rows if r is not None]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    res = {}

    # 1. derivatives
    res["derivative_check_max_rel_err"] = check_derivatives()
    print("derivative check (max relative error):", res["derivative_check_max_rel_err"], flush=True)

    # 2. identifiability. General position: camera 1.5 m off the centre line and a delivery
    # that swerves at contact, so neither arc's vertical plane contains the camera centre.
    # Degenerate: camera on the centre line and a straight delivery down it (both arcs in the
    # vertical plane through the camera), which is Experiment 1's reference placement.
    gen_d = Delivery(speed_kmh=120, length_m=6.0, line_m=0.3, release_y=-0.3, turn_ms=0.8)
    inplane_d = Delivery(speed_kmh=120, length_m=6.0, line_m=0.0, release_y=0.0)
    ident = {}
    for name, d, cam in (("general", gen_d, CAMERAS["striker_side"]), ("in_plane", inplane_d, CAMERAS["striker_ref"])):
        th = truth_theta(d)
        for gname, g in (("g", G), ("g0", 0.0)):
            ident[f"{name}_{gname}"] = identifiability_table(th, cam.pose(), g=g)
    # camera at the contact height: the ground plane is seen edge on
    th = truth_theta(gen_d)
    for h in (RB, 0.2, 1.7):
        cam = Camera(end="striker", back_m=2.8, height_m=h, offset_m=1.5)
        t = frame_times(th, cam.pose(), 60.0)
        S = setup(th, cam.pose(), t)
        sig, r, sv = lin_bound(S["J"], S["G"])
        ident[f"cam_height_{h:.3f}"] = dict(rank=r, smin_rel=float(sv[-1] / sv[0]),
                                            crlb_y_cm=100 * float(sig[0]), crlb_z_cm=100 * float(sig[1]))
    res["identifiability"] = ident
    with open(os.path.join(OUT, "crlb_identifiability.json"), "w") as fh:
        json.dump(ident, fh, indent=1)
    print("identifiability tables written", flush=True)

    # 3. reference: Experiment 1's camera, 60 Hz, 1 px, 2 px taps, the fixed 100-delivery grid
    ref_rows = [config_bounds(d, CAMERAS["striker_ref"], 60.0) for d in grid()]
    write_csv(os.path.join(OUT, "crlb_reference_grid.csv"), ref_rows)
    res["reference"] = summarise(ref_rows)
    res["reference_by_length"] = {str(L): summarise([r for r in ref_rows if r and r["length_m"] == L])
                                  for L in (2.0, 4.0, 6.0, 8.0)}
    print("reference:", res["reference"], flush=True)

    # 4. frame rate x camera placement
    fps_cam = {}
    for cname, cam in CAMERAS.items():
        for fps in (30.0, 60.0, 120.0, 240.0):
            rows = [config_bounds(d, cam, fps) for d in grid()]
            fps_cam[f"{cname}@{fps:g}"] = summarise(rows)
            print(cname, fps, {k: fps_cam[f"{cname}@{fps:g}"][k] for k in ("px_y_cm", "px_z_cm", "joint_y_cm", "joint_z_cm", "px_y_inf")}, flush=True)
    res["fps_by_camera"] = fps_cam
    res["fps_ref_by_length"] = {}
    for fps in (30.0, 60.0, 120.0, 240.0):
        rows = [config_bounds(d, CAMERAS["striker_ref"], fps) for d in grid()]
        for L in (2.0, 4.0, 6.0, 8.0):
            res["fps_ref_by_length"][f"L={L}@{fps:g}"] = summarise([r for r in rows if r and r["length_m"] == L])

    # 5. placement sweeps around the reference, 60 Hz
    place = {}
    for D in (1.5, 2.8, 4.0, 6.0, 10.0):
        place[f"back={D}"] = summarise([config_bounds(d, Camera(back_m=D, height_m=1.7), 60.0) for d in grid()])
    for h in (0.3, 0.5, 0.8, 1.2, 1.7, 2.6, 3.5):
        place[f"height={h}"] = summarise([config_bounds(d, Camera(back_m=2.8, height_m=h), 60.0) for d in grid()])
    for o in (0.0, 0.5, 1.5, 3.0):
        place[f"offset={o}"] = summarise([config_bounds(d, Camera(back_m=2.8, height_m=1.7, offset_m=o), 60.0) for d in grid()])
    res["placement"] = place
    print("placement sweeps done", flush=True)

    # 6. delivery length at 30/60/120/240 Hz: 120 km/h on a 0.2 m line
    length = {}
    for fps in (30.0, 60.0, 120.0, 240.0):
        for L in (1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 8.0, 10.0):
            length[f"L={L}@{fps:g}"] = config_bounds(Delivery(speed_kmh=120, length_m=L, line_m=0.2),
                                                     CAMERAS["striker_ref"], fps)
    res["length"] = length

    # 7. noise scaling at the reference (pixel-only bounds are exactly linear in sigma)
    noise = {}
    for s in (0.5, 1.0, 2.0, 3.0, 5.0):
        noise[f"sigma={s}"] = summarise([config_bounds(d, CAMERAS["striker_ref"], 60.0, sigma=s) for d in grid()])
    for st in (0.0001, 1.0, 2.0, 4.0, 8.0, 12.0):
        noise[f"tap={st}"] = summarise([config_bounds(d, CAMERAS["striker_ref"], 60.0, sigma_tap=st) for d in grid()])
    res["noise"] = noise

    # 8. what the contact supplies: anchored (A) vs free contact height (C) vs post arc alone (B)
    var = []
    for d in grid():
        th = truth_theta(d)
        pose = CAMERAS["striker_ref"].pose()
        t = frame_times(th, pose, 60.0)
        P = positions(th, t)
        sA = lin_bound(pixel_jac(pose, P, dp_dtheta(th, t)), measurand_grad_analytic(th))[0]
        sC = lin_bound(pixel_jac(pose, P, dp_dtheta(th, t, zb_free=True)), measurand_grad_analytic(th, zb_free=True))[0]
        tp = t[t >= th[0]]
        DC = dp_dtheta(th, tp, zb_free=True)
        idx = [1, 2, 9, 6, 7]
        DB = np.concatenate([DC[:, :, idx], np.zeros((len(tp), 3, 1))], axis=2)
        DB[:, 2, 5] = tp - th[0]
        GC = measurand_grad_analytic(th, zb_free=True)
        GB = np.zeros((2, 6))
        GB[:, :5] = GC[:, idx]
        GB[1, 5] = -GC[1, 8] / th[5]
        sB = lin_bound(pixel_jac(pose, positions(th, tp), DB), GB)[0] if len(tp) else np.array([np.inf, np.inf])
        var.append(dict(length_m=d.length_m, speed_kmh=d.speed_kmh, n_post=len(tp),
                        A_y=100 * sA[0], A_z=100 * sA[1], C_y=100 * sC[0], C_z=100 * sC[1], B_y=100 * sB[0], B_z=100 * sB[1]))
    res["variants"] = {k: _median(var, k) for k in ("A_y", "A_z", "C_y", "C_z", "B_y", "B_z")}
    res["variants_inf_frac"] = {k: _frac_inf(var, k) for k in ("A_y", "A_z", "C_y", "C_z", "B_y", "B_z")}
    fin = lambda a, b: [r for r in var if np.isfinite(r[a]) and np.isfinite(r[b])]
    res["variants_ratio_median"] = {
        f"{v}_over_A_{ax}": float(np.median([r[f"{v}_{ax}"] / r[f"A_{ax}"] for r in fin(f"{v}_{ax}", f"A_{ax}")]))
        for v in "CB" for ax in "yz"}
    write_csv(os.path.join(OUT, "crlb_variants.csv"), var)
    print("variants:", res["variants"], res["variants_ratio_median"], flush=True)

    # 9. depth coupling: the long axis of the 3-D position bound at the last tracked frame
    # against the viewing ray, and the lateral/vertical leverage of the crossing on it
    ang, lev = [], []
    for d in grid():
        th = truth_theta(d)
        cam = CAMERAS["striker_ref"]
        pose = cam.pose()
        t = frame_times(th, pose, 60.0)
        S = setup(th, pose, t)
        if S["n_pre"] < 2 or S["n_post"] < 3:
            continue
        F = S["J"].T @ S["J"]
        tl = t[-1:]
        Dp = dp_dtheta(th, tl)[0]
        Cp = Dp @ np.linalg.pinv(F) @ Dp.T
        w, V = np.linalg.eigh(Cp)
        ray = positions(th, tl)[0] - pose.centre_world
        ray /= np.linalg.norm(ray)
        ang.append(math.degrees(math.acos(min(1.0, abs(float(V[:, -1] @ ray))))))
        lev.append(math.sqrt(w[-1] / max(w[-2], 1e-30)))
    res["depth_axis"] = dict(median_angle_to_ray_deg=float(np.median(ang)), p90_angle_deg=float(np.percentile(ang, 90)),
                             median_axis_ratio=float(np.median(lev)))
    print("depth axis:", res["depth_axis"], flush=True)

    with open(os.path.join(OUT, "crlb_results.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    print("wrote", os.path.join(OUT, "crlb_results.json"))


if __name__ == "__main__":
    main()
