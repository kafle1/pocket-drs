"""Side-by-side frame strip: workingresult.mp4 vs current test3_tracked.mp4."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs")
WORKING = ROOT / "workingresult.mp4"
CUR = ROOT / "dump/validation/test3/test3_tracked.mp4"
OUT = ROOT / "dump/validation/test3/compare.png"


def sample(path: Path, n: int = 5):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"{path.name}: fps={fps} frames={tot} dur={tot/fps:.2f}s")
    idxs = [int(i * (tot - 1) / (n - 1)) for i in range(n)]
    out = []
    for i, f in enumerate(idxs):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok: continue
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 36), (0, 0, 0), -1)
        cv2.putText(frame, f"{path.stem} f={f} t={int(f/fps*1000)}ms", (8, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        out.append(frame)
    cap.release()
    return out


w = sample(WORKING)
c = sample(CUR)
N = min(len(w), len(c))

# stack each row: working | current
rows = []
for i in range(N):
    a = w[i]
    b = c[i]
    h = min(a.shape[0], b.shape[0])
    a = cv2.resize(a, (int(a.shape[1] * h / a.shape[0]), h))
    b = cv2.resize(b, (int(b.shape[1] * h / b.shape[0]), h))
    row = np.hstack([a, b])
    rows.append(row)

# stack all rows
rw = max(r.shape[1] for r in rows)
for i, r in enumerate(rows):
    if r.shape[1] != rw:
        pad = np.zeros((r.shape[0], rw - r.shape[1], 3), dtype=np.uint8)
        rows[i] = np.hstack([r, pad])

grid = np.vstack(rows)
# resize down
H_t, W_t = grid.shape[:2]
max_w = 1100
if W_t > max_w:
    s = max_w / W_t
    grid = cv2.resize(grid, (max_w, int(H_t * s)))
cv2.imwrite(str(OUT), grid)
print("wrote:", OUT, grid.shape)
