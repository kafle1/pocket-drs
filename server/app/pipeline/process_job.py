from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import ApiError, JobStatus, ProgressInfo
from .calibration import CalibrationError, homography_from_pitch_taps, map_track_to_pitch_plane
from .events import estimate_bounce_index, estimate_impact_index
from .lbw import assess_lbw
from .tracking import TrackPoint, track_seeded
from .video import VideoDecodeError, VideoReader


@dataclass(frozen=True)
class PipelineOutput:
    result: dict
    warnings: list[str]


ProgressFn = Callable[[int, str], None]


def _progress(fn: ProgressFn | None, pct: int, stage: str) -> None:
    if fn is not None:
        fn(int(max(0, min(100, pct))), stage)


def run_pipeline(
    *,
    video_path: Path,
    request_json: dict,
    artifacts_dir: Path,
    progress: ProgressFn | None = None,
) -> PipelineOutput:
    warnings: list[str] = []

    segment = request_json["segment"]
    start_ms = int(segment["start_ms"])
    end_ms = int(segment["end_ms"])

    tracking_req = request_json["tracking"]
    sample_fps = int(tracking_req.get("sample_fps", 30))
    max_frames = int(tracking_req.get("max_frames", 180))

    if tracking_req.get("mode") != "seeded":
        raise ValueError("Only tracking.mode='seeded' is supported in MVP")

    seed = tracking_req.get("seed_px")
    if not seed:
        raise ValueError("seed_px is required for seeded tracking")

    _progress(progress, 5, "decode")

    with VideoReader(str(video_path)) as reader:
        meta = reader.meta

        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("Invalid segment")
        if meta.duration_ms and start_ms >= meta.duration_ms:
            raise ValueError("Segment starts after video end")

        dt_ms = max(1, int(round(1000 / max(1, sample_fps))))
        times_ms: list[int] = []
        t = start_ms
        while t <= end_ms and len(times_ms) < max_frames:
            times_ms.append(int(t))
            t += dt_ms

        frames: list[np.ndarray] = []
        for i, t_ms in enumerate(times_ms):
            try:
                frames.append(reader.frame_at_ms(t_ms))
            except VideoDecodeError as e:
                warnings.append(str(e))
                # Keep a placeholder by repeating the last good frame if possible.
                if frames:
                    frames.append(frames[-1])
                else:
                    raise

            if i == 0:
                h, w = frames[0].shape[:2]
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                try:
                    import cv2

                    cv2.imwrite(str(artifacts_dir / "frame0.jpg"), frames[0])
                except Exception:
                    pass

            if i and (i % max(1, len(times_ms) // 10) == 0):
                _progress(progress, 5 + int(25 * (i / max(1, len(times_ms) - 1))), "decode")

        _progress(progress, 35, "tracking")

        track: list[TrackPoint] = track_seeded(
            frames_bgr=frames,
            times_ms=times_ms,
            seed_x=float(seed["x"]),
            seed_y=float(seed["y"]),
            search_radius_px=160,
        )

        if not track:
            raise RuntimeError("Tracking produced no points")

        width = int(frames[0].shape[1])
        height = int(frames[0].shape[0])

        track_points_payload = [
            {"t_ms": p.t_ms, "x_px": p.x_px, "y_px": p.y_px, "confidence": p.confidence}
            for p in track
        ]

        _progress(progress, 60, "calibration")

        cal_req = request_json.get("calibration") or {}
        cal_mode = cal_req.get("mode", "none")

        calibration_payload: dict = {"mode": cal_mode, "homography": None, "quality": None}
        pitch_plane_payload: dict | None = None

        H = None
        if cal_mode == "taps":
            corners = cal_req.get("pitch_corners_px")
            dims = cal_req.get("pitch_dimensions_m")
            if not corners or not dims:
                raise ValueError("calibration.pitch_corners_px and pitch_dimensions_m are required")

            pts = [(float(p["x"]), float(p["y"])) for p in corners]
            H = homography_from_pitch_taps(
                image_points_px=pts,
                pitch_length_m=float(dims["length"]),
                pitch_width_m=float(dims["width"]),
            )
            calibration_payload["homography"] = {"matrix": H.to_list()}
            calibration_payload["quality"] = {"score": 0.7, "notes": []}

            mapped = map_track_to_pitch_plane(
                H=H,
                track_points_px=[(p.t_ms, p.x_px, p.y_px, p.confidence) for p in track],
            )
            pitch_plane_points = [
                {"t_ms": t_ms, "x_m": float(x_m), "y_m": float(y_m)}
                for (t_ms, x_m, y_m, _conf) in mapped
            ]
            pitch_plane_payload = {"points_m": pitch_plane_points}

        _progress(progress, 75, "events")

        overrides = request_json.get("overrides") or {}
        bounce_idx = overrides.get("bounce_index")
        impact_idx = overrides.get("impact_index")

        if bounce_idx is None:
            bounce_est = estimate_bounce_index([p.y_px for p in track])
        else:
            bounce_est = estimate_bounce_index([p.y_px for p in track])
            bounce_est = bounce_est.__class__(index=int(bounce_idx), confidence=1.0)

        if impact_idx is None:
            impact_est = estimate_impact_index(len(track))
        else:
            impact_est = impact_est.__class__(index=int(impact_idx), confidence=1.0)

        events_payload = {
            "bounce": {"index": bounce_est.index, "confidence": bounce_est.confidence},
            "impact": {"index": impact_est.index, "confidence": impact_est.confidence},
        }

        lbw_payload = None
        if pitch_plane_payload is not None:
            _progress(progress, 85, "lbw")
            pts_m = [(p["x_m"], p["y_m"]) for p in pitch_plane_payload["points_m"]]
            safe_bounce = max(0, min(len(pts_m) - 2, bounce_est.index))
            safe_impact = max(safe_bounce + 1, min(len(pts_m) - 1, impact_est.index))

            assessment = assess_lbw(
                pitch_plane_points=pts_m,
                pitch_index=safe_bounce,
                impact_index=safe_impact,
                prediction_tail_points=10,
            )

            lbw_payload = {
                "likely_out": bool(
                    assessment.pitched_in_line and assessment.impact_in_line and assessment.wickets_hitting
                ),
                "checks": {
                    "pitching_in_line": bool(assessment.pitched_in_line),
                    "impact_in_line": bool(assessment.impact_in_line),
                    "wickets_hitting": bool(assessment.wickets_hitting),
                },
                "prediction": {"y_at_stumps_m": float(assessment.y_at_stumps_m)},
                "decision": assessment.decision_key,
                "reason": assessment.reason,
            }

        _progress(progress, 98, "finalize")

        result = {
            "video": {"duration_ms": int(meta.duration_ms), "fps_est": float(meta.fps)},
            "diagnostics": {"warnings": warnings, "log_id": "server.log"},
            "track": {"points": track_points_payload},
            "calibration": calibration_payload,
            "pitch_plane": pitch_plane_payload,
            "events": events_payload,
            "lbw": lbw_payload,
            "image_size": {"width": width, "height": height},
        }

        # Save a compact debug track for inspection.
        try:
            (artifacts_dir / "debug_track.json").write_text(json.dumps(result["track"], indent=2))
        except Exception:
            pass

        _progress(progress, 100, "done")
        return PipelineOutput(result=result, warnings=warnings)


def map_exception_to_api_error(exc: Exception) -> ApiError:
    msg = str(exc) if str(exc) else exc.__class__.__name__

    if isinstance(exc, VideoDecodeError):
        return ApiError(code="VIDEO_DECODE_FAILED", message=msg, details=None)
    if isinstance(exc, CalibrationError):
        return ApiError(code="CALIBRATION_DEGENERATE", message=msg, details=None)
    if isinstance(exc, ValueError):
        return ApiError(code="INVALID_REQUEST", message=msg, details=None)

    return ApiError(code="INTERNAL_ERROR", message=msg, details=None)
