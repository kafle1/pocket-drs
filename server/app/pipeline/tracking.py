from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True)
class TrackPoint:
    t_ms: int
    x_px: float
    y_px: float
    confidence: float


class TrackingError(RuntimeError):
    pass


def _require_cv2() -> None:
    if cv2 is None:
        raise TrackingError("OpenCV (cv2) is required for auto tracking")


class Kalman2D:
    """Tiny constant-velocity Kalman filter for (x, y).

    State: [x, y, vx, vy]
    """

    def __init__(self, initial_x: float, initial_y: float):
        self._x = np.array([[initial_x], [initial_y], [0.0], [0.0]], dtype=np.float64)
        self._p = np.array(
            [
                [16.0, 0.0, 0.0, 0.0],
                [0.0, 16.0, 0.0, 0.0],
                [0.0, 0.0, 800.0, 0.0],
                [0.0, 0.0, 0.0, 800.0],
            ],
            dtype=np.float64,
        )

        # Tuned parameters for better cricket ball tracking
        self.process_noise_pos = 16.0  # Reduced for smoother tracking
        self.process_noise_vel = 200.0  # Adjusted for cricket ball velocity
        self.measurement_noise = 36.0  # Lower noise for better accuracy

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

    def mask_close(self, patch_bgr: np.ndarray, tol: float = 45.0) -> np.ndarray:
        # L1 distance in BGR space with improved tolerance for cricket ball.
        b = patch_bgr[:, :, 0].astype(np.float64)
        g = patch_bgr[:, :, 1].astype(np.float64)
        r = patch_bgr[:, :, 2].astype(np.float64)
        dist = np.abs(b - self.b) + np.abs(g - self.g) + np.abs(r - self.r)
        # Tighter tolerance for better precision
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
            mask = sig.mask_close(patch, tol=45.0)
            centroid = _centroid_from_mask(mask)
            if centroid is not None:
                mx, my = centroid
                meas = (x0 + mx, y0 + my)
                # Higher confidence for successful detections
                confidence = 0.95

        if meas is None and last_meas is not None:
            # Fallback: keep the last measurement if detection drops.
            meas = last_meas

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


def _find_motion_centroids(prev_bgr: np.ndarray, curr_bgr: np.ndarray) -> list[tuple[float, float, float]]:
    """Return candidate moving object centroids as (x, y, score).

    This is intentionally simple and offline-friendly:
    - frame differencing
    - threshold
    - connected components

    score is proportional to component area.
    """
    _require_cv2()

    prev = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
    curr = cv2.cvtColor(curr_bgr, cv2.COLOR_BGR2GRAY)

    prev = cv2.GaussianBlur(prev, (5, 5), 0)
    curr = cv2.GaussianBlur(curr, (5, 5), 0)

    diff = cv2.absdiff(prev, curr)

    # Enhanced adaptive threshold for better ball detection in varying lighting.
    thr = max(15.0, float(np.percentile(diff, 94)))
    _, mask = cv2.threshold(diff, thr, 255, cv2.THRESH_BINARY)

    # Improved morphological operations for cleaner ball detection.
    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.dilate(mask, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out: list[tuple[float, float, float]] = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < 6.0 or area > 2500.0:
            continue
        m = cv2.moments(c)
        if m.get("m00", 0.0) == 0.0:
            continue
        cx = float(m["m10"] / m["m00"])
        cy = float(m["m01"] / m["m00"])
        out.append((cx, cy, area))

    out.sort(key=lambda t: t[2], reverse=True)
    return out


def track_auto(
    *,
    frames_bgr: list[np.ndarray],
    times_ms: list[int],
    search_radius_px: int = 36,
) -> list[TrackPoint]:
    """Track a likely ball without a user-provided seed.

    Strategy:
    - use frame differencing to find moving blobs
    - pick an initial centroid from the strongest early motion
    - then follow using a small constant-velocity Kalman filter and nearest-candidate gating
    """
    _require_cv2()
    if len(frames_bgr) != len(times_ms):
        raise ValueError("frames_bgr and times_ms must have same length")
    if not frames_bgr:
        return []

    if len(frames_bgr) < 2:
        raise TrackingError("auto tracking requires at least 2 frames")

    # Find initial candidate from the first few diffs.
    init: tuple[float, float] | None = None
    for i in range(1, min(6, len(frames_bgr))):
        cands = _find_motion_centroids(frames_bgr[i - 1], frames_bgr[i])
        if cands:
            init = (cands[0][0], cands[0][1])
            break
    if init is None:
        raise TrackingError("auto tracking failed: no moving object detected")

    kf = Kalman2D(initial_x=init[0], initial_y=init[1])
    last_meas: tuple[float, float] | None = init

    out: list[TrackPoint] = []
    for i in range(len(frames_bgr)):
        frame = frames_bgr[i]
        t_ms = int(times_ms[i])

        dt = 1.0 / 30.0
        if i > 0:
            dt = max(0.001, (times_ms[i] - times_ms[i - 1]) / 1000.0)
        kf.predict(dt)

        meas: tuple[float, float] | None = None
        confidence = 0.25

        if i > 0:
            cands = _find_motion_centroids(frames_bgr[i - 1], frame)
            if cands:
                px, py = kf.pos
                best: tuple[float, float, float] | None = None
                best_cost = float("inf")
                for (cx, cy, area) in cands[:8]:
                    dx = cx - px
                    dy = cy - py
                    dist2 = dx * dx + dy * dy
                    if dist2 > float(max(12, search_radius_px)) ** 2:
                        continue
                    # Prefer nearer candidates; area breaks ties.
                    cost = dist2 - 0.15 * area
                    if cost < best_cost:
                        best_cost = cost
                        best = (cx, cy, area)
                if best is not None:
                    meas = (best[0], best[1])
                    confidence = 0.75

        if meas is not None:
            kf.update(meas[0], meas[1])
            last_meas = meas
        else:
            # Keep prediction; confidence drops.
            confidence = 0.2 if last_meas is not None else 0.1

        x, y = kf.pos
        out.append(TrackPoint(t_ms=t_ms, x_px=float(x), y_px=float(y), confidence=float(confidence)))

    return out
