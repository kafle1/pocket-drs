# PocketDRS test videos

10 synthetic umpire-POV deliveries with known ground truth, for testing the
system end-to-end. Camera and pitch are fixed, so **every clip uses the same
four corner taps** (listed in `manifest.json`).

| File | Expected verdict |
|------|------------------|
| 01_out_off_stump.mp4 | OUT |
| 02_out_middle_stump.mp4 | OUT |
| 03_out_leg_stump.mp4 | OUT |
| 04_out_fast_middle.mp4 | OUT (fast) |
| 05_notout_wide_off.mp4 | NOT OUT |
| 06_notout_down_leg.mp4 | NOT OUT |
| 07_notout_outside_leg.mp4 | NOT OUT |
| 08_notout_well_wide_leg.mp4 | NOT OUT |
| 09_notout_off_drift.mp4 | NOT OUT |
| 10_umpirescall_leg.mp4 | UMPIRE'S CALL* |

\*Umpire's call is a marginal decision and is sampling-sensitive; it reproduces
exactly with the recorded request but may read as NOT OUT under different
sampling. The OUT and NOT OUT clips are robust.

## Pitch corner taps (same for all clips)

Frame size 1080×1920. Tap in this order: striker-L, striker-R, bowler-R, bowler-L.
See `manifest.json` → `pitch_corners_px` for exact pixel coordinates, plus
`pitch_dimensions_m` (20.12 × 3.05) and `ball_color` (red).

## Run them end-to-end (headless)

```bash
cd server
PYTHONPATH=. .venv/bin/python scripts/run_test_videos.py
```

Expected: `Passed 10/10`.

## Regenerate

```bash
cd server
PYTHONPATH=. .venv/bin/python scripts/export_test_videos.py
```

Source: `server/scripts/export_test_videos.py` (renders via the synthetic
harness in `synth_validate.py`).
