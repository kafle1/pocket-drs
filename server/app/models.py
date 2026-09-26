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


class Segment(BaseModel):
    model_config = Strict
    start_ms: int = Field(ge=0, le=86_400_000)
    end_ms: int = Field(ge=0, le=86_400_000)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("segment.end_ms must be greater than segment.start_ms")
        return self


class PitchDimensions(BaseModel):
    model_config = Strict
    width: float = Field(ge=1.0, le=5.0)
    length: float = Field(ge=10.0, le=25.0)


class Calibration(BaseModel):
    model_config = Strict
    pitch_dimensions_m: PitchDimensions
    # eight stump corners: striker TL, TR, BR, BL, then bowler TL, TR, BR, BL
    stump_quads_norm: list[Point2D] | None = None
    stump_quads_px: list[Point2D] | None = None

    @model_validator(mode="after")
    def _marks_present(self):
        stumps = self.stump_quads_norm or self.stump_quads_px
        if stumps is None or len(stumps) != 8:
            raise ValueError("calibration.stump_quads_norm or stump_quads_px with 8 points is required")
        if any(not (0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0) for p in self.stump_quads_norm or []):
            raise ValueError("calibration.stump_quads_norm points must be in [0, 1]")
        return self


class Tracking(BaseModel):
    model_config = Strict
    sample_fps: int = Field(default=30, ge=1, le=240)
    max_frames: int = Field(default=180, ge=1, le=300)
    ball_color: Literal["red", "pink", "white"] = "red"


class CreateJobRequest(BaseModel):
    model_config = Strict
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
