# Experiments

Every number, table and figure in the paper comes from a script here. Scripts write raw results
to `raw/`, `make_numbers.py` turns them into `../numbers.tex` and `../tables/*.tex`,
`make_figures.py` into `../figures/*.pdf`, and `verify_claims.py` checks that the manuscript
quotes only what the raw files say. Every script is seeded and gives the same output for any
worker count.

Run everything from the repo root with the server's environment:

```sh
PY=server/.venv/bin/python
cd paper/experiments
```

## Order and commands

| Step | Command | Needs | Writes | Runtime |
|---|---|---|---|---|
| exp1 geometry sweeps | `$PY exp1_geometry.py --workers 4` | nothing | `raw/exp1_geometry.csv`, `raw/exp1_config.json` | 228.0 s (4 workers); every row reuses the same 400 deliveries |
| exp1 calibration ablation | `$PY exp1_geometry.py --ablation --workers 4` | nothing | `raw/exp1_ablation.csv`, `raw/exp1_ablation_config.json` | 83.8 s (4) |
| exp2 rendered clips | `$PY exp2_rendered.py` | `server/models/cricket_ball.pt` | `raw/exp2_rendered_striker_ref.csv`, `raw/exp2_config_striker_ref.json` | 869.3 s (1) |
| exp3 real clips | `$PY exp3_real.py` | `server/models/cricket_ball.pt`, the clips | `raw/exp3_real.csv` | about 3 min (1) |
| exp4 JCGM 100 budget | `$PY exp4_budget.py --workers 4` | nothing | `raw/exp4_budget_rep.csv`, `raw/exp4_budget_dist.csv`, `raw/exp4_budget.json` | 717.6 s (4) |
| exp5 JCGM 101 Monte Carlo | `$PY exp5_mc.py --workers 4` | exp4 | `raw/exp5_mc_rep.csv`, `raw/exp5_mc_subset.csv`, `raw/exp5_mc.json` | 1268.2 s (4) |
| exp6 coverage and model error | `$PY exp6_coverage.py --n 600 --n-sweep 200 --workers 4` | nothing | `raw/exp6_worldb.csv`, `raw/exp6_sweeps.csv`, `raw/exp6_model_error.json` | 409.0 s (4) |
| exp6 calibration (height bias, split-conformal factors, held out) | `$PY exp6_calibrate.py` | exp6 | `raw/exp6_calibrated.csv`, `raw/exp6_calibrated.json` | about 1 s |
| exp7 JCGM 106 guard band | `$PY exp7_risk.py` | exp6, exp6 calibration | `raw/exp7_risk_curve.csv`, `raw/exp7_risk.json` | 0.5 s |
| exp8 unmodelled physics | `$PY exp8_physics.py --part physics --workers 4` | exp6 (for sigma_mod) | `raw/exp8_physics.csv` | 163.5 s (4) |
| exp8 tap perturbation | `$PY exp8_physics.py --part taps --workers 4` | exp6, exp7 | `raw/exp8_taps.csv` | 59.7 s (4) |
| exp8 summary | `$PY exp8_physics.py --summary-only` | both exp8 parts, exp7 | `raw/exp8_physics.json` | seconds |
| false detections | `$PY false_dets.py`, then `--root DIR --tag before` | `server/models/cricket_ball.pt` | `raw/false_dets_{filtered,before}.csv`, `.json` | 474.9 s and 467.4 s (1 each) |
| exp9 frame rate | `$PY exp9_fps.py --workers 4` | nothing | `raw/exp9_fps.csv`, `raw/exp9_fps.json` | 69.5 s (4) |
| macros and tables | `$PY make_numbers.py` | whatever raw files exist | `../numbers.tex`, `../tables/*.tex` | seconds |
| figures | `$PY make_figures.py` | exp1, exp7 | `../figures/*.pdf` | seconds |
| check | `$PY verify_claims.py` | all of the above | prints OK or the mismatches | seconds |

Runtimes are wall-clock from the `seconds` field each script writes to its json, measured on
an 11-core M3 Pro at `nice -n 10` while other jobs ran, so they vary from run to run. `--quick` on exp1, exp4, exp5 and exp6 runs a small
version for a smoke check; it overwrites the raw files, so rerun the full command after.

`make_numbers.py` guards each block on its raw file, so a missing experiment drops its macros
and tables rather than failing.

`../tables/budget.tex` is the per-input budget for the supplement; `../tables/budget_short.tex` groups the
same rows for the paper.

## exp2 and exp3: the retrained detector

Both run the full app pipeline, detector included (`run_pipeline`, `detector: "auto"`), and
the learned detector loads `server/models/cricket_ball.pt` (`process_job.py:50`). The submitted
weights were never in the repo, so the detector was retrained on photos and cricket video frames;
`server/models/DETECTOR.md` says how to rebuild it, and git ignores the `.pt` itself. `raw/exp2_*`,
`raw/exp3_real.csv` and `raw/false_dets_*` are the runs on those weights (sha1 `c3cdaba4`).
The 2026-09-02 runs the submission quoted (submitted code, submitted detector, old 26.4 cm wicket)
are kept as `raw/exp2_*_submitted.*` and `raw/exp3_real_submitted.csv`, and the false-detection runs on
the earlier photo-only weights (sha1 `43983dcc`) as `raw/false_dets_*_old.*`. `make_numbers.py`
reads only the plain names.

`false_dets.py` checks the false-detection filter on rendered clips only, never on the exp3 clips:
it adds one fake 90 px box to the learned detector's output on 8 exp2 deliveries and reports
whether it reaches the track or the verdict. `--root DIR --tag before` runs another checkout,
for example the code before the filter (`git archive 0893393 server | tar -x -C DIR`).

## Shared code

- `synth.py`: flight model, synthetic cameras, observation noise, truth verdict (exp1, exp2).
- `uq.py`: the uncertainty layer used by exp4 to exp9: effect PDFs, frame-time models
  (the submitted 17 ms sampler and the fixed one), rolling shutter, lens distortion, the calibration
  sigma, the verdict and the JCGM 106 specific risk.
- `render.py`: turns a synthetic delivery into video for exp2.
