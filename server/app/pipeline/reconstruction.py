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
the pitch) is fitted with the six-parameter single-parabola model of Ribnick et al., with
the ball's apparent size as the scale cue, and reported with its own, larger, uncertainty.

A tennis or tape ball is light enough for air drag to matter, so its horizontal speed decays
as k s^2 along its ground track; a leather ball keeps the drag-free model the paper measured.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from .calibration import CameraPose

GRAVITY = 9.81


@dataclass(frozen=True)
class Ball:
    radius: float                   # m
    drag_k: float                   # 1/m: rho Cd A / 2m, the horizontal deceleration per speed squared
    restitution: tuple[float, float, float]   # lowest, typical, highest
    speed_kmh: tuple[float, float]  # release speeds a bowler gives this ball; a fit outside is refused


# leather: Law 4, slow spin to the fastest recorded 161 km/h; tennis: 6.7 cm, 58 g, Cd 0.55, and light
# enough that nobody bowls it past about 130; tape: a taped tennis ball, about 75 g and smoother.
# the tennis and tape figures come from ball specs, not from clips, so their results are untested
BALLS = {"leather": Ball(0.036, 0.0, (0.25, 0.55, 0.85), (50.0, 165.0)),
         "tennis": Ball(0.0335, 0.020, (0.35, 0.75, 0.95), (25.0, 135.0)),
         "tape": Ball(0.0335, 0.013, (0.3, 0.65, 0.9), (25.0, 145.0))}
LEATHER = BALLS["leather"]
BALL_RADIUS_M = LEATHER.radius

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
    ball: Ball = LEATHER

    @property
    def restitution(self) -> float:
        return float(-self.v_post[2] / self.v_pre[2]) if self.v_pre[2] < 0 else float("nan")

    def position(self, t: np.ndarray | float) -> np.ndarray:
        """(N,3) world positions at times ``t``."""
        tau = np.atleast_1d(np.asarray(t, dtype=float)) - self.t_b
        post = tau >= 0.0
        v = np.where(post[:, None], self.v_post[None, :], self.v_pre[None, :])
        return fly(np.array([self.x_b, self.y_b, self.ball.radius]), v, tau, self.ball.drag_k)

    def velocity(self, t: float) -> np.ndarray:
        tau = t - self.t_b
        v = (self.v_post if tau >= 0.0 else self.v_pre).copy()
        v[:2] /= 1.0 + max(self.ball.drag_k * math.hypot(v[0], v[1]) * tau, -0.9)
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


def fly(p: np.ndarray, v: np.ndarray, tau: np.ndarray, k: float) -> np.ndarray:
    """(N,3) positions tau seconds from p at velocity v (one row, or one per tau), gravity down and the
    horizontal speed s slowing as k s^2 along its ground track; tau may be negative, back along the flight."""
    v = np.broadcast_to(v, (len(tau), 3))
    s = np.hypot(v[:, 0], v[:, 1])
    if k > 0:
        # ponytail: drag left out of the vertical, a few percent of gravity at bowling angles
        a = np.maximum(k * s * tau, -0.9)
        dist = np.log1p(a) / k
        step = np.where(s > 1e-9, dist / np.maximum(s, 1e-9), tau)
    else:
        step = tau
    out = p[None, :] + v * np.column_stack([step, step, tau])
    out[:, 2] -= 0.5 * GRAVITY * tau ** 2
    return out


def _tau_to(dx: float, v: np.ndarray, k: float) -> float:
    """Seconds for a ball at velocity v to move dx down the pitch (negative: back along its flight), nan
    when it never moves down the pitch."""
    if abs(v[0]) < 1e-6:
        return float("nan")
    s = math.hypot(v[0], v[1])
    d = dx * s / v[0]                     # along the ground track
    return d / s if k == 0 else math.expm1(k * d) / (k * s)


