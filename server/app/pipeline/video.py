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
        
        # Cap at video duration to avoid read errors near end
        if self._meta.duration_ms > 0 and t_ms >= self._meta.duration_ms:
            t_ms = max(0, self._meta.duration_ms - 100)

        # Try millisecond-based seek first
        ok = self._cap.set(cv2.CAP_PROP_POS_MSEC, float(t_ms))
        if not ok and self._meta.fps > 0:
            frame_idx = int(round((t_ms / 1000.0) * self._meta.fps))
            frame_idx = min(frame_idx, max(0, self._meta.frame_count - 1))
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_idx))

        ok, frame = self._cap.read()
        if not ok or frame is None:
            # Fallback: try reading next frame if seek failed
            ok, frame = self._cap.read()
            if not ok or frame is None:
                # Final fallback: return last good frame if available
                if self._last_frame is not None:
                    return self._last_frame.copy()
                raise VideoDecodeError(f"Failed to decode frame at {t_ms}ms")
        
        self._last_frame = frame
        return frame

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
