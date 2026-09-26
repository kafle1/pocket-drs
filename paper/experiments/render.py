"""Render a synthetic delivery to video so the full pipeline, detector included, can be run
on footage whose ground truth is known. Flat colours and a clean background: this exercises
the geometry end to end, not the detector's robustness to clutter, which the real clips do."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from synth import Truth, Camera, CREASE_X
from app.pipeline.calibration import (CameraPose, STUMP_HEIGHT_M, STUMP_LATERAL_DX_M, STUMP_OUTER_HALF_M,
                                      PITCH_LENGTH_M, PITCH_WIDTH_M)
from app.pipeline.reconstruction import BALL_RADIUS_M

BAIL_Z = STUMP_HEIGHT_M + 0.012


def _px(pose: CameraPose, p) -> tuple[int, int] | None:
    q = pose.project_one(*p)
    return None if q is None else (int(round(q[0])), int(round(q[1])))


def render(truth: Truth, cam: Camera, path: Path, *, fps: float, ball_bgr=(40, 40, 220)) -> dict:
    """Write the clip and return the calibration block the app would send."""
    pose = cam.pose()
    W, H = cam.width, cam.height
    st = truth.states
    dt_state = st[1, 0] - st[0, 0]
    t_end = float(st[np.argmax(st[:, 1] <= CREASE_X), 0])      # the pad intercepts the ball at the crease
    times = np.arange(0.0, t_end + 0.4, 1.0 / fps)             # a few frames after impact, ball gone
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer at {path}")

    hw = PITCH_WIDTH_M / 2
    pitch = [(0.0, -hw, 0.0), (0.0, hw, 0.0), (PITCH_LENGTH_M, hw, 0.0), (PITCH_LENGTH_M, -hw, 0.0)]
    pitch_px = [_px(pose, p) for p in pitch]
    creases = [((x, -hw, 0.0), (x, hw, 0.0)) for x in (1.22, PITCH_LENGTH_M - 1.22)]
    for tt in times:
        frame = np.full((H, W, 3), (50, 100, 60), dtype=np.uint8)
        if all(pitch_px):
            cv2.fillPoly(frame, [np.array(pitch_px, dtype=np.int32)], (70, 110, 160))
        for a, b in creases:
            pa, pb = _px(pose, a), _px(pose, b)
            if pa and pb:
                cv2.line(frame, pa, pb, (240, 240, 240), 2)
        for x_end, col, lw in ((0.0, (220, 220, 230), 4), (PITCH_LENGTH_M, (50, 200, 240), 3)):
            for dy in (-STUMP_LATERAL_DX_M, 0.0, STUMP_LATERAL_DX_M):
                base, top = _px(pose, (x_end, dy, 0.0)), _px(pose, (x_end, dy, STUMP_HEIGHT_M))
                if base and top:
                    cv2.line(frame, base, top, col, lw, cv2.LINE_AA)
            for da, db in ((-STUMP_LATERAL_DX_M, 0.0), (0.0, STUMP_LATERAL_DX_M)):
                a, b = _px(pose, (x_end, da, BAIL_Z)), _px(pose, (x_end, db, BAIL_Z))
                if a and b:
                    cv2.line(frame, a, b, col, max(2, lw - 1), cv2.LINE_AA)
        i = int(round((tt - st[0, 0]) / dt_state))
        if 0 <= i < len(st) and tt <= t_end:
            p = st[i, 1:4]
            q = pose.project_one(*p)
            if q is not None and q[2] > 0.3:
                r = max(2.0, pose.fx * BALL_RADIUS_M / q[2])
                # motion smear over the exposure: half a frame interval of travel
                j = min(len(st) - 1, i + int(round(0.5 / fps / dt_state)))
                q2 = pose.project_one(*st[j, 1:4])
                if q2 is not None:
                    cv2.line(frame, (int(round(q[0])), int(round(q[1]))), (int(round(q2[0])), int(round(q2[1]))),
                             ball_bgr, int(round(2 * r)), cv2.LINE_AA)
                cv2.circle(frame, (int(round(q[0])), int(round(q[1]))), int(round(r)), ball_bgr, -1, cv2.LINE_AA)
        writer.write(frame)
    writer.release()

    w, h = STUMP_OUTER_HALF_M, STUMP_HEIGHT_M
    side = [(-w, h), (w, h), (w, 0.0), (-w, 0.0)]
    marks = [(0.0, dy, dz) for dy, dz in side] + [(PITCH_LENGTH_M, dy, dz) for dy, dz in side]
    projected = [pose.project_one(*m) for m in marks]
    if any(q is None for q in projected):
        raise ValueError("a calibration mark is behind the camera for this placement")
    return {
        "pitch_dimensions_m": {"width": PITCH_WIDTH_M, "length": PITCH_LENGTH_M},
        "stump_quads_px": [{"x": q[0], "y": q[1]} for q in projected],
        "n_frames": len(times),
    }
