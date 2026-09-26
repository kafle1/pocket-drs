"""Pick the ball out of per-frame detections by fitting one calibrated 3-D delivery.

A flight is (p, v), the ball's position and velocity in pitch metres at an origin time, under
gravity alone. Three detections a few frames apart fix one by linear least squares on the pixel
position and the depth the apparent size implies. RANSAC over those triples keeps only flights a
bowler can produce: one crossing the bowling crease at hand height, or one rising off the pitch
after a bounce. The bounce's other half is then fitted from the bounce point, so the track runs
from the hand to wherever the ball leaves the model: bat, pad or the edge of the frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration import CameraPose
from .reconstruction import BALL_RADIUS_M, GRAVITY, Trajectory, flight_trajectory

TOP = 8                      # candidates per frame, strongest first
GAPS_S = (0.04, 0.07, 0.11)  # spacing of the three detections that seed a flight
SIG_PX, SIG_R = 2.0, 0.35    # centre noise in pixels; relative size noise, a weak depth cue
SIZE = (0.35, 2.8)           # a candidate's radius over the flight's predicted one
MAX_GAP_S = 0.15             # longest a track may go unseen, behind a player or against a wall the ball's colour
MIN_SWEEP = 0.035            # of fx: a blob sitting on one camera ray fits a flight but never moves
RELEASE_M = 1.6              # the hand lets go about this far in front of the bowler's stumps
MIN_POINTS = 6
BOUNCE_KEEP = np.linspace(0.65, 1.05, 9)  # share of the speed down the pitch a bounce can keep


@dataclass(frozen=True)
class BallTrack:
    points: list[dict]       # {t_ms, u, v, radius_px, confidence}, one per frame the ball was matched in
    score: float             # summed fit quality, at most 1 per point
    model: Trajectory        # the flight those points fit, t = 0 at the first point


@dataclass(frozen=True)
class _Arc:
    th: np.ndarray           # (p, v) at t0
    t0: float
    fit: np.ndarray          # per-frame fit quality, 0 where unmatched
    idx: np.ndarray          # per-frame candidate, -1 where unmatched
    post: bool               # the half after the bounce


def _flight(pose: CameraPose, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The camera-frame ball as A @ (p, v) + b, t seconds after the flight's origin."""
    A = np.concatenate([np.broadcast_to(pose.R, t.shape + (3, 3)), pose.R * t[..., None, None]], -1)
    return A, pose.t - 0.5 * GRAVITY * (t * t)[..., None] * pose.R[:, 2]


def _solve(pose: CameraPose, A, b, u, v, r) -> np.ndarray:
    """Least-squares x with the camera-frame ball at A @ x + b, batched over axis 0 of (H, n) inputs."""
    D = BALL_RADIUS_M * pose.fx / r
    du, dv = u - pose.cx, v - pose.cy
    rows = np.stack([du[..., None] * A[..., 2, :] - pose.fx * A[..., 0, :],
                     dv[..., None] * A[..., 2, :] - pose.fy * A[..., 1, :], A[..., 2, :]], -2)
    rhs = np.stack([pose.fx * b[..., 0] - du * b[..., 2], pose.fy * b[..., 1] - dv * b[..., 2], D - b[..., 2]], -1)
    w = 1.0 / (D[..., None] * np.array([SIG_PX, SIG_PX, SIG_R]))
    m = A.shape[-1]
    M = (rows * w[..., None]).reshape(len(u), -1, m)
    y = (rhs * w).reshape(len(u), -1)
    N = np.einsum("hki,hkj->hij", M, M) + 1e-9 * np.eye(m)
    return np.linalg.solve(N, np.einsum("hki,hk->hi", M, y)[..., None])[..., 0]


def _position(th: np.ndarray, t: np.ndarray) -> np.ndarray:
    p = th[:, None, :3] + th[:, None, 3:] * t[..., None]
    p[..., 2] -= 0.5 * GRAVITY * t * t
    return p


