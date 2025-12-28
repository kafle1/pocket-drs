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
from .tracking import TrackPoint, track_auto, track_seeded
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

    tracking_mode = str(tracking_req.get("mode") or "seeded")
    seed = tracking_req.get("seed_px")

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

        if tracking_mode == "auto":
            track = track_auto(
                frames_bgr=frames,
                times_ms=times_ms,
                search_radius_px=160,
            )
        elif tracking_mode == "seeded":
            if not seed:
                raise ValueError("seed_px is required for seeded tracking")
            track = track_seeded(
                frames_bgr=frames,
                times_ms=times_ms,
                seed_x=float(seed["x"]),
                seed_y=float(seed["y"]),
                search_radius_px=160,
            )
        else:
            raise ValueError("tracking.mode must be 'auto' or 'seeded'")

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
            corners_px = cal_req.get("pitch_corners_px")
            corners_norm = cal_req.get("pitch_corners_norm")
            stump_bases_px = cal_req.get("stump_bases_px")
            stump_bases_norm = cal_req.get("stump_bases_norm")
            dims = cal_req.get("pitch_dimensions_m")
            if not dims:
                raise ValueError("calibration.pitch_dimensions_m is required")

            if corners_px:
                pts = [(float(p["x"]), float(p["y"])) for p in corners_px]
            elif corners_norm:
                pts = [(float(p["x"]) * width, float(p["y"]) * height) for p in corners_norm]
            else:
                raise ValueError("Provide calibration.pitch_corners_px or calibration.pitch_corners_norm")

            stump_pts: list[tuple[float, float]] | None = None
            if stump_bases_px and isinstance(stump_bases_px, list) and len(stump_bases_px) == 2:
                try:
                    stump_pts = [(float(p["x"]), float(p["y"])) for p in stump_bases_px]
                except Exception:
                    stump_pts = None
            elif stump_bases_norm and isinstance(stump_bases_norm, list) and len(stump_bases_norm) == 2:
                try:
                    stump_pts = [(float(p["x"]) * width, float(p["y"]) * height) for p in stump_bases_norm]
                except Exception:
                    stump_pts = None

            H = homography_from_pitch_taps(
                image_points_px=pts,
                pitch_length_m=float(dims["length"]),
                pitch_width_m=float(dims["width"]),
                stump_bases_px=stump_pts,
            )
            calibration_payload["homography"] = {"matrix": H.to_list()}
            notes: list[str] = []
            if stump_pts is not None:
                notes.append("Refined homography using both stump bases")
            calibration_payload["quality"] = {"score": 0.7, "notes": notes}

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

        def _clamp_index(i: int, n: int) -> int:
            if n <= 0:
                return 0
            return max(0, min(n - 1, i))

        bounce_est = estimate_bounce_index([p.y_px for p in track])
        if bounce_idx is not None:
            bounce_est = bounce_est.__class__(index=int(bounce_idx), confidence=1.0)

        impact_est = estimate_impact_index(len(track))
        if impact_idx is not None:
            impact_est = impact_est.__class__(index=int(impact_idx), confidence=1.0)

        # Clamp indices to keep downstream consumers safe.
        bounce_i = _clamp_index(int(bounce_est.index), len(track))
        impact_i = _clamp_index(int(impact_est.index), len(track))

        events_payload = {
            "bounce": {"index": bounce_i, "confidence": float(bounce_est.confidence)},
            "impact": {"index": impact_i, "confidence": float(impact_est.confidence)},
        }

        lbw_payload = None
        if pitch_plane_payload is not None:
            _progress(progress, 85, "lbw")
            pts_m = [(p["x_m"], p["y_m"]) for p in pitch_plane_payload["points_m"]]
            safe_bounce = max(0, min(len(pts_m) - 2, bounce_est.index))

            # Extract tracking confidences for weighted LBW prediction
            point_confidences = [p.confidence for p in track]

            assessment = assess_lbw(
                pitch_plane_points=pts_m,
                pitch_index=safe_bounce,
                prediction_tail_points=15,  # Use more points for better accuracy
                point_confidences=point_confidences,
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
                "prediction": {
                    "y_at_stumps_m": float(assessment.y_at_stumps_m),
                    "confidence": float(assessment.prediction_confidence),
                    "r_squared": float(assessment.prediction_r_squared),
                },
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
