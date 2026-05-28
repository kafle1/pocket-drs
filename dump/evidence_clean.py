"""Clean consecutive frames (no overlay), upper flight region cropped & enlarged,
so we can locate the REAL ball by eye and establish ground truth."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
OUT = ROOT / "dump/validation/test3"

cap = cv2.VideoCapture(str(VIDEO))
fps = cap.get(cv2.CAP_PROP_FPS)
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print("fps", fps, "WxH", W, H)

# flight spans t459..1632ms -> frames ~28..98 at 60fps. Sample every 4 frames.
frames = list(range(28, 100, 4))
cells = []
for f in frames:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        continue
    c = fr.copy()
    cv2.putText(c, f"f{f} t{int(f/fps*1000)}", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
    cells.append(cv2.resize(c, (W // 3, H // 3)))
cap.release()

ncol = 6
rows = []
cw, ch = W // 3, H // 3
for i in range(0, len(cells), ncol):
    row = cells[i:i + ncol]
    while len(row) < ncol:
        row.append(np.zeros((ch, cw, 3), np.uint8))
    rows.append(np.hstack(row))
grid = np.vstack(rows)
cv2.imwrite(str(OUT / "evidence_clean.png"), grid)
print("wrote evidence_clean.png", grid.shape)
