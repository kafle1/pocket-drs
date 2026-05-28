"""Pull post-bounce frames straight from the rendered video to confirm the
red line + gold dot sit on the ball through and after the bounce."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VID = ROOT / "dump/validation/test3/test3_tracked.mp4"
OUT = ROOT / "dump/validation/test3"

cap = cv2.VideoCapture(str(VID))
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
# back half = around/after the bounce
picks = [int(round(t)) for t in np.linspace(n * 0.45, n - 1, 8)]
cells = []
for f in picks:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if ok:
        c = cv2.resize(fr, (fr.shape[1] // 2, fr.shape[0] // 2))
        cv2.putText(c, f"f{f}", (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cells.append(c)
cap.release()
cv2.imwrite(str(OUT / "evidence_render_postbounce.png"), np.hstack(cells))
print("wrote", len(cells), "frames")
