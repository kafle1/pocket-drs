"""Evidence: (a) tight high-res crops of each detection on its real frame,
(b) full frames with the whole detected path drawn. Verifies tracking is on
the actual ball, not clutter."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "test3.mp4"
RES = json.loads((ROOT / "dump/validation/test3/result.json").read_text())
OUT = ROOT / "dump/validation/test3"

fps = float(RES["video"]["fps_est"])
ip = RES["track"]["image_points"]
pi = RES["track"].get("post_impact_points") or []
CROP = 110


def crops(points, color, tag, ncol=5, cell=300):
    cap = cv2.VideoCapture(str(VIDEO))
    cells = []
    for k, p in enumerate(points):
        f = int(round(p["t_ms"] / 1000.0 * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            continue
        u, v = int(p["u"]), int(p["v"])
        x0, y0 = max(0, u - CROP), max(0, v - CROP)
        x1, y1 = min(frame.shape[1], u + CROP), min(frame.shape[0], v + CROP)
        c = frame[y0:y1, x0:x1].copy()
        r = int(round(p.get("radius_px", 8)))
        cv2.circle(c, (u - x0, v - y0), r, color, 2, cv2.LINE_AA)
        c = cv2.resize(c, (cell, cell))
        cv2.putText(c, f"{tag}{k} t{p['t_ms']} r{r} c{p.get('confidence',0):.2f}",
                    (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        cells.append(c)
    cap.release()
    if not cells:
        return None
    rows = []
    for i in range(0, len(cells), ncol):
        row = cells[i:i + ncol]
        while len(row) < ncol:
            row.append(np.zeros((cell, cell, 3), np.uint8))
        rows.append(np.hstack(row))
    return np.vstack(rows)


def full_frames(idxs):
    """Full raw frames with the entire tracked(red)+post-impact(green) path drawn."""
    cap = cv2.VideoCapture(str(VIDEO))
    track = [(int(p["u"]), int(p["v"])) for p in ip]
    post = [(int(p["u"]), int(p["v"])) for p in pi]
    outs = []
    for f in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            continue
        for i in range(1, len(track)):
            cv2.line(frame, track[i - 1], track[i], (60, 60, 255), 3, cv2.LINE_AA)
        for u, v in track:
            cv2.circle(frame, (u, v), 6, (0, 255, 255), -1, cv2.LINE_AA)
        for i in range(1, len(post)):
            cv2.line(frame, post[i - 1], post[i], (60, 220, 60), 3, cv2.LINE_AA)
        for u, v in post:
            cv2.circle(frame, (u, v), 6, (60, 220, 60), -1, cv2.LINE_AA)
        cv2.putText(frame, f"frame {f}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
        outs.append(cv2.resize(frame, (frame.shape[1] // 2, frame.shape[0] // 2)))
    cap.release()
    return np.hstack(outs) if outs else None


t = crops(ip, (60, 60, 255), "T")
if t is not None:
    cv2.imwrite(str(OUT / "evidence_tracked.png"), t)
    print("wrote evidence_tracked.png", t.shape)
p = crops(pi, (60, 220, 60), "P")
if p is not None:
    cv2.imwrite(str(OUT / "evidence_postimpact.png"), p)
    print("wrote evidence_postimpact.png", p.shape)

# full frames spanning the flight (t459..1632 -> frames ~28..98)
ff = full_frames([35, 55, 75, 95])
if ff is not None:
    cv2.imwrite(str(OUT / "evidence_fullpath.png"), ff)
    print("wrote evidence_fullpath.png", ff.shape)
