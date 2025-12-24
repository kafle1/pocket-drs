from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TrackPoint:
    t_ms: int
    x_px: float
    y_px: float
    confidence: float


class TrackingError(RuntimeError):
    pass


class Kalman2D:
    """Tiny constant-velocity Kalman filter for (x, y).

    State: [x, y, vx, vy]
    """

    def __init__(self, initial_x: float, initial_y: float):
        self._x = np.array([[initial_x], [initial_y], [0.0], [0.0]], dtype=np.float64)
        self._p = np.array(
            [
                [25.0, 0.0, 0.0, 0.0],
                [0.0, 25.0, 0.0, 0.0],
                [0.0, 0.0, 1000.0, 0.0],
                [0.0, 0.0, 0.0, 1000.0],
            ],
            dtype=np.float64,
        )

        self.process_noise_pos = 25.0
        self.process_noise_vel = 250.0
        self.measurement_noise = 64.0

    @property
    def pos(self) -> tuple[float, float]:
        return float(self._x[0, 0]), float(self._x[1, 0])

    def predict(self, dt: float) -> None:
        f = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self._x = f @ self._x
        q = np.diag(
            [
                self.process_noise_pos,
                self.process_noise_pos,
                self.process_noise_vel,
                self.process_noise_vel,
            ]
        ).astype(np.float64)
        self._p = f @ self._p @ f.T + q

    def update(self, meas_x: float, meas_y: float) -> None:
        h = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
        r = np.array(
            [[self.measurement_noise, 0.0], [0.0, self.measurement_noise]], dtype=np.float64
        )
        z = np.array([[meas_x], [meas_y]], dtype=np.float64)
        y = z - (h @ self._x)
        s = h @ self._p @ h.T + r
        try:
            k = self._p @ h.T @ np.linalg.inv(s)
        except np.linalg.LinAlgError:
            return
        self._x = self._x + (k @ y)
        i = np.eye(4, dtype=np.float64)
        self._p = (i - k @ h) @ self._p


@dataclass(frozen=True)
class ColorSignature:
    b: float
    g: float
    r: float

    @staticmethod
    def from_bgr_frame(frame_bgr: np.ndarray, x: int, y: int, radius_px: int = 3) -> "ColorSignature":
        h, w = frame_bgr.shape[:2]
        x0 = max(0, x - radius_px)
        x1 = min(w, x + radius_px + 1)
        y0 = max(0, y - radius_px)
        y1 = min(h, y + radius_px + 1)
        patch = frame_bgr[y0:y1, x0:x1]
        if patch.size == 0:
            b, g, r = frame_bgr[y, x].astype(np.float64)
            return ColorSignature(b=float(b), g=float(g), r=float(r))

        mean = patch.reshape(-1, 3).mean(axis=0)
        b, g, r = mean.tolist()
        return ColorSignature(b=float(b), g=float(g), r=float(r))

    def mask_close(self, patch_bgr: np.ndarray, tol: float = 55.0) -> np.ndarray:
        # L1 distance in BGR space.
        b = patch_bgr[:, :, 0].astype(np.float64)
        g = patch_bgr[:, :, 1].astype(np.float64)
        r = patch_bgr[:, :, 2].astype(np.float64)
        dist = np.abs(b - self.b) + np.abs(g - self.g) + np.abs(r - self.r)
        return dist < (tol * 3.0)


def _centroid_from_mask(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def track_seeded(
    *,
    frames_bgr: list[np.ndarray],
    times_ms: list[int],
    seed_x: float,
    seed_y: float,
    search_radius_px: int,
) -> list[TrackPoint]:
    if len(frames_bgr) != len(times_ms):
        raise ValueError("frames_bgr and times_ms must have same length")
    if not frames_bgr:
        return []

    h0, w0 = frames_bgr[0].shape[:2]
    sx = int(round(np.clip(seed_x, 0, w0 - 1)))
    sy = int(round(np.clip(seed_y, 0, h0 - 1)))

    sig = ColorSignature.from_bgr_frame(frames_bgr[0], sx, sy)

    kf: Kalman2D | None = None
    last_meas: tuple[float, float] | None = None
    out: list[TrackPoint] = []

    for i, (frame, t_ms) in enumerate(zip(frames_bgr, times_ms)):
        h, w = frame.shape[:2]

        if kf is None:
            pred_x, pred_y = float(sx), float(sy)
        else:
            pred_x, pred_y = kf.pos

        cx = int(round(np.clip(pred_x, 0, w - 1)))
        cy = int(round(np.clip(pred_y, 0, h - 1)))

        r = int(max(12, search_radius_px))
        x0 = max(0, cx - r)
        x1 = min(w, cx + r + 1)
        y0 = max(0, cy - r)
        y1 = min(h, cy + r + 1)

        patch = frame[y0:y1, x0:x1]
        meas: tuple[float, float] | None = None
        confidence = 0.35

        if patch.size:
            mask = sig.mask_close(patch, tol=55.0)
            centroid = _centroid_from_mask(mask)
            if centroid is not None:
                mx, my = centroid
                meas = (x0 + mx, y0 + my)
                confidence = 0.9

        if meas is None and last_meas is not None:
            # Fallback: keep the last measurement if detection drops.
            meas = None

        if kf is None and meas is not None:
            kf = Kalman2D(initial_x=meas[0], initial_y=meas[1])

        dt = 1.0 / 30.0
        if i > 0:
            dt = max(0.001, (times_ms[i] - times_ms[i - 1]) / 1000.0)
        kf.predict(dt) if kf else None

        if meas is not None and kf is not None:
            kf.update(meas[0], meas[1])
            last_meas = meas

        if kf is not None:
            px, py = kf.pos
        elif last_meas is not None:
            px, py = last_meas
        else:
            px, py = float(sx), float(sy)

        out.append(TrackPoint(t_ms=t_ms, x_px=float(px), y_px=float(py), confidence=float(confidence)))

    return out
