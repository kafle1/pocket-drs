"""Shared pieces for the uncertainty experiments (exp4 to exp9).

World B is the synthetic world of exp1 plus the measurement effects the estimator does not
model, each one switchable: rolling-shutter readout, radial lens distortion, frame-time
jitter, the app's frame sampler (as submitted, or fixed), a container frame rate that disagrees with the frame
timestamps, pitch and wicket dimensions off their Law values, bails tapped as the stump
top, and flight physics the two-parabola model leaves out. The estimator is the shipped
one, unchanged: solve_camera_pose on the taps, then reconstruct on the detections.
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import json
import math
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace, asdict

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from synth import Camera, Delivery, fly, CREASE_X                                        # noqa: E402
from app.pipeline import reconstruction as recon                                         # noqa: E402
from app.pipeline.calibration import (solve_camera_pose, CalibrationError, STUMP_HEIGHT_M,  # noqa: E402
                                      STUMP_OUTER_HALF_M, PITCH_LENGTH_M, PITCH_WIDTH_M)
from app.pipeline.decision import decide, WICKET_TOP_M                                   # noqa: E402
from app.pipeline.video import pick_frames                                               # noqa: E402

cv2.setNumThreads(1)
OUT = os.path.join(HERE, "raw")
os.makedirs(OUT, exist_ok=True)
R_BALL = recon.BALL_RADIUS_M
REF_CAM = Camera(end="striker", back_m=2.8, height_m=1.7)
QTY = ("pitch_y", "crease_y", "y", "z")      # the four measurands the verdict uses, metres
RATE_TEST5 = 59.803690616411465 / 60.0       # OpenCV's rate for test5.mp4 over its 60.000 Hz timestamps


@dataclass(frozen=True)
class Effects:
    """What World B does to a delivery on its way to the estimator. Defaults = none."""
    tap_px: float = 0.0          # 1-sigma noise on each tapped coordinate
    noise_px: float = 0.0        # 1-sigma noise on each ball-centre coordinate
    radius_noise: float = 0.0    # relative 1-sigma on the apparent radius
    dropout: float = 0.0         # probability a frame's detection is lost
    fps: float = 60.0            # true camera frame rate
    rate_ratio: float = 1.0      # frame rate the decoder reports / true rate
    sampler: str = "exact"       # exact: every frame at its timestamp; fixed / submitted: the app's sampler now / at submission
    sample_fps: float = 0.0      # fixed, submitted: the sample_fps the app sends (it hard-codes 60); 0 = match fps
    jitter_s: float = 0.0        # 1-sigma capture-instant noise per frame
    rs_s: float = 0.0            # rolling-shutter readout across the portrait width; sign = direction
    rs_correct_s: float = 0.0    # readout the estimator assumes and removes, same sign convention
    distortion: float = 0.0      # radial displacement at the image corner, fraction of the half diagonal
    dL: float = 0.0              # true pitch length minus 20.12 m
    dW: float = 0.0              # true pitch width minus 3.05 m
    dH: float = 0.0              # true stump height minus 0.711 m
    dw: float = 0.0              # true half wicket width minus 0.1143 m
    top_tap: float = 0.0         # how far above the stump top the user taps (bails), m


# --------------------------------------------------------------------------- #
# World B: taps, frame times, detections
# --------------------------------------------------------------------------- #

def distort(pose, u, v, d):
    if d == 0.0:
        return u, v
    rc2 = pose.cx ** 2 + pose.cy ** 2
    s = 1.0 + d * ((u - pose.cx) ** 2 + (v - pose.cy) ** 2) / rc2
    return pose.cx + (u - pose.cx) * s, pose.cy + (v - pose.cy) * s


def taps(pose, eff: Effects, rng) -> np.ndarray:
    """(12,2) marks as tapped on the true pitch: 8 stump corners then 4 pitch corners."""
    L = PITCH_LENGTH_M + eff.dL
    w = STUMP_OUTER_HALF_M + eff.dw
    h = STUMP_HEIGHT_M + eff.dH + eff.top_tap
    hw = (PITCH_WIDTH_M + eff.dW) / 2
    side = [(-w, h), (w, h), (w, 0.0), (-w, 0.0)]
    pts = np.array([(0.0, a, b) for a, b in side] + [(L, a, b) for a, b in side]
                   + [(0.0, -hw, 0.0), (0.0, hw, 0.0), (L, hw, 0.0), (L, -hw, 0.0)])
    u, v, _ = pose.project(pts)
    u, v = distort(pose, u, v, eff.distortion)
    xy = np.column_stack([u, v])
    if eff.tap_px > 0:
        xy = xy + rng.normal(0.0, eff.tap_px, xy.shape)
    return xy


def solve(pose_true, xy: np.ndarray, **kw):
    """The app's solve: free focal length, regulation pitch length unless kw says otherwise."""
    kw.setdefault("pitch_length_m", PITCH_LENGTH_M)
    return solve_camera_pose(image_size=(int(pose_true.cx * 2), int(pose_true.cy * 2)),
                             stump_quads_px=[tuple(p) for p in xy[:8]],
                             pitch_corners_px=[tuple(p) for p in xy[8:]], **kw)


