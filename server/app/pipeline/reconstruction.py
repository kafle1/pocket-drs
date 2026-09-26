"""Refine one tracked delivery into a metric 3-D path with an uncertainty.

trajectory.py picks the ball and a first 3-D flight. Here that flight is fitted to every
detection by robust least squares, with gravity, air drag, the ball's radius and the pitch
plane fixed, and its covariance is carried through to the stump-plane prediction.

Model: both halves leave the contact point (x_b, y_b, R) at t_b, the one before it with
velocity (vx-, vy-, vz-) under gravity plus a constant sideways swing, the one after it with
(k vx-, vy+, -e vz-) under gravity alone, and both slowed by a cricket ball's drag (_flight).

Ten parameters: t_b, x_b, y_b, vx-, vy-, vz-, k, vy+, e, swing. The post-bounce sideways
velocity is free so seam and spin deviation off the pitch is measured, not assumed; the pace
kept down the pitch (k) and the vertical rebound (restitution e) are estimated within
physical bounds.

A delivery whose bounce is not in the tracked window (a full toss, or a clip cut before
the pitch) is fitted as one flight under gravity and drag, with its own, larger, uncertainty.

The ball's apparent size is left out: blur and compression inflate a small blob by 20-40%,
which pulls the depth, and so the height at the stumps, off by more than it helps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from .calibration import CameraPose

GRAVITY = 9.81
BALL_RADIUS_M = 0.036
RESTITUTION_PRIOR = 0.55
RESTITUTION_BOUNDS = (0.25, 0.85)
# share of its pace down the pitch a ball keeps through the bounce, 76-88% measured (James et al. 2005)
PACE_KEPT_PRIOR = 0.85
PACE_KEPT_BOUNDS = (0.5, 1.0)
# drag deceleration over speed squared, 1/m: sea-level air, drag coefficient 0.45, a 160 g ball
DRAG_PER_M = 0.5 * 1.2 * 0.45 * math.pi * BALL_RADIUS_M ** 2 / 0.16
SWING_BOUND_MS2 = 6.0

Detection = tuple[float, float, float, float]   # t_s, u, v, weight


def _flight(p0: np.ndarray, v0: np.ndarray, a: np.ndarray, tau: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(N,3) positions and velocities tau seconds after (p0, v0), under the constant pull a and drag.

    Drag scales with the speed along the pitch instead of the full speed, 1-2% apart for a
    bowled ball, which solves dv/dt = a - k|vx|v in closed form."""
    c = max(DRAG_PER_M * abs(float(v0[0])), 1e-6)
    ct = np.maximum(c * np.asarray(tau, float), -0.9)     # a real flight never gets near -0.9; keeps a wild solver step finite
    s, L = ct / c, np.log1p(ct)
    p = p0[None, :] + v0[None, :] * (L / c)[:, None] + a[None, :] * (s / (2 * c) - L / (2 * c * c) + s * s / 4)[:, None]
    v = (v0[None, :] + a[None, :] * (s + c * s * s / 2)[:, None]) / (1.0 + ct)[:, None]
    return p, v


def _touchdown(p0: np.ndarray, v0: np.ndarray, a: np.ndarray) -> float | None:
    """Seconds until the ball centre next comes down to height R, or None if it never does."""
    vz, disc = float(v0[2]), float(v0[2]) ** 2 + 2.0 * GRAVITY * (float(p0[2]) - BALL_RADIUS_M)
    if disc <= 0:
        return None
    t = (vz + math.sqrt(disc)) / GRAVITY        # drag-free, then Newton on the drag model
    for _ in range(4):
        p, v = _flight(p0, v0, a, np.array([t]))
        t -= (p[0, 2] - BALL_RADIUS_M) / v[0, 2]
    return t


@dataclass(frozen=True)
class Trajectory:
    """Bounce delivery model. ``t`` is seconds from the first detection."""
    t_b: float
    x_b: float
    y_b: float
    v_pre: np.ndarray       # (vx-, vy-, vz-) at the instant before contact
    v_post: np.ndarray      # (vx+, vy+, vz+) at the instant after contact
    swing: float            # sideways acceleration before contact, m/s^2
    bounce_observed: bool   # False when the bounce lies outside the tracked window

    @property
    def restitution(self) -> float:
        return float(-self.v_post[2] / self.v_pre[2]) if self.v_pre[2] < 0 else float("nan")

    def _halves(self, t: np.ndarray | float) -> tuple[np.ndarray, tuple, tuple]:
        tau = np.atleast_1d(np.asarray(t, dtype=float)) - self.t_b
        anchor = np.array([self.x_b, self.y_b, BALL_RADIUS_M])
        pre = _flight(anchor, self.v_pre, np.array([0.0, self.swing, -GRAVITY]), tau)
        post = _flight(anchor, self.v_post, np.array([0.0, 0.0, -GRAVITY]), tau)
        return (tau >= 0.0)[:, None], pre, post

    def position(self, t: np.ndarray | float) -> np.ndarray:
        """(N,3) world positions at times ``t``."""
        after, pre, post = self._halves(t)
        return np.where(after, post[0], pre[0])

    def velocity(self, t: float) -> np.ndarray:
        after, pre, post = self._halves(t)
        return np.where(after, post[1], pre[1])[0]

    def as_dict(self) -> dict:
        return {
            "t_b_s": self.t_b, "x_b_m": self.x_b, "y_b_m": self.y_b,
            "v_pre_ms": [float(a) for a in self.v_pre],
            "v_post_ms": [float(a) for a in self.v_post],
            "swing_ms2": self.swing,
            "restitution": self.restitution,
            "bounce_observed": self.bounce_observed,
        }


