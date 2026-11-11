"""The four verdict inputs, their uncertainty, and the calibrated rule the verdict uses.

Measurands, in metres: pitch_y (contact point across the pitch, None when the bounce was not
seen), impact_y (where the ball meets the pad, read off the fit at the last tracked frame),
y and z (the stump-plane crossing, None when the path never reaches it). Each carries three
1-sigma terms:
  fit    the reconstruction's own covariance
  cal    tap noise pushed through the calibration solve and the fit
  model  model error as a function of the bounce distance x_b, fitted on simulation
The calibrated rule (calibrated_rule.json, written by paper/experiments/exp6_calibrate.py and
exp7_risk.py) holds one block per camera end. It removes the bias where one won held out,
scales the combined sigma by the held-out coverage factors and sets the guard band. Lateral
biases are leg-side signed, so one rule serves both hands. The app and the paper both read it
from that one file.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .calibration import CalibrationError
from .reconstruction import (LEATHER, Ball, Reconstruction, StumpPlanePrediction, Trajectory, bounce_sigma, position_sigma,
                             predict_stump_plane, reconstruct)

QTY = ("pitch_y", "impact_y", "y", "z")
LATERAL = ("pitch_y", "impact_y", "y")
RULE_PATH = Path(__file__).with_name("calibrated_rule.json")
RULE = json.loads(RULE_PATH.read_text())
GUARD_K = RULE["guard_k"]
# above this pixel residual the 3-D model does not explain the track and no verdict is given
MAX_FIT_RMS_PX = 12.0
# model-error forms over the bounce distance x_b (m); p in metres, or metres per metre
MODEL_FORMS = {
    "constant": lambda p, x: np.full_like(np.asarray(x, dtype=float), p[0]),
    "proportional to x_b": lambda p, x: p[0] * np.asarray(x, dtype=float),
    "constant + proportional": lambda p, x: np.sqrt(p[0] ** 2 + (p[1] * np.asarray(x, dtype=float)) ** 2),
}


@dataclass(frozen=True)
class Measurands:
    rec: Reconstruction
    pred: StumpPlanePrediction | None
    t_impact: float               # s, in the fit's time base (first detection = 0)
    impact: np.ndarray            # world position at impact
    values: dict                  # q -> m, or None
    sigma_fit: dict               # q -> m, or None

    @property
    def x_b(self) -> float:
        return max(float(self.rec.trajectory.x_b), 0.0)


def camera_end(pose) -> str:
    return "striker" if float(pose.centre_world[0]) < pose.pitch_length_m / 2 else "bowler"


def measurands(pose, dets, *, ball: Ball = LEATHER, bounce: Trajectory | None = None, split_rank: int = 0) -> Measurands | None:
    """Fit the delivery and read off the four measurands; impact is at the last detection. ball, bounce
    and split_rank go to reconstruct."""
    rec = reconstruct(pose, dets, ball=ball, bounce=bounce, split_rank=split_rank)
    if rec is None or rec.rms_px > MAX_FIT_RMS_PX:
        return None
    pred = predict_stump_plane(rec)
    tr = rec.trajectory
    t_i = max(d[0] for d in dets) - min(d[0] for d in dets)
    impact = tr.position(np.array([t_i]))[0]
    y, z, sy, sz = (None,) * 4 if pred is None else (pred.y, pred.z, pred.sigma_y, pred.sigma_z)
    values = dict(pitch_y=float(tr.y_b) if tr.bounce_observed else None, impact_y=float(impact[1]), y=y, z=z)
    sigma = dict(pitch_y=bounce_sigma(rec)[1], impact_y=position_sigma(rec, t_i)[1], y=sy, z=sz)
    return Measurands(rec, pred, t_i, impact, values, sigma)


def calibration_sigma(resolve, taps_px, dets, base: Measurands, tap_sigma_px: float, *, mark_bias_px: float = 0.0,
                      length_sigma_m: float = 0.0, **fit) -> tuple[dict, int]:
    """1-sigma of each measurand from tap noise, and how many of the perturbed solves failed.

    Each tapped coordinate is moved by one step in turn, the pose re-solved with resolve((n,2)
    taps) and the delivery refitted with measurands(**fit); the one-sided difference times the
    coordinate's sigma (the residual's tap noise and a fixed per-mark bias, in quadrature) is that
    coordinate's contribution. With length_sigma_m the pitch length is moved too, through
    resolve(taps, length_step). A solve or fit that fails makes every measurand it lost infinitely
    uncertain, so the verdict can't narrow on it. NaN taps are hidden marks and are skipped."""
    xy = np.asarray(taps_px, dtype=float)
    flat = xy.reshape(-1)
    sigma = math.hypot(tap_sigma_px, mark_bias_px)
    step = max(sigma, 0.5)                 # a derivative step, so exact taps still give a finite slope
    moves = [(i, step, sigma) for i in range(flat.size) if math.isfinite(flat[i])]
    if length_sigma_m:
        moves.append((None, length_sigma_m, length_sigma_m))
    sq = {q: 0.0 for q in QTY}
    failed = 0
    for i, d, s in moves:
        z = flat.copy()
        if i is not None:
            z[i] += d
        try:
            pose = resolve(z.reshape(xy.shape)) if i is not None else resolve(z.reshape(xy.shape), d)
            m = measurands(pose, dets, **fit)
        except (CalibrationError, cv2.error, np.linalg.LinAlgError):
            m = None
        lost = [q for q in QTY if base.values[q] is not None and (m is None or m.values[q] is None)]
        failed += bool(lost)
        for q in QTY:
            if base.values[q] is not None:
                sq[q] += math.inf if q in lost else ((m.values[q] - base.values[q]) / d * s) ** 2
    return {q: math.sqrt(v) for q, v in sq.items()}, failed


