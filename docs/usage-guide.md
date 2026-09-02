# PocketDRS usage guide

## 1. Recording a usable clip

- Stand behind the batter, a couple of metres back from the stumps, phone held still. Both sets of
  stumps and the full pitch must be in frame.
- 60 Hz or higher if the phone offers it; 30 Hz works but leaves fewer frames after the bounce.
- Portrait framing is fine. Avoid the ultra-wide lens: its distortion is not modelled.
- The bounce has to be visible. A full toss, or a clip cut before the ball pitches, is fitted with a
  single parabola instead and comes back flagged with a much wider band.
- The bowler's end works, but the arc that decides the verdict is then 15 to 20 m away and
  foreshortened; expect wider bands.

## 2. The app flow

1. Pick or record a clip and trim it to the delivery.
2. Tap the four corners of each stump set (top-left, top-right, bottom-right, bottom-left), striker's
   end first, then the four pitch corners (striker-left, striker-right, bowler-right, bowler-left).
3. Choose the batter's handedness and submit.
4. The result screen shows the tracked flight, the predicted path to the stumps, the pitching point,
   the release speed and turn, and the verdict with its reason. Umpire's call means the estimate
   could not support a decisive call at one sigma.

## 3. The HTTP API

`POST /v1/jobs` (multipart: `video_file` + `request_json`) starts a job; `GET /v1/jobs/{id}` polls
`status` and `progress`; `GET /v1/jobs/{id}/result` returns the result once `status` is `succeeded`.
All calls carry a Firebase ID token as a bearer header.

Request:

```json
{
  "segment": {"start_ms": 0, "end_ms": 2200},
  "video": {"rotation_deg": 0},
  "tracking": {"sample_fps": 60, "max_frames": 180, "ball_color": "red", "detector": "auto"},
  "calibration": {
    "mode": "taps",
    "pitch_dimensions_m": {"width": 3.05, "length": 20.12},
    "pitch_corners_norm": [{"x": 0.31, "y": 0.62}, {"x": 0.69, "y": 0.62}, {"x": 0.55, "y": 0.28}, {"x": 0.45, "y": 0.28}],
    "stump_quads_norm": [8 points: striker TL, TR, BR, BL, then bowler TL, TR, BR, BL]
  },
  "batsman_handedness": "right"
}
```

`pitch_dimensions_m.length` is optional. Pin it to 20.12 on a regulation pitch; leave it out on an
indoor net and the calibration fits the length from the marks. `h_fov_deg` may be given to pin the
focal length; otherwise it is swept.

Result, the fields the app reads:

| Field | Meaning |
|---|---|
| `lbw.decision`, `lbw.reason` | `out`, `not_out` or `umpires_call`, and why |
| `lbw.checks` | `pitching_in_line`, `impact_in_line`, `wickets_hitting` |
| `lbw.prediction.y_at_stumps_m`, `z_at_stumps_m` | where the ball crosses the stump plane |
| `lbw.prediction.sigma_y_m`, `sigma_z_m` | one-sigma bounds propagated from the fit |
| `events.bounce` | pitching point with `sigma_x_m`, `sigma_y_m`; null when no contact was seen |
| `events.impact` | where the track ended (bat or pad) |
| `metrics.speed_kmh`, `swing_sf`, `spin_deg` | release speed, lateral movement in the air (cm), turn off the pitch (degrees) |
| `world_trajectory.model` | the nine fitted parameters, `restitution`, `bounce_observed` |
| `overlay.*` | pixel-space flight, predicted path, stumps, corridor for drawing on the clip |
| `calibration.quality` | reprojection error (px), score, notes |
| `diagnostics.warnings` | anything the pipeline wants you to know, including why a verdict was declined |

`lbw` is null when the calibration or the 3-D fit was rejected; `diagnostics.warnings` says which.

## 4. Offline, without the app

`server/scripts/real_clip.py test3` builds the request for a bundled clip, runs the job in
process, and renders the overlay under `dump/validation/test3/`. Add a clip by putting its
twelve marks in the table at the top of that script.

The paper's harness is independent of the server: `paper/experiments/synth.py` generates
deliveries with exact truth and `exp1_geometry.py` runs the estimator on them without any video.

## 5. Reading the verdict

The three Law 36 tests are applied to the model's pitching point, its position where the track
ended, and its predicted stump-plane crossing. Each is compared with the ICC review band (one ball
radius outside a boundary is umpire's call), widened to the propagated one-sigma bound when that is
larger. A verdict is decisive only when every test is clear of its band. The bands are wider
vertically than laterally because that is where a single camera is weakest, and the paper measures
that the stated sigma is slightly optimistic: read a one-sigma band as roughly a 55 per cent bound.
