"""Stage 1 for the test3.mp4 report case study.

Probe the clip, run the YOLO cricket-ball detector across every sampled frame,
keep the single best (highest-confidence) ball detection per frame, and write
the raw 2D pixel track + a few sample frames for inspection.

Output: dump/validation/test3/{meta.json, track_raw.json, frame_*.png}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs")
sys.path.insert(0, str(ROOT / "server"))

from app.pipeline.tracking import YoloBallDetector
from app.pipeline.video import VideoReader

VIDEO = ROOT / "test3.mp4"
WEIGHTS = ROOT / "server" / "models" / "cricket_ball.pt"
OUT = ROOT / "dump" / "validation" / "test3"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    reader = VideoReader(str(VIDEO))
    meta = reader.meta
    cap = cv2.VideoCapture(str(VIDEO))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    meta_d = {
        "fps": meta.fps,
        "frame_count": meta.frame_count,
        "duration_ms": meta.duration_ms,
        "width": w,
        "height": h,
    }
    (OUT / "meta.json").write_text(json.dumps(meta_d, indent=2))
    print(f"meta: {meta_d}")

    det = YoloBallDetector(str(WEIGHTS), conf=0.15, imgsz=1280)

    fps = meta.fps if meta.fps > 0 else 60.0
    n = meta.frame_count if meta.frame_count > 0 else 200
    # Sample every frame at native cadence.
    track = []
    saved_frames = {}
    stale = 0
    for idx in range(n):
        t_ms = int(round(idx / fps * 1000.0))
        try:
            frame = reader.frame_at_ms(t_ms)
        except Exception as exc:  # truncated tail
            print(f"stop at frame {idx} ({t_ms}ms): {exc}")
            break
        dets = det.detect(frame)
        best = dets[0] if dets else None
        if best is not None:
            track.append({
                "frame": idx,
                "t_ms": t_ms,
                "u": round(best["x"], 2),
                "v": round(best["y"], 2),
                "radius_px": round(best["radius_px"], 2),
                "confidence": round(best["confidence"], 4),
                "n_dets": len(dets),
            })
        # Keep a handful of full frames for later overlay rendering.
        if idx % 5 == 0:
            saved_frames[idx] = frame.copy()

    reader.close()

    (OUT / "track_raw.json").write_text(json.dumps(track, indent=2))

    print(f"\nframes with a ball detection: {len(track)}")
    if track:
        us = [p["u"] for p in track]
        vs = [p["v"] for p in track]
        fr = [p["frame"] for p in track]
        print(f"frame range with ball : {min(fr)} - {max(fr)}")
        print(f"u span: {min(us):.0f}..{max(us):.0f} ({max(us)-min(us):.0f}px)")
        print(f"v span: {min(vs):.0f}..{max(vs):.0f} ({max(vs)-min(vs):.0f}px)")
        print("\nframe  t_ms     u       v     r_px   conf  n")
        for p in track:
            print(f"{p['frame']:5d} {p['t_ms']:6d} {p['u']:7.1f} {p['v']:7.1f} "
                  f"{p['radius_px']:5.1f} {p['confidence']:.3f} {p['n_dets']}")

    # Save sample frames for visual corner picking.
    for idx in (0, 20, 30, 40, 50, 60):
        if idx in saved_frames:
            cv2.imwrite(str(OUT / f"frame_{idx:03d}.png"), saved_frames[idx])
    print(f"\nwrote sample frames + track to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
