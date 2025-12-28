"""Simple ball detection for cricket tracking.

Provides fallback detection methods when YOLO is not available.
For production, use YOLOv8/v9 custom-trained model.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


class MotionBallDetector:
    """Frame-differencing ball detector (fallback method)."""
    
    def __init__(
        self,
        min_area: int = 10,
        max_area: int = 2000,
        threshold: int = 25,
    ):
        self.min_area = min_area
        self.max_area = max_area
        self.threshold = threshold
        self.prev_gray: np.ndarray | None = None
    
    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Detect ball candidates using motion.
        
        Returns:
            List of {"x": float, "y": float, "confidence": float}
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        
        if self.prev_gray is None:
            self.prev_gray = gray
            return []
        
        # Frame difference
        diff = cv2.absdiff(gray, self.prev_gray)
        _, binary = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)
        
        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        # Find contours
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        detections = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if self.min_area <= area <= self.max_area:
                M = cv2.moments(contour)
                if M["m00"] > 0:
                    cx = M["m10"] / M["m00"]
                    cy = M["m01"] / M["m00"]
                    confidence = min(1.0, area / self.max_area)
                    
                    detections.append({
                        "x": float(cx),
                        "y": float(cy),
                        "confidence": float(confidence),
                    })
        
        self.prev_gray = gray
        return detections


class ColorBallDetector:
    """HSV color-based ball detector (for red cricket balls)."""
    
    def __init__(self, h_range=(0, 10), s_range=(100, 255), v_range=(100, 255)):
        self.h_min, self.h_max = h_range
        self.s_min, self.s_max = s_range
        self.v_min, self.v_max = v_range
    
    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Detect ball by color."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Red has two ranges in HSV
        mask1 = cv2.inRange(hsv, (self.h_min, self.s_min, self.v_min), (self.h_max, self.s_max, self.v_max))
        mask2 = cv2.inRange(hsv, (170, self.s_min, self.v_min), (180, self.s_max, self.v_max))
        mask = cv2.bitwise_or(mask1, mask2)
        
        # Clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        detections = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 10:
                M = cv2.moments(contour)
                if M["m00"] > 0:
                    cx = M["m10"] / M["m00"]
                    cy = M["m01"] / M["m00"]
                    
                    detections.append({
                        "x": float(cx),
                        "y": float(cy),
                        "confidence": 0.7,  # Lower confidence than YOLO
                    })
        
        return detections
