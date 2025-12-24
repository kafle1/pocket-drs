from __future__ import annotations

import math

from app.pipeline.calibration import homography_from_pitch_taps


def test_homography_maps_pitch_corners():
    # Simple square in pixels to rectangle in meters.
    src = [(10.0, 10.0), (10.0, 90.0), (90.0, 90.0), (90.0, 10.0)]
    H = homography_from_pitch_taps(image_points_px=src, pitch_length_m=20.12, pitch_width_m=3.05)

    half_w = 3.05 / 2.0
    dst = [(0.0, -half_w), (0.0, half_w), (20.12, half_w), (20.12, -half_w)]

    for (x, y), (X, Y) in zip(src, dst):
        X2, Y2 = H.apply(x, y)
        assert math.isfinite(X2) and math.isfinite(Y2)
        assert abs(X2 - X) < 1e-6
        assert abs(Y2 - Y) < 1e-6
