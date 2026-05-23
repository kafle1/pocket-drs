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
_MAX_AREA_PX = 4000.0
_MIN_CIRCULARITY = 0.45
_MIN_ASPECT = 0.55
_MAX_ASPECT = 1.80

# Motion-blur streak parameters. A cricket ball at 25 m/s, ~6 m from the
# camera, with a typical 1/120 s phone exposure smears into a ~30 px streak
# that is only ~5 px wide. Such a streak has circularity ~0.2-0.35 and aspect
# 3-8, so the round-blob gates above reject it outright. We therefore accept
# elongated contours as "streak" detections when the minor axis is ball-sized
# and the shape is a clean, filled ellipse (a real motion-blurred ball) rather
# than a jagged background fragment.
_STREAK_MIN_ASPECT = 2.0
_STREAK_MAX_ASPECT = 12.0
_STREAK_MIN_MINOR_PX = 2.0
_STREAK_MAX_MINOR_PX = 40.0
_STREAK_MIN_FILL = 0.55          # contour area / min-area-rect area
_STREAK_MIN_CIRCULARITY = 0.12


def _contour_metrics(contour: np.ndarray) -> dict[str, float] | None:
    """Compute centroid, effective radius and shape descriptors for a contour.

    Accepts two ball shapes:
      * round blob   - a slow / distant ball that is barely smeared;
      * motion streak - a fast ball smeared along its direction of travel.

    Returns None when the contour matches neither so the caller can skip it.
    The `is_streak` flag and `streak_len` let downstream code use the streak
    geometry (the minor axis is the true ball diameter; the major axis encodes
    image-space speed).
    """
    area = float(cv2.contourArea(contour))
    if not (_MIN_AREA_PX <= area <= _MAX_AREA_PX):
        return None
    perimeter = float(cv2.arcLength(contour, True))
    if perimeter <= 0:
        return None
    circularity = 4.0 * math.pi * area / (perimeter * perimeter)

    # Oriented bounding box gives true minor/major axes for streaks.
    (rc_x, rc_y), (rw, rh), _angle = cv2.minAreaRect(contour)
    minor = float(min(rw, rh))
    major = float(max(rw, rh))
    if minor <= 1e-3:
        return None
    aspect_oriented = major / minor
    rect_area = max(1e-3, rw * rh)
    fill = area / rect_area

    moments = cv2.moments(contour)
    m00 = moments.get("m00", 0.0)
    if m00 > 0:
        cx = float(moments["m10"] / m00)
        cy = float(moments["m01"] / m00)
    else:
        cx, cy = float(rc_x), float(rc_y)

    is_streak = False
    if circularity >= _MIN_CIRCULARITY:
        # Round-blob path: classic compact ball.
        x, y, w, h = cv2.boundingRect(contour)
        if h == 0:
            return None
        if not (_MIN_ASPECT <= w / h <= _MAX_ASPECT):
            return None
        # Effective radius from area avoids the anti-aliasing halo over-
        # estimate of minEnclosingCircle.
        radius = float(math.sqrt(area / math.pi))
    elif (
        _STREAK_MIN_ASPECT <= aspect_oriented <= _STREAK_MAX_ASPECT
        and _STREAK_MIN_MINOR_PX <= minor <= _STREAK_MAX_MINOR_PX
        and fill >= _STREAK_MIN_FILL
        and circularity >= _STREAK_MIN_CIRCULARITY
    ):
        # Streak path: a clean, well-filled elongated ellipse -> motion-blurred
        # ball. The ball's true radius is half the minor axis.
        is_streak = True
        radius = minor / 2.0
    else:
        return None

    return {
        "x": cx,
        "y": cy,
        "radius": radius,
        "area": area,
        "circularity": float(circularity),
        "is_streak": 1.0 if is_streak else 0.0,
        "streak_len": major,
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
    y_mid = (y_min + y_max) * 0.5

    # The narrower end in image is the far end (perspective foreshortening).
    # The airborne ball arc lives just beyond that far end, so we extend the
    # envelope in that direction. Standard umpire-POV has the far/bowler end
    # at the top of the image, but we infer the direction from geometry so
    # the mask also works when the camera is inverted.
    top_pts = pts[pts[:, 1] <= y_mid]
    bottom_pts = pts[pts[:, 1] > y_mid]
    top_width = (float(top_pts[:, 0].max() - top_pts[:, 0].min())
                 if len(top_pts) >= 2 else 0.0)
    bottom_width = (float(bottom_pts[:, 0].max() - bottom_pts[:, 0].min())
                    if len(bottom_pts) >= 2 else 0.0)
    far_is_top = top_width <= bottom_width
    near_width = max(top_width, bottom_width, 1.0)

    lat = max(8.0, lateral_margin_frac * near_width)
    cx = float(pts[:, 0].mean())

    # Build polygon: original corners + airborne envelopes BOTH past the far
    # end (the bowler/release arc) and past the near end (the batsman/impact
    # zone). The previous one-sided envelope silenced post-bounce candidates
    # that crossed into the batsman area, so the detector never saw them.
    # The lateral expansion stays modest; the convex hull smooths the edges.
    far_sign = -1.0 if far_is_top else 1.0   # toward image top if far is up
    near_sign = -far_sign                    # toward image bottom (batsman)
    extended_far: list[tuple[float, float]] = []
    extended_near: list[tuple[float, float]] = []
    for x, y in pts:
        depth_norm = (y - y_min) / span_y  # 0 at top, 1 at bottom
        near_norm = depth_norm if far_is_top else (1.0 - depth_norm)
        far_norm = 1.0 - near_norm
        far_dy = far_sign * vertical_envelope_px * (0.25 + 0.75 * near_norm)
        # Batsman envelope is shorter — the impact zone sits just past the
        # near end and we do not want to swallow the whole bottom of the frame.
        near_dy = near_sign * (0.5 * vertical_envelope_px) * (0.25 + 0.75 * far_norm)
        dx = (-lat) if x < cx else lat
        extended_far.append((float(x + dx), float(y + far_dy)))
        extended_near.append((float(x + dx), float(y + near_dy)))

    # Combine original quad (with lateral margin) + both airborne extensions.
    grounded = [
        ((-lat) + float(x) if x < cx else float(x) + lat, float(y))
        for x, y in pts
    ]
    all_pts = np.array(grounded + extended_far + extended_near, dtype=np.float32)

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
        area = m["area"]
        is_streak = m.get("is_streak", 0.0) >= 0.5
        if is_streak:
            # Streak detections cannot use circularity as a quality signal
            # (they are intentionally elongated). Score them on minor-axis
            # ball-likeness instead: a clean motion-blurred ball has a tight,
            # well-filled minor axis.
            r = m["radius"]
            size_score = 1.0 if 2.0 <= r <= 18.0 else max(0.2, 1.0 - abs(r - 10.0) / 20.0)
            conf = 0.25 + 0.45 * size_score
        else:
            # Round-blob path: circularity + size sanity.
            circ_score = min(1.0, (m["circularity"] - _MIN_CIRCULARITY) / (1.0 - _MIN_CIRCULARITY))
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
            "is_streak": 1.0 if is_streak else 0.0,
            "streak_len": m.get("streak_len", 0.0),
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
                    "is_streak": max(md.get("is_streak", 0.0), cd.get("is_streak", 0.0)),
                    "streak_len": max(md.get("streak_len", 0.0), cd.get("streak_len", 0.0)),
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


class YoloBallDetector:
    """Learned ball detector (Ultralytics YOLO) for cluttered real footage.

    Motion+colour fails on real matches where moving people dominate the frame;
    a trained cricket-ball model isolates the ball directly. Drop-in replacement
    for ``CombinedBallDetector`` — same ``detect`` signature, same candidate
    dicts — so the trajectory finder, reconstruction, and LBW stages are
    unchanged. Optional: needs ``ultralytics`` plus a weights file, selected via
    the request (``tracking.detector = "yolo"``); otherwise the colour/motion
    detector is used.

    The ROI mask is intentionally ignored: a delivery's airborne arc rises well
    above the pitch quad, and the model already rejects non-ball pixels, so
    masking would only clip the true flight.
    """

    def __init__(self, weights_path: str, *, conf: float = 0.2, imgsz: int = 1280):
        from ultralytics import YOLO  # local import keeps ML deps optional

        self._model = YOLO(weights_path)
        self._conf = conf
        self._imgsz = imgsz

    def detect(self, frame: np.ndarray, roi_mask: np.ndarray | None = None) -> list[dict[str, Any]]:
        res = self._model.predict(frame, imgsz=self._imgsz, conf=self._conf, verbose=False)[0]
        dets: list[dict[str, Any]] = []
        for box in res.boxes:
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            w, h = x2 - x1, y2 - y1
            dets.append({
                "x": (x1 + x2) / 2.0,
                "y": (y1 + y2) / 2.0,
                "radius_px": max(2.0, (w + h) / 4.0),
                "area_px": float(w * h),
                "circularity": 1.0,
                "is_streak": 0.0,
                "streak_len": 0.0,
                "confidence": float(box.conf[0]),
                "source": "yolo",
            })
        dets.sort(key=lambda d: d["confidence"], reverse=True)
        return dets