@dataclass(frozen=True)
class Reconstruction:
    trajectory: Trajectory
    covariance: np.ndarray          # 9x9 over (t_b, x_b, y_b, v_pre, vx+, vy+, e)
    rms_px: float
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


def _arc_sse(pose: CameraPose, side: list[Detection]) -> float:
    """Weighted pixel error of the one gravity flight that best explains these detections."""
    th = _linear_parabola(pose, side)
    if th is None:
        return math.inf
    t = np.array([d[0] for d in side])
    u, v, _ = pose.project(fly(th[:3], th[3:], t, 0.0))
    return float(sum(d[4] * ((d[1] - a) ** 2 + (d[2] - b) ** 2) for d, a, b in zip(side, u, v)))


def find_bounce_split(dets: list[Detection], *, min_side: int = 3, rank: int = 0,
                      pose: CameraPose | None = None) -> tuple[int, float, float, float] | None:
    """Locate the pitch contact in the image track.

    Fits the whole track and every pre/post split, and keeps the split that explains the pixels
    best. Vertical image motion reverses at contact, so a real bounce halves the residual; a
    full toss gains nothing from splitting and is reported as None. With the pose each side is
    one gravity flight seen through the camera; without it, one quadratic per image axis, which
    perspective bends enough on a long slow flight to split it mid-air. Returns (k, t_b, u_b, v_b):
    the first post-bounce index, the contact instant interpolated from the two vertical arcs, and
    the image point at that instant. rank 1 and 2 give the next best splits, for the stability check.
    """
    n = len(dets)
    if n < 2 * min_side:
        return None
    t = np.array([d[0] for d in dets]); u = np.array([d[1] for d in dets])
    v = np.array([d[2] for d in dets]); w = np.array([max(d[4], 0.05) for d in dets])
    whole = _arc_sse(pose, dets) if pose else _quad_fit(t, u, w)[1] + _quad_fit(t, v, w)[1]

    ranked = []
    for k in range(min_side, n - min_side + 1):
        cu1, s1 = _quad_fit(t[:k], u[:k], w[:k]); cv1, s2 = _quad_fit(t[:k], v[:k], w[:k])
        cu2, s3 = _quad_fit(t[k:], u[k:], w[k:]); cv2, s4 = _quad_fit(t[k:], v[k:], w[k:])
        tm = 0.5 * (t[k - 1] + t[k])
        # contact sends the ball up, so on an upright camera its image motion bends up (v slows) at either end
        if np.polyval(np.polyder(cv2), tm) >= np.polyval(np.polyder(cv1), tm):
            continue
        sse = _arc_sse(pose, dets[:k]) + _arc_sse(pose, dets[k:]) if pose else s1 + s2 + s3 + s4
        ranked.append((sse, k, cu1, cv1, cu2, cv2))
    ranked = sorted((r for r in ranked if r[0] <= 0.5 * whole), key=lambda r: r[0])
    if len(ranked) <= rank:
        return None
    sse, k, cu1, cv1, cu2, cv2 = ranked[rank]

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

def _unpack(theta: np.ndarray, bounce_observed: bool, ball: Ball = LEATHER) -> Trajectory:
    t_b, x_b, y_b, vx0, vy0, vz0, vx1, vy1, e = (float(a) for a in theta)
    v_pre = np.array([vx0, vy0, vz0])
    v_post = np.array([vx1, vy1, -e * vz0])
    return Trajectory(t_b, x_b, y_b, v_pre, v_post, bounce_observed, ball)


