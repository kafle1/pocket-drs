# PocketDRS usage guide

## 1. Setting up

- Put the phone on a tripod a couple of metres behind the bowler's stumps, in portrait, so both
  sets of stumps are in frame.
- The app assumes a full-length pitch (22 yards, 20.12 m between the stumps). On a shorter net,
  set the real length in Settings > Pitch length, or every distance and the speed come out scaled.
- Use the main lens, not the ultra-wide: its distortion is not modelled.
- Use a red or pink ball. The app doesn't track a white ball yet.

## 2. The app flow

1. Tap **Start a session**. The camera starts recording.
2. Mark the stumps once: the striker's (far) set, then the bowler's (near) set, each top-left,
   top-right, bottom-right, bottom-left. Pinch to zoom for the taps, then drag any mark to
   fine-tune it; a magnifier shows the spot under your finger.
3. Pick the batter's handedness.
4. After each delivery press **Ball** or a volume key. The app cuts the last 4 seconds and sends them
   off; the result shows up in the list when the server is done.
5. Open a ball to see the tracked flight, the predicted path to the stumps, the pitching point,
   the speed, and the verdict with its reason.

**Analyse a video** does the same for one clip you already have: pick it, trim it to the delivery,
mark the stumps, submit.

Don't move the tripod during a session. If it gets knocked, start a new session and mark again.

## 3. Reading the verdict

The three Law 36 tests are applied to the pitching point, where the tracked ball stopped (pad or
bat), and the predicted crossing of the stump plane. Each is compared with the ICC review band
(within one ball radius of a boundary is umpire's call), widened to the one-sigma bound when that
is larger. That bound counts both the scatter of the tracked ball and how far off the stump marks
could be. A verdict is only decisive when every test is clear of its band.

The app can't tell bat from pad. If the ball hit the bat first it isn't out, whatever the verdict
says.

The flight is modelled with gravity, air drag, and swing up to the bounce. After the bounce the
ball is assumed to carry on under gravity and drag alone, with no further sideways curve.

No verdict comes back when the stumps were marked badly, when the tracked ball doesn't fit a
bouncing ball in flight, or when the predicted path is too unsure to call (its one-sigma miss at
the stumps is bigger than the stumps are tall, usually a short clip or a ball seen for only a few
frames). The warnings say which. The speed is left out when the clip can't pin it
to within about 8 km/h, which happens when the bounce is out of view or only a few frames
of the ball were seen.

## 4. The HTTP API

`POST /v1/jobs` (multipart: `video_file` + `request_json`) starts a job; `GET /v1/jobs/{id}` polls
`status` and `progress`; `GET /v1/jobs/{id}/result` returns the result once `status` is `succeeded`;
`GET /v1/jobs/{id}/three-d` is the 3D view as a web page. The API is public and anonymous; the
job id is the only access control.

Request (unknown fields are rejected):

```json
{
  "segment": {"start_ms": 0, "end_ms": 4000},
  "tracking": {"sample_fps": 60, "max_frames": 240},
  "calibration": {
    "pitch_dimensions_m": {"width": 3.05, "length": 20.12},
    "stump_quads_norm": [8 points: striker TL, TR, BR, BL, then bowler TL, TR, BR, BL]
  },
  "batsman_handedness": "right"
}
```

`stump_quads_px` takes the same eight points in pixels instead. The lens angle is not an input:
the server finds it from how big the far stumps look next to the near ones.

Result, the fields the app reads:

| Field | Meaning |
|---|---|
| `lbw.decision`, `lbw.reason` | `out`, `not_out` or `umpires_call`, and why |
| `lbw.checks` | `pitching_in_line`, `impact_in_line`, `wickets_hitting` |
| `lbw.prediction.y_at_stumps_m`, `z_at_stumps_m` | where the ball crosses the stump plane |
| `lbw.prediction.sigma_y_m`, `sigma_z_m` | one-sigma bounds, from the fit and the stump marks together |
| `events.bounce` | pitching point with `sigma_x_m`, `sigma_y_m`; the point is null with no bounce seen, the sigma fields are not |
| `events.impact` | where the track ended (bat or pad) |
| `metrics.speed_kmh`, `speed_mph`, `swing_cm`, `spin_deg` | release speed in km/h and mph, sideways movement in the air (cm), turn off the pitch (degrees). Speed is null when its one-sigma spread is over 8 km/h, swing and spin when no bounce was seen. Swing and spin are rough guides |
| `overlay.*` | pixel-space flight, predicted path, stumps, corridor for drawing on the clip |
| `calibration.quality` | reprojection error (px) of the stump marks, notes |
| `diagnostics.warnings` | anything the pipeline wants you to know, including why a verdict was declined |

## 5. Offline, without the app

`server/scripts/real_clip.py test3` builds the request for a bundled clip, runs the job in
process, and renders the overlay under `dump/validation/test3/`. Add a clip by putting its eight
stump marks in the table at the top of that script.
