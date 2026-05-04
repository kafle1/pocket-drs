"""Ball detection for cricket tracking (umpire-POV monocular).

Detector returns per-frame candidate balls with pixel position, pixel radius
(needed for monocular depth-from-size), and confidence.  Two strategies are
fused:

- Motion (MOG2 background subtraction) — finds anything that moves.
- Color (HSV thresholding) — finds the ball by hue.

The ROI mask is shaped for an umpire-POV camera: it covers the pitch quad
plus a generous *upward* envelope (in image space) to capture the airborne
arc above the pitch, but does **not** extend sideways into adjacent nets or
fielding positions where false motion is common.
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

# Cricket ball area bounds in pixels.  These are deliberately wide because the
# apparent size shrinks ~5x from near to far end at typical phone framings.
_MIN_AREA_PX = 8.0
_MAX_AREA_PX = 2500.0
_MIN_CIRCULARITY = 0.45
_MIN_ASPECT = 0.55
_MAX_ASPECT = 1.80


def _contour_metrics(contour: np.ndarray) -> dict[str, float] | None:
    """Compute area, perimeter, circularity, aspect, and centroid+radius.

    Returns None when the contour fails basic shape gates so the caller can
    skip it cheaply.
    """
    area = float(cv2.contourArea(contour))
    if not (_MIN_AREA_PX <= area <= _MAX_AREA_PX):
        return None
    perimeter = float(cv2.arcLength(contour, True))
    if perimeter <= 0:
        return None
    circularity = 4.0 * math.pi * area / (perimeter * perimeter)
    if circularity < _MIN_CIRCULARITY:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    if h == 0:
        return None
    aspect = w / h
    if not (_MIN_ASPECT <= aspect <= _MAX_ASPECT):
        return None
    (cx, cy), radius = cv2.minEnclosingCircle(contour)
    return {
        "x": float(cx),
        "y": float(cy),
        "radius": float(radius),
        "area": area,
        "circularity": float(circularity),
    }


def build_pitch_roi_mask(
    frame_shape: tuple[int, ...],
    corners_px: list[tuple[float, float]],
    *,
    lateral_margin_frac: float = 0.05,
    vertical_envelope_px: float = 350.0,
    margin_factor: float | None = None,  # legacy; retained for back-compat
) -> np.ndarray:
    """Pitch quad + airborne envelope above it.

    Parameters
    ----------
    corners_px:
        Four pitch corners in image pixels, ordered as the calibration step
        emits them: striker-left, striker-right, bowler-right, bowler-left
        (clockwise starting at striker-end).  Order is not strictly required
        — we re-derive top/bottom from image-y.
    lateral_margin_frac:
        Fractional outward margin on each side, expressed as a fraction of
        the pitch's image-width at the bottom edge.  Tight on purpose.
    vertical_envelope_px:
        How far above the pitch quad (toward image top) to extend the mask
        in order to cover the airborne ball.  Scaled per-corner by image-y
        so that the near-camera (bottom) end gets the most height.
    margin_factor:
        Legacy parameter kept so existing callers don't crash.  When set,
        we approximate the old behaviour by deriving sensible new params.
    """
    h_img, w_img = frame_shape[:2]
    pts = np.array(corners_px, dtype=np.float32)

    if margin_factor is not None:
        # Map old margin_factor to a vertical envelope; ignore lateral.
        vertical_envelope_px = max(vertical_envelope_px, float(margin_factor) * 600.0)

    # Identify top vs bottom corners by image y.
    y_min = float(pts[:, 1].min())
    y_max = float(pts[:, 1].max())
    span_y = max(1.0, y_max - y_min)

    # Lateral margin scaled by pitch image-width at the bottom.
    bottom_pts = pts[pts[:, 1] > (y_min + y_max) * 0.5]
    if len(bottom_pts) >= 2:
        bottom_width = float(bottom_pts[:, 0].max() - bottom_pts[:, 0].min())
    else:
        bottom_width = float(pts[:, 0].max() - pts[:, 0].min())
    lat = max(8.0, lateral_margin_frac * bottom_width)
    cx = float(pts[:, 0].mean())

    # Build polygon: original corners + their upward-shifted twins (above the pitch).
    extended: list[tuple[float, float]] = []
    for x, y in pts:
        depth_norm = (y - y_min) / span_y  # 0 at far/striker end, 1 at near/bowler end
        dy = -vertical_envelope_px * (0.25 + 0.75 * depth_norm)
        dx = (-lat) if x < cx else lat
        extended.append((float(x + dx), float(y + dy)))

    # Combine original quad (with lateral margin) + airborne extension.
    grounded = [
        ((-lat) + float(x) if x < cx else float(x) + lat, float(y))
        for x, y in pts
    ]
    all_pts = np.array(grounded + extended, dtype=np.float32)

    hull = cv2.convexHull(all_pts).astype(np.int32)
    hull[:, 0, 0] = np.clip(hull[:, 0, 0], 0, w_img - 1)
    hull[:, 0, 1] = np.clip(hull[:, 0, 1], 0, h_img - 1)

    mask = np.zeros((h_img, w_img), dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    return mask


def _detect_contours(binary: np.ndarray, roi_mask: np.ndarray | None) -> list[dict[str, Any]]:
    if roi_mask is not None:
        binary = cv2.bitwise_and(binary, roi_mask)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dets: list[dict[str, Any]] = []
    for c in contours:
        m = _contour_metrics(c)
        if m is None:
            continue
        # Confidence: weighted combination of circularity + size sanity.
        # Round shape (cricket ball) → high conf; jagged shape → low conf.
        circ_score = min(1.0, (m["circularity"] - _MIN_CIRCULARITY) / (1.0 - _MIN_CIRCULARITY))
        # Penalise very tiny detections (likely noise) and huge ones (people, kit).
        area = m["area"]
        if area < 30:
            size_score = area / 30.0
        elif area > 1200:
            size_score = max(0.2, 1.0 - (area - 1200) / 1300.0)
        else:
            size_score = 1.0
        conf = 0.30 + 0.50 * circ_score + 0.20 * size_score
        dets.append({
            "x": m["x"],
            "y": m["y"],
            "radius_px": m["radius"],
            "area_px": area,
            "circularity": m["circularity"],
            "confidence": float(min(1.0, conf)),
        })
    return dets


class MotionBallDetector:
    """MOG2 background subtraction.  Picks up anything that moves."""

    def __init__(self, threshold: int = 25):
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=12,
            varThreshold=float(threshold),
            detectShadows=False,
        )
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def detect(self, frame: np.ndarray, roi_mask: np.ndarray | None = None) -> list[dict[str, Any]]:
        fg = self._bg.apply(frame)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel)
        return _detect_contours(fg, roi_mask)


class ColorBallDetector:
    """HSV-thresholded color ball detector."""

    def __init__(self, ball_color: str = "red"):
        self.ball_color = ball_color
        if ball_color == "red":
            # Tighter than before: bright cricket-ball crimson, not skin/lips/wood.
            self.ranges = [
                ((0, 110, 70), (10, 255, 255)),
                ((170, 110, 70), (180, 255, 255)),
            ]
        elif ball_color == "pink":
            self.ranges = [
                ((150, 60, 130), (175, 255, 255)),
                ((0, 60, 130), (8, 255, 255)),
            ]
        else:  # white
            self.ranges = [((0, 0, 210), (180, 35, 255))]
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def detect(self, frame: np.ndarray, roi_mask: np.ndarray | None = None) -> list[dict[str, Any]]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask: np.ndarray | None = None
        for lo, hi in self.ranges:
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
            mask = m if mask is None else cv2.bitwise_or(mask, m)
        if mask is None:
            return []
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        return _detect_contours(mask, roi_mask)


class CombinedBallDetector:
    """Fuse motion + color.  A blob seen by both is the strongest ball candidate."""

    _MERGE_DIST_PX = 25.0

    def __init__(self, ball_color: str = "red"):
        self.motion = MotionBallDetector()
        self.color = ColorBallDetector(ball_color)

    def detect(self, frame: np.ndarray, roi_mask: np.ndarray | None = None) -> list[dict[str, Any]]:
        motion_dets = self.motion.detect(frame, roi_mask)
        color_dets = self.color.detect(frame, roi_mask)

        merged: list[dict[str, Any]] = []
        used_color: set[int] = set()

        for md in motion_dets:
            mx, my = md["x"], md["y"]
            best_idx: int | None = None
            best_dist = self._MERGE_DIST_PX
            for i, cd in enumerate(color_dets):
                if i in used_color:
                    continue
                d = math.hypot(mx - cd["x"], my - cd["y"])
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            if best_idx is not None:
                used_color.add(best_idx)
                cd = color_dets[best_idx]
                w1, w2 = md["confidence"], cd["confidence"]
                total = max(1e-6, w1 + w2)
                merged.append({
                    "x": (md["x"] * w1 + cd["x"] * w2) / total,
                    "y": (md["y"] * w1 + cd["y"] * w2) / total,
                    "radius_px": (md["radius_px"] * w1 + cd["radius_px"] * w2) / total,
                    "area_px": max(md["area_px"], cd["area_px"]),
                    "circularity": max(md["circularity"], cd["circularity"]),
                    "confidence": float(min(1.0, max(w1, w2) + 0.25)),
                    "source": "motion+color",
                })
            else:
                md["source"] = "motion"
                merged.append(md)

        for i, cd in enumerate(color_dets):
            if i not in used_color:
                cd["source"] = "color"
                merged.append(cd)

        merged.sort(key=lambda d: d["confidence"], reverse=True)
        return merged
