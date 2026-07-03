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

    _MAX_CONSECUTIVE_STALE = 3
    # Safety margin (in frames) on top of ``target_idx`` bounding the forward
    # scan after a seek, so a stuck/mislabelled stream can never loop forever.
    _MAX_SEEK_SCAN = 300

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
        self._consecutive_stale = 0

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

        # Already parked on the requested frame — hand back the cached copy.
        if target_idx == self._cursor_idx and self._last_frame is not None:
            return self._last_frame.copy()

        # If the target is close and forward of the cursor, decode
        # sequentially (the codec's fast path — no keyframe rescan, no MSEC
        # ambiguity). Otherwise do a one-off frame-index seek. On long-GOP
        # HEVC ``set(POS_FRAMES, N)`` lands on the nearest keyframe <= N, so we
        # must never assume the next frame *is* N: we read forward and trust
        # the container's real POS_FRAMES to tell us which frame we hold.
        gap = target_idx - self._cursor_idx
        if gap < 0 or gap > 16:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(target_idx))
            # Provisional; the true index is re-derived from POS_FRAMES after
            # the first read below, which corrects for a keyframe landing.
            self._cursor_idx = target_idx - 1

        # Bound the forward scan: from any keyframe we need at most
        # ``target_idx`` reads to reach the target, plus a margin to absorb
        # POS_FRAMES reporting jitter. Guarantees termination even if the
        # container's position never advances.
        budget = target_idx + self._MAX_SEEK_SCAN
        reads = 0
        frame = None
        while self._cursor_idx < target_idx:
            if reads >= budget:
                break  # give up cleanly; return the best frame decoded so far
            ok, raw = self._cap.read()
            reads += 1
            if not ok or raw is None:
                if self._last_frame is None:
                    raise VideoDecodeError(f"Failed to decode frame at {t_ms}ms")
                self._consecutive_stale += 1
                if self._consecutive_stale >= self._MAX_CONSECUTIVE_STALE:
                    raise VideoDecodeError(
                        f"Video appears truncated near {t_ms}ms "
                        f"(decoding failed for {self._consecutive_stale} "
                        "consecutive frames)"
                    )
                # One frame failed to decode. Re-anchor the cursor to the
                # container's real position so a single skip can't offset the
                # index/timestamp of every later frame.
                pos = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
                if pos > 0:
                    self._cursor_idx = pos - 1
                return self._last_frame.copy()
            # Trust the container's real frame index rather than a virtual +1,
            # so a keyframe landing or a dropped frame can't drift the
            # labelling. Fall back to +1 only if POS_FRAMES is unavailable.
            pos = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
            self._cursor_idx = (pos - 1) if pos > 0 else (self._cursor_idx + 1)
            frame = raw

        if frame is None:
            # Cursor already at/after target but nothing decoded this call;
            # the cached last_frame is the correct response.
            return (self._last_frame.copy() if self._last_frame is not None
                    else self._read_nonseek_fallback(t_ms))

        self._consecutive_stale = 0
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