def stability(pose, dets, base: Measurands, **fit) -> list[Measurands]:
    """Refits that should agree with base: odd frames only, even frames only, and the image track's three
    best bounce splits. Fits that fail are left out."""
    seed = fit.pop("bounce", None)
    runs = [measurands(pose, dets[1::2], bounce=seed, **fit), measurands(pose, dets[0::2], bounce=seed, **fit)]
    runs += [measurands(pose, dets, split_rank=r, **fit) for r in range(3)]
    return [m for m in runs if m is not None]


def factors(entry: dict, x_b: float) -> tuple[float, float]:
    """Coverage factors (k68, k95) of the band whose upper edge is the first at or above x_b."""
    band = next(b for b in entry["factors"] if b["x_b_max"] is None or x_b <= b["x_b_max"])
    return band["k68"], band["k95"]


def calibrated(end: str, leg_sign: float, values: dict, sigma_fit: dict, sigma_cal: dict, x_b: float,
               bounce: bool) -> dict:
    """Each measured quantity under the rule for this camera end: value with the bias removed, u and
    U95 (half-widths of the calibrated 68 and 95 % intervals), and sigma = U95 / 1.96 for the verdict.
    A fit that saw no bounce is outside what the rule was fitted on, so its value stays as measured
    and its half-widths take the widest band's factors and the model term at the longest calibrated x_b."""
    out = {}
    for q in QTY:
        if values[q] is None:
            continue
        e = RULE[end][q]
        a = np.array([1.0, x_b])
        bias, u_b2 = 0.0, 0.0
        if bounce and e["bias"] is not None:
            bias = float(a @ np.array(e["bias"]["coef_m"])) * (leg_sign if q in LATERAL else 1.0)
            u_b2 = float(a @ np.array(e["bias"]["cov_m2"]) @ a)
        k68, k95 = factors(e, x_b) if bounce else (max(b["k68"] for b in e["factors"]), max(b["k95"] for b in e["factors"]))
        x_mod = x_b if bounce else e["x_b_max"]       # the forms grow with x_b
        s = math.sqrt(sigma_fit[q] ** 2 + sigma_cal[q] ** 2 + u_b2 + float(MODEL_FORMS[e["form"]](e["params_m"], x_mod)) ** 2)
        out[q] = dict(value=values[q] - bias, u=k68 * s, U95=k95 * s, sigma=k95 * s / 1.96)
    return out
