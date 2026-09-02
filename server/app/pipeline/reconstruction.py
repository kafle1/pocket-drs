"""Monocular 3-D reconstruction of one cricket delivery from a calibrated single view.

A delivery is a projectile from release to the pitch, one bounce, and a projectile again
until it reaches the batter. One camera cannot measure the depth of any single detection,
but three things are known exactly: gravity, the ball's radius, and the plane it bounces
on. The bounce is the anchor. Its image position back-projects onto the ground plane to a
metric point with no depth ambiguity, and once that point and the bounce instant are fixed
every other parameter of the two parabolas is linear in the pixel measurements.

Model, with tau = t - t_b and the ball centre at height R at contact:

    pre-bounce   p(t) = (x_b, y_b, R) + (vx-, vy-, vz-) tau - (0, 0, g/2) tau^2
    post-bounce  p(t) = (x_b, y_b, R) + (vx+, vy+, -e vz-) tau - (0, 0, g/2) tau^2

Nine parameters: t_b, x_b, y_b, vx-, vy-, vz-, vx+, vy+, e. The post-bounce horizontal
velocity is free so seam and spin deviation off the pitch is measured, not assumed; the
vertical rebound is tied to the pre-bounce descent through a restitution coefficient that
is itself estimated within physical bounds.

A delivery whose bounce is not in the observed window (a full toss, or a clip cut before
the pitch) falls back to the six-parameter single-parabola model of Ribnick et al. with the
ball's apparent size as the scale cue. That estimate is reported with its own, larger,
uncertainty.
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

Detection = tuple[float, float, float, float, float]   # t_s, u, v, radius_px, weight


@dataclass(frozen=True)
class Trajectory:
    """Two-parabola delivery model. ``t`` is seconds from the first detection."""
    t_b: float
    x_b: float
    y_b: float
    v_pre: np.ndarray       # (vx-, vy-, vz-) at the instant before contact
    v_post: np.ndarray      # (vx+, vy+, vz+) at the instant after contact
    bounce_observed: bool   # False when the bounce lies outside the tracked window

    @property
    def restitution(self) -> float:
        return float(-self.v_post[2] / self.v_pre[2]) if self.v_pre[2] < 0 else float("nan")

    def position(self, t: np.ndarray | float) -> np.ndarray:
        """(N,3) world positions at times ``t``."""
        tau = np.atleast_1d(np.asarray(t, dtype=float)) - self.t_b
        anchor = np.array([self.x_b, self.y_b, BALL_RADIUS_M])
        post = tau >= 0.0
        v = np.where(post[:, None], self.v_post[None, :], self.v_pre[None, :])
        p = anchor[None, :] + v * tau[:, None]
        p[:, 2] -= 0.5 * GRAVITY * tau ** 2
        return p

    def velocity(self, t: float) -> np.ndarray:
        tau = t - self.t_b
        v = (self.v_post if tau >= 0.0 else self.v_pre).copy()
        v[2] -= GRAVITY * tau
        return v

    def as_dict(self) -> dict:
        return {
            "t_b_s": self.t_b, "x_b_m": self.x_b, "y_b_m": self.y_b,
            "v_pre_ms": [float(a) for a in self.v_pre],
            "v_post_ms": [float(a) for a in self.v_post],
            "restitution": self.restitution,
            "bounce_observed": self.bounce_observed,
        }


@dataclass(frozen=True)
class Reconstruction:
    trajectory: Trajectory
    covariance: np.ndarray          # 9x9 over (t_b, x_b, y_b, v_pre, vx+, vy+, e)
    rms_px: float
    n_pre: int
    n_post: int
    notes: list[str]


@dataclass(frozen=True)
class StumpPlanePrediction:
    t: float
    y: float
    z: float
    sigma_y: float
    sigma_z: float
    extra_bounces: int


# --------------------------------------------------------------------------- #
# Image-space bounce detection
# --------------------------------------------------------------------------- #

def _quad_fit(t: np.ndarray, x: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, float]:
    """Weighted quadratic in t. Returns coefficients (highest first) and weighted SSE."""
    deg = 2 if len(t) >= 3 else 1
    c = np.polyfit(t, x, deg, w=np.sqrt(w))
    r = x - np.polyval(c, t)
    return c, float(np.sum(w * r * r))


def find_bounce_split(dets: list[Detection], *, min_side: int = 3) -> tuple[int, float, float, float] | None:
    """Locate the pitch contact in the image track.

    Fits one quadratic per axis to the whole track and to every pre/post split, and keeps
    the split that explains the pixels best. Vertical image motion reverses at contact, so
    a real bounce halves the residual; a full toss gains nothing from splitting and is
    reported as None. Returns (k, t_b, u_b, v_b): the first post-bounce index, the contact
    instant interpolated from the two vertical arcs, and the image point at that instant.
    """
    n = len(dets)
    if n < 2 * min_side:
        return None
    t = np.array([d[0] for d in dets]); u = np.array([d[1] for d in dets])
    v = np.array([d[2] for d in dets]); w = np.array([max(d[4], 0.05) for d in dets])
    _, sse_u = _quad_fit(t, u, w)
    _, sse_v = _quad_fit(t, v, w)
    whole = sse_u + sse_v

    best = None
    for k in range(min_side, n - min_side + 1):
        cu1, s1 = _quad_fit(t[:k], u[:k], w[:k]); cv1, s2 = _quad_fit(t[:k], v[:k], w[:k])
        cu2, s3 = _quad_fit(t[k:], u[k:], w[k:]); cv2, s4 = _quad_fit(t[k:], v[k:], w[k:])
        sse = s1 + s2 + s3 + s4
        if best is None or sse < best[0]:
            best = (sse, k, cu1, cv1, cu2, cv2)
    if best is None or best[0] > 0.5 * whole:
        return None
    sse, k, cu1, cv1, cu2, cv2 = best

    # contact instant: where the two vertical arcs meet, bracketed by the neighbouring frames
    lo, hi = t[k - 1], t[k]
    ts = np.linspace(lo, hi, 41)
    gap = np.abs(np.polyval(cv1, ts) - np.polyval(cv2, ts)) + np.abs(np.polyval(cu1, ts) - np.polyval(cu2, ts))
    t_b = float(ts[int(np.argmin(gap))])
    u_b = 0.5 * (np.polyval(cu1, t_b) + np.polyval(cu2, t_b))
    v_b = 0.5 * (np.polyval(cv1, t_b) + np.polyval(cv2, t_b))
    return k, t_b, float(u_b), float(v_b)


# --------------------------------------------------------------------------- #
# Linear initialisation
# --------------------------------------------------------------------------- #

def _velocity_from_anchor(pose: CameraPose, dets: list[Detection], anchor: np.ndarray, t_b: float) -> np.ndarray | None:
    """Velocity at contact for one side of the bounce, given the contact point.

    With p(t) = a + V tau - (0,0,g/2) tau^2 and a known, the projection equations are
    linear in V after cross-multiplying out the depth. Two equations per frame, three
    unknowns.
    """
    if len(dets) < 2:
        return None
    R, tr = pose.R, pose.t
    rows, rhs = [], []
    for t, u, v, _r, w in dets:
        tau = t - t_b
        b = R @ (anchor + np.array([0.0, 0.0, -0.5 * GRAVITY * tau * tau])) + tr
        M = R * tau
        sw = math.sqrt(max(w, 0.05))
        rows.append(sw * ((u - pose.cx) * M[2] - pose.fx * M[0]))
        rhs.append(sw * (pose.fx * b[0] - (u - pose.cx) * b[2]))
        rows.append(sw * ((v - pose.cy) * M[2] - pose.fy * M[1]))
        rhs.append(sw * (pose.fy * b[1] - (v - pose.cy) * b[2]))
    V, *_ = np.linalg.lstsq(np.asarray(rows), np.asarray(rhs), rcond=None)
    return V if np.all(np.isfinite(V)) else None


def _linear_parabola(pose: CameraPose, dets: list[Detection]) -> np.ndarray | None:
    """Ribnick, Atev and Papanikolopoulos (2009): the six parameters of a single gravity
    parabola are linear in the pixel measurements. Returns (x0, y0, z0, vx, vy, vz) at t=0."""
    if len(dets) < 3:
        return None
    R, tr = pose.R, pose.t
    rows, rhs = [], []
    for t, u, v, _r, w in dets:
        A = np.hstack([R, R * t])                       # camera coords = A theta + b
        b = R @ np.array([0.0, 0.0, -0.5 * GRAVITY * t * t]) + tr
        sw = math.sqrt(max(w, 0.05))
        rows.append(sw * ((u - pose.cx) * A[2] - pose.fx * A[0]))
        rhs.append(sw * (pose.fx * b[0] - (u - pose.cx) * b[2]))
        rows.append(sw * ((v - pose.cy) * A[2] - pose.fy * A[1]))
        rhs.append(sw * (pose.fy * b[1] - (v - pose.cy) * b[2]))
    th, *_ = np.linalg.lstsq(np.asarray(rows), np.asarray(rhs), rcond=None)
    return th if np.all(np.isfinite(th)) else None


# --------------------------------------------------------------------------- #
# Nonlinear refinement
# --------------------------------------------------------------------------- #

def _unpack(theta: np.ndarray, bounce_observed: bool) -> Trajectory:
    t_b, x_b, y_b, vx0, vy0, vz0, vx1, vy1, e = (float(a) for a in theta)
    v_pre = np.array([vx0, vy0, vz0])
    v_post = np.array([vx1, vy1, -e * vz0])
    return Trajectory(t_b, x_b, y_b, v_pre, v_post, bounce_observed)


def _fit_bounce(pose: CameraPose, dets: list[Detection], theta0: np.ndarray, *, f_scale: float) -> tuple[np.ndarray, np.ndarray, float] | None:
    t = np.array([d[0] for d in dets]); u = np.array([d[1] for d in dets])
    v = np.array([d[2] for d in dets]); w = np.sqrt(np.array([max(d[4], 0.05) for d in dets]))
    t_lo, t_hi = float(t.min()), float(t.max())

    def residuals(theta):
        tr = _unpack(theta, True)
        uu, vv, depth = pose.project(tr.position(t))
        bad = depth <= 0.05
        ru = np.where(bad, 1e3, (u - uu) * w)
        rv = np.where(bad, 1e3, (v - vv) * w)
        # soft priors, in pixel-comparable units: restitution near its typical value, and the
        # horizontal velocity change at contact small unless the pixels say otherwise
        pri = np.array([
            (theta[8] - RESTITUTION_PRIOR) / 0.15,
            (theta[6] - theta[3]) / 4.0,
            (theta[7] - theta[4]) / 2.0,
        ])
        return np.concatenate([ru, rv, pri])

    lower = np.array([t_lo, -10.0, -3.0, -60.0, -15.0, -25.0, -60.0, -15.0, RESTITUTION_BOUNDS[0]])
    upper = np.array([t_hi, 35.0, 3.0, 60.0, 15.0, -0.05, 60.0, 15.0, RESTITUTION_BOUNDS[1]])
    x0 = np.clip(theta0, lower + 1e-6, upper - 1e-6)
    try:
        sol = least_squares(residuals, x0, bounds=(lower, upper), loss="soft_l1",
                            f_scale=f_scale, max_nfev=400, xtol=1e-10, ftol=1e-10)
    except Exception:
        return None
    if not sol.success and sol.status <= 0:
        return None
    m = 2 * len(dets)
    pix = sol.fun[:m]
    rms = float(np.sqrt(np.mean(pix ** 2)))
    dof = max(1, m - len(x0))
    cov = _covariance(sol.jac, float(np.sum(sol.fun ** 2)) / dof)
    return sol.x, cov, rms


def _fit_flight(pose: CameraPose, dets: list[Detection], theta0: np.ndarray, *, f_scale: float, radius_weight: float) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Single parabola with the apparent-size cue. theta = (x0, y0, z0, vx, vy, vz) at t=0."""
    t = np.array([d[0] for d in dets]); u = np.array([d[1] for d in dets])
    v = np.array([d[2] for d in dets]); r = np.array([d[3] for d in dets])
    w = np.sqrt(np.array([max(d[4], 0.05) for d in dets]))
    use_r = r > 1.0

    def positions(theta):
        p = theta[None, :3] + theta[None, 3:] * t[:, None]
        p[:, 2] -= 0.5 * GRAVITY * t * t
        return p

    def residuals(theta):
        uu, vv, depth = pose.project(positions(theta))
        bad = depth <= 0.05
        ru = np.where(bad, 1e3, (u - uu) * w)
        rv = np.where(bad, 1e3, (v - vv) * w)
        r_hat = pose.fx * BALL_RADIUS_M / np.where(bad, 1.0, depth)
        rr = np.where(use_r & ~bad, radius_weight * w * (r - r_hat), 0.0)
        return np.concatenate([ru, rv, rr])

    lower = np.array([-10.0, -3.0, 0.0, -60.0, -15.0, -25.0])
    upper = np.array([35.0, 3.0, 4.0, 60.0, 15.0, 15.0])
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

