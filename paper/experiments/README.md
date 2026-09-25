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
| exp1 geometry sweeps | `$PY exp1_geometry.py --workers 8` | nothing | `raw/exp1_geometry.csv`, `raw/exp1_config.json` | 1681.8 s (8 workers) |
| exp1 calibration ablation | `$PY exp1_geometry.py --ablation --workers 5` | nothing | `raw/exp1_ablation.csv`, `raw/exp1_ablation_config.json` | 1137.6 s (5) |
| exp2 rendered clips | `$PY exp2_rendered.py` | `server/models/cricket_ball.pt` | `raw/exp2_rendered_striker_ref.csv`, `raw/exp2_config_striker_ref.json` | BLOCKED ON WEIGHTS |
| exp3 real clips | `$PY exp3_real.py` | `server/models/cricket_ball.pt`, the clips | `raw/exp3_real.csv` | BLOCKED ON WEIGHTS |
| exp4 JCGM 100 budget | `$PY exp4_budget.py --workers 6` | nothing | `raw/exp4_budget_rep.csv`, `raw/exp4_budget_dist.csv`, `raw/exp4_budget.json` | 3399.4 s (6) |
| exp5 JCGM 101 Monte Carlo | `$PY exp5_mc.py --workers 6` | exp4 | `raw/exp5_mc_rep.csv`, `raw/exp5_mc_subset.csv`, `raw/exp5_mc.json` | 1350.3 s (6) |
| exp6 coverage and model error | `$PY exp6_coverage.py --n 600 --n-sweep 200 --workers 5` | nothing | `raw/exp6_worldb.csv`, `raw/exp6_sweeps.csv`, `raw/exp6_model_error.json` | 2811.0 s (5) |
| exp7 JCGM 106 guard band | `$PY exp7_risk.py` | exp6 | `raw/exp7_risk_curve.csv`, `raw/exp7_risk.json` | 3.6 s |
| exp8 unmodelled physics | `$PY exp8_physics.py --part physics --workers 3` | exp6 (for sigma_mod) | `raw/exp8_physics.csv` | 2357.4 s (3) |
| exp8 tap perturbation | `$PY exp8_physics.py --part taps --workers 3` | exp6, exp7 | `raw/exp8_taps.csv` | 324.3 s (3) |
| exp8 summary | `$PY exp8_physics.py --summary-only` | both exp8 parts, exp7 | `raw/exp8_physics.json` | seconds |
| exp9 frame rate | `$PY exp9_fps.py --workers 3` | nothing | `raw/exp9_fps.csv`, `raw/exp9_fps.json` | 665.0 s (3) |
| macros and tables | `$PY make_numbers.py` | whatever raw files exist | `../numbers.tex`, `../tables/*.tex` | seconds |
| figures | `$PY make_figures.py` | exp1, exp7 | `../figures/*.pdf` | seconds |
| check | `$PY verify_claims.py` | all of the above | prints OK or the mismatches | seconds |
| edit plan | `sh editplan/build.sh` | macros, tables, figures | the edited paper in a temp dir; prints the page count | 2 s |

Runtimes are wall-clock from the `seconds` field each script writes to its json, measured on
an 11-core M3 Pro that was running other jobs at the same time (load average about 50), so a
quiet machine is several times faster. `--quick` on exp1, exp4, exp5 and exp6 runs a small
version for a smoke check; it overwrites the raw files, so rerun the full command after.

`make_numbers.py` guards each block on its raw file, so a missing experiment drops its macros
and tables rather than failing.

`../tables/budget.tex` is the per-input budget for the supplement; `../tables/budget_short.tex` groups the
same rows for the paper. `editplan/` holds the proposed main.tex changes: `apply_edits.py` applies
them to a copy made by `build.sh`, never to `paper/` itself (see section 12 of the notes).

## exp2 and exp3: blocked on weights

Both run the full app pipeline, detector included (`run_pipeline`, `detector: "auto"`), and
the learned detector loads `server/models/cricket_ball.pt` (`process_job.py:50`). That file
is not in the repo, so neither script can be rerun as the paper describes. The committed
`raw/exp2_*` and `raw/exp3_real.csv` are the real 2026-09-02 runs and are left untouched.
They were made before the Law 8 width, ICC band and focal-length fixes, so their verdicts
and truth labels are on the old 26.4 cm wicket. Swapping in the colour detector would run,
but it is a different detector from the paper's, so it was not done.

## Shared code

- `synth.py`: flight model, synthetic cameras, observation noise, truth verdict (exp1, exp2).
- `uq.py`: the uncertainty layer used by exp4 to exp9: effect PDFs, frame-time models
  (including the shipped 17 ms sampler), rolling shutter, lens distortion, the calibration
  sigma, the verdict and the JCGM 106 specific risk.
- `render.py`: turns a synthetic delivery into video for exp2.
