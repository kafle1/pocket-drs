#!/usr/bin/env python
"""Run the pipeline on one of the bundled real clips and render the overlay.

Usage:  server/.venv/bin/python server/scripts/real_clip.py test3 [--no-render]

The taps below were read off the first frame of each clip. test3 is a full-length outdoor net,
so its pitch length is pinned; test4 and test5 are short indoor nets and the length is fitted
from the marks.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
from app.pipeline.process_job import run_pipeline   # noqa: E402

# name -> (striker stumps TL,TR,BR,BL ; bowler stumps TL,TR,BR,BL ; pitch corners SL,SR,BR,BL ; pinned length)
CLIPS = {
    "test3": ([(0.509, 0.482), (0.552, 0.482), (0.552, 0.545), (0.509, 0.545)],
              [(0.403, 0.633), (0.544, 0.633), (0.544, 0.851), (0.403, 0.851)],
              [(0.420, 0.465), (0.595, 0.465), (0.625, 0.800), (0.305, 0.800)], 20.12),
    "test4": ([(0.509, 0.483), (0.552, 0.483), (0.552, 0.545), (0.509, 0.545)],
              [(0.452, 0.618), (0.574, 0.618), (0.574, 0.817), (0.452, 0.817)],
              [(0.398, 0.532), (0.591, 0.532), (0.833, 0.982), (0.160, 0.982)], None),
    "test5": ([(0.509, 0.481), (0.556, 0.481), (0.556, 0.549), (0.509, 0.549)],
              [(0.431, 0.608), (0.580, 0.608), (0.580, 0.818), (0.431, 0.818)],
              [(0.398, 0.532), (0.591, 0.532), (0.833, 0.982), (0.160, 0.982)], None),
}


def build_request(name: str) -> dict:
    striker, bowler, corners, length = CLIPS[name]
    dims = {"width": 3.05}
    if length is not None:
        dims["length"] = length
    return {
        "segment": {"start_ms": 0, "end_ms": 600000},
        "video": {"rotation_deg": 0},
        "tracking": {"sample_fps": 60, "max_frames": 180, "ball_color": "red", "detector": "auto"},
        "calibration": {"mode": "taps", "pitch_dimensions_m": dims,
                        "pitch_corners_norm": [{"x": x, "y": y} for x, y in corners],
                        "stump_quads_norm": [{"x": x, "y": y} for x, y in striker + bowler]},
        "batsman_handedness": "right",
    }


def render(name: str, result: dict, out_dir: Path) -> None:
    """Draw the tracked flight, the predicted path, the stumps and the verdict on the clip."""
    ov = result.get("overlay") or {}
    lbw = result.get("lbw") or {}
    cap = cv2.VideoCapture(str(ROOT / f"{name}.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(out_dir / f"{name}_tracked.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    path = ov.get("path_px") or []
    sample = None
    frame_i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t_ms = frame_i * 1000.0 / fps
        for key, colour in (("corridor_px", (60, 200, 245)), ("pitch_rect_px", (200, 200, 200))):
            poly = ov.get(key)
            if poly:
                cv2.polylines(frame, [np.array([[p["u"], p["v"]] for p in poly], dtype=np.int32)], True, colour, 2)
        for st in (ov.get("stumps_px") or {}).values():
            if st:
                cv2.line(frame, (int(st["base"]["u"]), int(st["base"]["v"])), (int(st["top"]["u"]), int(st["top"]["v"])), (255, 255, 255), 3)
        seen = [p for p in path if p["t_ms"] <= t_ms or p["phase"] == "predicted"]
        for a, b in zip(seen, seen[1:]):
            colour = (60, 60, 235) if a["phase"] == "flight" else (235, 170, 60)
            cv2.line(frame, (int(a["u"]), int(a["v"])), (int(b["u"]), int(b["v"])), colour, 4, cv2.LINE_AA)
        for key, colour in (("bounce_px", (60, 200, 245)), ("impact_px", (235, 170, 60))):
            m = ov.get(key)
            if m and m["t_ms"] <= t_ms:
                cv2.circle(frame, (int(m["u"]), int(m["v"])), 14, colour, 3)
        if lbw:
            cv2.putText(frame, f"{lbw['decision'].replace('_', ' ').upper()}  {lbw['reason']}", (30, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        writer.write(frame)
        if sample is None and path and t_ms >= path[len(path) // 2]["t_ms"]:
            sample = frame.copy()
        frame_i += 1
    writer.release()
    cap.release()
    if sample is not None:
        cv2.imwrite(str(out_dir / f"{name}_sample.png"), sample)


def main() -> int:
    name = next((a for a in sys.argv[1:] if a in CLIPS), None)
    if name is None:
        print(f"usage: real_clip.py {{{','.join(CLIPS)}}} [--no-render]")
        return 2
    out = ROOT / "dump" / "validation" / name
    out.mkdir(parents=True, exist_ok=True)
    result = run_pipeline(video_path=ROOT / f"{name}.mp4", request_json=build_request(name),
                          artifacts_dir=Path(tempfile.mkdtemp(prefix=f"{name}_")), progress=None).result
    (out / "result.json").write_text(json.dumps(result, indent=2))
    q = result["calibration"]["quality"]
    lbw = result.get("lbw") or {}
    print(f"{name}: reproj {q['reproj_error_px']:.1f} px  track {len(result['track']['image_points'])} points  "
          f"verdict {lbw.get('decision')}  {lbw.get('reason') or ''}")
    for w in result["diagnostics"]["warnings"]:
        print("  warning:", w)
    if "--no-render" not in sys.argv and result.get("overlay"):
        render(name, result, out)
        print(f"  wrote {out}/{name}_tracked.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
