# PocketDRS

Single-phone leg-before-wicket review for cricket. One hand-held clip from behind the batter,
twelve taps on the stumps and pitch corners, and the server returns the delivery in metres:
where it pitched, where it would have crossed the stumps, the release speed, the turn off the
pitch, a Law 36 verdict, and how sure it is about each of those.

It is a coaching and training instrument, not an officiating one. Where the estimate cannot
support a call at one sigma the verdict is umpire's call, and where the fit does not explain the
pixels the job returns no verdict rather than a guess.

## How it works

The ball is a projectile from release to the pitch, bounces once, and is a projectile again to
the batter. One camera cannot measure depth, but the bounce is on a plane the calibration
already knows. The contact instant is found in the image as the split that explains the track
with two parabolas far better than one; the contact pixel back-projects onto the ground plane to
a metric point with no depth cue; and with that anchor fixed the velocities before and after
contact are linear in the pixel measurements. A nine-parameter model (contact time and point,
pre-contact velocity, post-contact horizontal velocity, restitution) is then refined by robust
least squares and its covariance is propagated to the stump-plane crossing.

```
phone clip ─► calibration (PnP on 8 stump corners + 4 pitch corners, FOV and length swept)
           ─► detection (fine-tuned YOLO + colour/motion) ─► RANSAC association into one track
           ─► contact split in the image ─► anchored two-parabola fit ─► covariance
           ─► stump-plane prediction ± sigma ─► Law 36 with uncertainty-widened bands
           ─► overlay, metrics, verdict
```

Measured on synthetic deliveries with exact truth (60 Hz, 1 px noise, 2 px tap error, drag and
swing on): 93% verdict agreement, median stump-plane error 2.4 cm lateral and 3.4 cm vertical, six
false outs in 9110 not-out deliveries. Through the full pipeline on rendered clips: 77 of 100 with no
false out. The paper under `paper/` has every number and the scripts that produce them.

## Layout

```
server/app/pipeline/
  calibration.py     camera model, stump-anchored PnP, back-projection
  tracking.py        YOLO and colour/motion ball detectors, pitch ROI
  trajectory.py      RANSAC association of detections into one arc, bounce stitching
  reconstruction.py  contact split, anchored two-parabola fit, covariance, stump-plane prediction
  decision.py        Law 36 with the ICC review bands widened by the propagated sigma
  overlay.py         pixel-space overlay for the client
  process_job.py     one job end to end; the result schema is the client contract
server/app/           FastAPI job API, Firebase auth, job store, 3-D viewer
server/models/        cricket_ball.pt, the fine-tuned detector
app/pocket_drs/       Flutter client (Android, iOS, web)
paper/                manuscript, experiments, raw results, figure and number generators
docs/college-report/  the original BIT project report and slides
```

## Run

```bash
make setup          # backend venv + flutter pub get
make dev            # backend on :8000 and the app on a connected phone
```

Put Firebase credentials in `server/firebase-service-account.json` and the app's
`firebase_options.dart`; both are gitignored. The API is `POST /v1/jobs` (multipart: clip +
request JSON), `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/result`. The request needs the segment,
the sampling rate, the twelve calibration taps in normalised image coordinates, the pitch
dimensions and the batter's handedness; `server/scripts/test3_e2e.py` builds one.

## Reproduce the paper

```bash
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

Behind the batter, phone held still, both sets of stumps in frame, 60 Hz or more if the phone
offers it. The bowler's end works but the decisive arc is far away and foreshortened; the paper
measures the difference. A yorker leaves one or two frames after the bounce and will usually come
back as umpire's call.

## License

AGPL-3.0. See `LICENSE`.
