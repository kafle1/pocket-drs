"""Matched-time comparison: workingresult (top) vs my test3_tracked (bottom)."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dump/validation/test3"


def frames(video, n_pick):
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    picks = [int(round(t)) for t in np.linspace(0, max(0, n - 1), n_pick)]
    out = []
    for f in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, fr = cap.read()
        if ok:
            out.append(fr)
    cap.release()
    return out


N = 7
wr = frames(ROOT / "workingresult.mp4", N)
me = frames(ROOT / "dump/validation/test3/test3_tracked.mp4", N)
cw, ch = 200, 356
cols = []
for i in range(min(len(wr), len(me))):
    a = cv2.resize(wr[i], (cw, ch))
    b = cv2.resize(me[i], (cw, ch))
    cv2.putText(a, "WANT", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(b, "MINE", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cols.append(np.vstack([a, b]))
grid = np.hstack(cols)
cv2.imwrite(str(OUT / "evidence_sidebyside.png"), grid)
print("wrote evidence_sidebyside.png", grid.shape)
