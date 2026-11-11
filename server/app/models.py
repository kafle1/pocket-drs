"""Request and response schemas. The request models declare exactly what the pipeline reads;
unknown fields are rejected so a renamed key fails at the API instead of deep in a job."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Strict = ConfigDict(extra="forbid")
STUMP_MARKS_MISSING = "Only one stump corner can be left unmarked. Mark the other corners and send it again."


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
    width: float = Field(default=3.05, ge=1.0, le=5.0)
    length: float = Field(default=20.12, ge=10.0, le=25.0)


class StumpDimensions(BaseModel):
    model_config = Strict
    # outer edge to outer edge, and ground to the top of the stumps; street and portable sets differ
    width: float = Field(default=0.2286, ge=0.1, le=0.6)
    height: float = Field(default=0.711, ge=0.3, le=1.2)


class Calibration(BaseModel):
    model_config = Strict
    pitch_dimensions_m: PitchDimensions = Field(default_factory=PitchDimensions)
    stumps_m: StumpDimensions = Field(default_factory=StumpDimensions)
    # the frame the marks were tapped on
    frame_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    # eight stump corners: striker TL, TR, BR, BL, then bowler TL, TR, BR, BL; one may be null when the pads hide it
    stump_quads_norm: list[Point2D | None]
    # optional four popping-crease ends, clockwise on the screen from the striker end
    crease_marks_norm: list[Point2D] | None = None

    @model_validator(mode="after")
    def _marks_present(self):
        if len(self.stump_quads_norm) != 8:
            raise ValueError("calibration.stump_quads_norm needs 8 points")
        if self.stump_quads_norm.count(None) > 1:
            raise ValueError(STUMP_MARKS_MISSING)
        if self.crease_marks_norm is not None and len(self.crease_marks_norm) != 4:
            raise ValueError("calibration.crease_marks_norm needs 4 points")
        marks = [p for p in self.stump_quads_norm if p is not None] + (self.crease_marks_norm or [])
        if any(not (0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0) for p in marks):
            raise ValueError("calibration marks must be in [0, 1]")
        return self


class Tracking(BaseModel):
    model_config = Strict
    ball_color: Literal["red", "pink"] = "red"
    ball_type: Literal["leather", "tennis", "tape"] = "tennis"


class CreateJobRequest(BaseModel):
    model_config = Strict
    segment: Segment
    calibration: Calibration
    tracking: Tracking = Field(default_factory=Tracking)
    batsman_handedness: Literal["right", "left"] = "right"
    # the phone's recording rate; slow-motion clips run up to 960
    capture_fps: float | None = Field(default=None, gt=0, le=1000)
    on_field_call: Literal["out", "not_out", "none"] = "none"
    shot_played: bool = True
    pitch_length_m: float | None = Field(default=None, ge=10.0, le=25.0)


class ProgressInfo(BaseModel):
    pct: int = Field(ge=0, le=100)
    stage: str


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    # place in line while queued, 1 is next
    queue_position: int | None = None
    progress: ProgressInfo | None = None
    error: ApiError | None = None


class JobResultResponse(BaseModel):
    # the result dict is built by process_job against the schema documented there; the client
    # reads it directly, so it is passed through rather than re-declared here
    job_id: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: ApiError | None = None
