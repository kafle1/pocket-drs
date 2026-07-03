# PocketDRS — Usage Guide

PocketDRS analyses one delivery from a single phone clip and returns an LBW
verdict. There are three ways to use it: the **Flutter app** (the normal path),
the **HTTP API** (for integrations), and the **offline scripts** (for validation
without a server). All three run the identical pipeline in `server/app/pipeline`.

---

## 1. Recording a usable clip

The pipeline is monocular, so the framing carries the accuracy. For a good result:

- **Fixed camera.** Put the phone on a tripod/stand behind the bowler or behind
  the striker, looking straight down the pitch. No panning or zooming during the ball.
- **Both stump sets visible.** The striker's and bowler's stumps must both be in
  frame — the calibration is anchored to them.
- **Rectilinear lens.** Avoid fisheye/ultra-wide (GoPro) modes; they break the
  pinhole-camera assumption.
- **60 fps or higher**, ball visually distinct (red/white/orange), good light.
- One complete delivery: release → bounce → batsman.

---

## 2. The app flow

1. **Record or pick** a clip.
2. **Choose batsman handedness** (Right / Left) on the first screen — this sets
   which side is leg vs off for the verdict.
3. **Trim** to the single delivery.
4. **Pick a calibration frame** (a clear frame with both stump sets visible).
5. **Tap the 4 pitch corners** (clockwise from the striker end).
6. **Tap the 4 corners of each stump cluster** (striker end, then bowler end).
7. **Analyse.** The app uploads the clip + your taps, polls the job, and shows the
   verdict, speed, and the overlay drawn on the video, plus a 3-D view.

The app pins the regulation pitch length (20.12 m) so the monocular scale is
well-conditioned.

---

## 3. The HTTP API

`POST /v1/jobs` — multipart form with `video_file` and a `request_json` string.
Auth is a Firebase ID token in `Authorization: Bearer <token>`.

Request JSON shape (normalised coordinates are 0–1 over the analysed frame):

```json
{
  "segment": { "start_ms": 0, "end_ms": 4000 },
  "batsman_handedness": "right",
  "calibration": {
    "mode": "taps",
    "pitch_dimensions_m": { "width": 3.05, "length": 20.12 },
    "pitch_corners_norm": [ {"x":..,"y":..}, ... 4 corners: SL, SR, BR, BL ],
    "stump_quads_norm": [ ... 8 points: striker TL,TR,BR,BL then bowler TL,TR,BR,BL ]
  },
  "tracking": { "sample_fps": 60, "max_frames": 180, "ball_color": "red" }
}
```

Then poll and fetch:

```
GET /v1/jobs/{job_id}            -> { status: queued|running|succeeded|failed }
GET /v1/jobs/{job_id}/result     -> { result: { lbw, metrics, world_trajectory, overlay, ... } }
GET /v1/jobs/{job_id}/three-d    -> interactive 3-D viewer (HTML)
```

Notes:
- The YOLO weights are resolved server-side only; the request cannot choose them.
- `ball_color` is a seed only — the detector also tries the alternates and the
  learned detector, and keeps whichever forms the most ball-like arc.
- A degenerate reconstruction is refused with a clear message rather than
  returning a confident wrong verdict.

The `result.lbw` object carries `decision` (`out` / `not_out` / `umpires_call`),
a human-readable `reason`, the three ICC checks, and the predicted `(y, z)` at
the stump plane. `result.metrics` carries speed, swing, and spin.

---

## 4. Offline validation (no server)

```bash
cd server
.venv/bin/python scripts/synth_validate.py     # 8 synthetic deliveries vs ground truth
.venv/bin/python scripts/test3_e2e.py          # real net clip, full pipeline + overlay
.venv/bin/python scripts/test4_e2e.py
.venv/bin/python scripts/test5_e2e.py
```

Each `test*_e2e.py` calls the same `run_pipeline` the API uses, with the clip's
recovered calibration taps baked in, and writes the tracked overlay video, a
sample frame, the 3-D render, and `result.json` under `dump/validation/`.

---

## 5. Reading the verdict

- **Pitching in line** — the ball must not pitch outside the leg-stump line
  (outside off is legal). Leg/off is set by handedness and the camera end.
- **Impact in line** — the ball must strike in line with the stumps.
- **Wickets hitting** — the predicted path must clip the stumps.
- **Umpire's call** — a marginal clip within one ball-radius laterally or one
  ball-diameter vertically (the vertical band is wider because a single camera
  resolves height less precisely than line).

Absolute speed and the exact bounce location are shown as **indicative** — they
depend on the depth axis, which one camera resolves least well. The line-based
decision is the reliable output.
