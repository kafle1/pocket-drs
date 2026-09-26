# PocketDRS

Get the Android app from the [latest release](https://github.com/kafle1/pocket-drs/releases/latest)
(under 20 MB; [which file to pick](docs/GUIDE.md#get-the-app)). New to the app? Read the
[user guide](docs/GUIDE.md) or the [screen-by-screen walkthrough](docs/WALKTHROUGH.md), or watch the
[36 second app walkthrough](docs/media/app-walkthrough.mp4).

Single-phone leg-before-wicket review for cricket. Put a phone on a tripod behind the bowler's
stumps, mark the stumps once, and press Ball after each delivery. For every ball the server
returns where it pitched, where it would have crossed the stumps, the release speed, the turn off
the pitch, a Law 36 verdict, and how sure it is about each of those.

It is a coaching and training instrument, not an officiating one. Where the estimate cannot
support a call at one sigma the verdict is umpire's call, and where the fit does not explain the
pixels the job returns no verdict rather than a guess.

## How it works

The ball flies from release to the pitch under gravity, air drag and swing, bounces once, and
flies on to the batter under gravity and drag. One camera cannot measure depth, but the bounce
is on a plane the calibration already knows. The contact instant is found in the image as the
split that explains the track with two flights far better than one, and the contact pixel
back-projects onto the ground plane to a metric point with no depth cue. From that anchor a
ten-parameter model (contact time and point, pre-contact velocity, share of pace kept through
the bounce, post-contact sideways velocity, restitution, swing) is refined by robust least
squares. Its covariance, plus the spread from re-solving the calibration with jittered stump
marks, is carried to the stump-plane crossing. When that 1-sigma miss is bigger than the stumps
are tall, the app gives no call instead of guessing.

```
phone clip ─► calibration (PnP on 8 stump corners, pitch length pinned, lens angle swept)
           ─► colour/motion detection ─► RANSAC over calibrated 3-D flights into one delivery
           ─► contact split in the image ─► anchored drag-and-swing fit ─► covariance
           ─► stump-plane prediction ± sigma ─► Law 36 with uncertainty-widened bands
           ─► overlay, metrics, verdict
```

Measured on 150 random synthetic deliveries per cell with exact truth: 60 Hz, 1 px detection
noise, swing, and air drag that changes from ball to ball and that the model doesn't know. The
detections are made up, so this checks the app's calibration, ball picking, fit and call, not
its ball detector. A ball counts as right only when the call matches exactly (out, not out, or
umpire's call), and a no call counts as wrong. `paper/experiments/bench_app.py` reruns it in
about 4 minutes.

| Camera | Stump marks exact | 1 px off | 2 px off | 4 px off | Given out when it wasn't out |
|---|---|---|---|---|---|
| Behind the bowler (the app's setup) | 97% | 95% | 92% | 83% | 0 to 4 in 150 |
| Behind the batter | 97% | 99% | 99% | 96% | none |

Of the 4 wrong outs with marks 4 px off, 3 were umpire's call and 1 was not out.

The rendered clips run the whole pipeline, ball detector included, on 100 clips from each end:
95 right from behind the bowler and 99 from behind the batter. None gave out on a not-out ball
or the other way round. Every miss is one step off, umpire's call against a clear decision. From
behind the bowler the speed is shown on 59 of the 100 balls, with a median error of 5 km/h.
`paper/experiments/exp2_rendered.py --camera bowler_ref` (or `striker_ref`) reruns it in about
15 minutes; point `POCKET_DRS_OUT` and `POCKET_DRS_CLIPS` at a scratch folder so the paper's
files stay as they are.

The paper under `paper/` describes an earlier model, and its numbers are not these.

## Layout

```
server/app/pipeline/
  calibration.py     camera model, stump-anchored PnP
  tracking.py        colour/motion ball detector, pitch ROI
  trajectory.py      picks the ball: RANSAC over 3-D flights that start in a bowler's hand
  reconstruction.py  contact split, anchored drag-and-swing fit, covariance, stump-plane prediction
  decision.py        Law 36 with the ICC review bands widened by the propagated sigma
  overlay.py         pixel-space overlay for the client
  process_job.py     one job end to end; the result schema is the client contract
server/app/           FastAPI job API, job store, 3-D viewer
app/pocket_drs/       Flutter client (Android, iOS, web)
paper/                manuscript, experiments, raw results, figure and number generators
docs/college-report/  the original BIT project report and slides
```

## Run

```bash
make setup          # backend venv + flutter pub get
make dev            # backend on :8000 and the app on a connected phone
```

The server API is public and anonymous: `POST /v1/jobs` (multipart: clip + request JSON),
`GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/result`, and `GET /v1/jobs/{id}/three-d` for the 3D
page. `docs/usage-guide.md` has the request and result fields; `server/scripts/real_clip.py`
builds a request for a bundled clip.

To host the server yourself: `docker build -t pocket-drs-server server && docker run -p 7860:7860 pocket-drs-server`.
The public server is a free Hugging Face Docker Space built from the same `server/` folder, and
`make space` redeploys it.

## Reproduce the paper

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

Every run is seeded. `experiments/synth.py` is the generator (its physics is richer than the
estimator's model on purpose), `experiments/render.py` turns a delivery into a clip the app would
accept.

## Filming

Tripod behind the bowler's stumps, both sets of stumps in frame, a full-length pitch, a red or
pink ball. `docs/usage-guide.md` has the details. A yorker leaves one or two frames after the
bounce and will usually come back as umpire's call.

## Privacy

No accounts, no ads, no analytics. The server deletes each clip once it is analysed.
`docs/privacy-policy.md` lists exactly what leaves the phone.

## License

Copyright (c) 2025-2026 Niraj Kafle.

AGPL-3.0, see `LICENSE`. If you ship or host a changed copy, even only as a server, you must
publish all of its source under AGPL-3.0 too. For a commercial licence without those terms,
write to contact.me.kafle@gmail.com.
