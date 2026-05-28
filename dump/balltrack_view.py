"""View the independent balltrack.json: bigger per-frame crops (chosen ball only)
+ the connected trajectory drawn on a single full frame."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
OUT = ROOT / "dump/validation/test3"
track = json.loads((OUT / "balltrack.json").read_text())
fps = 60.0

cap = cv2.VideoCapture(str(VIDEO))
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

# Strip 1: every chosen frame, W/3, red circle on chosen ball.
cells = []
for p in track:
    cap.set(cv2.CAP_PROP_POS_FRAMES, p["f"])
    ok, fr = cap.read()
    if not ok:
        continue
    cv2.circle(fr, (int(p["u"]), int(p["v"])), int(max(p["r"], 10)), (60, 60, 255), 3, cv2.LINE_AA)
    c = cv2.resize(fr, (W // 3, H // 3))
    cv2.putText(c, f"f{p['f']}", (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cells.append(c)
ncol = 7
cw, ch = W // 3, H // 3
rows = []
for i in range(0, len(cells), ncol):
    row = cells[i:i + ncol]
    while len(row) < ncol:
        row.append(np.zeros((ch, cw, 3), np.uint8))
    rows.append(np.hstack(row))
cv2.imwrite(str(OUT / "balltrack_chosen.png"), np.vstack(rows))

# Composite: trajectory polyline on the last flight frame.
cap.set(cv2.CAP_PROP_POS_FRAMES, track[-1]["f"])
ok, base = cap.read()
if ok:
    poly = [(int(p["u"]), int(p["v"])) for p in track]
    for i in range(1, len(poly)):
        cv2.line(base, poly[i-1], poly[i], (60, 60, 255), 3, cv2.LINE_AA)
    for p in poly:
        cv2.circle(base, p, 5, (0, 255, 255), -1, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "balltrack_poly.png"), base)
cap.release()
print("wrote balltrack_chosen.png + balltrack_poly.png", len(track), "pts")
