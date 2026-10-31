# PocketDRS

Leg-before-wicket review for cricket with one phone. Put the phone on a tripod behind the bowler's
stumps, mark the stumps once, and press Ball after each delivery. The server sends back where the
ball pitched, where it would have crossed the stumps, the release speed, the turn off the pitch, a
Law 36 verdict, and how sure it is about each.

<img src="docs/media/app-walkthrough.jpg" alt="Result screen with the verdict and the tracked ball" width="300">

It is meant for coaching and practice, not for officiating. If the estimate can't support a call at
one sigma, it says umpire's call. If the fit doesn't explain the pixels, it gives no verdict.

Get the Android app from the [latest release](https://github.com/kafle1/pocket-drs/releases/latest)
(under 20 MB; [which file to pick](docs/GUIDE.md#get-the-app)), or use the
[website](https://pocketdrs-saarathi.centralindia.cloudapp.azure.com) on any phone, iPhone included.
Both need a Google sign-in. Every account and every phone gets 5 free reviews, then **Contact admin**
asks for premium. See the [user guide](docs/GUIDE.md) or the
[36 second app walkthrough](docs/media/app-walkthrough.mp4).

## How it works

The phone is calibrated from the 8 stump corners you mark. The ball is found by colour and motion,
and RANSAC over 3-D flights picks out the delivery. One camera can't measure depth, but the bounce
is on the ground plane, so the contact pixel gives a metric anchor. From there a drag-and-swing
model is fitted, and its uncertainty is carried to the stump plane and into the Law 36 bands.

## Results

Synthetic test: 150 random deliveries per cell at 60 Hz, 1 px detection noise, swing, and air drag
that changes from ball to ball and that the model doesn't know. The detections are made up, so the
ball detector isn't tested here. Only an exact call counts as right, and a no call counts as wrong. `paper/experiments/bench_app.py` reruns it in about 4 minutes.

| Camera | Stump marks exact | 1 px off | 2 px off | 4 px off | Given out when it wasn't out |
|---|---|---|---|---|---|
| Behind the bowler (the app's setup) | 97% | 95% | 92% | 83% | 0 to 4 in 150 |
| Behind the batter | 97% | 99% | 99% | 96% | none |

Of the 4 wrong outs with marks 4 px off, 3 were umpire's call and 1 was not out.

On rendered clips the whole pipeline runs, ball detector included. Of 100 clips from each end, 95
were right from behind the bowler and 99 from behind the batter. None gave out on a not-out ball
or the other way round. Every miss is one step off, umpire's call against a clear decision. From
behind the bowler the speed is shown on 59 of the 100 balls, with a median error of 5 km/h.
`paper/experiments/exp2_rendered.py --camera bowler_ref` (or `striker_ref`) reruns it in about
15 minutes. Point `POCKET_DRS_OUT` and `POCKET_DRS_CLIPS` at a scratch folder so the paper's files
stay as they are.

The paper under `paper/` describes an earlier model, and its numbers are not these.

## Run

```bash
make setup     # server venv + flutter pub get
make dev       # the app on a connected phone, against the public server
make server    # the server locally on :8000 (make dev SERVER_URL=http://<your-ip>:8000 to use it)
make apk       # release apks, one per phone chip
make deploy    # copy server/ to the Azure VM, rebuild the Docker container behind Caddy
make logs      # follow the live server's log
```

The server is FastAPI. It serves the website at `/` and the admin page at `/admin`, keeps accounts
in SQLite under `/data`, and gives admin rights to the emails in `ADMIN_EMAILS`. `server/README.md`
has the details.

### API

Starting a job needs a Firebase ID token (`Authorization: Bearer`) and an `X-Device-Id` header.
After that the job id is the only access control.

- `POST /v1/jobs`, multipart `video_file` + `request_json`, starts a job
- `GET /v1/jobs/{id}` gives `status` and `progress`
- `GET /v1/jobs/{id}/result` gives the result once `status` is `succeeded`
- `GET /v1/jobs/{id}/three-d` is the 3D view as a web page

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

`stump_quads_px` takes the same points in pixels. The lens angle is not an input: the server works
it out from how big the far stumps look next to the near ones.

| Result field | Meaning |
|---|---|
| `lbw.decision`, `lbw.reason`, `lbw.checks` | `out`, `not_out` or `umpires_call`, why, and the three Law 36 tests |
| `lbw.prediction` | where the ball crosses the stump plane, with one-sigma bounds |
| `events.bounce`, `events.impact` | the pitching point (null with no bounce seen) and where the track ended |
| `metrics` | speed (null when its one-sigma spread is over 8 km/h), swing in cm, spin in degrees |
| `overlay.*` | pixel paths for drawing on the clip |
| `diagnostics.warnings` | anything worth knowing, including why a verdict was declined |

Each Law 36 test is compared with the ICC review band (one ball radius), widened to the one-sigma
bound when that is larger. A verdict is only decisive when every test clears its band.

`server/scripts/real_clip.py test3` runs a bundled clip in process and draws the overlay under
`dump/validation/test3/`.

## Reproduce the paper

The paper in `paper/` is under review at IEEE Transactions on Instrumentation and Measurement.
The paper's numbers come from the code at the `paper-v1` tag, so check that out first.

```bash
git checkout paper-v1
cd paper
../server/.venv/bin/python experiments/exp1_geometry.py     # ~75 min, 21 600 reconstructions
../server/.venv/bin/python experiments/exp2_rendered.py     # ~55 min, renders and runs 100 clips
../server/.venv/bin/python experiments/exp3_real.py         # ~10 min, the three real clips
../server/.venv/bin/python experiments/make_numbers.py      # numbers.tex and tables/
../server/.venv/bin/python experiments/make_figures.py
pdflatex main && bibtex main && pdflatex main && pdflatex main
../server/.venv/bin/python experiments/verify_claims.py     # fails if the manuscript is stale
```

Every run is seeded. `experiments/synth.py` makes the deliveries and `experiments/render.py` turns
them into clips.

## Filming

Tripod behind the bowler's stumps, both sets of stumps in frame, a red or pink ball, 60 frames a
second (in-app recording sets it; on an iPhone use Settings, Camera, Record Video, 1080p at 60 fps).
Yorkers usually come back as umpire's call. The [user guide](docs/GUIDE.md) has the details.

## Privacy

You sign in with Google, and the app sends usage events to Google Analytics for Firebase. The server
deletes each clip after analysis, and `docs/privacy-policy.md` lists what is kept and for how long.

## License

Copyright (c) 2025-2026 Niraj Kafle.

AGPL-3.0, see `LICENSE`. If you ship or host a changed copy, even only as a server, its full source
must be published under AGPL-3.0 too. For a commercial licence, write to contact.me.kafle@gmail.com.

`server/app/static/three` is three.js, copied in unchanged under its own MIT licence.
