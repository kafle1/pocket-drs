"""Extract full-res frames from the APPROVED workingresult.mp4 so we can study
the overlay design the user liked, and reproduce it."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WR = ROOT / "workingresult.mp4"
OUT = ROOT / "dump/validation/test3"

cap = cv2.VideoCapture(str(WR))
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print("workingresult frames", n, "WxH", W, H)

idxs = [int(round(t)) for t in np.linspace(0, max(0, n - 1), 6)]
cells = []
for f in idxs:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        continue
    cv2.putText(fr, f"WR f{f}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
    cells.append(fr)
cap.release()
if cells:
    strip = np.hstack([cv2.resize(c, (W // 2, H // 2)) for c in cells])
    cv2.imwrite(str(OUT / "evidence_working.png"), strip)
    print("wrote evidence_working.png", strip.shape)