def reconstruct(pose: CameraPose, dets: list[Detection], *, f_scale_px: float = 2.0) -> Reconstruction | None:
    """Recover the delivery from per-frame detections (t_s, u, v, radius_px, weight).

    Tries the bounce model first. When no contact is visible in the track, or the anchored
    fit does not explain the pixels, the single-parabola model is used and flagged.
    """
    dets = sorted(dets, key=lambda d: d[0])
    if len(dets) < 4:
        return None
    t0 = dets[0][0]
    dets = [(d[0] - t0, d[1], d[2], d[3], d[4]) for d in dets]
    notes: list[str] = []

    split = find_bounce_split(dets)
    if split is not None:
        k, t_b, u_b, v_b = split
        best = None
        for anchor in _anchor_candidates(pose, dets, k, t_b, u_b, v_b):
            v_pre = _velocity_from_anchor(pose, dets[:k], anchor, t_b)
            if v_pre is None or v_pre[2] >= -0.05:
                continue
            v_post = _velocity_from_anchor(pose, dets[k:], anchor, t_b)
            if v_post is None:
                v_post = v_pre * np.array([1.0, 1.0, -RESTITUTION_PRIOR])
            e0 = float(np.clip(-v_post[2] / v_pre[2], *RESTITUTION_BOUNDS))
            theta0 = np.array([t_b, anchor[0], anchor[1], *v_pre, v_post[0], v_post[1], e0])
            fit = _fit_bounce(pose, dets, theta0, f_scale=f_scale_px)
            if fit is not None and (best is None or fit[2] < best[2]):
                best = fit
        if best is not None:
            theta, cov, rms = best
            tr = _unpack(theta, True)
            notes.append(f"bounce anchored at frame {k}, t_b={tr.t_b:.3f}s, e={tr.restitution:.2f}")
            n_post = int(np.sum(np.array([d[0] for d in dets]) >= tr.t_b))
            return Reconstruction(tr, cov, rms, len(dets) - n_post, n_post, notes)
        notes.append("bounce seen in image but no anchored fit converged")

    # no contact in the window: one parabola, scale from gravity and apparent size
    th0 = _linear_parabola(pose, dets)
    if th0 is None:
        return None
    fit = _fit_flight(pose, dets, th0, f_scale=f_scale_px, radius_weight=0.3)
    if fit is None:
        return None
    theta, cov6, rms = fit
    tr = _flight_as_trajectory(theta, pose)
    cov = _flight_covariance(theta, cov6, pose)
    notes.append("no bounce in the tracked window; single-parabola fit")
    return Reconstruction(tr, cov, rms, len(dets), 0, notes)