def _fit_bounce(pose: CameraPose, dets: list[Detection], theta0: np.ndarray, *, f_scale: float,
                ball: Ball = LEATHER) -> tuple[np.ndarray, np.ndarray, float] | None:
    t = np.array([d[0] for d in dets]); u = np.array([d[1] for d in dets])
    v = np.array([d[2] for d in dets]); w = np.sqrt(np.array([max(d[4], 0.05) for d in dets]))
    t_lo, t_hi = float(t.min()), float(t.max())

    def pixels(theta):
        tr = _unpack(theta, True, ball)
        uu, vv, depth = pose.project(tr.position(t))
        bad = depth <= 0.05
        ru = np.where(bad, 1e3, (u - uu) * w)
        rv = np.where(bad, 1e3, (v - vv) * w)
        return np.concatenate([ru, rv])

    def priors(theta):
        # in units of their own sd: restitution near its typical value, and the horizontal
        # velocity change at contact small unless the pixels say otherwise
        return np.array([
            (theta[8] - ball.restitution[1]) / 0.15,
            (theta[6] - theta[3]) / 4.0,
            (theta[7] - theta[4]) / 2.0,
        ])

    lower = np.array([t_lo, -10.0, -3.0, -60.0, -15.0, -25.0, -60.0, -15.0, ball.restitution[0]])
    upper = np.array([t_hi, 35.0, 3.0, 60.0, 15.0, -0.05, 60.0, 15.0, ball.restitution[2]])
    x0 = np.clip(theta0, lower + 1e-6, upper - 1e-6)
    try:
        sol = least_squares(lambda th: np.concatenate([pixels(th), priors(th)]), x0, bounds=(lower, upper),
                            loss="soft_l1", f_scale=f_scale, max_nfev=400, xtol=1e-10, ftol=1e-10)
    except Exception:
        return None
    if sol.status <= 0 or _on_bound(sol.x, lower, upper):      # stopped on a bound: no minimum, no covariance
        return None
    pix = pixels(sol.x)
    rms = float(np.sqrt(np.mean(pix ** 2)))
    return sol.x, _covariance(pixels, priors, sol.x), rms


