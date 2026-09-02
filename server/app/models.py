"""Request and response schemas. The request models declare exactly what the pipeline reads;
unknown fields are rejected so a renamed key fails at the API instead of deep in a job."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Strict = ConfigDict(extra="forbid")


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
    model_config = Strict
    x: float
    y: float


class ClientInfo(BaseModel):
    model_config = Strict
    platform: str | None = None
    app_version: str | None = None


class VideoInfo(BaseModel):
    model_config = Strict
    rotation_deg: Literal[0, 90, 180, 270] = 0


class Segment(BaseModel):
    model_config = Strict
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("segment.end_ms must be greater than segment.start_ms")
        return self


class PitchDimensions(BaseModel):
    model_config = Strict
    width: float = Field(gt=0)
    # pin the length on a regulation pitch; leave it out on an indoor net and it is fitted from the marks
    length: float | None = Field(default=None, gt=0)


class Calibration(BaseModel):
    model_config = Strict
    mode: Literal["taps"] = "taps"
    pitch_dimensions_m: PitchDimensions
    # four pitch corners: striker-left, striker-right, bowler-right, bowler-left
    pitch_corners_norm: list[Point2D] | None = None
    pitch_corners_px: list[Point2D] | None = None
    # eight stump corners: striker TL, TR, BR, BL, then bowler TL, TR, BR, BL
    stump_quads_norm: list[Point2D] | None = None
    stump_quads_px: list[Point2D] | None = None
    h_fov_deg: float | None = Field(default=None, gt=1, lt=179)

    @model_validator(mode="after")
    def _marks_present(self):
        for name, n in (("pitch_corners", 4), ("stump_quads", 8)):
            pts = getattr(self, f"{name}_norm") or getattr(self, f"{name}_px")
            if pts is None or len(pts) != n:
                raise ValueError(f"calibration.{name}_norm or {name}_px with {n} points is required")
        for name in ("pitch_corners_norm", "stump_quads_norm"):
            pts = getattr(self, name) or []
            if any(not (0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0) for p in pts):
                raise ValueError(f"calibration.{name} points must be in [0, 1]")
        return self


class Tracking(BaseModel):
    model_config = Strict
    sample_fps: int = Field(default=30, ge=1, le=240)
    max_frames: int = Field(default=180, ge=1, le=2000)
    ball_color: Literal["red", "pink", "white"] = "red"
    detector: Literal["auto", "yolo", "colour"] = "auto"


class CreateJobRequest(BaseModel):
    model_config = Strict
    client: ClientInfo | None = None
    video: VideoInfo = VideoInfo()
    segment: Segment
    calibration: Calibration
    tracking: Tracking = Tracking()
    batsman_handedness: Literal["right", "left"] = "right"


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


class JobResultResponse(BaseModel):
    # the result dict is built by process_job against the schema documented there; the client
    # reads it directly, so it is passed through rather than re-declared here
    job_id: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: ApiError | None = None