def _anchor_candidates(pose: CameraPose, dets: list[Detection], k: int, t_b: float, u_b: float, v_b: float) -> list[np.ndarray]:
    """Starting points for the contact position. The image intersection is exact when the
    contact is close; seen from far down the pitch a pixel of error on the ground plane is
    metres, so the pre- and post-bounce parabolas' own ground crossings are tried as well
    and the fit that explains the pixels best wins."""
    L = pose.pitch_length_m
    out = []

    def keep(p):
        if p is not None and np.all(np.isfinite(p)) and -2.0 <= p[0] <= L + 2.0 and abs(p[1]) <= 2.0:
            out.append(np.array([p[0], p[1], BALL_RADIUS_M]))

    keep(pose.backproject_to_plane(u_b, v_b, BALL_RADIUS_M))
    for side in (dets[:k], dets[k:]):
        th = _linear_parabola(pose, side) if len(side) >= 3 else None
        if th is None:
            continue
        t_side = side[0][0]
        tau = t_b - t_side
        keep(np.array([th[0] + th[3] * tau, th[1] + th[4] * tau, BALL_RADIUS_M]))
    for i in (k - 1, k):
        keep(pose.backproject_to_plane(dets[i][1], dets[i][2], BALL_RADIUS_M))
    if not out:
        p = pose.backproject_to_plane(u_b, v_b, BALL_RADIUS_M)
        x = float(np.clip(p[0], 0.5, L - 0.5)) if p is not None and np.isfinite(p[0]) else L / 3.0
        y = float(np.clip(p[1], -1.5, 1.5)) if p is not None and np.isfinite(p[1]) else 0.0
        out.append(np.array([x, y, BALL_RADIUS_M]))
    return out


