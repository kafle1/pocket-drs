from __future__ import annotations

import cv2
import numpy as np


MAX_SIDE_PX = 1920     # 4K frames add nothing the tracker uses and would need 25 MB each
MAX_GRABS = 5000       # 20 s of 240 fps video; frames skipped by the sample gap still cost a decode each
SAMPLE_FPS = 60.0      # real-time frames a second kept; the checks found 60 as good as 120 and 240
MAX_FRAMES = 300       # 5 s at 60 a second, longer than any delivery
MIN_FPS = 27.0         # the frame-rate checks covered 30 a second and up, so allow a little under for 29.97 jitter
PHONE_ASPECTS = (16 / 9, 4 / 3)
# mean grey level, 0 to 255, below which the ball can't be told from the ground; not tuned on clips
MIN_BRIGHTNESS = 35.0


class NoCall(Exception):
    """The clip or the marks can't give a call: a code, and the message and fix in the user's words."""

    def __init__(self, code: str, message: str, fix: str):
        super().__init__(message)
        self.code, self.message, self.fix = code, message, fix


class VideoDecodeError(RuntimeError):
    pass


def read_frames(path: str, *, start_ms: int, end_ms: int, frame_ms: int | None, capture_fps: float | None,
                warnings: list[str]) -> tuple[list[np.ndarray], list[float], int, float, bool]:
    """Frames in [start_ms, end_ms] of the video's timeline, at most SAMPLE_FPS a second of real time.

    Returns the frames, their real times in ms (the container's timestamps, slowed back down for a
    slow-motion file filmed at capture_fps), the index of the frame nearest frame_ms (the first when
    None), the scale they were shrunk by to fit MAX_SIDE_PX, and whether MAX_FRAMES cut the part short."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoDecodeError("Could not open the video")
    # pin auto-rotation explicitly so a phone clip decodes upright, matching what the app showed the user
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    rate = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    # a slow-motion file is stamped at its playback rate, so its timestamps run slow by this much
    stretch = rate / capture_fps if capture_fps and rate > 0 and capture_fps > 1.5 * rate else 1.0
    gap = 900.0 / SAMPLE_FPS / stretch     # in video time, 10% under the period so rounding never drops a frame
    frames: list[np.ndarray] = []
    stamps: list[float] = []
    scale, cut, stuck, grabs, last = 1.0, False, 0, 0, -1.0
    try:
        if start_ms > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, start_ms)
        for grabs in range(1, MAX_GRABS + 1):
            if not cap.grab():
                break
            t = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            stuck += t <= last
            last = max(last, t)
            if t > end_ms:
                break
            if t < start_ms or (stamps and t - stamps[-1] < gap):
                continue
            if len(frames) == MAX_FRAMES:
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
            stamps.append(t)
        else:
            cut = True
    finally:
        cap.release()
    if stuck > grabs / 2:
        raise NoCall("clip_timing", "This video's frames carry no usable times, so the ball's speed can't be measured.",
                     "Use the video straight from the phone's camera app, not one saved from a chat or an editor.")
    if not frames:
        raise VideoDecodeError("No frames in the selected part of the video")
    ref = 0 if frame_ms is None else int(np.argmin(np.abs(np.array(stamps) - frame_ms)))
    times = [stamps[0] + (t - stamps[0]) * stretch for t in stamps]
    fps = (len(times) - 1) * 1000.0 / (times[-1] - times[0]) if len(times) > 2 and times[-1] > times[0] else 0.0
    if fps < MIN_FPS:
        raise NoCall("frame_rate_too_low", f"This clip has about {fps:.0f} frames a second, too few to follow the ball.",
                     "Film at 30 frames a second or more; 60 is best.")
    if float(np.median([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).mean() for f in frames[::10]])) < MIN_BRIGHTNESS:
        raise NoCall("too_dark", "The clip is too dark to see the ball.", "Film in daylight or under bright lights.")
    h, w = frames[0].shape[:2]
    # a phone films 16:9 or 4:3; any other shape was cropped, which moves the lens centre the calibration assumes
    if min(abs(max(w, h) / min(w, h) / a - 1) for a in PHONE_ASPECTS) > 0.02:
        warnings.append(f"the picture is {w} x {h}, so it was cropped or edited; use the video straight from "
                        "the camera for a surer call")
    # most phone cameras default to 30 a second, which sees a fast ball in half as many places
    if len(times) > 2 and float(np.median(np.diff(times))) > 25:
        warnings.append(f"filmed at about {1000 / float(np.median(np.diff(times))):.0f} frames a second; set the "
                        "camera to 60 frames a second for a surer call")
    if cut:
        warnings.append(f"only the first {(times[-1] - times[0]) / 1000:.1f} s were checked; trim the clip to just the delivery")
    return frames, times, ref, scale, cut
