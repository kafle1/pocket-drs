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


def test_homography_accepts_stump_bases_and_maps_them():
    # Same square -> pitch rectangle, plus two stump bases at mid-height.
    src = [(10.0, 10.0), (10.0, 90.0), (90.0, 90.0), (90.0, 10.0)]
    stump_bases = [(10.0, 50.0), (90.0, 50.0)]

    H = homography_from_pitch_taps(
        image_points_px=src,
        pitch_length_m=20.12,
        pitch_width_m=3.05,
        stump_bases_px=stump_bases,
    )

    X0, Y0 = H.apply(*stump_bases[0])
    X1, Y1 = H.apply(*stump_bases[1])
    assert math.isfinite(X0) and math.isfinite(Y0)
    assert math.isfinite(X1) and math.isfinite(Y1)

    # Stumps should map close to x=0 and x=L on centerline y=0.
    assert abs(X0 - 0.0) < 1e-6
    assert abs(Y0 - 0.0) < 1e-6
    assert abs(X1 - 20.12) < 1e-6
    assert abs(Y1 - 0.0) < 1e-6


def test_homography_stump_bases_swapped_order_is_handled():
    src = [(10.0, 10.0), (10.0, 90.0), (90.0, 90.0), (90.0, 10.0)]
    stump_bases_swapped = [(90.0, 50.0), (10.0, 50.0)]

    H = homography_from_pitch_taps(
        image_points_px=src,
        pitch_length_m=20.12,
        pitch_width_m=3.05,
        stump_bases_px=stump_bases_swapped,
    )

    # Even if caller sends them swapped, we should still map correctly.
    X_left, Y_left = H.apply(10.0, 50.0)
    X_right, Y_right = H.apply(90.0, 50.0)

    assert abs(X_left - 0.0) < 1e-6
    assert abs(Y_left - 0.0) < 1e-6
    assert abs(X_right - 20.12) < 1e-6
    assert abs(Y_right - 0.0) < 1e-6
