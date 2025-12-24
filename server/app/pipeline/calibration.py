from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class CalibrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Homography:
    matrix: np.ndarray  # 3x3

    def to_list(self) -> list[list[float]]:
        return [[float(v) for v in row] for row in self.matrix.tolist()]

    def apply(self, x: float, y: float) -> tuple[float, float]:
        p = np.array([[x], [y], [1.0]], dtype=np.float64)
        q = self.matrix @ p
        w = float(q[2, 0])
        if abs(w) < 1e-12:
            return float("nan"), float("nan")
        return float(q[0, 0] / w), float(q[1, 0] / w)


def homography_from_pitch_taps(
    *,
    image_points_px: list[tuple[float, float]],
    pitch_length_m: float,
    pitch_width_m: float,
) -> Homography:
    if len(image_points_px) != 4:
        raise CalibrationError("Expected 4 pitch corner points")

    half_w = pitch_width_m / 2.0
    dst = [
        (0.0, -half_w),
        (0.0, half_w),
        (pitch_length_m, half_w),
        (pitch_length_m, -half_w),
    ]

    src_np = np.array(image_points_px, dtype=np.float64)
    dst_np = np.array(dst, dtype=np.float64)

    # Solve for H using DLT least-squares.
    a_rows: list[list[float]] = []
    for (x, y), (X, Y) in zip(src_np.tolist(), dst_np.tolist()):
        a_rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, x * X, y * X, X])
        a_rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, x * Y, y * Y, Y])

    a = np.array(a_rows, dtype=np.float64)
    try:
        _, _, vt = np.linalg.svd(a)
    except np.linalg.LinAlgError as e:
        raise CalibrationError(f"SVD failed while computing homography: {e}")

    h = vt[-1, :].reshape(3, 3)
    if abs(h[2, 2]) > 1e-12:
        h = h / h[2, 2]

    if not np.isfinite(h).all():
        raise CalibrationError("Homography contains non-finite values")

    det = float(np.linalg.det(h))
    if abs(det) < 1e-12:
        raise CalibrationError("Homography is degenerate (determinant near 0)")

    return Homography(matrix=h)


def map_track_to_pitch_plane(
    *,
    H: Homography,
    track_points_px: list[tuple[int, float, float, float]],
) -> list[tuple[int, float, float, float]]:
    out: list[tuple[int, float, float, float]] = []
    for t_ms, x_px, y_px, conf in track_points_px:
        x_m, y_m = H.apply(x_px, y_px)
        out.append((t_ms, x_m, y_m, conf))
    return out
