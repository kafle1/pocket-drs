from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoMeta:
    fps: float
    frame_count: int
    duration_ms: int


class VideoDecodeError(RuntimeError):
    pass


class VideoReader:
    """Frame-aligned video reader that survives phone-recorded HEVC.

    Phone clips routinely arrive with non-standard b-frame ordering and sparse
    keyframes; ``cv2.CAP_PROP_POS_MSEC`` seek then blocks inside FFmpeg as it
    scans for the nearest decodable frame, which is what shows up to the user
    as the analysis job "stuck at 6%". We avoid the trap by never seeking by
    millisecond. Instead we keep a running cursor on the current frame index
    and either grab the next frame sequentially (the common case, since the
    sampler asks for monotonically increasing timestamps) or do a single,
    cheap ``CAP_PROP_POS_FRAMES`` jump when the gap is large.
    """

    def __init__(self, video_path: str):
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise VideoDecodeError("Could not open video")

        fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            fps = 30.0

        frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_ms = 0
        if frame_count > 0 and fps > 0:
            duration_ms = int(round((frame_count / fps) * 1000.0))

        self._meta = VideoMeta(fps=fps, frame_count=frame_count, duration_ms=duration_ms)
        self._last_frame: np.ndarray | None = None
        self._cursor_idx: int = -1  # next read returns frame index cursor+1

    @property
    def meta(self) -> VideoMeta:
        return self._meta

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass

    def frame_at_ms(self, t_ms: int) -> np.ndarray:
        if t_ms < 0:
            t_ms = 0
        if self._meta.duration_ms > 0 and t_ms >= self._meta.duration_ms:
            t_ms = max(0, self._meta.duration_ms - 1)

        target_idx = int(round((t_ms / 1000.0) * self._meta.fps))
        if self._meta.frame_count > 0:
            target_idx = min(target_idx, max(0, self._meta.frame_count - 1))

        # If the target is forward of (or equal to) the current cursor, read
        # frames sequentially until we land on it. Sequential decode is the
        # codec's fast path — no keyframe rescan, no MSEC ambiguity. We jump
        # only when the gap is large enough that scanning would be slower
        # than a one-off frame-index seek.
        gap = target_idx - self._cursor_idx
        if gap < 0 or gap > 16:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(target_idx))
            self._cursor_idx = target_idx - 1

        frame = None
        while self._cursor_idx < target_idx:
            ok, raw = self._cap.read()
            if not ok or raw is None:
                # Do not synthesize analysis frames from the previous image:
                # duplicated tail frames look like a stopped ball and corrupt
                # bounce/impact classification. A failed sequential read may
                # still be a keyframe/seek hiccup, so try one explicit frame
                # seek before declaring the clip exhausted or truncated.
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(target_idx))
                ok, raw = self._cap.read()
                if not ok or raw is None:
                    raise VideoDecodeError(f"Failed to decode frame at {t_ms}ms")
                self._cursor_idx = target_idx
                frame = raw
                break
            self._cursor_idx += 1
            frame = raw

        if frame is None:
            # target_idx equals cursor_idx and we already returned that frame
            # earlier; the cached last_frame is the correct response.
            return (self._last_frame.copy() if self._last_frame is not None
                    else self._read_nonseek_fallback(t_ms))

        self._last_frame = frame
        return frame

    def _read_nonseek_fallback(self, t_ms: int) -> np.ndarray:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise VideoDecodeError(f"Failed to decode frame at {t_ms}ms")
        self._cursor_idx += 1
        self._last_frame = frame
        return frame

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