def _predict(pose: CameraPose, th: np.ndarray, t: np.ndarray):
    """Pixel centre, expected radius and an in-play mask for flights th (H, 6) at times t (H, F)."""
    p = _position(th, t)
    u, v, d = (a.reshape(t.shape) for a in pose.project(p.reshape(-1, 3)))
    live = ((d > 0.5) & (p[..., 0] > 0) & (p[..., 0] < pose.pitch_length_m + 4) & (p[..., 2] > -0.05)
            & (np.abs(p[..., 1]) < 3.5))
    return u, v, BALL_RADIUS_M * pose.fx / np.maximum(d, 0.5), live


def _plausible(th: np.ndarray) -> np.ndarray:
    """Down the pitch at 43 to 180 km/h with modest sideways and vertical speed."""
    vx, vy, vz = th[:, 3], th[:, 4], th[:, 5]
    return (vx > -50) & (vx < -12) & (np.abs(vy) < 8) & (vz > -25) & (vz < 12)


def _released(th: np.ndarray, pitch_length: float) -> np.ndarray:
    """Traced back, the flight crosses the bowling crease at hand height."""
    t = (pitch_length - RELEASE_M - th[:, 0]) / th[:, 3]
    z = th[:, 2] + th[:, 5] * t - 0.5 * GRAVITY * t * t
    return (z > 1.0) & (z < 3.2) & (np.abs(th[:, 1] + th[:, 4] * t) < 1.8)


def _bounced(th: np.ndarray, pitch_length: float) -> np.ndarray:
    """Traced back, the flight leaves the pitch rising: the half after a bounce."""
    up = np.sqrt(th[:, 5] ** 2 + 2 * GRAVITY * np.maximum(th[:, 2], 0))
    t = (th[:, 5] - up) / GRAVITY
    x = th[:, 0] + th[:, 3] * t
    return (th[:, 2] > 0) & (up < 8) & (x > 0.5) & (x < pitch_length - 3) & (np.abs(th[:, 1] + th[:, 4] * t) < 1.8)


def _bounce_ok(w: np.ndarray, vb: np.ndarray, after: bool) -> np.ndarray:
    """A real bounce keeps most of the speed down the pitch and sends the ball back up."""
    ratio = w[:, 0] / vb[0]
    ok = (w[:, 0] < -3) & (np.abs(w[:, 1] - vb[1]) < 4)
    if after:
        e = w[:, 2] / -vb[2]
        return ok & (ratio > 0.6) & (ratio < 1.1) & (e > 0.25) & (e < 0.9)
    e = vb[2] / -w[:, 2]
    return ok & (ratio > 1 / 1.1) & (ratio < 1 / 0.6) & (w[:, 2] < 0) & (e > 0.25) & (e < 0.9)


def _run(hit: np.ndarray, seed: np.ndarray, T: np.ndarray) -> np.ndarray:
    """Hits reachable from each row's seed frame across gaps of at most MAX_GAP_S."""
    H, F = hit.shape
    h = hit.copy()
    h[np.arange(H), seed] = True
    last = np.maximum.accumulate(np.where(h, np.arange(F), -1), 1)
    prev = np.concatenate([np.full((H, 1), -1), last[:, :-1]], 1)
    seg = np.cumsum(h & (T - np.append(T, -np.inf)[prev] > MAX_GAP_S), 1)
    return hit & (seg == seg[np.arange(H), seed][:, None])


def _score(pose: CameraPose, th, t0, T, U, V, R, seed, keep=True, spread=0.0):
    """Each flight's nearest fitting candidate per frame. Returns fit quality (H, F) and candidate (H, F)."""
    u, v, rhat, live = _predict(pose, th, T[None] - t0[:, None])
    tau = np.hypot(3.0 + 1.2 * rhat, 3.0 * spread)
    d = np.hypot(U[None] - u[..., None], V[None] - v[..., None])
    ratio = R[None] / rhat[..., None]
    d = np.where((live & keep)[..., None] & (d < tau[..., None]) & (ratio > SIZE[0]) & (ratio < SIZE[1]), d, np.inf)
    k = d.argmin(-1)
    dm = np.take_along_axis(d, k[..., None], -1)[..., 0]
    hit = _run(np.isfinite(dm), seed, T)
    return np.where(hit, 1.0 - (dm / tau) ** 2, 0.0), np.where(hit, k, -1)


