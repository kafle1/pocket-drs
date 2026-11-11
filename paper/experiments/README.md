# Experiments

Every number, table and figure in the paper comes from a script here. Scripts write raw results
to `raw/`, `make_numbers.py` turns them into `../numbers.tex` and `../tables/*.tex`,
`make_figures.py` into `../figures/*.pdf`, and `verify_claims.py` checks that the manuscript
quotes only what the raw files say. Every script is seeded and gives the same output for any
worker count.

Run everything with the server's environment, built from the pinned list that produced `raw/`:

```sh
uv venv --python 3.12.2 server/.venv
uv pip install --python server/.venv/bin/python -r paper/experiments/requirements-frozen.txt
PY=$PWD/server/.venv/bin/python
cd paper/experiments
```

exp6_calibrate.py writes the calibrated rule to `raw/exp6_rule.json`, and exp7 adds its guard factor and
ships it complete as `server/app/pipeline/calibrated_rule.json`; exp2, exp3, exp8, false_dets and exp10 read that file, so run
them after exp7.

## Order and commands

| Step | Command | Needs | Writes | Runtime |
|---|---|---|---|---|
| exp6 coverage and model error, both camera ends and both hands | `$PY exp6_coverage.py --n 1200 --n-sweep 200 --workers 4` | nothing | `raw/exp6_worldb.csv`, `raw/exp6_sweeps.csv`, `raw/exp6_model_error.json` | 398 s (4) |
| exp6 calibration per camera end (bias line or none by the five folds' summed held-out likelihood, model form chosen held out, conformal factors by bounce-distance third) | `$PY exp6_calibrate.py` | exp6 | `raw/exp6_calibrated.csv`, `raw/exp6_calibrated.json`, `raw/exp6_rule.json` | 8 s |
| exp7 JCGM 106 guard band | `$PY exp7_risk.py` | exp6, exp6 calibration | `raw/exp7_risk_curve.csv`, `raw/exp7_risk.json`, `server/app/pipeline/calibrated_rule.json` | 2 s |
| exp1 geometry sweeps | `$PY exp1_geometry.py --workers 4` | nothing | `raw/exp1_geometry.csv`, `raw/exp1_config.json` | 390 s (4); the reference setting runs once, every row reuses the same 400 deliveries |
| exp1 calibration ablation | `$PY exp1_geometry.py --ablation --workers 4` | nothing | `raw/exp1_ablation.csv`, `raw/exp1_ablation_config.json` | 128 s (4) |
| exp8 unmodelled physics and tap perturbation | `$PY exp8_physics.py --workers 4` | exp6, exp7 | `raw/exp8_physics.csv`, `raw/exp8_taps.csv`, `raw/exp8_physics.json` | 346 s (4) |
| exp9 frame rate | `$PY exp9_fps.py --workers 4` | nothing | `raw/exp9_fps.csv`, `raw/exp9_fps.json` | 65 s (4) |
| exp4 JCGM 100 budget | `$PY exp4_budget.py --workers 4` | nothing | `raw/exp4_budget_rep.csv`, `raw/exp4_budget_dist.csv`, `raw/exp4_budget.json` | 481 s (4) |
| exp5 JCGM 101 Monte Carlo | `$PY exp5_mc.py --workers 4` | exp4 | `raw/exp5_mc_rep.csv`, `raw/exp5_mc_subset.csv`, `raw/exp5_mc.json` | 1102 s (4) |
| exp2 rendered clips | `$PY exp2_rendered.py` | `server/models/cricket_ball.pt`, exp7 | `raw/exp2_rendered_striker_ref.csv`, `raw/exp2_config_striker_ref.json` | 1149 s (1) |
| exp2 from the bowler's end | `$PY exp2_rendered.py --camera bowler_ref` | as exp2 | `raw/exp2_rendered_bowler_ref.csv`, `raw/exp2_config_bowler_ref.json` | 859 s (1) |
| false detections | `$PY false_dets.py` | `server/models/cricket_ball.pt`, exp7 | `raw/false_dets_filtered.csv`, `.json` | 482 s (1) |
| exp3 real clips | `$PY exp3_real.py` | `server/models/cricket_ball.pt`, the clips, exp7 | `raw/exp3_real.csv` | 341 s (1) |
| exp10 real-world checks on the real clips | `$PY exp10_real.py` | `server/models/cricket_ball.pt`, the clips, exp1 ablation, exp7 | `raw/exp10_config.json`, `raw/exp10_real.json` (with the gravity fit on 200 simulated deliveries), `raw/exp10_size.csv` | 142 s (1) |
| scoreboard: both rendered ends and test3 to test5 in one table, for comparing pipeline changes | `$PY scoreboard.py --workers 8 [--dump DIR]` | `server/models/cricket_ball.pt`, the clips, exp7 | prints only | about 40 min (8) on a loaded machine |
| calibration lower-bound check | `$PY ../theory/calib_check.py` | nothing | `../theory/out/calib_check.txt` | 5 s |
| macros and tables | `$PY make_numbers.py` | whatever raw files exist | `../numbers.tex`, `../tables/*.tex` | seconds |
| figures | `$PY make_figures.py` | exp1, exp6, exp7 | `../figures/*.pdf` | seconds |
| check | `$PY verify_claims.py` | all of the above | prints OK or the mismatches | seconds |

Runtimes are wall-clock from the `seconds` field each script writes to its json, measured on
an 11-core M3 Pro while other jobs ran, so they vary from run to run. `--quick` on exp1, exp4, exp5 and exp6 runs a small
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
whether it reaches the track or the verdict.

## Shared code

- `synth.py`: flight model, synthetic cameras, observation noise, truth verdict (exp1, exp2).
- `uq.py`: the uncertainty layer used by exp4 to exp9: effect PDFs, frame-time models
  (the submitted 17 ms sampler and the fixed one), rolling shutter, lens distortion, the calibration
  sigma, the verdict and the JCGM 106 specific risk.
- `render.py`: turns a synthetic delivery into video for exp2.
