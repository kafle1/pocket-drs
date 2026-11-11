from __future__ import annotations

import cv2
import numpy as np


MAX_SIDE_PX = 1920     # 4K frames add nothing the tracker uses and would need 25 MB each
MAX_GRABS = 5000       # 20 s of 240 fps video; frames skipped by the sample gap still cost a decode each
MIN_FPS = 27.0         # the frame-rate checks covered 30 a second and up, so allow a little under for 29.97 jitter
PHONE_ASPECTS = (16 / 9, 4 / 3)


class VideoDecodeError(RuntimeError):
    pass


class ClipRefused(ValueError):
    """The clip itself can't give a call; the message says why in the user's words."""


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
    fps = (len(times) - 1) * 1000.0 / (times[-1] - times[0]) if len(times) > 2 and times[-1] > times[0] else 0.0
    if fps < MIN_FPS <= sample_fps:
        raise ClipRefused(f"This clip has about {fps:.0f} frames a second, too few to follow the ball. "
                          "Film at 30 frames a second or more; 60 is best.")
    h, w = frames[0].shape[:2]
    # a phone films 16:9 or 4:3; any other shape was cropped, which moves the lens centre the calibration assumes
    if min(abs(max(w, h) / min(w, h) / a - 1) for a in PHONE_ASPECTS) > 0.02:
        warnings.append(f"the picture is {w} x {h}, so it was cropped or edited; use the video straight from "
                        "the camera for a surer call")
    # most phone cameras default to 30 a second, which sees a fast ball in half as many places
    if len(times) > 2 and float(np.median(np.diff(times))) > 25:
        fps = 1000 / float(np.median(np.diff(times)))
        warnings.append(f"filmed at about {fps:.0f} frames a second; set the camera to 60 frames a second "
                        "for a surer call")
    if cut:
        warnings.append(f"only the first {(times[-1] - times[0]) / 1000:.1f} s were checked; trim the clip to just the delivery")
    return frames, times, scale, cut
