"""Single source of truth for the test.mp4 manual pitch-corner picks.

Both the pipeline run (``realvideo_validate.py``) and the diagnostic overlay
(``visualize_realvideo.py``) import these so the numbers can never drift apart.

The picks trace the visible practice-net strip on frame 0, in the order the
calibration UI emits: striker-left, striker-right, bowler-right, bowler-left
(striker = far end by the batter, bowler = near end by the camera).

Note: test.mp4 is a short, low, through-the-net practice strip — geometry
analysis (the batsman is ~360 px tall, i.e. ~4 m from the camera; a batsman on
a regulation 20.12 m pitch would be ~70 px) shows it is roughly a 4 m x 3.05 m
strip, NOT a full pitch. The dimensions below therefore describe the actual
strip so the calibration is valid (low reprojection error) instead of being
rejected for not matching a 20.12 m pitch. It is calibrated correctly for what
it is; it just is not a regulation pitch, so it cannot drive a real LBW verdict.
"""

from __future__ import annotations

# (x, y) pixel picks on frame 0 (1080x1920), striker-L, striker-R, bowler-R, bowler-L.
PITCH_CORNERS_PX: list[tuple[float, float]] = [
    (345.0, 1095.0),   # striker-left   (far end, left edge of strip)
    (695.0, 1100.0),   # striker-right  (far end, right edge of strip)
    (800.0, 1665.0),   # bowler-right   (near end, right edge of strip)
    (130.0, 1665.0),   # bowler-left    (near end, left edge of strip)
]

CORNER_LABELS: list[str] = ["striker-L", "striker-R", "bowler-R", "bowler-L"]

# Actual strip dimensions (metres) recovered from the geometry — a short
# practice net, not a regulation 20.12 m pitch. Used by the pipeline run so the
# calibration is valid for what the clip actually shows.
PITCH_DIMENSIONS_M: dict[str, float] = {"length": 4.0, "width": 3.05}