def _flight_as_trajectory(theta: np.ndarray, pose: CameraPose) -> Trajectory:
    """Express a single parabola in the bounce parameterisation by placing the (unobserved)
    contact where the parabola would meet the ground, with the prior restitution."""
    x0, y0, z0, vx, vy, vz = (float(a) for a in theta)
    h = z0 - BALL_RADIUS_M
    disc = vz * vz + 2.0 * GRAVITY * h
    t_b = (vz + math.sqrt(disc)) / GRAVITY if disc > 0 else max(0.0, (vz + 1e-6) / GRAVITY)
    v_pre = np.array([vx, vy, vz - GRAVITY * t_b])
    v_post = np.array([vx, vy, -RESTITUTION_PRIOR * v_pre[2]])
    return Trajectory(t_b, x0 + vx * t_b, y0 + vy * t_b, v_pre, v_post, False)


def _flight_covariance(theta: np.ndarray, cov6: np.ndarray, pose: CameraPose) -> np.ndarray:
    """Push the 6-parameter covariance through the reparameterisation numerically, and give
    the unobserved restitution and post-bounce deviation their prior spread."""
    def f(th):
        tr = _flight_as_trajectory(th, pose)
        return np.array([tr.t_b, tr.x_b, tr.y_b, *tr.v_pre, tr.v_post[0], tr.v_post[1], RESTITUTION_PRIOR])
    J = _numeric_jacobian(f, theta)
    cov = J @ cov6 @ J.T
    cov[6, 6] += 4.0 ** 2
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
    return np.array([tr.t_b, tr.x_b, tr.y_b, *tr.v_pre, tr.v_post[0], tr.v_post[1], e])


