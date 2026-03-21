"""Ball detection for cricket tracking.

Two detection strategies — motion (frame differencing) and color (HSV) —
are fused by CombinedBallDetector. Every candidate is filtered by area,
circularity, and aspect-ratio so that fielders, stumps, and clothing
noise are rejected before the tracker ever sees them.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

# Shared contour validation constants.
_MIN_AREA = 20
_MAX_AREA = 1500
_MIN_CIRCULARITY = 0.30
_MIN_ASPECT = 0.40  # bounding-box w/h ratio lower bound
_MAX_ASPECT = 2.50  # bounding-box w/h ratio upper bound


def _contour_is_ball_shaped(contour: np.ndarray, area: float) -> tuple[bool, float]:
    """Return (passes_shape_check, circularity) for a single contour."""
    if not (_MIN_AREA <= area <= _MAX_AREA):
        return False, 0.0

    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0:
        return False, 0.0

    circularity = 4.0 * np.pi * area / (perimeter * perimeter)
    if circularity < _MIN_CIRCULARITY:
        return False, circularity

    x, y, w, h = cv2.boundingRect(contour)
    if h == 0:
        return False, circularity
    aspect = w / h
    if not (_MIN_ASPECT <= aspect <= _MAX_ASPECT):
        return False, circularity

    return True, circularity


class MotionBallDetector:
    """Frame-differencing ball detector using MOG2 background subtraction."""

    def __init__(self, threshold: int = 25):
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=8,
            varThreshold=float(threshold),
            detectShadows=False,
        )
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        fg = self._bg.apply(frame)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel)

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        dets: list[dict[str, Any]] = []
        for c in contours:
            area = cv2.contourArea(c)
            ok, circ = _contour_is_ball_shaped(c, area)
            if not ok:
                continue

            M = cv2.moments(c)
            if M["m00"] <= 0:
                continue

            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]

            area_score = min(1.0, area / 400.0)
            circ_score = min(1.0, circ / 0.6)
            conf = 0.25 + 0.35 * area_score + 0.40 * circ_score

            dets.append({"x": float(cx), "y": float(cy), "confidence": float(min(1.0, conf))})

        return dets


class ColorBallDetector:
    """HSV color-based ball detector."""

    def __init__(self, ball_color: str = "red"):
        self.ball_color = ball_color
        if ball_color == "red":
            self.ranges = [
                ((0, 90, 70), (12, 255, 255)),
                ((168, 90, 70), (180, 255, 255)),
            ]
        elif ball_color == "pink":
            self.ranges = [
                ((150, 40, 120), (175, 255, 255)),
                ((0, 40, 120), (10, 255, 255)),
            ]
        else:  # white
            self.ranges = [((0, 0, 210), (180, 35, 255))]

        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        mask: np.ndarray | None = None
        for lo, hi in self.ranges:
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
            mask = m if mask is None else cv2.bitwise_or(mask, m)

        if mask is None:
            return []

        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        dets: list[dict[str, Any]] = []
        for c in contours:
            area = cv2.contourArea(c)
            ok, circ = _contour_is_ball_shaped(c, area)
            if not ok:
                continue

            M = cv2.moments(c)
            if M["m00"] <= 0:
                continue

            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]

            circ_score = min(1.0, circ / 0.6)
            conf = 0.35 + 0.25 * circ_score

            dets.append({"x": float(cx), "y": float(cy), "confidence": float(min(1.0, conf))})

        return dets


class CombinedBallDetector:
    """Fuses motion and color detections, boosting confidence for matches."""

    _MERGE_DIST = 30.0

    def __init__(self, ball_color: str = "red"):
        self.motion = MotionBallDetector()
        self.color = ColorBallDetector(ball_color)

    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        motion_dets = self.motion.detect(frame)
        color_dets = self.color.detect(frame)

        merged: list[dict[str, Any]] = []
        used_color: set[int] = set()

        for md in motion_dets:
            mx, my, mc = md["x"], md["y"], md["confidence"]

            best_idx: int | None = None
            best_dist = self._MERGE_DIST
            for i, cd in enumerate(color_dets):
                if i in used_color:
                    continue
                d = ((mx - cd["x"]) ** 2 + (my - cd["y"]) ** 2) ** 0.5
                if d < best_dist:
                    best_dist = d
                    best_idx = i

            if best_idx is not None:
                used_color.add(best_idx)
                cd = color_dets[best_idx]
                w1, w2 = mc, cd["confidence"]
                total = w1 + w2
                merged.append({
                    "x": (mx * w1 + cd["x"] * w2) / total,
                    "y": (my * w1 + cd["y"] * w2) / total,
                    "confidence": min(1.0, mc + 0.15),
                })
            else:
                merged.append(md)

        for i, cd in enumerate(color_dets):
            if i not in used_color:
                merged.append(cd)

        merged.sort(key=lambda d: d["confidence"], reverse=True)
        return merged
