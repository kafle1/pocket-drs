"""Tile EVERY frame of the approved workingresult.mp4 (what the user wants) and
of my test3_tracked.mp4 (what I produced), so the overlay behaviour can be
compared frame-by-frame."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dump/validation/test3"


def grid_all(video, label, ncol=6, scale=4):
    cap = cv2.VideoCapture(str(video))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cw, ch = W // scale, H // scale
    cells = []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        c = cv2.resize(fr, (cw, ch))
        cv2.putText(c, f"{label}{i}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cells.append(c)
        i += 1
    cap.release()
    if not cells:
        return None, 0
    rows = []
    for k in range(0, len(cells), ncol):
        row = cells[k:k + ncol]
        while len(row) < ncol:
            row.append(np.zeros((ch, cw, 3), np.uint8))
        rows.append(np.hstack(row))
    return np.vstack(rows), len(cells)


wr, nwr = grid_all(ROOT / "workingresult.mp4", "WR")
if wr is not None:
    cv2.imwrite(str(OUT / "allframes_working.png"), wr)
    print(f"workingresult: {nwr} frames -> allframes_working.png {wr.shape}")

mine, nmine = grid_all(ROOT / "dump/validation/test3/test3_tracked.mp4", "ME")
if mine is not None:
    cv2.imwrite(str(OUT / "allframes_mine.png"), mine)
    print(f"mine: {nmine} frames -> allframes_mine.png {mine.shape}")