@dataclass(frozen=True)
class Reconstruction:
    trajectory: Trajectory
    covariance: np.ndarray          # 10x10 over (t_b, x_b, y_b, v_pre, k, vy+, e, swing)
    rms_px: float
    notes: list[str]


@dataclass(frozen=True)
class StumpPlanePrediction:
    t: float
    y: float
    z: float
    sigma_y: float
    sigma_z: float


def _flight_px(pose: CameraPose, theta: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pixels and depth of the single flight theta = (x0, y0, z0, vx, vy, vz) at times t."""
    return pose.project(_flight(theta[:3], theta[3:], np.array([0.0, 0.0, -GRAVITY]), t)[0])


# --------------------------------------------------------------------------- #
# Nonlinear refinement
# --------------------------------------------------------------------------- #

def _unpack(theta: np.ndarray, bounce_observed: bool) -> Trajectory:
    t_b, x_b, y_b, vx0, vy0, vz0, k, vy1, e, swing = (float(a) for a in theta)
    v_pre = np.array([vx0, vy0, vz0])
    v_post = np.array([k * vx0, vy1, -e * vz0])
    return Trajectory(t_b, x_b, y_b, v_pre, v_post, swing, bounce_observed)


def _fit_bounce(pose: CameraPose, dets: list[Detection], theta0: np.ndarray, *, f_scale: float) -> tuple[np.ndarray, np.ndarray, float] | None:
    t, u, v, w = (np.array(c, float) for c in zip(*dets))
    w = np.sqrt(np.maximum(w, 0.05))
    t_lo, t_hi = float(t.min()), float(t.max())

    def residuals(theta):
        tr = _unpack(theta, True)
        uu, vv, depth = pose.project(tr.position(t))
        bad = depth <= 0.05
        ru = np.where(bad, 1e3, (u - uu) * w)
        rv = np.where(bad, 1e3, (v - vv) * w)
        # soft priors, in pixel-comparable units: typical restitution and pace kept, little
        # sideways change at contact and modest swing unless the pixels say otherwise
        pri = np.array([
            (theta[8] - RESTITUTION_PRIOR) / 0.15,
            (theta[6] - PACE_KEPT_PRIOR) / 0.15,
            (theta[7] - theta[4]) / 2.0,
            theta[9] / 2.0,
        ])
        return np.concatenate([ru, rv, pri])

    lower = np.array([t_lo, -10.0, -3.0, -60.0, -15.0, -25.0, PACE_KEPT_BOUNDS[0], -15.0, RESTITUTION_BOUNDS[0], -SWING_BOUND_MS2])
    upper = np.array([t_hi, 35.0, 3.0, -1.0, 15.0, -0.05, PACE_KEPT_BOUNDS[1], 15.0, RESTITUTION_BOUNDS[1], SWING_BOUND_MS2])
    x0 = np.clip(theta0, lower + 1e-6, upper - 1e-6)
    try:
        sol = least_squares(residuals, x0, bounds=(lower, upper), loss="soft_l1",
                            f_scale=f_scale, max_nfev=400, xtol=1e-10, ftol=1e-10)
    except Exception:
        return None
    if sol.status <= 0:
        return None
    rms = float(np.sqrt(np.mean(sol.fun[:2 * len(dets)] ** 2)))
    dof = max(1, len(sol.fun) - len(x0))
    cov = _covariance(sol.jac, float(np.sum(sol.fun ** 2)) / dof)
    return sol.x, cov, rms


def _fit_flight(pose: CameraPose, dets: list[Detection], theta0: np.ndarray, *, f_scale: float) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Single flight under gravity and drag. theta = (x0, y0, z0, vx, vy, vz) at t=0."""
    t, u, v, w = (np.array(c, float) for c in zip(*dets))
    w = np.sqrt(np.maximum(w, 0.05))

    def residuals(theta):
        uu, vv, depth = _flight_px(pose, theta, t)
        bad = depth <= 0.05
        ru = np.where(bad, 1e3, (u - uu) * w)
        rv = np.where(bad, 1e3, (v - vv) * w)
        return np.concatenate([ru, rv])

    lower = np.array([-10.0, -3.0, 0.0, -60.0, -15.0, -25.0])
    upper = np.array([35.0, 3.0, 4.0, -1.0, 15.0, 15.0])
    x0 = np.clip(theta0, lower + 1e-6, upper - 1e-6)
    try:
        sol = least_squares(residuals, x0, bounds=(lower, upper), loss="soft_l1",
                            f_scale=f_scale, max_nfev=400, xtol=1e-10, ftol=1e-10)
    except Exception:
        return None
    m = 2 * len(dets)
    rms = float(np.sqrt(np.mean(sol.fun[:m] ** 2)))
    dof = max(1, len(sol.fun) - len(x0))
    cov = _covariance(sol.jac, float(np.sum(sol.fun ** 2)) / dof)
    return sol.x, cov, rms


def _covariance(jac: np.ndarray, sigma2: float) -> np.ndarray:
    jtj = jac.T @ jac
    try:
        return sigma2 * np.linalg.pinv(jtj)
    except np.linalg.LinAlgError:
        return np.full((jtj.shape[0], jtj.shape[0]), np.inf)


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #

def reconstruct(pose: CameraPose, dets: list[Detection], start: Trajectory, *, f_scale_px: float = 2.0) -> Reconstruction | None:
    """Refine the tracker's delivery on its detections (t_s from the first, u, v, weight).

    With a bounce in the track both parabolas are fitted through one contact point. Without one,
    a single parabola, reported with its own, larger, uncertainty.
    """
    if start.bounce_observed:
        fit = _fit_bounce(pose, dets, _theta_of(start), f_scale=f_scale_px)
        if fit is None:
            return None
        theta, cov, rms = fit
        tr = _unpack(theta, True)
        return Reconstruction(tr, cov, rms, [f"bounce at t_b={tr.t_b:.3f}s, e={tr.restitution:.2f}"])
    th0 = np.concatenate([start.position(0.0)[0], start.velocity(0.0)])
    fit = _fit_flight(pose, dets, th0, f_scale=f_scale_px)
    if fit is None:
        return None
    theta, cov6, rms = fit
    return Reconstruction(flight_trajectory(theta), _flight_covariance(theta, cov6), rms,
                          ["no bounce in the tracked window; single-parabola fit"])


def flight_trajectory(theta: np.ndarray) -> Trajectory:
    """Express a single flight in the bounce parameterisation by placing the (unobserved)
    contact where it would meet the ground, with the prior restitution and pace kept."""
    p0, v0, g = np.asarray(theta[:3], float), np.asarray(theta[3:], float), np.array([0.0, 0.0, -GRAVITY])
    t_b = _touchdown(p0, v0, g)
    if t_b is None:
        t_b = max(0.0, (float(v0[2]) + 1e-6) / GRAVITY)
    p, v = (a[0] for a in _flight(p0, v0, g, np.array([t_b])))
    v_post = np.array([PACE_KEPT_PRIOR * v[0], v[1], -RESTITUTION_PRIOR * v[2]])
    return Trajectory(t_b, float(p[0]), float(p[1]), v, v_post, 0.0, False)


def _flight_covariance(theta: np.ndarray, cov6: np.ndarray) -> np.ndarray:
    """Push the 6-parameter covariance through the reparameterisation numerically, and give
    the unobserved pace kept, restitution and post-bounce deviation their prior spread."""
    def f(th):
        tr = flight_trajectory(th)
        return np.array([tr.t_b, tr.x_b, tr.y_b, *tr.v_pre, PACE_KEPT_PRIOR, tr.v_post[1], RESTITUTION_PRIOR, 0.0])
    J = _numeric_jacobian(f, theta)
    cov = J @ cov6 @ J.T
    cov[6, 6] += 0.15 ** 2
    cov[7, 7] += 2.0 ** 2
    cov[8, 8] += 0.15 ** 2
    return cov


def _numeric_jacobian(f, x: np.ndarray, rel: float = 1e-6) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    f0 = np.atleast_1d(f(x))
    J = np.zeros((f0.size, x.size))
    for i in range(x.size):
        h = rel * max(1.0, abs(x[i]))
        xp = x.copy(); xp[i] += h
        xm = x.copy(); xm[i] -= h
        J[:, i] = (np.atleast_1d(f(xp)) - np.atleast_1d(f(xm))) / (2 * h)
    return J


def _theta_of(tr: Trajectory) -> np.ndarray:
    e = tr.restitution if math.isfinite(tr.restitution) else RESTITUTION_PRIOR
    k = tr.v_post[0] / tr.v_pre[0] if tr.v_pre[0] else PACE_KEPT_PRIOR
    return np.array([tr.t_b, tr.x_b, tr.y_b, *tr.v_pre, k, tr.v_post[1], e, tr.swing])


def _stump_plane_point(theta: np.ndarray, x_target: float, bounce_observed: bool) -> np.ndarray:
    """(t, y, z, n_extra_bounces) where the path crosses x = x_target.
    A ball that would touch down again before the plane is bounced again with the same
    restitution."""
    tr = _unpack(theta, bounce_observed)
    p, v, t_b = np.array([tr.x_b, tr.y_b, BALL_RADIUS_M]), tr.v_post.copy(), tr.t_b
    g = np.array([0.0, 0.0, -GRAVITY])
    if tr.x_b <= x_target:
        # a full toss lands past the plane, so it crosses on the way down
        if abs(tr.v_pre[0]) < 1e-6:
            return np.array([np.nan, np.nan, np.nan, 0])
        c = DRAG_PER_M * abs(tr.v_pre[0])
        ct = math.expm1((x_target - tr.x_b) * c / tr.v_pre[0])
        if ct <= -0.9:
            return np.array([np.nan, np.nan, np.nan, 0])
        q = _flight(p, tr.v_pre, np.array([0.0, tr.swing, -GRAVITY]), np.array([ct / c]))[0][0]
        return np.array([t_b + ct / c, q[1], q[2], 0])
    extra = 0
    for _ in range(4):
        if abs(v[0]) < 1e-6:
            return np.array([np.nan, np.nan, np.nan, extra])
        c = DRAG_PER_M * abs(v[0])
        tau = max(0.0, math.expm1((x_target - p[0]) * c / v[0]) / c)   # x under drag, inverted
        q = _flight(p, v, g, np.array([tau]))[0][0]
        if q[2] >= BALL_RADIUS_M - 1e-9:
            return np.array([t_b + tau, q[1], q[2], extra])
        # second contact before the plane
        t_hit = _touchdown(p, v, g) if v[2] > 0 else 1e-6
        p, v = (a[0] for a in _flight(p, v, g, np.array([t_hit])))
        p[2] = BALL_RADIUS_M
        v = np.array([v[0], v[1], -tr.restitution * v[2]])
        t_b += t_hit
        extra += 1
    return np.array([np.nan, np.nan, np.nan, extra])


def predict_stump_plane(rec: Reconstruction, x_target: float = 0.0) -> StumpPlanePrediction | None:
    """Where the ball crosses the stump plane, with 1-sigma bounds propagated from the fit."""
    theta = _theta_of(rec.trajectory)
    p = _stump_plane_point(theta, x_target, rec.trajectory.bounce_observed)
    if not np.all(np.isfinite(p[:3])):
        return None
    J = _numeric_jacobian(lambda th: _stump_plane_point(th, x_target, rec.trajectory.bounce_observed)[1:3], theta)
    S = J @ rec.covariance @ J.T
    sy = float(math.sqrt(max(S[0, 0], 0.0)))
    sz = float(math.sqrt(max(S[1, 1], 0.0)))
    return StumpPlanePrediction(float(p[0]), float(p[1]), float(p[2]), sy, sz)


def position_sigma(rec: Reconstruction, t: float) -> tuple[float, float, float]:
    """1-sigma of the modelled position at time ``t``, per axis."""
    theta = _theta_of(rec.trajectory)
    J = _numeric_jacobian(lambda th: _unpack(th, rec.trajectory.bounce_observed).position(t)[0], theta)
    S = J @ rec.covariance @ J.T
    return tuple(float(math.sqrt(max(S[i, i], 0.0))) for i in range(3))


def bounce_sigma(rec: Reconstruction) -> tuple[float, float]:
    """1-sigma of the contact point along and across the pitch."""
    c = rec.covariance
    return float(math.sqrt(max(c[1, 1], 0.0))), float(math.sqrt(max(c[2, 2], 0.0)))


def speed_sigma(rec: Reconstruction) -> float:
    """1-sigma of the speed at the first detection, m/s."""
    theta = _theta_of(rec.trajectory)
    J = _numeric_jacobian(lambda th: np.linalg.norm(_unpack(th, rec.trajectory.bounce_observed).velocity(0.0)), theta)
    return float(math.sqrt(max((J @ rec.covariance @ J.T)[0, 0], 0.0)))


def sample_path(tr: Trajectory, t_from: float, t_to: float, n: int = 48) -> np.ndarray:
    """(n,4) rows of t, x, y, z along the modelled flight, clamped to the ground."""
    ts = np.linspace(t_from, t_to, max(2, n))
    p = tr.position(ts)
    p[:, 2] = np.maximum(p[:, 2], 0.0)
    return np.column_stack([ts, p])
