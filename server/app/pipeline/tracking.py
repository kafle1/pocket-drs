"""Ball candidates per frame: HSV hue plus MOG2 background subtraction inside a pitch mask.

Each frame gives a list of {x, y, radius_px, confidence}, strongest first. Most are
people, kit and shadows; trajectory.py keeps the one set that flies like a bowled ball.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .calibration import CalibrationError, CameraPose

# a ball is a compact blob, or a filled streak when the exposure smears it along its travel
_MIN_AREA_PX, _MAX_AREA_PX = 8.0, 4000.0
_MIN_CIRCULARITY = 0.45
_STREAK_ASPECT = (2.0, 12.0)
_STREAK_MINOR_PX = (2.0, 40.0)
_STREAK_MIN_FILL = 0.55
_STREAK_MIN_CIRCULARITY = 0.12


def corridor_mask(frame_shape: tuple[int, ...], pose: CameraPose) -> np.ndarray:
    """Pixels the ball can occupy: the box over the pitch, a little wider, from the ground to above any release."""
    hw = pose.pitch_width_m / 2.0 + 0.3
    box = np.array([(x, y, z) for x in (0.0, pose.pitch_length_m) for y in (-hw, hw) for z in (0.0, 2.6)])
    u, v, depth = pose.project(box)
    if depth.min() < 0.3:
        raise CalibrationError("The stump marks put the phone on the pitch. It must stand behind one set of stumps, "
                               "looking down the pitch. Re-mark the stumps.")
    mask = np.zeros(frame_shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(np.stack([u, v], axis=1).astype(np.int32)), 255)
    return mask


def _candidates(binary: np.ndarray) -> list[dict]:
    """Ball-shaped contours in a binary mask, with a confidence from shape and size."""
    out = []
    for c in cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = float(cv2.contourArea(c))
        # hull perimeter, so the ragged edge a motion mask gives a real ball does not cost it its roundness
        perimeter = float(cv2.arcLength(cv2.convexHull(c), True))
        if not (_MIN_AREA_PX <= area <= _MAX_AREA_PX) or perimeter <= 0:
            continue
        circularity = 4.0 * math.pi * area / (perimeter * perimeter)
        (rx, ry), (rw, rh), _ = cv2.minAreaRect(c)
        minor, major = min(rw, rh), max(rw, rh)
        if minor <= 1e-3:
            continue
        m = cv2.moments(c)
        x, y = (m["m10"] / m["m00"], m["m01"] / m["m00"]) if m["m00"] > 0 else (rx, ry)
        if circularity >= _MIN_CIRCULARITY:
            _, _, w, h = cv2.boundingRect(c)
            if h == 0 or not (0.55 <= w / h <= 1.8):
                continue
            radius = math.sqrt(area / math.pi)
            circ = min(1.0, (circularity - _MIN_CIRCULARITY) / (1.0 - _MIN_CIRCULARITY))
            size = area / 30.0 if area < 30 else max(0.2, 1.0 - (area - 1200) / 1300.0) if area > 1200 else 1.0
            conf = 0.30 + 0.50 * circ + 0.20 * size
        elif (_STREAK_ASPECT[0] <= major / minor <= _STREAK_ASPECT[1]
              and _STREAK_MINOR_PX[0] <= minor <= _STREAK_MINOR_PX[1]
              and area / max(1e-3, rw * rh) >= _STREAK_MIN_FILL and circularity >= _STREAK_MIN_CIRCULARITY):
            radius = minor / 2.0                       # the minor axis is the ball's true diameter
            size = 1.0 if 2.0 <= radius <= 18.0 else max(0.2, 1.0 - abs(radius - 10.0) / 20.0)
            conf = 0.25 + 0.45 * size
        else:
            continue
        out.append({"x": float(x), "y": float(y), "radius_px": float(radius),
                    "confidence": float(min(1.0, conf))})
    return out


class ColourMotionDetector:
    """Hue threshold and background subtraction, fused: a blob both see is the strongest candidate."""

    _RANGES = {
        "red": [((0, 110, 70), (10, 255, 255)), ((170, 110, 70), (180, 255, 255))],
        "pink": [((150, 60, 130), (175, 255, 255)), ((0, 60, 130), (8, 255, 255))],
        "white": [((0, 0, 210), (180, 35, 255))],
    }
    _MERGE_PX = 25.0

    def __init__(self, ball_color: str, roi_mask: np.ndarray):
        self._ranges = self._RANGES[ball_color]
        self._mask = roi_mask
        self._bg = cv2.createBackgroundSubtractorMOG2(history=12, varThreshold=25.0, detectShadows=False)
        self._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def detect(self, frame: np.ndarray) -> list[dict]:
        fg = self._bg.apply(frame)
        fg = cv2.morphologyEx(cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._k3), cv2.MORPH_CLOSE, self._k3)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        colour = None
        for lo, hi in self._ranges:
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
            colour = m if colour is None else cv2.bitwise_or(colour, m)
        colour = cv2.morphologyEx(cv2.morphologyEx(colour, cv2.MORPH_CLOSE, self._k5), cv2.MORPH_OPEN, self._k5)
        motion = _candidates(cv2.bitwise_and(fg, self._mask))
        hue = _candidates(cv2.bitwise_and(colour, self._mask))

        merged, used = [], set()
        for md in motion:
            near = [(math.hypot(md["x"] - cd["x"], md["y"] - cd["y"]), i) for i, cd in enumerate(hue) if i not in used]
            best = min(near, default=(self._MERGE_PX, -1))
            if best[0] < self._MERGE_PX:
                used.add(best[1])
                cd = hue[best[1]]
                w1, w2 = md["confidence"], cd["confidence"]
                merged.append({"x": (md["x"] * w1 + cd["x"] * w2) / (w1 + w2),
                               "y": (md["y"] * w1 + cd["y"] * w2) / (w1 + w2),
                               "radius_px": (md["radius_px"] * w1 + cd["radius_px"] * w2) / (w1 + w2),
                               "confidence": min(1.0, max(w1, w2) + 0.25)})
            else:
                merged.append(md)
        merged.extend(cd for i, cd in enumerate(hue) if i not in used)
        merged.sort(key=lambda d: d["confidence"], reverse=True)
        return merged
