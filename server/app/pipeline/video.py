from __future__ import annotations

import cv2
import numpy as np


MAX_SIDE_PX = 1920     # 4K frames add nothing the tracker uses and would need 25 MB each
MAX_GRABS = 5000       # 20 s of 240 fps video; frames skipped by the sample gap still cost a decode each


class VideoDecodeError(RuntimeError):
    pass


def read_frames(path: str, *, start_ms: int, end_ms: int, sample_fps: int, max_frames: int,
                warnings: list[str]) -> tuple[list[np.ndarray], list[int], float, bool]:
    """Frames in [start_ms, end_ms], at most sample_fps a second, stamped with the container's own
    timestamps, the scale they were shrunk by to fit MAX_SIDE_PX, and whether a frame cap cut the part
    short. The reported fps is never used: phones record at a variable frame rate."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoDecodeError("Could not open the video")
    # pin auto-rotation explicitly so a phone clip decodes upright, matching what the app showed the user
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    gap = 900.0 / sample_fps          # 10% under the sample period so millisecond rounding never drops a frame
    frames: list[np.ndarray] = []
    times: list[int] = []
    scale = 1.0
    cut = False
    try:
        if start_ms > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, start_ms)
        for _ in range(MAX_GRABS):
            if not cap.grab():
                break
            t = round(cap.get(cv2.CAP_PROP_POS_MSEC))
            if t > end_ms:
                break
            if t < start_ms or (times and t - times[-1] < gap):
                continue
            if len(frames) == max_frames:
                cut = True
                break
            ok, frame = cap.retrieve()
            if not ok:
                break
            if not frames:
                scale = min(1.0, MAX_SIDE_PX / max(frame.shape[:2]))
            if scale < 1.0:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            frames.append(frame)
            times.append(t)
        else:
            cut = True
    finally:
        cap.release()
    if not frames:
        raise VideoDecodeError("No frames in the selected part of the video")
    if cut:
        warnings.append(f"only the first {(times[-1] - times[0]) / 1000:.1f} s were checked; trim the clip to just the delivery")
    return frames, times, scale, cut
