from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Point2D(BaseModel):
    x: float
    y: float


class ClientInfo(BaseModel):
    platform: str | None = None
    app_version: str | None = None


class VideoInfoRequest(BaseModel):
    source: Literal["import", "record"] | None = None
    rotation_deg: int = 0


class SegmentRequest(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @field_validator("end_ms")
    @classmethod
    def _validate_end_after_start(cls, end_ms: int, info):
        start_ms = info.data.get("start_ms")
        if start_ms is not None and end_ms <= start_ms:
            raise ValueError("end_ms must be > start_ms")
        return end_ms


class PitchDimensionsM(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)


class CalibrationRequest(BaseModel):
    mode: Literal["taps", "marker", "none"] = "taps"
    pitch_corners_px: list[Point2D] | None = None
    pitch_dimensions_m: PitchDimensionsM | None = None

    @field_validator("pitch_corners_px")
    @classmethod
    def _validate_pitch_corners(cls, v: list[Point2D] | None, info):
        mode = info.data.get("mode")
        if mode == "taps":
            if v is None or len(v) != 4:
                raise ValueError("pitch_corners_px must contain 4 points when mode='taps'")
        return v


class TrackingRequest(BaseModel):
    mode: Literal["auto", "seeded"] = "seeded"
    seed_px: Point2D | None = None
    max_frames: int = Field(default=180, ge=1, le=2000)
    sample_fps: int = Field(default=30, ge=1, le=240)

    @field_validator("seed_px")
    @classmethod
    def _validate_seed(cls, seed_px: Point2D | None, info):
        mode = info.data.get("mode")
        if mode == "seeded" and seed_px is None:
            raise ValueError("seed_px is required when tracking.mode='seeded'")
        return seed_px


class OverridesRequest(BaseModel):
    bounce_index: int | None = Field(default=None, ge=0)
    impact_index: int | None = Field(default=None, ge=0)
    full_toss: bool = False


class CreateJobRequest(BaseModel):
    client: ClientInfo | None = None
    video: VideoInfoRequest | None = None
    segment: SegmentRequest
    calibration: CalibrationRequest
    tracking: TrackingRequest
    overrides: OverridesRequest | None = None


class ProgressInfo(BaseModel):
    pct: int = Field(ge=0, le=100)
    stage: str


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: ProgressInfo | None = None
    error: ApiError | None = None


class TrackPoint(BaseModel):
    t_ms: int
    x_px: float
    y_px: float
    confidence: float


class HomographyResponse(BaseModel):
    matrix: list[list[float]]


class CalibrationResponse(BaseModel):
    mode: str
    homography: HomographyResponse | None = None
    quality: dict[str, Any] | None = None


class PitchPlanePoint(BaseModel):
    t_ms: int
    x_m: float
    y_m: float


class EventEstimate(BaseModel):
    index: int
    confidence: float


class EventsResponse(BaseModel):
    bounce: EventEstimate
    impact: EventEstimate


class LbwChecks(BaseModel):
    pitching_in_line: bool
    impact_in_line: bool
    wickets_hitting: bool


class LbwResponse(BaseModel):
    likely_out: bool
    checks: LbwChecks
    prediction: dict[str, float]
    decision: str


class VideoMeta(BaseModel):
    duration_ms: int
    fps_est: float


class Diagnostics(BaseModel):
    warnings: list[str] = []
    log_id: str | None = None


class JobResultPayload(BaseModel):
    video: VideoMeta
    diagnostics: Diagnostics
    track: dict[str, list[TrackPoint]]
    calibration: CalibrationResponse
    pitch_plane: dict[str, list[PitchPlanePoint]] | None = None
    events: EventsResponse | None = None
    lbw: LbwResponse | None = None


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: JobResultPayload | None = None
    error: ApiError | None = None
