"""Run the cricket-ball YOLO on EVERY flight frame, take the best box per frame,
render it, and montage so the detector's per-frame output can be verified."""
import json
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
OUT = ROOT / "dump/validation/test3"
WEIGHTS = ROOT / "server/models/cricket_ball.pt"
F0, F1 = 26, 102

model = YOLO(str(WEIGHTS))
cap = cv2.VideoCapture(str(VIDEO))
fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

rows_track = []
cells = []
for f in range(F0, F1):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        break
    res = model(fr, conf=0.05, imgsz=1280, verbose=False)[0]
    best = None
    for b in res.boxes:
        x1, y1, x2, y2 = b.xyxy[0].tolist()
        conf = float(b.conf[0])
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        r = (x2 - x1 + y2 - y1) / 4
        if best is None or conf > best[0]:
            best = (conf, cx, cy, r)
    disp = fr.copy()
    if best:
        conf, cx, cy, r = best
        rows_track.append({"f": f, "t_ms": round(f / fps * 1000), "u": round(cx, 1),
                           "v": round(cy, 1), "r": round(r, 1), "conf": round(conf, 3)})
        col = (60, 60, 255) if conf >= 0.25 else (0, 200, 255)
        cv2.circle(disp, (int(cx), int(cy)), int(max(r, 10)), col, 3, cv2.LINE_AA)
        cv2.putText(disp, f"f{f} c{conf:.2f}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
    else:
        cv2.putText(disp, f"f{f} NONE", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
    cells.append(cv2.resize(disp, (W // 4, H // 4)))
cap.release()

(OUT / "balltrack_yolo.json").write_text(json.dumps(rows_track, indent=1))
print("yolo detections:", len(rows_track), "/", len(cells), "frames")

ncol = 10
cw, ch = W // 4, H // 4
grid = []
for i in range(0, len(cells), ncol):
    row = cells[i:i + ncol]
    while len(row) < ncol:
        row.append(np.zeros((ch, cw, 3), np.uint8))
    grid.append(np.hstack(row))
cv2.imwrite(str(OUT / "balltrack_yolo.png"), np.vstack(grid))
print("wrote balltrack_yolo.png")
