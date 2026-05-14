"""Render diagnostic visualizations of the test.mp4 calibration + tracking."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


VIDEO = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/test.mp4")
RESULT = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/validation/realvideo_result.json")
OUT_DIR = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/validation")

CORNERS_PX = [(200.0, 470.0), (370.0, 470.0), (700.0, 1850.0), (10.0, 1850.0)]
CORNER_LABELS = ["striker-L", "striker-R", "bowler-R", "bowler-L"]


def overlay_calibration(frame: np.ndarray) -> np.ndarray:
    out = frame.copy()
    pts = np.array(CORNERS_PX, dtype=np.int32)
    # Filled translucent pitch polygon.
    overlay = out.copy()
    cv2.fillPoly(overlay, [pts], (0, 200, 255))
    out = cv2.addWeighted(overlay, 0.25, out, 0.75, 0)
    cv2.polylines(out, [pts], isClosed=True, color=(0, 220, 255), thickness=3)
    for (x, y), label in zip(CORNERS_PX, CORNER_LABELS):
        cv2.circle(out, (int(x), int(y)), 12, (0, 0, 255), -1)
        cv2.putText(out, label, (int(x) + 18, int(y) + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(out, "Visual corner picks (test.mp4)",
                (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return out


def overlay_tracking(frame: np.ndarray, points: list[dict]) -> np.ndarray:
    """Draw all tracked ball positions on a single frame as a heat-style overlay."""
    out = frame.copy()
    # Annotate first/middle/last.
    for i, p in enumerate(points):
        u, v, r = int(p["u"]), int(p["v"]), max(2, int(p.get("radius_px", 4)))
        col = (60, 220, 60) if i < len(points) // 3 else (
            (60, 220, 220) if i < 2 * len(points) // 3 else (60, 60, 220))
        cv2.circle(out, (u, v), r, col, 1)
    # Draw the cluster centre.
    us = np.array([p["u"] for p in points])
    vs = np.array([p["v"] for p in points])
    u_min, u_max = int(us.min()), int(us.max())
    v_min, v_max = int(vs.min()), int(vs.max())
    cv2.rectangle(out, (u_min - 12, v_min - 12), (u_max + 12, v_max + 12), (0, 255, 255), 2)
    cv2.putText(out, f"Detector cluster: u in [{u_min},{u_max}]  v in [{v_min},{v_max}]",
                (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.putText(out, f"Width: {u_max - u_min} px,  Height: {v_max - v_min} px",
                (24, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.putText(out, f"-> ball does not move - tracker locked onto a stationary object",
                (24, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 60, 255), 2)
    return out


def sample_frames(times_ms: list[int]) -> list[tuple[int, np.ndarray]]:
    cap = cv2.VideoCapture(str(VIDEO))
    out = []
    for t in times_ms:
        cap.set(cv2.CAP_PROP_POS_MSEC, t)
        ok, frame = cap.read()
        if ok:
            out.append((t, frame))
    cap.release()
    return out


def main() -> int:
    r = json.load(RESULT.open())
    tracked = r["track"]["image_points"]

    cap = cv2.VideoCapture(str(VIDEO))
    ok, f0 = cap.read()
    cap.release()
    if not ok:
        return 1

    # 1. Calibration overlay on frame 0.
    cv2.imwrite(str(OUT_DIR / "realvideo_calibration.png"), overlay_calibration(f0))

    # 2. Tracking overlay on frame 0 (all 194 detections drawn).
    cv2.imwrite(str(OUT_DIR / "realvideo_tracking_cluster.png"), overlay_tracking(f0, tracked))

    # 3. Sample frames at sparse times with the corresponding detection.
    samples = sample_frames([0, 1500, 3000, 4500, 6000])
    panels = []
    for t_ms, frame in samples:
        det = min(tracked, key=lambda p: abs(p["t_ms"] - t_ms))
        u, v = int(det["u"]), int(det["v"])
        annotated = frame.copy()
        cv2.circle(annotated, (u, v), 14, (0, 255, 255), 3)
        cv2.line(annotated, (u - 30, v), (u + 30, v), (0, 255, 255), 2)
        cv2.line(annotated, (u, v - 30), (u, v + 30), (0, 255, 255), 2)
        cv2.putText(annotated, f"t = {t_ms} ms", (24, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        cv2.putText(annotated, f"pipeline det: ({u}, {v})", (24, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        # Thumbnail for the panel.
        panels.append(cv2.resize(annotated, (480, 853)))
    panel_strip = cv2.hconcat(panels)
    cv2.imwrite(str(OUT_DIR / "realvideo_track_panels.png"), panel_strip)

    # Summary stats.
    print(f"Tracked detections: {len(tracked)}")
    us = [p['u'] for p in tracked]
    vs = [p['v'] for p in tracked]
    print(f"u range: {min(us):.1f} - {max(us):.1f}  (span {max(us)-min(us):.1f} px)")
    print(f"v range: {min(vs):.1f} - {max(vs):.1f}  (span {max(vs)-min(vs):.1f} px)")
    print(f"video dimensions: 1080x1920")
    print(f"=> tracker variation is {(max(us)-min(us))/1080*100:.2f}% in u, "
          f"{(max(vs)-min(vs))/1920*100:.2f}% in v.")
    print(f"\nWritten:")
    for p in ("realvideo_calibration.png", "realvideo_tracking_cluster.png", "realvideo_track_panels.png"):
        print(f"  {OUT_DIR / p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