def _spread(pose: CameraPose, th: np.ndarray, t0: float, T: np.ndarray, f: np.ndarray, u, v) -> np.ndarray:
    """Per-frame pixel spread of a flight fitted to detections u, v at frames f.

    Tight across the matches, it widens past them: a short arc barely fixes speed along the camera's line of sight."""
    d = 1e-3
    pu, pv, rh, _ = _predict(pose, th[None] + np.vstack([np.zeros(6), d * np.eye(6)]), np.broadcast_to(T - t0, (7, len(T))))
    J = np.stack([pu[1:] - pu[0], pv[1:] - pv[0]], -1) / d                     # (6, F, 2)
    res = np.r_[pu[0, f] - u, pv[0, f] - v]
    s2 = max(SIG_PX ** 2, res @ res / max(len(res) - 6, 1))
    Jm = J[:, f].reshape(6, -1)
    Jr = (rh[1:, f] - rh[0, f]) / (d * SIG_R * rh[0, f])                     # the size cue, in units of its noise
    C = np.linalg.inv(Jm @ Jm.T / s2 + Jr @ Jr.T + 1e-9 * np.eye(6))
    return np.sqrt(np.maximum(np.einsum("ifk,ij,jfk->f", J, C, J), 0.0))


def _sweep(U, V, idx) -> np.ndarray:
    """Image distance from each track's first match to its last."""
    hit = idx >= 0
    a = hit.argmax(1)
    z = hit.shape[1] - 1 - hit[:, ::-1].argmax(1)
    h = np.arange(len(idx))
    return np.hypot(U[a, idx[h, a]] - U[z, idx[h, z]], V[a, idx[h, a]] - V[z, idx[h, z]])


def _arcs(pose: CameraPose, T, U, V, R) -> list[_Arc]:
    """The best flight out of the hand and the best off the pitch, each refined on its matches."""
    L = pose.pitch_length_m
    dt = float(np.median(np.diff(T)))
    has = ~np.isnan(U)
    best = {}                                   # post-bounce? -> (score, th, t0, seed frame)
    for g in sorted({max(1, round(s / dt)) for s in GAPS_S}):
        for i in range(len(T) - 2 * g):
            fr = np.array([i, i + g, i + 2 * g])
            ks = [np.flatnonzero(has[f]) for f in fr]
            if not all(len(k) for k in ks):
                continue
            k = np.stack([m.ravel() for m in np.meshgrid(*ks, indexing="ij")], 1)
            t = np.broadcast_to(T[fr] - T[i], k.shape)
            u, v, r = U[fr, k], V[fr, k], R[fr, k]
            th = _solve(pose, *_flight(pose, t), u, v, r)
            m = _plausible(th)
            if not m.any():
                continue
            th, t, u, v = th[m], t[m], u[m], v[m]
            pu, pv, rhat, live = _predict(pose, th, t)
            m = (live & (np.hypot(pu - u, pv - v) < 3.0 + 1.2 * rhat)).all(1)
            post = _bounced(th, L)
            m &= post | _released(th, L)
            if not m.any():
                continue
            th, post = th[m], post[m]
            fit, idx = _score(pose, th, np.full(len(th), T[i]), T, U, V, R, seed=np.full(len(th), i))
            s = np.where(_sweep(U, V, idx) > MIN_SWEEP * pose.fx, fit.sum(1), 0.0)
            for side in (False, True):
                sc = np.where(post == side, s, 0.0)
                j = int(np.argmax(sc))
                if sc[j] > best.get(side, (0.0,))[0]:
                    best[side] = (sc[j], th[j], T[i], i)
    arcs = []
    for post, (_, th, t0, i) in best.items():
        ok = _bounced if post else _released
        th, t0v, seed = th[None], np.array([t0]), np.array([i])
        fit, idx = _score(pose, th, t0v, T, U, V, R, seed=seed)
        for _ in range(10):
            f = np.flatnonzero(idx[0] >= 0)
            if len(f) < 3:
                break
            k = idx[0, f]
            new = _solve(pose, *_flight(pose, (T[f] - t0)[None]), U[f, k][None], V[f, k][None], R[f, k][None])
            if not (_plausible(new) & ok(new, L))[0]:
                break
            th = new
            # grow the track into frames the refit can now reach, looking as wide as the fit is unsure
            fit, grown = _score(pose, th, t0v, T, U, V, R, seed=seed, spread=_spread(pose, th[0], t0, T, f, U[f, k], V[f, k]))
            if (grown == idx).all():
                break
            idx = grown
        arcs.append(_Arc(th[0], t0, fit[0], idx[0], post))
    return arcs


