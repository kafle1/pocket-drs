"""Verify the post-bounce detections: zoom each post_impact point on its real
frame, and draw the full tracked(red)+post_impact(green) path on full frames."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
RES = json.loads((ROOT / "dump/validation/test3/result.json").read_text())
OUT = ROOT / "dump/validation/test3"

fps = float(RES["video"]["fps_est"])
tr = RES["track"]["image_points"]
pi = RES["track"].get("post_impact_points") or []
print("tracked", len(tr), "post_impact", len(pi))

# Zoom crops of each post_impact detection.
cap = cv2.VideoCapture(str(VIDEO))
WIN, CELL = 60, 240
cells = []
for k, p in enumerate(pi):
    f = int(round(p["t_ms"] / 1000.0 * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        continue
    u, v = int(p["u"]), int(p["v"])
    x0, y0 = max(0, u - WIN), max(0, v - WIN)
    x1, y1 = min(fr.shape[1], u + WIN), min(fr.shape[0], v + WIN)
    c = cv2.resize(fr[y0:y1, x0:x1].copy(), (CELL, CELL), interpolation=cv2.INTER_NEAREST)
    cx = int((u - x0) / max(1, x1 - x0) * CELL)
    cy = int((v - y0) / max(1, y1 - y0) * CELL)
    cv2.drawMarker(c, (cx, cy), (60, 255, 60), cv2.MARKER_CROSS, 30, 1, cv2.LINE_AA)
    cv2.putText(c, f"P{k} t{p['t_ms']} c{p.get('confidence',0):.2f}", (4, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    cells.append(c)
cap.release()
if cells:
    ncol = 7
    rows = []
    for i in range(0, len(cells), ncol):
        row = cells[i:i + ncol]
        while len(row) < ncol:
            row.append(np.zeros((CELL, CELL, 3), np.uint8))
        rows.append(np.hstack(row))
    cv2.imwrite(str(OUT / "evidence_postbounce_zoom.png"), np.vstack(rows))
    print("wrote evidence_postbounce_zoom.png")

# Full frames with tracked(red)+post(green) drawn.
cap = cv2.VideoCapture(str(VIDEO))
trxy = [(int(p["u"]), int(p["v"])) for p in tr]
pixy = [(int(p["u"]), int(p["v"])) for p in pi]
shots = []
for f in [55, 75, 95, 100]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        continue
    for i in range(1, len(trxy)):
        cv2.line(fr, trxy[i-1], trxy[i], (60, 60, 255), 3, cv2.LINE_AA)
    for i in range(1, len(pixy)):
        cv2.line(fr, pixy[i-1], pixy[i], (60, 220, 60), 3, cv2.LINE_AA)
    for u, v in pixy:
        cv2.circle(fr, (u, v), 6, (60, 220, 60), -1, cv2.LINE_AA)
    cv2.putText(fr, f"f{f}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
    shots.append(cv2.resize(fr, (fr.shape[1] // 2, fr.shape[0] // 2)))
cap.release()
if shots:
    cv2.imwrite(str(OUT / "evidence_postbounce_full.png"), np.hstack(shots))
    print("wrote evidence_postbounce_full.png")
