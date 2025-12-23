# PocketDRS (Pocket Decision Review System)

Offline, mobile-first prototype that uses **single-view video** (one smartphone camera) to reconstruct and predict a cricket ball trajectory (LBW assistance) and optionally sync a second phone as a stump microphone (edge assistance).

> Current status: **planning + scaffolding**. The proposal is ambitious; we’ll ship this by building an MVP in small, testable steps and only then adding “fancier” physics and audio sync.

## What “done” means (project definition)
A **working Android prototype** that can:
1. Record or load a delivery video.
2. Track the ball over time (2D trajectory overlay).
3. Calibrate the scene (camera pose w.r.t. pitch/stumps) using known geometry or markers.
4. Reconstruct an approximate 3D path and predict the path to the stumps.
5. Visualize pitching/impact/wicket regions and output an LBW suggestion.

Optional stretch goal:
- Second-device audio capture and **frame-aligned** audio-video correlation for edge assistance.

## Repo contents
- `proposal.txt` — submitted proposal draft.
- `architecture.png` — high-level pipeline diagram.
- `docs/` — research notes + build plan + decisions.

## Start here
- Answer the short questions in `docs/00-questions.md`.
- Follow the build plan in `docs/roadmap.md`.

## App code
Flutter app lives at:
- `app/pocket_drs/`

To run locally (Android preferred for this project), open that folder in VS Code and run using the Flutter extension (or your usual Flutter workflow).

## Guiding principles (how we avoid getting stuck)
- **MVP first**: a “good-enough” demo beats an unfinished perfect system.
- **De-risk early**: ball tracking + calibration are the hardest; we validate them first.
- **Manual interactions are allowed** in a student prototype (e.g., tap stumps/crease, choose impact frame) if automation is too risky.

## License
TBD (we’ll set this when we start adding code/assets).