def frame_times(t_end: float, eff: Effects, rng, v0: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(label_s, actual_s) of every sampled frame between release (t=0) and t_end.

    Frames are exposed at j/fps on the video clock, with the release at a random video time,
    and stamped j/(reported rate) in the container. exact: every frame, labelled with its stamp.
    fixed: process_job asks for a frame every 1000/sample_fps ms and pick_frames returns the
    nearest frame by its stamp, labelled with it. submitted: the code at submission asked every
    round(1000/sample_fps) ms, mapped each to frame round(ms/1000*reported rate) and labelled
    it with the requested ms, not the frame's own time."""
    T = 1.0 / eff.fps
    if v0 is None:
        v0 = rng.uniform(0.2, 0.4)                 # video time of the release
    j0, j1 = int(math.floor(v0 * eff.fps)) - 2, int(math.ceil((v0 + t_end) * eff.fps)) + 2
    if eff.sampler == "exact":
        idx = np.arange(j0, j1 + 1)
        label = idx * T / eff.rate_ratio
    elif eff.sampler == "fixed":
        rate = eff.fps * eff.rate_ratio
        step = 1000.0 / (eff.sample_fps or eff.fps)
        start = math.floor(v0 * 1000) - 20
        reqs = [start + k * step for k in range(int((t_end + 0.06) * 1000 / step) + 2)]
        ja, jb = max(0, int(start / 1000.0 * rate) - 2), int(math.ceil(reqs[-1] / 1000.0 * rate)) + 3
        picks, _ = pick_frames(((j * 1000.0 / rate, j * 1000.0 / rate, j) for j in range(ja, jb)), reqs, rate)
        idx = np.array([j for _, j in picks])
        label = np.array([m for m, _ in picks]) / 1000.0
    elif eff.sampler == "submitted":
        step = max(1, round(1000 / (eff.sample_fps or eff.fps)))
        start = int(math.floor(v0 * 1000)) - 20
        ks = np.arange(0, int((t_end + 0.06) * 1000 / step) + 2)
        label_ms = start + ks * step
        idx = np.array([int(round(m / 1000.0 * eff.fps * eff.rate_ratio)) for m in label_ms])
        label = label_ms / 1000.0
    else:
        raise ValueError(eff.sampler)
    actual = idx * T - v0
    if eff.jitter_s > 0:
        actual = actual + rng.normal(0.0, eff.jitter_s, actual.size)
    return label - v0, actual


def _rs_delay(u, width, rs):
    return rs * (u / width) if rs >= 0 else -rs * (1.0 - u / width)


def observe(truth, pose, eff: Effects, rng, v0: float | None = None) -> list[tuple]:
    """Detections (t_label, u, v, radius, weight) the tracker would hand on in World B.
    v0 fixes the frame phase (video time of the release) for paired comparisons."""
    st = truth.states
    t_end = float(st[np.argmax(st[:, 1] <= CREASE_X), 0])      # the pad intercepts at the crease
    label, actual = frame_times(t_end, eff, rng, v0)
    W = pose.cx * 2
    out = []
    for lab, act in zip(label, actual):
        tc = act + abs(eff.rs_s) / 2
        for _ in range(3):                                      # capture instant depends on the column
            if not (0.0 <= tc <= t_end):
                break
            p = np.array([np.interp(tc, st[:, 0], st[:, k]) for k in (1, 2, 3)])
            u, v, depth = pose.project(p[None, :])
            tc = act + _rs_delay(float(u[0]), W, eff.rs_s)
        if not (0.0 <= tc <= t_end) or depth[0] <= 0.5:
            continue
        p = np.array([np.interp(tc, st[:, 0], st[:, k]) for k in (1, 2, 3)])
        u, v, depth = pose.project(p[None, :])
        u, v = distort(pose, u, v, eff.distortion)
        u, v = float(u[0]), float(v[0])
        if not (0 <= u < W and 0 <= v < pose.cy * 2):
            continue
        if eff.dropout and rng.random() < eff.dropout:
            continue
        r = pose.fx * R_BALL / depth[0]
        if eff.noise_px > 0:
            u += rng.normal(0.0, eff.noise_px); v += rng.normal(0.0, eff.noise_px)
        if eff.radius_noise > 0:
            r *= 1.0 + rng.normal(0.0, eff.radius_noise)
        t_est = lab + (_rs_delay(u, W, eff.rs_correct_s) if eff.rs_correct_s else 0.0)
        out.append((float(t_est), u, v, float(max(0.5, r)), 1.0))
    return out


def truth_q(truth) -> dict:
    py = float(truth.contact[1]) if np.isfinite(truth.contact[0]) else None
    return dict(pitch_y=py, crease_y=float(truth.crease[1]), y=float(truth.stumps[1]), z=float(truth.stumps[2]))


# --------------------------------------------------------------------------- #
# The estimator and its outputs
# --------------------------------------------------------------------------- #

def estimate(pose, dets) -> dict | None:
    """The four verdict inputs with the pipeline's own 1-sigma, or None if no fit."""
    if len(dets) < 6:
        return None
    rec = recon.reconstruct(pose, dets)
    pred = recon.predict_stump_plane(rec) if rec is not None else None
    if pred is None:
        return None
    tr = rec.trajectory
    _, sy_b = recon.bounce_sigma(rec)
    if abs(tr.v_post[0]) < 1e-6:
        return None
    t_c = tr.t_b + (CREASE_X - tr.x_b) / tr.v_post[0]
    crease = tr.position(np.array([t_c]))[0]
    return dict(pitch_y=float(tr.y_b) if tr.bounce_observed else None, crease_y=float(crease[1]),
                y=pred.y, z=pred.z,
                s_pitch_y=sy_b, s_crease_y=recon.position_sigma(rec, t_c)[1], s_y=pred.sigma_y, s_z=pred.sigma_z,
                bounce=bool(tr.bounce_observed), x_b=float(tr.x_b), t_b=float(tr.t_b), rms_px=rec.rms_px,
                e=float(tr.restitution))


def qvec(est: dict | None) -> np.ndarray:
    """The four measurands as a vector, NaN where missing."""
    if est is None:
        return np.full(4, np.nan)
    return np.array([np.nan if est[k] is None else est[k] for k in QTY], dtype=float)


def cal_sigma(pose_true, xy, dets, base: np.ndarray, tap_px: float, **kw) -> np.ndarray:
    """1-sigma of the four measurands from tap noise: one-sided differences of the full solve
    and fit, one tapped coordinate at a time, step = tap_px."""
    flat = xy.reshape(-1)
    J = np.zeros((flat.size, 4))
    for i in range(flat.size):
        z = flat.copy(); z[i] += tap_px
        try:
            q = qvec(estimate(solve(pose_true, z.reshape(-1, 2), **kw), dets))
        except CalibrationError:
            q = np.full(4, np.nan)
        J[i] = (q - base) / tap_px
    J = np.where(np.isfinite(J), J, 0.0)
    return tap_px * np.sqrt(np.sum(J ** 2, axis=0))


@contextmanager
def forced_split(shift: int):
    """Make the bounce detector pick the split `shift` frames away from its own choice."""
    orig = recon.find_bounce_split

    def shifted(dets, **kw):
        s = orig(dets, **kw)
        if s is None or shift == 0:
            return s
        k = min(max(s[0] + shift, 3), len(dets) - 3)
        t_b = 0.5 * (dets[k - 1][0] + dets[k][0])
        return k, t_b, 0.5 * (dets[k - 1][1] + dets[k][1]), 0.5 * (dets[k - 1][2] + dets[k][2])
    recon.find_bounce_split = shifted
    try:
        yield
    finally:
        recon.find_bounce_split = orig


# --------------------------------------------------------------------------- #
# Verdicts and risk
# --------------------------------------------------------------------------- #

def verdict(q: dict, s: dict, k: float) -> str:
    """decide() on measurands q (metres) and 1-sigmas s. pitch_y None = bounce not seen."""
    return decide(leg_sign=1.0, pitch_y=q["pitch_y"], pitch_sigma=s["pitch_y"],
                  impact_y=q["crease_y"], impact_sigma=s["crease_y"],
                  stump_y=q["y"], stump_z=q["z"], sigma_y=s["y"], sigma_z=s["z"], k=k).decision


def margins(q: dict) -> list[tuple[float, float]]:
    """(signed distance inside the boundary, umpire's-call width outside it) for each test
    decide() applies, in the same order and with the same geometry."""
    w = STUMP_OUTER_HALF_M
    out = []
    if q["pitch_y"] is not None:
        out.append((w - q["pitch_y"], 0.0))
    out.append((w - abs(q["crease_y"]), R_BALL))
    out.append((w - abs(q["y"]), R_BALL))
    out.append((WICKET_TOP_M - q["z"], R_BALL))
    return out


def specific_risk(q: dict, s: dict) -> tuple[float, float]:
    """JCGM 106 specific risks under a flat prior and independent Gaussian errors:
    P(the ICC rule on the true path says not out) and P(it says out)."""
    from scipy.stats import norm
    sig = [s["pitch_y"]] if q["pitch_y"] is not None else []
    sig += [s["crease_y"], s["y"], s["z"]]
    p_pass, p_in = 1.0, 1.0
    for (m, outer), sg in zip(margins(q), sig):
        sg = max(sg, 1e-9)
        p_pass *= norm.cdf((m + outer) / sg)     # not a clear fail
        p_in *= norm.cdf(m / sg)                 # fully inside
    return 1.0 - p_pass, p_in


def load_json(name):
    with open(os.path.join(OUT, name)) as fh:
        return json.load(fh)


def save_json(name, obj):
    with open(os.path.join(OUT, name), "w") as fh:
        json.dump(obj, fh, indent=2, default=float)


__all__ = ["Effects", "Camera", "Delivery", "fly", "REF_CAM", "QTY", "RATE_TEST5", "taps", "solve",
           "observe", "frame_times", "truth_q", "estimate", "qvec", "cal_sigma", "forced_split",
           "verdict", "specific_risk", "margins", "replace", "asdict", "CalibrationError", "OUT",
           "load_json", "save_json", "PITCH_LENGTH_M"]
