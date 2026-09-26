from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, Iterable

import cv2
import numpy as np

_log = logging.getLogger("pocket_drs.pipeline")

# two decoded frames closer than this in time are one frame shown twice (holds up to ~1000 fps)
_SAME_FRAME_MS = 0.5
# start decoding this far before the first requested time, so a seek that snaps to a keyframe
# or lands a little late still starts before it
_SEEK_LEAD_MS = 1000.0


@dataclass(frozen=True)
class VideoMeta:
    fps: float
    frame_count: int
    duration_ms: int


class VideoDecodeError(RuntimeError):
    pass


def pick_frames(stream: Iterable[tuple], requests_ms: list[float], fps: float, origin_ms: float = 0.0,
                progress: Callable[[float], None] | None = None) -> tuple[list[tuple[float, object]], list[str]]:
    """The decoded frame nearest each requested time, judged by the frame's own timestamp.

    stream yields (pts_ms, nominal_ms, payload) in decode order: pts_ms is the container's
    presentation time (0 or None when missing), nominal_ms the frame index over the reported
    rate. Requests are ascending, in ms from the first frame. Returns ([(label_ms, payload)],
    notes). Each frame comes back at most once, labelled with its timestamp minus origin_ms, or
    with the requested time when it had no usable timestamp (the old behaviour). Frames whose
    timestamp repeats or goes backwards are dropped."""
    period = 1000.0 / fps
    n = len(requests_ms)
    picks: list[tuple[float, object]] = []
    n_fallback = n_dup = n_back = 0
    last_valid = prev = last_id = None
    ri, fid, told = 0, -1, 0

    def take(frame, r):
        nonlocal last_id, n_fallback
        c, payload, valid, i = frame
        label = c if valid else r
        if i == last_id or (picks and label <= picks[-1][0]):
            return
        last_id = i
        n_fallback += not valid
        picks.append((label, payload))

    for pts, nominal, payload in stream:
        fid += 1
        # OpenCV reports a missing timestamp as 0, which only the clip's first frame can really have
        valid = pts is not None and math.isfinite(pts) and (pts > 0 or (pts == 0 and nominal < period / 2))
        if valid:
            c = pts - origin_ms
            if last_valid is not None and abs(c - last_valid) < _SAME_FRAME_MS:
                n_dup += 1
                continue
            if last_valid is not None and c < last_valid:
                n_back += 1
                continue
            last_valid = c
        else:
            c = prev[0] + period if prev is not None else float(nominal)
        cur = (c, payload, valid, fid)
        while ri < n and requests_ms[ri] <= c:
            r = requests_ms[ri]
            take(prev if prev is not None and r - prev[0] <= c - r else cur, r)
            ri += 1
        prev = cur
        if progress is not None and ri - told >= max(1, n // 10):
            told = ri
            progress(ri / n)
        if ri >= n:
            break

    # the last frame also answers requests that fall within one frame after it
    while prev is not None and ri < n and requests_ms[ri] <= prev[0] + period:
        take(prev, requests_ms[ri])
        ri += 1
    notes = []
    if n_fallback:
        notes.append(f"{n_fallback} of {len(picks)} frames had no timestamp and were labelled with the requested time")
    if n_dup:
        notes.append(f"dropped {n_dup} decoded frames that repeated the previous timestamp")
    if n_back:
        notes.append(f"dropped {n_back} decoded frames whose timestamp went backwards")
    if ri < n and picks:
        notes.append(f"video truncated: analysed {len(picks)} frames, the stream ended at "
                     f"{prev[0]:.0f} ms before {n - ri} of {n} requested times")
    return picks, notes


class VideoReader:
    """Reads a phone clip forward and labels each frame with its own presentation timestamp.

    Seeking by millisecond hangs FFmpeg on long-GOP phone HEVC (the old "stuck at 6%"), so the
    reader makes at most one frame-index seek, a second before the segment, and decodes forward
    from there. Times are in ms from the clip's first frame, so a stream whose first frame is
    stamped later than 0 still lines up with the player position the app sends."""

    _MAX_CONSECUTIVE_FAILS = 3

    def __init__(self, video_path: str):
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise VideoDecodeError("Could not open video")

        fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0

        frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_ms = 0
        if frame_count > 0:
            duration_ms = int(round((frame_count / fps) * 1000.0))

        self._meta = VideoMeta(fps=fps, frame_count=frame_count, duration_ms=duration_ms)
        # held so a segment near the start needs no seek at all
        self._first = self._read()
        if self._first is None:
            raise VideoDecodeError("Could not decode the first frame")
        pts = self._first[0]
        self._origin_ms = pts if math.isfinite(pts) and pts > 0 else 0.0

    @property
    def meta(self) -> VideoMeta:
        return self._meta

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass

    def frames(self, requests_ms: list[float],
               progress: Callable[[float], None] | None = None) -> tuple[list[tuple[float, np.ndarray]], list[str]]:
        """[(label_ms, frame)] for ascending requested times, plus notes for the job's warnings."""
        if not requests_ms:
            return [], []
        picks, notes = pick_frames(self._stream(float(requests_ms[0])), requests_ms, self._meta.fps,
                                   self._origin_ms, progress)
        if not picks:
            raise VideoDecodeError(f"no frame decoded at or after {requests_ms[0]:.0f} ms")
        return picks, notes

    def _read(self):
        """(pts_ms, nominal_ms, frame) of the next decoded frame, or None at the end."""
        for _ in range(self._MAX_CONSECUTIVE_FAILS):
            ok, raw = self._cap.read()
            if ok and raw is not None:
                pts = float(self._cap.get(cv2.CAP_PROP_POS_MSEC))
                pos = float(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
                return pts, max(0.0, pos - 1.0) * 1000.0 / self._meta.fps, raw
        return None

    def _stream(self, first_ms: float):
        idx = int((first_ms - _SEEK_LEAD_MS) * self._meta.fps / 1000.0)
        if idx > 0:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(idx))
            self._first = None
            head = self._read()
            if head is not None:
                t = head[0] - self._origin_ms if math.isfinite(head[0]) and head[0] > 0 else head[1]
                if t <= first_ms:
                    yield head
                    yield from self._rest()
                    return
                _log.warning("seek to frame %d landed at %.0f ms, past the first requested %.0f ms; "
                             "decoding from the start instead", idx, t, first_ms)
        if self._first is None:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0.0)
            head = self._read()
        else:
            head, self._first = self._first, None
        if head is not None:
            yield head
            yield from self._rest()

    def _rest(self):
        while (f := self._read()) is not None:
            yield f

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
