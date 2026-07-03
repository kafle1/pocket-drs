# Pocket DRS

**Phone-based, single-camera cricket LBW review**

PocketDRS reconstructs a cricket delivery in 3-D from a single hand-held phone
clip, predicts the ball's path onto the stumps, and returns an ICC-Rule-36 LBW
verdict with a broadcast-style overlay. It is built for grassroots cricket,
coaching, and training review — one phone instead of the six-to-eight
calibrated high-speed cameras a broadcast DRS rig uses.

It is **not** a substitute for officiating DRS, and it is not ICC-certified.
Where a single viewpoint is strong (the line of the ball) it is accurate to
sub-centimetre; where one camera is inherently weak (depth: absolute speed and
the exact down-pitch position of the bounce) it is coarse and reports those as
indicative. See **Accuracy** below for the measured numbers, honestly stated.

---

## 🎯 What it does

- **Single-phone ball tracking** from an ordinary 60–120 fps clip
- **Stump-anchored calibration** from a few taps — no checkerboard, no rig
- **Physics-constrained monocular 3-D reconstruction** (gravity + a single
  restitution bounce), refined by bundle adjustment
- **Trajectory prediction** to the stump plane by forward projectile integration
- **ICC-Rule-36 LBW engine** — pitching-in-line, impact-in-line, wickets-hitting,
  with handedness-aware off/leg and monocular umpire's-call margins
- **Hawk-Eye-style overlay** drawn back onto the source video, plus a Three.js 3-D view

---

## 🏗️ Pipeline

```
📱 Phone clip (60–120 fps, portrait)
  ↓
📐 Stump-anchored calibration — PnP from the tapped pitch corners + the two
   stump rectangles; jointly fits camera FOV and pitch length when unpinned
  ↓
🎯 Ball detection — learned YOLO detector + classical HSV colour/motion,
   fused by a clutter-aware auto-selector
  ↓
📈 Trajectory fit — RANSAC projectile arc over the per-frame detections
  ↓
📏 3-D reconstruction — depth-from-apparent-size seeds metric scale; a
   gravity + restitution-bounce model is fit and bundle-adjusted
  ↓
🔮 Prediction — forward-integrate the post-bounce projectile to the stump plane
  ↓
⚖️ LBW decision — ICC Rule 36, handedness-aware, anisotropic umpire's-call bands
  ↓
🎥 Overlay — flight (from the observed detections) + predicted corridor + verdict
```

There is no Extended Kalman Filter and no checkerboard intrinsic step; scale
comes from the known regulation stump geometry, and the trajectory is recovered
by RANSAC plus a gravity-constrained least-squares fit.

---

## 📂 Project structure

```
pocket-drs/
├── server/                          # Python backend (FastAPI)
│   └── app/
│       ├── main.py                  # HTTP API (jobs, status, result, 3-D, artifacts)
│       ├── jobs.py                  # Job store + orphan recovery
│       ├── models.py                # Pydantic request/response models
│       ├── three_d_viewer.py        # Three.js viewer HTML
│       └── pipeline/
│           ├── calibration.py       # Shared calibration error type
│           ├── tracking.py          # YOLO + HSV/motion ball detectors
│           ├── trajectory.py        # RANSAC projectile fit, clutter suppression
│           ├── reconstruction.py    # Camera solve, 3-D lift, prediction, overlay
│           ├── process_job.py       # Pipeline orchestration + LBW decision
│           └── video.py             # Frame decoding / sampling
├── app/pocket_drs/                  # Flutter mobile app (lib/, android/, ios/)
├── server/scripts/                  # synth_validate.py, test{3,4,5}_e2e.py
└── docs/usage-guide.md
```

---

## 🚀 Quick start

```bash
# Backend
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                        # serves on :8000 (needs Firebase config)

# Flutter app
cd app/pocket_drs && flutter pub get && flutter run

# Or use the Makefile from the repo root
make setup && make dev
```

Offline validation (no server / Firebase needed):

```bash
cd server
.venv/bin/python scripts/synth_validate.py      # synthetic ground-truth sweep
.venv/bin/python scripts/test3_e2e.py           # real net clip, end-to-end
```

---

## 📊 Accuracy (measured, not aspirational)

Synthetic ground-truth sweep (8 rendered deliveries with known physics):

| Metric | Result |
|--------|--------|
| LBW decision agreement | **8 / 8 (100%)** |
| Predicted position at the stumps | 11.7 cm mean — lateral 0.3 cm, vertical 11.7 cm |
| Bounce localisation | 54.6 cm (almost entirely down-pitch; lateral ~0.5 cm) |
| Release speed | ~22 km/h mean error — **indicative only** |

The error is strongly anisotropic and this is fundamental, not a bug: a single
camera resolves the **line** of the ball (the coordinate that decides an LBW)
to sub-centimetre, while the **depth** axis (down-pitch distance, absolute
speed) is the least observable and carries essentially all of the error as
zero-mean noise. Closing that gap needs a second viewpoint, not more single-view
processing. Full analysis and per-axis decomposition are in the paper
(`dump/report_docs/pocketdrs_paper.tex`).

**Best on:** a fixed phone behind the bowler or striker, both stump sets clearly
in frame, a rectilinear (non-fisheye) lens, ball visually distinct.
**Declines gracefully on:** fisheye/occluded/short clips — it refuses rather
than emitting a confident wrong verdict.

---

## 🛠️ Development

```bash
make dev          # backend + Flutter app
make dev-server   # backend only
make server-test  # backend tests
make logs         # tail server logs
```

**Stack:** Python 3.12, FastAPI, OpenCV, NumPy/SciPy, Ultralytics YOLO,
firebase-admin (backend); Flutter/Dart, Three.js (frontend).

---

## 📝 License

**Proprietary — All Rights Reserved.** Copyright (c) 2025-2026 Niraj Kafle.
No copying, use, modification, distribution, or ML training on any part of
this repository without prior written permission. See [LICENSE](LICENSE).

---

## 🙏 Acknowledgments

Methodology draws on: Zhang's camera calibration; Hartley & Zisserman,
*Multiple View Geometry*; Ribnick et al. on 3-D from monocular projectile
views; the YOLO detector family; Fischler & Bolles (RANSAC); and Hawk-Eye's
published ball-tracking approach.

**Built for research and educational purposes. Not affiliated with the ICC or
Hawk-Eye. Not a certified officiating system.**
