"""Super-zoom each detection: tiny window, big display, so we can settle
whether the WHITE ball is actually centered in the detector circle."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
RES = json.loads((ROOT / "dump/validation/test3/result.json").read_text())
OUT = ROOT / "dump/validation/test3"

fps = float(RES["video"]["fps_est"])
ip = RES["track"]["image_points"]
WIN = 55          # half-window (small -> big zoom)
CELL = 240

cap = cv2.VideoCapture(str(VIDEO))
cells = []
for k, p in enumerate(ip):
    f = int(round(p["t_ms"] / 1000.0 * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        continue
    u, v = int(p["u"]), int(p["v"])
    x0, y0 = max(0, u - WIN), max(0, v - WIN)
    x1, y1 = min(fr.shape[1], u + WIN), min(fr.shape[0], v + WIN)
    c = fr[y0:y1, x0:x1].copy()
    c = cv2.resize(c, (CELL, CELL), interpolation=cv2.INTER_NEAREST)
    # crosshair at detection center
    cx = int((u - x0) / max(1, (x1 - x0)) * CELL)
    cy = int((v - y0) / max(1, (y1 - y0)) * CELL)
    cv2.drawMarker(c, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 30, 1, cv2.LINE_AA)
    cv2.putText(c, f"T{k} t{p['t_ms']} c{p.get('confidence',0):.2f}", (4, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    cells.append(c)
cap.release()

ncol = 7
rows = []
for i in range(0, len(cells), ncol):
    row = cells[i:i + ncol]
    while len(row) < ncol:
        row.append(np.zeros((CELL, CELL, 3), np.uint8))
    rows.append(np.hstack(row))
cv2.imwrite(str(OUT / "evidence_zoom.png"), np.vstack(rows))
print("wrote evidence_zoom.png", len(cells), "cells")
