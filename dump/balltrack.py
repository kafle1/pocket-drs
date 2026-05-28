"""Independent ground-truth ball tracker for test3.mp4.

White ball + static-ish camera. Strategy: median-background subtraction (motion)
INTERSECT whiteness (bright, low-saturation) -> small round candidates per frame.
Then RANSAC a constant-acceleration image-space parabola over ALL candidates to
pick the inlier ball track. Dumps:
  - balltrack.json : per-frame chosen ball (f, t_ms, u, v, r) + inlier flags
  - balltrack_allframes.png : EVERY flight frame with candidates(yellow) + chosen(red)
so the track can be verified frame-by-frame.
"""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
OUT = ROOT / "dump/validation/test3"
F0, F1 = 26, 102   # flight window

cap = cv2.VideoCapture(str(VIDEO))
fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

frames = []
for f in range(F0, F1):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, fr = cap.read()
    if not ok:
        break
    frames.append((f, fr))
cap.release()
print(f"loaded {len(frames)} frames {W}x{H} @ {fps}fps")

# Median background (static scene) for motion subtraction.
stack = np.stack([fr for _, fr in frames[::2]], axis=0)
bg = np.median(stack, axis=0).astype(np.uint8)
bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY).astype(np.int16)


def candidates(fr):
    gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.int16)
    motion = cv2.threshold(np.abs(gray - bg_gray).astype(np.uint8), 22, 255, cv2.THRESH_BINARY)[1]
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    # whitish: bright value, low saturation
    white = cv2.inRange(hsv, (0, 0, 165), (180, 95, 255))
    mask = cv2.bitwise_and(motion, white)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 8 or a > 1200:
            continue
        (x, y), r = cv2.minEnclosingCircle(c)
        if r < 2 or r > 30:
            continue
        circ = a / (np.pi * r * r + 1e-6)   # 1.0 = perfect circle
        if circ < 0.30:
            continue
        out.append((float(x), float(y), float(r), float(a), float(circ)))
    return out


per_frame = []
for f, fr in frames:
    cands = candidates(fr)
    per_frame.append((f, f / fps * 1000.0, cands))

# RANSAC constant-accel parabola over (t, u) and (t, v) jointly.
pts = []  # (idx, t, u, v, r)
for i, (f, t, cands) in enumerate(per_frame):
    for (x, y, r, a, circ) in cands:
        pts.append((i, t, x, y, r))

best_inliers = []
rng = np.random.default_rng(0)
P = len(pts)
if P >= 6:
    for _ in range(4000):
        s = rng.choice(P, 3, replace=False)
        sample = [pts[i] for i in s]
        ts = np.array([p[1] for p in sample]) / 1000.0
        if len(set(np.round(ts, 4))) < 3:
            continue
        A = np.vstack([ts**2, ts, np.ones_like(ts)]).T
        try:
            cu = np.linalg.solve(A, np.array([p[2] for p in sample]))
            cv_ = np.linalg.solve(A, np.array([p[3] for p in sample]))
        except np.linalg.LinAlgError:
            continue
        inl = []
        for p in pts:
            tt = p[1] / 1000.0
            pu = cu[0] * tt * tt + cu[1] * tt + cu[2]
            pv = cv_[0] * tt * tt + cv_[1] * tt + cv_[2]
            if (pu - p[2]) ** 2 + (pv - p[3]) ** 2 < 30 ** 2:
                inl.append(p)
        # keep at most one (closest) inlier per frame index
        byf = {}
        for p in inl:
            d = (cu[0]*(p[1]/1000)**2+cu[1]*(p[1]/1000)+cu[2]-p[2])**2 + \
                (cv_[0]*(p[1]/1000)**2+cv_[1]*(p[1]/1000)+cv_[2]-p[3])**2
            if p[0] not in byf or d < byf[p[0]][1]:
                byf[p[0]] = (p, d)
        uniq = [v[0] for v in byf.values()]
        if len(uniq) > len(best_inliers):
            best_inliers = uniq

chosen = {p[0]: p for p in best_inliers}
print(f"candidates={P}  inlier-frames={len(chosen)} / {len(per_frame)}")

# Dump chosen track.
track = []
for i, (f, t, cands) in enumerate(per_frame):
    if i in chosen:
        _, tt, u, v, r = chosen[i]
        track.append({"f": f, "t_ms": round(tt), "u": round(u, 1), "v": round(v, 1), "r": round(r, 1)})
(OUT / "balltrack.json").write_text(json.dumps(track, indent=1))
print("wrote balltrack.json", len(track), "points")

# Render EVERY frame with all candidates (yellow) + chosen (red) for inspection.
cells = []
for i, (f, t, cands) in enumerate(frames and per_frame):
    fr = frames[i][1].copy()
    for (x, y, r, a, circ) in cands:
        cv2.circle(fr, (int(x), int(y)), int(max(r, 6)), (0, 220, 255), 2, cv2.LINE_AA)
    if i in chosen:
        _, tt, u, v, r = chosen[i]
        cv2.circle(fr, (int(u), int(v)), int(max(r, 8)), (60, 60, 255), 3, cv2.LINE_AA)
    cv2.putText(fr, f"f{f}", (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
    cells.append(cv2.resize(fr, (W // 4, H // 4)))

ncol = 10
cw, ch = W // 4, H // 4
rows = []
for i in range(0, len(cells), ncol):
    row = cells[i:i + ncol]
    while len(row) < ncol:
        row.append(np.zeros((ch, cw, 3), np.uint8))
    rows.append(np.hstack(row))
cv2.imwrite(str(OUT / "balltrack_allframes.png"), np.vstack(rows))
print("wrote balltrack_allframes.png")
