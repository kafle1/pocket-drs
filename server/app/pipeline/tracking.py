"""Ball detection for cricket tracking.

Two strategies (motion + color) are fused by CombinedBallDetector.
An optional ROI mask restricts detection to the pitch region and its
immediate surroundings, eliminating fielders, boundary boards, and sky.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

_MIN_AREA = 20
_MAX_AREA = 1500
_MIN_CIRCULARITY = 0.30
_MIN_ASPECT = 0.40
_MAX_ASPECT = 2.50


def _contour_is_ball_shaped(contour: np.ndarray, area: float) -> tuple[bool, float]:
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


def build_pitch_roi_mask(
    frame_shape: tuple[int, ...],
    corners_px: list[tuple[float, float]],
    margin_factor: float = 0.5,
) -> np.ndarray:
    """Build a binary mask that covers the pitch plus a generous margin.

    The margin allows detecting the ball in its airborne arc above/beside
    the pitch, while still rejecting far-off fielders and background.
    """
    h, w = frame_shape[:2]
    pts = np.array(corners_px, dtype=np.float32)
    cx, cy = pts.mean(axis=0)
    expanded = pts.copy()
    for i in range(len(expanded)):
        dx = expanded[i, 0] - cx
        dy = expanded[i, 1] - cy
        expanded[i, 0] = cx + dx * (1.0 + margin_factor)
        expanded[i, 1] = cy + dy * (1.0 + margin_factor)
    expanded[:, 0] = np.clip(expanded[:, 0], 0, w - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, h - 1)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, expanded.astype(np.int32), 255)
    return mask


def _detect_contours(binary: np.ndarray, roi_mask: np.ndarray | None) -> list[dict[str, Any]]:
    """Find ball-shaped contours in a binary image, optionally masked by ROI."""
    if roi_mask is not None:
        binary = cv2.bitwise_and(binary, roi_mask)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
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


class MotionBallDetector:
    """MOG2 background subtraction ball detector."""

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
    """HSV color-based ball detector."""

    def __init__(self, ball_color: str = "red"):
        self.ball_color = ball_color
        if ball_color == "red":
            self.ranges = [
                ((0, 70, 50), (15, 255, 255)),
                ((165, 70, 50), (180, 255, 255)),
            ]
        elif ball_color == "pink":
            self.ranges = [
                ((150, 40, 120), (175, 255, 255)),
                ((0, 40, 120), (10, 255, 255)),
            ]
        else:  # white
            self.ranges = [((0, 0, 200), (180, 40, 255))]
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
        dets = _detect_contours(mask, roi_mask)
        for d in dets:
            d["confidence"] = float(min(1.0, d["confidence"] * 0.85))
        return dets


class CombinedBallDetector:
    """Fuses motion and color detections, boosting confidence for matches."""

    _MERGE_DIST = 30.0

    def __init__(self, ball_color: str = "red"):
        self.motion = MotionBallDetector()
        self.color = ColorBallDetector(ball_color)

    def detect(self, frame: np.ndarray, roi_mask: np.ndarray | None = None) -> list[dict[str, Any]]:
        motion_dets = self.motion.detect(frame, roi_mask)
        color_dets = self.color.detect(frame, roi_mask)

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
                    "confidence": min(1.0, mc + 0.20),
                })
            else:
                merged.append(md)

        for i, cd in enumerate(color_dets):
            if i not in used_color:
                merged.append(cd)

        merged.sort(key=lambda d: d["confidence"], reverse=True)
        return merged
