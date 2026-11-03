"""Detector and image-track check on uncalibrated field clips (no taps, so no 3-D).

Runs the app's learned detector on every frame, the app's RANSAC association on the result,
and the app's bounce split on the track. Writes one json per clip next to the clips, plus a
contact sheet of the frames with detections drawn, so a person can count the misses.

    python field_dets.py DIR      # every *.mp4 in DIR
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
from app.pipeline.tracking import YoloDetector                      # noqa: E402
from app.pipeline.trajectory import find_ball_trajectory           # noqa: E402
from app.pipeline.reconstruction import find_bounce_split          # noqa: E402

WEIGHTS = ROOT / "server" / "models" / "cricket_ball.pt"


def run(path: Path, det: YoloDetector) -> dict:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames, thumbs = [], []
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC)
        d = det.detect(f)
        frames.append(dict(i=i, t_ms=t, dets=d[:8]))
        h, w = f.shape[:2]
        s = 360 / w
        th = cv2.resize(f, (360, int(h * s)))
        for k, x in enumerate(d[:3]):
            cv2.circle(th, (int(x["x"] * s), int(x["y"] * s)), max(4, int(x["radius_px"] * s) + 3), (0, 255, 0) if k == 0 else (0, 200, 255), 1)
        cv2.putText(th, str(i), (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        thumbs.append(th)
        i += 1
    cap.release()
    diag = math.hypot(w, h)
    fit = find_ball_trajectory([(fr["t_ms"], fr["dets"]) for fr in frames], image_diagonal_px=diag, min_inliers=6)
    out = dict(clip=path.name, fps=fps, frames=len(frames), width=w, height=h,
               frames_with_det=sum(1 for fr in frames if fr["dets"]), per_frame=frames)
    if fit is None:
        out["track"] = None
    else:
        pts = [(p.t_ms, p.x_px, p.y_px, p.radius_px, p.confidence) for p in fit.points]
        out["track"] = dict(n=len(pts), rms_px=fit.rms_px, inliers=fit.inliers, points=pts)
        sp = find_bounce_split([(p[0] / 1000, p[1], p[2], p[3], p[4]) for p in pts])
        out["bounce"] = None if sp is None else dict(k=sp[0], t_ms=sp[1] * 1000, u=sp[2], v=sp[3], before=sp[0], after=len(pts) - sp[0])
    # contact sheet, 10 per row
    rows = [np.hstack(thumbs[j:j + 10] + [np.zeros_like(thumbs[0])] * (10 - len(thumbs[j:j + 10]))) for j in range(0, len(thumbs), 10)]
    cv2.imwrite(str(path.with_name(path.stem + "-dets.jpg")), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 70])
    return out


def main():
    d = Path(sys.argv[1])
    det = YoloDetector(str(WEIGHTS))
    for p in sorted(d.glob("*.mp4")):
        r = run(p, det)
        p.with_name(p.stem + "-dets.json").write_text(json.dumps(r, default=float))
        tr = r["track"]
        print(p.name, f"frames {r['frames']} with a detection {r['frames_with_det']}",
              "no track" if tr is None else f"track {tr['n']} pts rms {tr['rms_px']:.1f}px bounce {r.get('bounce')}", flush=True)


if __name__ == "__main__":
    main()
