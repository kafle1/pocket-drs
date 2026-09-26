"""Synthetic deliveries with exact ground truth.

Everything the estimator is later asked to recover is generated here from a known physical
model, so every error reported in the paper is measured against a value that is known
without approximation. The flight model is richer than the estimator's: it can carry
aerodynamic drag, lateral swing before the pitch, a friction loss and a spin deviation at
contact, and a restitution coefficient chosen per delivery. The estimator assumes none of
those, which is the point: model mismatch is part of what is being measured.

World frame: x down the pitch (0 at the striker's stumps), y across it (+y = the
right-hander's leg side as seen from the striker's end), z up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server"))
from app.pipeline.calibration import (CameraPose, intrinsics, solve_camera_pose,       # noqa: E402
                                      STUMP_HEIGHT_M, STUMP_OUTER_HALF_M, PITCH_LENGTH_M,
                                      PITCH_WIDTH_M)
from app.pipeline.reconstruction import GRAVITY, BALL_RADIUS_M                          # noqa: E402

CREASE_X = 1.22          # popping crease: where the batter's pad intercepts the ball
BALL_MASS = 0.16
AIR_DENSITY = 1.2
DRAG_CD = 0.5
DRAG_K = 0.5 * AIR_DENSITY * DRAG_CD * math.pi * BALL_RADIUS_M ** 2 / BALL_MASS   # 1/m


@dataclass(frozen=True)
class Delivery:
    speed_kmh: float
    length_m: float            # intended pitching distance from the striker's stumps
    line_m: float              # intended pitching line, +leg
    release_z: float = 2.05
    release_y: float = 0.0
    restitution: float = 0.55
    friction: float = 0.10     # fraction of horizontal speed lost at contact
    turn_ms: float = 0.0       # lateral velocity added at contact (spin), m/s, +leg
    swing_ms2: float = 0.0     # lateral acceleration in the air before contact, +leg
    drag: bool = False


@dataclass(frozen=True)
class Camera:
    end: str = "striker"       # "striker" or "bowler"
    back_m: float = 2.8        # distance behind the near stumps
    height_m: float = 1.7
    offset_m: float = 0.0      # lateral offset from the pitch centre line
    width: int = 1080
    height: int = 1920
    fov_deg: float = 90.5      # along the long axis; 950 px focal at 1920

    def pose(self) -> CameraPose:
        K = intrinsics(self.width, self.height, self.fov_deg)
        if self.end == "striker":
            eye = np.array([-self.back_m, self.offset_m, self.height_m])
            look = np.array([10.0, 0.0, 0.3])
        else:
            eye = np.array([PITCH_LENGTH_M + self.back_m, self.offset_m, self.height_m])
            look = np.array([PITCH_LENGTH_M - 10.0, 0.0, 0.3])
        f = look - eye; f /= np.linalg.norm(f)
        r = np.cross(f, [0.0, 0.0, 1.0]); r /= np.linalg.norm(r)      # image right, so image down is world down
        d = np.cross(f, r)
        R = np.stack([r, d, f])
        return CameraPose(K=K, R=R, t=-R @ eye, reproj_error_px=0.0, fov_deg=self.fov_deg,
                          pitch_length_m=PITCH_LENGTH_M, pitch_width_m=PITCH_WIDTH_M)


@dataclass(frozen=True)
class Truth:
    contact_t: float
    contact: np.ndarray          # x, y at the pitch
    crease: np.ndarray           # x, y, z where the ball crosses the popping crease
    stumps: np.ndarray           # x, y, z where the ball crosses the stump plane
    release_speed_kmh: float
    states: np.ndarray           # (N,4) t, x, y, z at 1 kHz


def _launch(d: Delivery) -> tuple[np.ndarray, np.ndarray]:
    """Release point and velocity so the drag-free flight pitches at (length, line)."""
    s = d.speed_kmh / 3.6
    p0 = np.array([PITCH_LENGTH_M - 1.2, d.release_y, d.release_z])
    dx = d.length_m - p0[0]
    dy = d.line_m - p0[1]

    def miss(alpha):
        vx = -s * math.cos(alpha); vz = s * math.sin(alpha)
        t = dx / vx
        return p0[2] + vz * t - 0.5 * GRAVITY * t * t - BALL_RADIUS_M

    lo, hi = math.radians(-45.0), math.radians(20.0)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if miss(mid) > 0: hi = mid
        else: lo = mid
    alpha = 0.5 * (lo + hi)
    vx = -s * math.cos(alpha); vz = s * math.sin(alpha)
    t = dx / vx
    vy = (dy - 0.5 * d.swing_ms2 * t * t) / t
    return p0, np.array([vx, vy, vz])


def fly(d: Delivery, dt: float = 1e-3) -> Truth:
    """Integrate the delivery from release until it passes the stump plane."""
    p, v = _launch(d)
    release_speed = float(np.linalg.norm(v)) * 3.6
    rows, t = [], 0.0
    bounced = False
    contact_t, contact = None, None
    crease, stumps = None, None
    while p[0] > -0.5 and t < 3.0:
        rows.append((t, *p))
        a = np.array([0.0, 0.0, -GRAVITY])
        if not bounced:
            a[1] += d.swing_ms2
        if d.drag:
            a -= DRAG_K * np.linalg.norm(v) * v
        v_new = v + a * dt
        p_new = p + v * dt + 0.5 * a * dt * dt
        if not bounced and p_new[2] <= BALL_RADIUS_M and v_new[2] < 0:
            frac = (p[2] - BALL_RADIUS_M) / max(p[2] - p_new[2], 1e-12)
            contact_t = t + frac * dt
            contact = (p + frac * (p_new - p)).copy()
            v_c = v + a * frac * dt
            v_c[0] *= (1.0 - d.friction); v_c[1] = v_c[1] * (1.0 - d.friction) + d.turn_ms
            v_c[2] = -d.restitution * v_c[2]
            rest = (1.0 - frac) * dt
            p_new = contact + v_c * rest; p_new[2] = max(p_new[2], BALL_RADIUS_M)
            v_new = v_c + np.array([0.0, 0.0, -GRAVITY]) * rest
            bounced = True
        for target, name in ((CREASE_X, "crease"), (0.0, "stumps")):
            if p[0] > target >= p_new[0]:
                frac = (p[0] - target) / (p[0] - p_new[0])
                q = p + frac * (p_new - p)
                if name == "crease": crease = q
                else: stumps = q
        p, v, t = p_new, v_new, t + dt
    if contact is None:            # full toss: no contact before the stumps
        contact_t, contact = math.nan, np.array([math.nan, math.nan, math.nan])
    if crease is None or stumps is None:
        raise ValueError("delivery never reached the stump plane")
    return Truth(contact_t, contact[:2], crease, stumps, release_speed, np.asarray(rows))


def observe(truth: Truth, pose: CameraPose, *, fps: float, noise_px: float, radius_noise: float,
            dropout: float, rng: np.random.Generator) -> list[tuple[float, float, float, float, float]]:
    """Per-frame detections (t, u, v, radius_px, weight) the tracker would hand on."""
    st = truth.states
    t_end = float(st[np.argmax(st[:, 1] <= CREASE_X), 0])      # the pad intercepts the ball at the crease
    times = np.arange(0.0, t_end, 1.0 / fps)
    out = []
    for tt in times:
        i = int(round(tt / (st[1, 0] - st[0, 0])))
        if i >= len(st):
            break
        p = st[i, 1:4]
        u, v, depth = pose.project(p[None, :])
        if depth[0] <= 0.5:
            continue
        if not (0 <= u[0] < pose.cx * 2 and 0 <= v[0] < pose.cy * 2):
            continue
        if rng.random() < dropout:
            continue
        r = pose.fx * BALL_RADIUS_M / depth[0]
        out.append((float(tt), float(u[0] + rng.normal(0, noise_px)), float(v[0] + rng.normal(0, noise_px)),
                    float(max(0.5, r * (1.0 + rng.normal(0, radius_noise)))), 1.0))
    return out


def calibration_taps(pose: CameraPose, *, noise_px: float, rng: np.random.Generator):
    """The eight stump corners the user taps, perturbed, and the pose the server solves from them."""
    w, h = STUMP_OUTER_HALF_M, STUMP_HEIGHT_M
    side = [(-w, h), (w, h), (w, 0.0), (-w, 0.0)]
    su, sv, _ = pose.project(np.array([(0.0, dy, dz) for dy, dz in side] + [(PITCH_LENGTH_M, dy, dz) for dy, dz in side]))
    stumps = [(float(a + rng.normal(0, noise_px)), float(b + rng.normal(0, noise_px))) for a, b in zip(su, sv)]
    return solve_camera_pose(image_size=(int(pose.cx * 2), int(pose.cy * 2)), stump_quads_px=stumps,
                             pitch_length_m=PITCH_LENGTH_M)


# --------------------------------------------------------------------------- #
# Ground-truth verdict, same geometry the decision layer uses
# --------------------------------------------------------------------------- #

def truth_verdict(truth: Truth, leg_sign: float = 1.0) -> str:
    from app.pipeline.decision import decide
    py = None if not np.isfinite(truth.contact[0]) else float(truth.contact[1])
    v = decide(leg_sign=leg_sign, pitch_y=py, pitch_sigma=0.0,
               impact_y=float(truth.crease[1]), impact_sigma=0.0,
               stump_y=float(truth.stumps[1]), stump_z=float(truth.stumps[2]),
               sigma_y=0.0, sigma_z=0.0, k=0.0)
    return v.decision


def grid() -> list[Delivery]:
    """The fixed evaluation grid: 5 speeds x 5 lines x 4 lengths = 100 deliveries."""
    out = []
    for s in (90, 105, 120, 135, 145):
        for line in (-0.40, -0.20, 0.0, 0.20, 0.40):
            for length in (2.0, 4.0, 6.0, 8.0):
                out.append(Delivery(speed_kmh=s, length_m=length, line_m=line))
    return out


def random_delivery(rng: np.random.Generator, *, physics: bool) -> Delivery:
    """A delivery drawn from realistic ranges; ``physics`` switches on the effects the
    estimator does not model."""
    d = Delivery(
        speed_kmh=float(rng.uniform(60, 150)),
        length_m=float(rng.uniform(1.0, 10.0)),
        line_m=float(rng.uniform(-0.6, 0.6)),
        release_z=float(rng.uniform(1.8, 2.3)),
        release_y=float(rng.uniform(-0.4, 0.4)),
        restitution=float(rng.uniform(0.40, 0.70)),
    )
    if physics:
        d = replace(d, friction=float(rng.uniform(0.05, 0.20)), turn_ms=float(rng.uniform(-2.0, 2.0)),
                    swing_ms2=float(rng.uniform(-2.0, 2.0)), drag=True)
    return d
