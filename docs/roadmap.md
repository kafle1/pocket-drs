# Roadmap (build order that avoids pain)

This roadmap is intentionally **boring**. Boring ships.

## Milestone 0 — Tooling + repo hygiene (0.5–1 day)
- Flutter project created.
- Basic CI-ish checks locally (format/analyze).
- Minimal doc set + decision log.

## Milestone 1 — Video in/out + timeline (2–4 days)
Goal: you can record a clip or import one, scrub frames, and see timestamps.
- Record video.
- Extract frames (or decode on the fly).
- Display frame index + time.

## Milestone 2 — Ball tracking MVP (1–2 weeks)
Goal: reliable 2D ball centers over time.
- Start with classical CV (motion + circle/colour) for controlled videos.
- Add a Kalman filter smoother.
- If needed: switch to TFLite detection.
Deliverable: overlay polyline trajectory and confidence.

## Milestone 3 — Calibration MVP (1–2 weeks)
Goal: estimate camera pose relative to pitch/stumps.
- Preferred: printed ArUco/AprilTag markers near stumps/crease.
- Backup: tap-to-mark known points.
Use: OpenCV `solvePnP`.
Deliverable: render a simple 3D axis / wicket box overlay onto video.

## Milestone 4 — 3D reconstruction + prediction (2–3 weeks)
Goal: reconstruct approximate 3D trajectory and predict to wicket.
- Turn 2D track into 3D using constraints (delivery plane + pitch geometry).
- Fit motion parameters (gravity + optional drag).
Deliverable: 3D curve + predicted stump intersection, with error bars.

## Milestone 5 — LBW decision UI (1–2 weeks)
Goal: an umpire-friendly screen.
- Show pitching point, impact point (manual if needed), and wicket zone.
- Provide “in line / pitching outside / missing” summaries.

## Milestone 6 — Optional edge support (2–4 weeks)
Stretch goal.
- Start with **single-device** audio spike detection.
- Then add second-device UDP time sync + alignment if time permits.

## Milestone 7 — Testing + evaluation + report (ongoing; final 2–3 weeks heavy)
- Collect a small dataset of deliveries.
- Evaluate: 2D tracking stability, calibration repeatability, prediction consistency.
- Document limitations honestly (markers, camera angle constraints, lighting).
