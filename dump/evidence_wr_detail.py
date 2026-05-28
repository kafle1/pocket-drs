"""Full-res workingresult frames to read the exact overlay style the user wants."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dump/validation/test3"
cap = cv2.VideoCapture(str(ROOT / "workingresult.mp4"))
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
cells = []
for f in [8, 15, 22, 29]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(f, n - 1))
    ok, fr = cap.read()
    if ok:
        cv2.putText(fr, f"WR{f}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
        cells.append(fr)
cap.release()
if cells:
    strip = np.hstack([cv2.resize(c, (c.shape[1] * 2 // 3, c.shape[0] * 2 // 3)) for c in cells])
    cv2.imwrite(str(OUT / "evidence_wr_detail.png"), strip)
    print("wrote", strip.shape)