def _stump_plane_point(theta: np.ndarray, x_target: float, bounce_observed: bool) -> np.ndarray:
    """(t, y, z, n_extra_bounces) where the post-contact path crosses x = x_target.
    A ball that would touch down again before the plane is bounced again with the same
    restitution."""
    tr = _unpack(theta, bounce_observed)
    x_b, y_b, v = tr.x_b, tr.y_b, tr.v_post.copy()
    t_b = tr.t_b
    extra = 0
    for _ in range(4):
        if abs(v[0]) < 1e-6:
            return np.array([np.nan, np.nan, np.nan, extra])
        tau = (x_target - x_b) / v[0]
        if tau < 0:
            tau = 0.0
        z = BALL_RADIUS_M + v[2] * tau - 0.5 * GRAVITY * tau * tau
        if z >= BALL_RADIUS_M - 1e-9:
            return np.array([t_b + tau, y_b + v[1] * tau, z, extra])
        # second contact before the plane
        disc = v[2] * v[2]
        t_hit = (v[2] + math.sqrt(disc)) / GRAVITY if v[2] > 0 else 1e-6
        x_b += v[0] * t_hit; y_b += v[1] * t_hit; t_b += t_hit
        v = np.array([v[0], v[1], -tr.restitution * (v[2] - GRAVITY * t_hit)])
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
    return StumpPlanePrediction(float(p[0]), float(p[1]), float(p[2]), sy, sz, int(p[3]))


def bounce_sigma(rec: Reconstruction) -> tuple[float, float]:
    """1-sigma of the contact point along and across the pitch."""
    c = rec.covariance
    return float(math.sqrt(max(c[1, 1], 0.0))), float(math.sqrt(max(c[2, 2], 0.0)))


def sample_path(tr: Trajectory, t_from: float, t_to: float, n: int = 48) -> np.ndarray:
    """(n,4) rows of t, x, y, z along the modelled flight, clamped to the ground."""
    ts = np.linspace(t_from, t_to, max(2, n))
    p = tr.position(ts)
    p[:, 2] = np.maximum(p[:, 2], 0.0)
    return np.column_stack([ts, p])