def _fit_flight(pose: CameraPose, dets: list[Detection], theta0: np.ndarray, *, f_scale: float, radius_weight: float,
                ball: Ball = LEATHER) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Single parabola with the apparent-size cue. theta = (x0, y0, z0, vx, vy, vz) at t=0."""
    t = np.array([d[0] for d in dets]); u = np.array([d[1] for d in dets])
    v = np.array([d[2] for d in dets]); r = np.array([d[3] for d in dets])
    w = np.sqrt(np.array([max(d[4], 0.05) for d in dets]))
    use_r = r > 1.0

    def positions(theta):
        return fly(theta[:3], theta[3:], t, ball.drag_k)

    def measured(theta):
        uu, vv, depth = pose.project(positions(theta))
        bad = depth <= 0.05
        ru = np.where(bad, 1e3, (u - uu) * w)
        rv = np.where(bad, 1e3, (v - vv) * w)
        r_hat = pose.fx * ball.radius / np.where(bad, 1.0, depth)
        rr = np.where(bad, 0.0, radius_weight * w * (r - r_hat))
        return np.concatenate([ru, rv, rr[use_r]])

    lower = np.array([-10.0, -3.0, 0.0, -60.0, -15.0, -25.0])
    upper = np.array([35.0, 3.0, 4.0, 60.0, 15.0, 15.0])
    x0 = np.clip(theta0, lower + 1e-6, upper - 1e-6)
    try:
        sol = least_squares(measured, x0, bounds=(lower, upper), loss="soft_l1",
                            f_scale=f_scale, max_nfev=400, xtol=1e-10, ftol=1e-10)
    except Exception:
        return None
    if sol.status <= 0 or _on_bound(sol.x, lower, upper):
        return None
    m = 2 * len(dets)
    rms = float(np.sqrt(np.mean(sol.fun[:m] ** 2)))
    return sol.x, _covariance(measured, None, sol.x), rms


def _on_bound(x: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> bool:
    """trf keeps x a hair inside the box even when the optimum lies outside, so test the distance."""
    return bool(np.any(np.minimum(x - lower, upper - x) <= 1e-6 * (upper - lower)))


def _covariance(measured, priors, theta: np.ndarray) -> np.ndarray:
    """Gauss-Newton covariance at the robust solution: the measured rows
    (raw residuals, raw Jacobian) are scaled by their fitted variance, prior rows are already in
    units of their own sd and add their information unscaled."""
    r = measured(theta)
    if r.size <= theta.size:
        return np.full((theta.size, theta.size), np.inf)     # no residual degrees of freedom: undetermined
    jm = _numeric_jacobian(measured, theta)
    s2 = max(float(r @ r) / (r.size - theta.size), 1e-12)
    info = jm.T @ jm / s2
    if priors is not None:
        jp = _numeric_jacobian(priors, theta)
        info = info + jp.T @ jp
    return np.linalg.pinv(info)


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #

def reconstruct(pose: CameraPose, dets: list[Detection], *, ball: Ball = LEATHER, bounce: Trajectory | None = None,
                split_rank: int = 0, f_scale_px: float = 2.0) -> Reconstruction | None:
    """Recover the delivery from per-frame detections (t_s, u, v, radius_px, weight).

    bounce is the tracker's own two-arc model, in the same time base as dets; when given, the fit
    starts from it and the image split only checks it. Otherwise the image split picks the contact
    (split_rank 1 and 2 take the runner-up splits), and only when no contact is visible is the
    single-parabola model used, and flagged.
    """
    dets = sorted(dets, key=lambda d: d[0])
    if len(dets) < 4:
        return None
    t0 = dets[0][0]
    dets = [(d[0] - t0, d[1], d[2], d[3], d[4]) for d in dets]
    notes: list[str] = []
    split = find_bounce_split(dets, rank=split_rank, pose=pose)

    if bounce is not None:
        e0 = float(np.clip(bounce.restitution, ball.restitution[0] + 1e-3, ball.restitution[2] - 1e-3))
        theta0 = np.array([bounce.t_b - t0, bounce.x_b, bounce.y_b, *bounce.v_pre, *bounce.v_post[:2], e0])
        fit = _fit_bounce(pose, dets, theta0, f_scale=f_scale_px, ball=ball)
        if fit is None:
            return None
        tr = _unpack(fit[0], True, ball)
        dt = float(np.median(np.diff([d[0] for d in dets])))
        notes.append(f"bounce from the tracker, t_b={tr.t_b:.3f}s, e={tr.restitution:.2f}")
        if split is None or abs(split[1] - tr.t_b) > 2 * dt:
            notes.append("the image track alone puts the bounce elsewhere")
        return Reconstruction(tr, fit[1], fit[2], notes)

    if split is not None:
        k, t_b, u_b, v_b = split
        best = None
        for anchor in _anchor_candidates(pose, dets, k, t_b, u_b, v_b, ball.radius):
            v_pre = _velocity_from_anchor(pose, dets[:k], anchor, t_b)
            if v_pre is None or v_pre[2] >= -0.05:
                continue
            v_post = _velocity_from_anchor(pose, dets[k:], anchor, t_b)
            if v_post is None:
                v_post = v_pre * np.array([1.0, 1.0, -ball.restitution[1]])
            e0 = float(np.clip(-v_post[2] / v_pre[2], ball.restitution[0], ball.restitution[2]))
            theta0 = np.array([t_b, anchor[0], anchor[1], *v_pre, v_post[0], v_post[1], e0])
            fit = _fit_bounce(pose, dets, theta0, f_scale=f_scale_px, ball=ball)
            if fit is not None and (best is None or fit[2] < best[2]):
                best = fit
        if best is not None:
            theta, cov, rms = best
            tr = _unpack(theta, True, ball)
            notes.append(f"bounce anchored at frame {k}, t_b={tr.t_b:.3f}s, e={tr.restitution:.2f}")
            return Reconstruction(tr, cov, rms, notes)
        return None         # a bounce was seen, so the single parabola below would model the wrong flight
    if split_rank:
        return None

    # no contact in the window: one parabola, scale from gravity and apparent size
    th0 = _linear_parabola(pose, dets)
    if th0 is None:
        return None
    fit = _fit_flight(pose, dets, th0, f_scale=f_scale_px, radius_weight=0.3, ball=ball)
    if fit is None:
        return None
    theta, cov6, rms = fit
    notes.append("no bounce in the tracked window; single-parabola fit")
    return Reconstruction(flight_trajectory(theta, ball), _flight_covariance(theta, cov6, ball), rms, notes)


def _anchor_candidates(pose: CameraPose, dets: list[Detection], k: int, t_b: float, u_b: float, v_b: float,
                       radius: float) -> list[np.ndarray]:
    """Starting points for the contact position. The image intersection is exact when the
    contact is close; seen from far down the pitch a pixel of error on the ground plane is
    metres, so the pre- and post-bounce parabolas' own ground crossings are tried as well
    and the fit that explains the pixels best wins."""
    L = pose.pitch_length_m
    out = []

    def keep(p):
        if p is not None and np.all(np.isfinite(p)) and -2.0 <= p[0] <= L + 2.0 and abs(p[1]) <= 2.0:
            out.append(np.array([p[0], p[1], radius]))

    keep(pose.backproject_to_plane(u_b, v_b, radius))
    for side in (dets[:k], dets[k:]):
        th = _linear_parabola(pose, side) if len(side) >= 3 else None
        if th is None:
            continue
        t_side = side[0][0]
        tau = t_b - t_side
        keep(np.array([th[0] + th[3] * tau, th[1] + th[4] * tau, radius]))
    for i in (k - 1, k):
        keep(pose.backproject_to_plane(dets[i][1], dets[i][2], radius))
    return out


def flight_trajectory(theta: np.ndarray, ball: Ball = LEATHER) -> Trajectory:
    """Express a single parabola in the bounce parameterisation by placing the (unobserved)
    contact where the parabola would meet the ground, with the prior restitution."""
    x0, y0, z0, vx, vy, vz = (float(a) for a in theta)
    h = z0 - ball.radius
    disc = vz * vz + 2.0 * GRAVITY * h
    t_b = (vz + math.sqrt(disc)) / GRAVITY if disc > 0 else max(0.0, (vz + 1e-6) / GRAVITY)
    v0 = np.array([vx, vy, vz])
    x_b, y_b, _ = fly(np.array([x0, y0, z0]), v0, np.array([t_b]), ball.drag_k)[0]
    v_pre = Trajectory(0.0, x0, y0, v0, v0, False, ball).velocity(t_b)
    v_post = np.array([v_pre[0], v_pre[1], -ball.restitution[1] * v_pre[2]])
    return Trajectory(t_b, float(x_b), float(y_b), v_pre, v_post, False, ball)


def _flight_covariance(theta: np.ndarray, cov6: np.ndarray, ball: Ball = LEATHER) -> np.ndarray:
    """Push the 6-parameter covariance through the reparameterisation numerically, and give
    the unobserved restitution and post-bounce deviation their prior spread."""
    def f(th):
        tr = flight_trajectory(th, ball)
        return np.array([tr.t_b, tr.x_b, tr.y_b, *tr.v_pre, tr.v_post[0], tr.v_post[1], ball.restitution[1]])
    if not np.all(np.isfinite(cov6)):
        return np.full((9, 9), np.inf)
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
    e = tr.restitution if math.isfinite(tr.restitution) else tr.ball.restitution[1]
    return np.array([tr.t_b, tr.x_b, tr.y_b, *tr.v_pre, tr.v_post[0], tr.v_post[1], e])


def _stump_plane_point(theta: np.ndarray, x_target: float, bounce_observed: bool, ball: Ball = LEATHER) -> np.ndarray:
    """(t, y, z, n_extra_bounces) where the post-contact path crosses x = x_target.
    A ball that would touch down again before the plane is bounced again with the same
    restitution."""
    tr = _unpack(theta, bounce_observed, ball)
    R, k = ball.radius, ball.drag_k
    tau = _tau_to(x_target - tr.x_b, tr.v_pre, k)
    if tau < 0:                         # the plane comes before the contact: read the incoming arc
        p = tr.position(tr.t_b + tau)[0]
        return np.array([tr.t_b + tau, p[1], p[2], 0])
    seg = Trajectory(tr.t_b, tr.x_b, tr.y_b, tr.v_pre, tr.v_post, bounce_observed, ball)
    extra = 0
    for _ in range(4):
        tau = _tau_to(x_target - seg.x_b, seg.v_post, k)
        if not math.isfinite(tau) or tau < 0:
            return np.array([np.nan, np.nan, np.nan, extra])
        p = seg.position(seg.t_b + tau)[0]
        if p[2] >= R - 1e-9:
            return np.array([seg.t_b + tau, p[1], p[2], extra])
        # second contact before the plane
        t_hit = 2 * seg.v_post[2] / GRAVITY if seg.v_post[2] > 0 else 1e-6
        q, v = seg.position(seg.t_b + t_hit)[0], seg.velocity(seg.t_b + t_hit)
        v_new = np.array([v[0], v[1], -tr.restitution * v[2]])
        seg = Trajectory(seg.t_b + t_hit, float(q[0]), float(q[1]), v, v_new, bounce_observed, ball)
        extra += 1
    return np.array([np.nan, np.nan, np.nan, extra])


def predict_stump_plane(rec: Reconstruction, x_target: float = 0.0) -> StumpPlanePrediction | None:
    """Where the ball crosses the stump plane, with 1-sigma bounds propagated from the fit."""
    tr = rec.trajectory
    theta = _theta_of(tr)
    p = _stump_plane_point(theta, x_target, tr.bounce_observed, tr.ball)
    if not np.all(np.isfinite(p[:3])):
        return None
    J = _numeric_jacobian(lambda th: _stump_plane_point(th, x_target, tr.bounce_observed, tr.ball)[1:3], theta)
    sy, sz = _spread(J, rec.covariance)
    return StumpPlanePrediction(float(p[0]), float(p[1]), float(p[2]), sy, sz, int(p[3]))


def _spread(J: np.ndarray, cov: np.ndarray) -> list[float]:
    """1-sigma of each row of J under cov; infinite when the fit left cov undetermined."""
    if not (np.all(np.isfinite(cov)) and np.all(np.isfinite(J))):     # a perturbed path lost the plane
        return [math.inf] * J.shape[0]
    return [float(math.sqrt(max(v, 0.0))) for v in np.einsum("ij,jk,ik->i", J, cov, J)]


def position_sigma(rec: Reconstruction, t: float) -> tuple[float, float, float]:
    """1-sigma of the modelled position at time ``t``, per axis."""
    tr = rec.trajectory
    J = _numeric_jacobian(lambda th: _unpack(th, tr.bounce_observed, tr.ball).position(t)[0], _theta_of(tr))
    return tuple(_spread(J, rec.covariance))


def bounce_sigma(rec: Reconstruction) -> tuple[float, float]:
    """1-sigma of the contact point along and across the pitch."""
    c = rec.covariance
    return float(math.sqrt(max(c[1, 1], 0.0))), float(math.sqrt(max(c[2, 2], 0.0)))


def speed_sigma(rec: Reconstruction) -> float:
    """1-sigma of the speed at the first detection, m/s."""
    tr = rec.trajectory
    J = _numeric_jacobian(lambda th: np.linalg.norm(_unpack(th, tr.bounce_observed, tr.ball).velocity(0.0)), _theta_of(tr))
    return _spread(J, rec.covariance)[0]


def sample_path(tr: Trajectory, t_from: float, t_to: float, n: int = 48) -> np.ndarray:
    """(n,4) rows of t, x, y, z along the modelled flight, clamped to the ground."""
    ts = np.linspace(t_from, t_to, max(2, n))
    p = tr.position(ts)
    p[:, 2] = np.maximum(p[:, 2], 0.0)
    return np.column_stack([ts, p])
