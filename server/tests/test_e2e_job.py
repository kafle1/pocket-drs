from __future__ import annotations

import importlib
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient


def _make_synthetic_video(path: Path, *, fps: int = 30, frames: int = 45) -> None:
    w, h = 160, 120
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    assert writer.isOpened()

    for i in range(frames):
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # Draw a small bright ball.
        x = 30 + i
        y = 30 + (i if i < frames // 2 else (frames - i))
        cv2.circle(img, (int(x), int(y)), 4, (255, 255, 255), -1)
        writer.write(img)

    writer.release()


def test_create_job_and_fetch_result(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("POCKET_DRS_DATA_DIR", str(tmp_path / "data"))

    # Import app after env var so it uses the temp data directory.
    main = importlib.import_module("app.main")
    importlib.reload(main)

    client = TestClient(main.app)

    video_path = tmp_path / "clip.mp4"
    _make_synthetic_video(video_path)

    req = {
        "client": {"platform": "pytest", "app_version": "0"},
        "video": {"source": "import", "rotation_deg": 0},
        "segment": {"start_ms": 0, "end_ms": 1200},
        "calibration": {"mode": "none", "pitch_corners_px": None, "pitch_dimensions_m": None},
        "tracking": {
            "mode": "auto",
            "seed_px": None,
            "max_frames": 60,
            "sample_fps": 30,
        },
        "overrides": {"bounce_index": None, "impact_index": None, "full_toss": False},
    }

    with video_path.open("rb") as f:
        resp = client.post(
            "/v1/jobs",
            files={"video_file": ("clip.mp4", f, "video/mp4")},
            data={"request_json": json.dumps(req)},
        )

    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Poll status.
    deadline = time.time() + 6.0
    status = None
    while time.time() < deadline:
        s = client.get(f"/v1/jobs/{job_id}")
        assert s.status_code == 200
        status = s.json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert status == "succeeded"

    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "succeeded"
    assert payload["result"]["track"]["points"]


def test_create_job_with_tap_calibration_and_stump_bases(tmp_path: Path, monkeypatch):
    """End-to-end validation of the 'taps' calibration contract.

    This specifically exercises the optional stump-base refinement path to
    ensure request parsing, homography computation, pitch-plane mapping, and
    LBW assessment all run without regressions.
    """

    monkeypatch.setenv("POCKET_DRS_DATA_DIR", str(tmp_path / "data"))

    # Import app after env var so it uses the temp data directory.
    main = importlib.import_module("app.main")
    importlib.reload(main)

    client = TestClient(main.app)

    video_path = tmp_path / "clip.mp4"
    _make_synthetic_video(video_path)

    # Use a simple quadrilateral within frame bounds. The synthetic video has
    # size (w=160, h=120). These are normalized coords.
    req = {
        "client": {"platform": "pytest", "app_version": "0"},
        "video": {"source": "import", "rotation_deg": 0},
        "segment": {"start_ms": 0, "end_ms": 1200},
        "calibration": {
            "mode": "taps",
            "pitch_corners_norm": [
                {"x": 0.20, "y": 0.25},
                {"x": 0.80, "y": 0.25},
                {"x": 0.85, "y": 0.85},
                {"x": 0.15, "y": 0.85},
            ],
            # Two stump bases; their order may be striker/bowler or swapped.
            # The calibration module will auto-order for refinement.
            "stump_bases_norm": [
                {"x": 0.50, "y": 0.30},
                {"x": 0.52, "y": 0.80},
            ],
            "pitch_dimensions_m": {"length": 20.12, "width": 3.05},
        },
        "tracking": {
            "mode": "auto",
            "seed_px": None,
            "max_frames": 60,
            "sample_fps": 30,
        },
        "overrides": {"bounce_index": None, "impact_index": None, "full_toss": False},
    }

    with video_path.open("rb") as f:
        resp = client.post(
            "/v1/jobs",
            files={"video_file": ("clip.mp4", f, "video/mp4")},
            data={"request_json": json.dumps(req)},
        )

    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Poll status.
    deadline = time.time() + 6.0
    status = None
    while time.time() < deadline:
        s = client.get(f"/v1/jobs/{job_id}")
        assert s.status_code == 200
        status = s.json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert status == "succeeded"

    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "succeeded"

    res = payload["result"]
    assert res["track"]["points"], "tracking produced no points"

    # Calibration should have a homography and the stump-base refinement note.
    cal = res["calibration"]
    assert cal["mode"] == "taps"
    assert cal["homography"] and cal["homography"]["matrix"], "missing homography"
    notes = (cal.get("quality") or {}).get("notes") or []
    assert any("stump base" in str(n).lower() for n in notes), notes

    # Pitch-plane mapping should exist for taps calibration.
    assert res["pitch_plane"] and res["pitch_plane"]["points_m"], "missing pitch plane points"

    # LBW payload should be present when pitch_plane exists.
    assert res.get("lbw") is not None
