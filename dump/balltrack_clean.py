"""Filter YOLO detections to high-confidence (drops the stationary FP), render
each kept frame LARGE to verify on-ball, and draw the clean trajectory."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
OUT = ROOT / "dump/validation/test3"
det = json.loads((OUT / "balltrack_yolo.json").read_text())

CONF = 0.45
kept = [p for p in det if p["conf"] >= CONF]
# Drop residual stationary FP cluster near (471, 987).
kept = [p for p in kept if not (abs(p["u"] - 471) < 18 and abs(p["v"] - 987) < 18)]
kept.sort(key=lambda p: p["f"])
print("kept", len(kept), "of", len(det), "frames")
for p in kept:
    print(p["f"], p["u"], p["v"], p["conf"])

cap = cv2.VideoCapture(str(VIDEO))
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

cells = []
for p in kept:
    cap.set(cv2.CAP_PROP_POS_FRAMES, p["f"])
    ok, fr = cap.read()
    if not ok:
        continue
    cv2.circle(fr, (int(p["u"]), int(p["v"])), int(max(p["r"], 12)), (60, 60, 255), 3, cv2.LINE_AA)
    c = cv2.resize(fr, (W // 2, H // 2))
    cv2.putText(c, f"f{p['f']} c{p['conf']:.2f}", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cells.append(c)
ncol = 5
cw, ch = W // 2, H // 2
rows = []
for i in range(0, len(cells), ncol):
    row = cells[i:i + ncol]
    while len(row) < ncol:
        row.append(np.zeros((ch, cw, 3), np.uint8))
    rows.append(np.hstack(row))
cv2.imwrite(str(OUT / "balltrack_clean.png"), np.vstack(rows))

cap.set(cv2.CAP_PROP_POS_FRAMES, kept[-1]["f"])
ok, base = cap.read()
if ok:
    poly = [(int(p["u"]), int(p["v"])) for p in kept]
    for i in range(1, len(poly)):
        cv2.line(base, poly[i-1], poly[i], (60, 60, 255), 3, cv2.LINE_AA)
    for q in poly:
        cv2.circle(base, q, 6, (0, 255, 255), -1, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "balltrack_clean_poly.png"), base)
cap.release()
(OUT / "balltrack_clean.json").write_text(json.dumps(kept, indent=1))
print("wrote balltrack_clean.png + _poly.png + .json")
