"""Run the tracking pipeline on a local video without going through the Flutter UI.

Usage:
  python -m scripts.debug_pipeline --video ../test.mp4 --out /tmp/pdrs/run

Hardcodes the test.mp4 calibration so we can iterate on the math.
Writes:
  - result.json
  - frames/det_NNN.jpg  (each sampled frame with ROI + detection overlays)
  - track_overlay.jpg   (single image of all detections layered on frame 0)
  - summary.txt         (sanity numbers: pitch-plane bounds, decision, etc.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# Allow `python -m scripts.debug_pipeline` from server/.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.process_job import run_pipeline  # noqa: E402
from app.pipeline.tracking import CombinedBallDetector, build_pitch_roi_mask  # noqa: E402


# Pitch corners visually estimated from frame 0 of test.mp4 (1080x1920).
# Order: striker-left, striker-right, bowler-right, bowler-left.
TEST_MP4_CORNERS_PX = [
    (240.0, 625.0),    # striker-left (top-left of green turf)
    (350.0, 625.0),    # striker-right (top-right of green turf)
    (445.0, 1290.0),   # bowler-right (bottom-right)
    (130.0, 1290.0),   # bowler-left (bottom-left)
]
# Bowler-end stumps base in image (yellow stumps in foreground).
TEST_MP4_BOWLER_STUMP_BASE_PX = (270.0, 870.0)
# Striker-end stumps base (estimated; partially occluded by batter).
TEST_MP4_STRIKER_STUMP_BASE_PX = (290.0, 625.0)


def build_request(start_ms: int, end_ms: int, mode: str = "auto") -> dict:
    return {
        "client": {"platform": "debug", "app_version": "0"},
        "segment": {"start_ms": start_ms, "end_ms": end_ms},
        "calibration": {
            "mode": "taps",
            "pitch_id": "test-mp4",
            "pitch_corners_px": [{"x": x, "y": y} for x, y in TEST_MP4_CORNERS_PX],
            "stump_bases_px": [
                {"x": TEST_MP4_STRIKER_STUMP_BASE_PX[0], "y": TEST_MP4_STRIKER_STUMP_BASE_PX[1]},
                {"x": TEST_MP4_BOWLER_STUMP_BASE_PX[0], "y": TEST_MP4_BOWLER_STUMP_BASE_PX[1]},
            ],
            "pitch_dimensions_m": {"length": 20.12, "width": 3.05},
        },
        "tracking": {"mode": mode, "max_frames": 180, "sample_fps": 30, "ball_color": "red"},
        "overrides": {},
    }


def overlay_detections(video_path: Path, out_dir: Path, sample_fps: int = 30, max_frames: int = 60) -> None:
    """Dump per-frame detection overlays so we can SEE what the detector picks up."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    detector = CombinedBallDetector(ball_color="red")

    # Build ROI mask from hardcoded corners on the first frame.
    ok, frame0 = cap.read()
    if not ok:
        print("could not read frame 0")
        return
    roi = build_pitch_roi_mask(frame0.shape, TEST_MP4_CORNERS_PX, margin_factor=0.6)
    cv2.imwrite(str(out_dir / "roi_mask.jpg"), roi)

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    composite = frame0.copy()
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        dets = detector.detect(f, roi)
        # overlay ROI as semi-transparent
        vis = f.copy()
        roi_color = np.zeros_like(f)
        roi_color[:, :, 1] = roi  # green channel
        vis = cv2.addWeighted(vis, 1.0, roi_color, 0.15, 0)
        # draw pitch quad
        pts = np.array(TEST_MP4_CORNERS_PX, dtype=np.int32)
        cv2.polylines(vis, [pts], True, (0, 255, 255), 2)
        # draw detections
        for d in dets:
            x, y, c = int(d["x"]), int(d["y"]), float(d["confidence"])
            color = (0, 0, 255) if c > 0.5 else (0, 165, 255)
            cv2.circle(vis, (x, y), 8, color, 2)
            cv2.putText(vis, f"{c:.2f}", (x + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            cv2.circle(composite, (x, y), 5, color, -1)
        if i % 2 == 0:
            cv2.imwrite(str(out_dir / f"det_{i:03d}.jpg"), vis)
        i += 1
        if i >= max_frames:
            break
    cap.release()
    # composite
    pts = np.array(TEST_MP4_CORNERS_PX, dtype=np.int32)
    cv2.polylines(composite, [pts], True, (0, 255, 255), 2)
    cv2.imwrite(str(out_dir / "track_overlay.jpg"), composite)
    print(f"wrote detection overlays to {out_dir}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video", default=str(ROOT.parent / "test.mp4"))
    p.add_argument("--out", default="/tmp/pdrs/run")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=7000)
    p.add_argument("--mode", default="auto", choices=["auto", "seeded"])
    p.add_argument("--no-overlay", action="store_true")
    args = p.parse_args()

    video = Path(args.video).resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    artifacts = out / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    if not args.no_overlay:
        overlay_detections(video, out / "frames")

    req = build_request(args.start, args.end, mode=args.mode)
    (out / "request.json").write_text(json.dumps(req, indent=2))

    progress_log: list[tuple[int, str]] = []

    def progress(pct: int, stage: str) -> None:
        progress_log.append((pct, stage))
        print(f"  {pct:3d}%  {stage}")

    print(f"Running pipeline on {video}")
    output = run_pipeline(
        video_path=video,
        request_json=req,
        artifacts_dir=artifacts,
        progress=progress,
    )
    (out / "result.json").write_text(json.dumps(output.result, indent=2, default=str))

    summary = []
    summary.append(f"video: {video}")
    summary.append(f"warnings: {output.warnings}")
    track = output.result.get("track", {}).get("points", [])
    pp = output.result.get("pitch_plane")
    summary.append(f"track points: {len(track)}")
    if pp and pp.get("points_m"):
        xs = [p["x_m"] for p in pp["points_m"]]
        ys = [p["y_m"] for p in pp["points_m"]]
        summary.append(f"pitch_plane points: {len(pp['points_m'])}")
        summary.append(f"  x range: [{min(xs):.2f}, {max(xs):.2f}] (expect [0, 20.12])")
        summary.append(f"  y range: [{min(ys):.2f}, {max(ys):.2f}] (expect [-1.5, 1.5])")
    cal = output.result.get("calibration", {})
    if cal.get("quality"):
        summary.append(f"calibration quality: {cal['quality']}")
    ev = output.result.get("events")
    if ev:
        summary.append(f"events: bounce={ev['bounce']}, impact={ev['impact']}")
    lbw = output.result.get("lbw")
    if lbw:
        summary.append(f"decision: {lbw['decision']} ({lbw['reason']})")
        summary.append(f"  prediction: {lbw['prediction']}")
    text = "\n".join(summary)
    (out / "summary.txt").write_text(text + "\n")
    print()
    print(text)


if __name__ == "__main__":
    main()