def _other_half(pose: CameraPose, arc: _Arc, T, U, V, R):
    """The bounce's other half, fitted from a bounce point on the arc's path.

    Returns (per-frame fit, candidates, other half's flight, bounce time, arc's velocity at the bounce), or None."""
    used = np.flatnonzero(arc.idx >= 0)
    ka = arc.idx[used]
    after = not arc.post
    sgn = 1 if after else -1
    edge = used[-1] if after else used[0]
    dt = float(np.median(np.diff(T)))
    ends = T[used[-3:] if after else used[:3]] - arc.t0
    # the bounce can hide in a run of missed frames, so step on through the gap to where this half meets the pitch
    z, vz = arc.th[2], arc.th[5]
    ground = (vz + (1 if after else -1) * np.sqrt(max(vz * vz + 2 * GRAVITY * (z - BALL_RADIUS_M), 0.0))) / GRAVITY
    reach = MAX_GAP_S
    lo, hi = (ends[0], max(ends[-1] + 0.5 * dt, min(ground, ends[-1] + reach))) if after else \
        (min(ends[0] - 0.5 * dt, max(ground, ends[0] - reach)), ends[-1])
    best = None
    for tb in np.arange(lo, hi + 0.25 * dt, 0.5 * dt):
        # refit the arc to land on the pitch at tb, so the bounce can't hang in the air
        A, b = _flight(pose, (T[used] - arc.t0 - tb)[None])
        g = _solve(pose, A[..., [0, 1, 3, 4, 5]], b + A[..., 2] * BALL_RADIUS_M, *(a[used, ka][None] for a in (U, V, R)))[0]
        g = np.r_[g[:2], BALL_RADIUS_M, g[2:]]
        P, vb = g[:3], g[3:]
        s = T - arc.t0 - tb
        side = ((s > 0) if after else (s < 0)) & (np.abs(s) < 0.6)

        def solve(f, k, wx=None):
            A, b = _flight(pose, s[f])
            if wx is None:
                return _solve(pose, A[..., 3:], b + pose.R @ P, U[f, k], V[f, k], R[f, k])
            w = _solve(pose, A[..., 4:], b + pose.R @ P + A[..., 3] * wx[:, None, None], U[f, k], V[f, k], R[f, k])
            return np.concatenate([wx[:, None], w], 1)

        # grow out from the bounce a gap at a time, so the half can't leap ahead to the batter's gloves
        keep = side & (sgn * (T - T[edge]) <= MAX_GAP_S)
        f, k = np.nonzero(keep[:, None] & ~np.isnan(U))
        if not len(f):
            continue
        if after:
            # a few frames after the bounce can't split speed from rise; the pre half skips this so clutter can't pose as a release
            wx = vb[0] * BOUNCE_KEEP
            f, k, x = np.repeat(f, len(wx)), np.repeat(k, len(wx)), np.tile(wx, len(f))
            w = solve(f[:, None], k[:, None], x)
        else:
            w = solve(f[:, None], k[:, None])
        w = w[_bounce_ok(w, vb, after)]
        if not len(w):
            continue
        th = np.concatenate([np.broadcast_to(P, w.shape), w], 1)
        t0v = np.array([arc.t0 + tb])
        fit, idx = _score(pose, th, np.repeat(t0v, len(th)), T, U, V, R, seed=np.full(len(th), edge), keep=keep)
        j = int(np.argmax(fit.sum(1)))
        th, fit, idx = th[j:j + 1], fit[j:j + 1], idx[j:j + 1]
        for _ in range(10):
            fi = np.flatnonzero(idx[0] >= 0)
            if not len(fi):
                break
            wj = solve(fi[None], idx[0, fi][None], th[:, 3] if after else None)
            if not _bounce_ok(wj, vb, after)[0]:
                break
            th = np.concatenate([P[None], wj], 1)
            keep = side & (sgn * (T - T[fi[-1] if after else fi[0]]) <= MAX_GAP_S)
            fit, grown = _score(pose, th, t0v, T, U, V, R, seed=np.array([edge]), keep=keep)
            if (grown == idx).all():
                break
            idx = grown
        if not ((idx[0] >= 0) & (arc.idx < 0)).any():
            continue                             # it only re-labels the arc's own frames
        afit, aidx = _score(pose, g[None], t0v, T, U, V, R, seed=np.array([edge]), keep=~side,
                            spread=_spread(pose, g, t0v[0], T, used, U[used, ka], V[used, ka]))
        merged = np.where(side, fit[0], afit[0])
        if best is None or merged.sum() > best[0].sum():
            best = (merged, np.where(side, idx[0], aidx[0]), th[0], arc.t0 + tb, vb)
    return best


