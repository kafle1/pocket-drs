"""Objective ball-path evidence via frame differencing. Moving objects (ball,
bowler) light up; static net/pitch stay dark. Overlay the DETECTED track to see
whether it lies on the real moving-ball streak."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
RES = json.loads((ROOT / "dump/validation/test3/result.json").read_text())
OUT = ROOT / "dump/validation/test3"

cap = cv2.VideoCapture(str(VIDEO))
fps = cap.get(cv2.CAP_PROP_FPS)
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

F0, F1 = 26, 100
prev = None
accum = np.zeros((H, W), np.float32)
base = None
for f in range(F0, F1):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        break
    if base is None:
        base = fr.copy()
    g = cv2.GaussianBlur(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
    if prev is not None:
        d = np.abs(g - prev)
        accum = np.maximum(accum, d)
    prev = g
cap.release()

acc = np.clip(accum / max(accum.max(), 1) * 255, 0, 255).astype(np.uint8)
heat = cv2.applyColorMap(acc, cv2.COLORMAP_JET)
vis = cv2.addWeighted(base, 0.45, heat, 0.75, 0)

# overlay detected track (white) + post-impact (cyan)
ip = RES["track"]["image_points"]
pi = RES["track"].get("post_impact_points") or []
tr = [(int(p["u"]), int(p["v"])) for p in ip]
po = [(int(p["u"]), int(p["v"])) for p in pi]
for i in range(1, len(tr)):
    cv2.line(vis, tr[i - 1], tr[i], (255, 255, 255), 2, cv2.LINE_AA)
for k, (u, v) in enumerate(tr):
    cv2.circle(vis, (u, v), 7, (255, 255, 255), 2, cv2.LINE_AA)
for i in range(1, len(po)):
    cv2.line(vis, po[i - 1], po[i], (255, 255, 0), 2, cv2.LINE_AA)
for u, v in po:
    cv2.circle(vis, (u, v), 7, (255, 255, 0), 2, cv2.LINE_AA)
cv2.putText(vis, "JET=motion(ball+bowler)  WHITE=detected track  CYAN=post-impact",
            (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)

cv2.imwrite(str(OUT / "evidence_motion.png"), cv2.resize(vis, (W // 2, H // 2)))
print("wrote evidence_motion.png")
