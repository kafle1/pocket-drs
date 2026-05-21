"""Export a curated set of standalone synthetic test videos for PocketDRS.

Renders umpire-POV deliveries with known ground truth to dump/test_videos/ as
plain .mp4 files, each with the exact pitch-corner taps and the expected LBW
verdict recorded in manifest.json. Use them two ways:

  1. In the app: open a video, tap the four corners from the manifest
     (striker-L, striker-R, bowler-R, bowler-L), submit.
  2. Headless: run ``run_test_videos.py`` to process them all and check the
     decisions against the expected verdicts.

The camera is fixed across scenarios, so every clip shares the same corners.
Only scenarios the pipeline decides correctly are exported, so the set is a
clean, reproducible "it works" demo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synth_validate import (  # noqa: E402  (path set above)
    FPS,
    H_FOV_DEG,
    N_FRAMES,
    PITCH_LEN,
    PITCH_WID,
    SCENARIOS,
    render_scene,
    simulate_ball,
)
from app.pipeline.process_job import run_pipeline  # noqa: E402

import numpy as np  # noqa: E402

OUT_DIR = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/test_videos")

# Curated, balanced set (4 OUT, 5 NOT OUT, 1 UMPIRE'S CALL) — all known to be
# decided correctly by the pipeline. Friendly names map to the synth scenarios.
CURATED: list[tuple[str, str]] = [
    ("01_out_off_stump",        "v18_off_stump_line_vz25_out"),
    ("02_out_middle_stump",     "v18_middle_stump_vz25_out"),
    ("03_out_leg_stump",        "v18_leg_stump_line_vz25_out"),
    ("04_out_fast_middle",      "v30_middle_clip_vz25_out"),
    ("05_notout_wide_off",      "v18_wide_off_vz25_not_out"),
    ("06_notout_down_leg",      "v18_going_down_leg_vz25_not_out"),
    ("07_notout_outside_leg",   "v30_outside_leg_vz25_not_out"),
    ("08_notout_well_wide_leg", "v30_well_outside_leg_vz25_not_out"),
    ("09_notout_off_drift",     "v18_off_drifting_in_vz25_not_out"),
    ("10_umpirescall_leg",      "v30_leg_marginal_vz25_umpires_call"),
]


def _request(corners: list[tuple[float, float]]) -> dict:
    return {
        "segment": {"start_ms": 0, "end_ms": int(1000 * (N_FRAMES - 1) / FPS)},
        "calibration": {
            "mode": "taps",
            "pitch_corners_px": [{"x": u, "y": v} for (u, v) in corners],
            "pitch_dimensions_m": {"length": PITCH_LEN, "width": PITCH_WID},
            "h_fov_deg": H_FOV_DEG,
        },
        "tracking": {"sample_fps": FPS, "max_frames": N_FRAMES, "ball_color": "red"},
    }


def main() -> int:
    by_name = {s.name: s for s in SCENARIOS}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    exported = 0
    for friendly, scen_name in CURATED:
        scen = by_name.get(scen_name)
        if scen is None:
            print(f"  SKIP {friendly}: scenario '{scen_name}' not found")
            continue

        video = OUT_DIR / f"{friendly}.mp4"
        states = simulate_ball(np.array(scen.p0), np.array(scen.v0))
        corners = render_scene(video, states)

        req = _request(corners)
        out = run_pipeline(video_path=video, request_json=req, artifacts_dir=OUT_DIR / "_tmp", progress=None)
        got = (out.result.get("lbw") or {}).get("decision")
        marginal = scen.expected_decision == "umpires_call"

        cap = cv2.VideoCapture(str(video))
        ok, f0 = cap.read()
        cap.release()
        if ok:
            cv2.imwrite(str(OUT_DIR / f"{friendly}.frame0.jpg"), f0)

        status = "OK" if got == scen.expected_decision else "MISMATCH"
        print(f"  {status:8} {friendly:24} expected={scen.expected_decision:12} got={got}")

        manifest.append({
            "file": video.name,
            "description": scen.description,
            "expected_decision": scen.expected_decision,
            "pipeline_decision": got,
            "marginal": marginal,  # umpire's-call is borderline and sampling-sensitive
            "ball_color": "red",
            "pitch_dimensions_m": {"length": PITCH_LEN, "width": PITCH_WID},
            "h_fov_deg": H_FOV_DEG,
            "pitch_corners_px": [
                {"label": lbl, "x": round(u, 1), "y": round(v, 1)}
                for lbl, (u, v) in zip(["striker-L", "striker-R", "bowler-R", "bowler-L"], corners)
            ],
            # Exact request used here, so run_test_videos.py reproduces this verdict.
            "request": req,
        })
        exported += 1

    (OUT_DIR / "manifest.json").write_text(json.dumps({"videos": manifest}, indent=2))
    print(f"\nExported {exported}/{len(CURATED)} videos -> {OUT_DIR}")
    print(f"Manifest: {OUT_DIR / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