def find_ball(pose: CameraPose, dets_per_frame: list[tuple[int, list[dict]]]) -> BallTrack | None:
    """The delivery the detections best support, or None when nothing moves like a bowled ball.

    dets_per_frame is [(t_ms, candidates strongest first)] in time order."""
    F = len(dets_per_frame)
    if F < 3:
        return None
    T = np.array([t for t, _ in dets_per_frame], float) / 1000.0
    L = pose.pitch_length_m
    far = max(np.linalg.norm(np.array([x, y, 0.0]) - pose.centre_world) for x in (0.0, L + 4) for y in (-3.5, 3.5))
    # a speck smaller than the ball at the far end of play never fits a flight, so it can't take a slot
    rmin = SIZE[0] * BALL_RADIUS_M * pose.fx / far
    U, V, R, C = (np.full((F, TOP), np.nan) for _ in range(4))
    for f, (_, ds) in enumerate(dets_per_frame):
        for k, d in enumerate([c for c in ds if c["radius_px"] >= rmin][:TOP]):
            U[f, k], V[f, k], R[f, k], C[f, k] = d["x"], d["y"], max(d["radius_px"], 1.0), d["confidence"]
    best = None
    for arc in _arcs(pose, T, U, V, R):
        other = _other_half(pose, arc, T, U, V, R)
        # only a whole delivery counts: the half before the bounce must leave the hand
        if arc.post and (other is None or not _released(other[2][None], pose.pitch_length_m)[0]):
            continue
        if other is not None and not arc.post and other[0].sum() <= arc.fit.sum():
            other = None
        fit = arc.fit if other is None else other[0]
        if best is None or fit.sum() > best[1].sum():
            best = (arc, fit, arc.idx if other is None else other[1], other)
    if best is None or (best[2] >= 0).sum() < MIN_POINTS:
        return None
    arc, fit, idx, other = best
    f = np.flatnonzero(idx >= 0)
    points = [{"t_ms": int(dets_per_frame[i][0]), "u": float(U[i, j]), "v": float(V[i, j]),
               "radius_px": float(R[i, j]), "confidence": float(C[i, j])} for i, j in zip(f, idx[f])]
    return BallTrack(points, float(fit.sum()), _model(arc, other, T[f[0]]))


def _model(arc: _Arc, other, t_first: float) -> Trajectory:
    """The matched flight, or both halves of the bounce, as a Trajectory from t_first."""
    if other is None:
        s = t_first - arc.t0
        p = _position(arc.th[None], np.array([[s]]))[0, 0]
        return flight_trajectory(np.concatenate([p, arc.th[3:] - np.array([0.0, 0.0, GRAVITY * s])]))
    th, tb, vb = other[2], other[3], other[4]
    v_pre, v_post = (th[3:], vb) if arc.post else (vb, th[3:])
    return Trajectory(tb - t_first, float(th[0]), float(th[1]), v_pre, v_post, 0.0, True)
