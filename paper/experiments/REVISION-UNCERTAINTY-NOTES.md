# Revision notes: measurement uncertainty (TIM-26-10891)

Everything below comes from files under `paper/experiments/raw/`, produced by the scripts named
next to each result. Run commands and runtimes are in `README.md`. Macro names in brackets are
what `make_numbers.py` writes to `numbers.tex`, so the paper can quote the same value.

## 0. Before the uncertainty work: the geometry was wrong

Three fixes went in first, because every uncertainty number sits on top of them.

- **Wicket width.** The code and the paper used outer stump edges at ±0.132 m (26.4 cm). Law 8
  gives 22.86 cm, so ±0.1143 m. Fixed in `calibration.py` (commit d14d948).
- **ICC bands.** Umpire's call now sits only outside an edge (centre outside, part of the ball
  still in), there is no band on the pitching test, and the wicket zone reaches the top of the
  bails, 0.7239 m (Law 8.3.1 allows bails 1.27 cm above the stumps). Source: ICC Men's Test
  playing conditions, Dec 2023, Appendix D 3.4 (`icc2023drs`). Commit 91e0bf8.
- **Focal length unpinned.** The synthetic runs were handing the solver the true focal length
  and pitch length. The main exp1 run now uses the app's own setup: focal length solved from the
  taps, pitch length fixed at the Laws' 20.12 m. Commit 81f97e0.

exp1 was rerun on this geometry (commit ccce0b7, tables 85d420c, figures 777ef73,
1681.8 s on 8 workers). It was rerun again on the fixed code (pose refine, commit 2f99c7b),
this time 608.7 s on 4 workers. What moved, old value to new:

| Quantity | Macro | Submitted | Now |
|---|---|---|---|
| pooled agreement (%) | GeoAgreeAll | 94.3 | 93.7 |
| truly not out | GeoNotOut | 9110 | 9783 |
| truly out | GeoOut | 512 | 715 |
| false outs | GeoFalseOut | 6 | 12 |
| false-out rate (%) | GeoFalseOutPct | 0.07 | 0.12 |
| missed outs | GeoMissedOut | 3 | 12 |
| umpire's calls | GeoUmp | 1178 | 302 |
| contact point along pitch (cm) | GeoMedContactX | 4.7 | 8.0 |
| 1-sigma coverage, lateral (%) | CovYOne | 50.5 | 51.6 |
| 1-sigma coverage, vertical (%) | CovZOne | 60.6 | 61.4 |
| 2-sigma coverage, lateral (%) | CovYTwo | 79.3 | 80.8 |
| 2-sigma coverage, vertical (%) | CovZTwo | 84.7 | 85.8 |
| k = 0 false outs | KZeroFalseOut | 13 | 40 |
| k = 0 missed outs | KZeroMissedOut | 12 | 56 |
| k = 0 umpire's call (%) | KZeroUmp | 10.4 | 2.9 |
| k = 1 false outs | KOneFalseOut | 6 | 12 |
| k = 1 missed outs | KOneMissedOut | 3 | 12 |
| k = 1 umpire's call (%) | KOneUmp | 12.0 | 7.8 |
| k = 2 agreement (%) | KTwoAgree | 93.2 | 90.6 |
| k = 2 false outs | KTwoFalseOut | 4 | 8 |
| k = 2 missed outs | KTwoMissedOut | 2 | 5 |
| k = 2 umpire's call (%) | KTwoUmp | 14.3 | 11.6 |
| physics off, agreement (%) | PhysOffAgree | 97.0 | 94.5 |
| physics on, agreement (%) | PhysOnAgree | 95.5 | 96.2 |
| 5 px centre noise, agreement (%) | NoiseFiveAgree | 88.0 | 83.0 |
| 12 px taps, agreement (%) | TapTwelveAgree | 91.0 | 95.2 |
| worst sweep row, false outs | SweepFalseOutMax | 1 | 4 |
| bowler's-end camera, agreement (%) | CamBowlerRefAgree | 88.0 | 87.5 |

The full list of the 115 exp1 macros that moved is Appendix A at the end of this file.

Calibration ablation (`exp1_geometry.py --ablation`, 400 deliveries per cell, 116.6 s on
4 workers):

| Setup | Focal error (%) | Contact x (cm) | Median y / z (cm) | Agree (%) | False outs |
|---|---|---|---|---|---|
| app setup: focal solved, L = 20.12 m (main run) | 1.65 | 7.4 | 2.3 / 3.4 | 96.0 | 0 |
| focal length handed to the solver (the submitted setup) | 0.00 | 4.0 | 2.2 / 3.4 | 95.8 | 0 |
| focal and pitch length both solved | 8.38 | 42.7 | 2.3 / 3.6 | 95.5 | 0 |
| 70 deg camera, app setup | 1.09 | 5.2 | 2.2 / 3.0 | 94.5 | 1 |
| 70 deg camera, focal handed over | 0.00 | 3.0 | 2.2 / 3.0 | 94.8 | 1 |

So pinning the focal length was hiding a 1.65 % focal error and nearly doubling the
pitching-point accuracy, but it did not flatter agreement or the stump-plane error. Leaving
pitch length free as well is what breaks the contact point (42.7 cm). The app's setup is the
honest one to report.

## 1. JCGM 100 budget (exp4)

`exp4_budget.py`, seed 404, 717.6 s on 4 workers. Raw: `raw/exp4_budget_rep.csv`,
`raw/exp4_budget_dist.csv`, `raw/exp4_budget.json`. Paper table: `tables/budget.tex`.

**What is measured.** The error of the stump-plane crossing (estimate minus truth), lateral y and
vertical z, with the pitching and crease points alongside. Every input goes through the app's own
calibration solve and bounce-anchored fit. Nothing is linearised by hand.

**How each u_i is found.**
- Vector inputs (the 12 taps, the per-frame ball centres, the per-frame time jitter): u_i = σ‖J‖,
  with J from one-sided differences of step σ on every coordinate. c is ‖J‖ per unit input.
- Scalar inputs with a stated PDF (rolling shutter, frame-rate metadata, distortion, pitch and
  wicket dimensions, bails, the five physics coefficients): u_i is the RMS of the output change
  over the PDF, by Gauss-Legendre quadrature (5 nodes), averaged over 8 frame phases. An effect
  the pipeline does not correct counts in full, bias included (JCGM 100 F.2.4.5). c is the
  least-squares slope through the quadrature points and is shown for reference only.
- Type A: only the bounce split (20 noisy draws). Everything else is Type B, and the table says
  where each range comes from.

**Why RMS over the PDF and not c·u.** The vertical error is an even function of the swing
coefficient: swing either way drops the crossing. So c_z for swing is -0.0316 mm per 0.01, and
c·u would give about 0.5 mm. The RMS over U[-0.3, 0.3] is 46.5 mm, most of it a -37.0 mm
bias. A first-order budget misses the largest vertical term.

**Representative delivery** (120 km/h, 6 m length, line -0.10 m, e = 0.55, 60 fps, reference
camera 2.8 m behind and 1.7 m up):

| Input | Type and PDF | u(x) | c_y | c_z | u_i(y) | u_i(z) | median u_i(y) | median u_i(z) |
|---|---|---|---|---|---|---|---|---|
| calibration taps | B: 2 px per coordinate (real clips: 2.05-10.55 px reprojection) | 2 px | 1.48 mm/px | 2.38 mm/px | 3.0 | 4.8 | 3.4 | 4.8 |
| ball centre | B: 1 px per coordinate (assumed) | 1 px | 7.28 mm/px | 35.2 mm/px | 7.3 | 35.2 | 15.6 | 25.1 |
| frame-time jitter | B: 0.5 ms per frame (assumed; PTS jitter measures the muxer only) | 0.5 ms | 5.72 mm/ms | 31.6 mm/ms | 2.9 | 15.8 | 6.9 | 9.5 |
| frame phase | B: release instant U[0, T] against the frame clock | 4.81 ms | 0.0897 mm/ms | 0.517 mm/ms | 0.4 | 2.5 | 0.2 | 0.5 |
| submitted frame sampler | B: effect of the submitted 17 ms request grid, RMS over phases | 17 ms grid |  |  | 16.7 | 86.4 | 19.0 | 38.3 |
| bounce split | A: split index from 20 noisy draws x effect of k+-1 | P = 0.5 |  |  | 0.0 | 0.0 | 0.0 | 0.0 |
| frame rate 59.80 vs 60 Hz | B: container rate over timestamp rate, U[0.99673, 1] (test5.mp4) | 0.189 % | 0.0791 mm/0.1 % | 0.524 mm/0.1 % | 0.1 | 1.0 | 0.4 | 1.1 |
| rolling shutter, uncorrected | B: readout 0-30 ms, either direction (assumed) | 17.3 ms | -0.02 mm/ms | -0.119 mm/ms | 0.7 | 4.0 | 3.1 | 6.7 |
| lens distortion | B: +-1 % radial at the corner (assumed) | 0.577 % | 0.115 mm/% | -1.28 mm/% | 0.1 | 0.7 | 0.2 | 0.9 |
| pitch length L | B: +-5 cm marking, rectangular | 2.89 cm | -0.0000214 mm/cm | -0.00897 mm/cm | 0.0 | 0.0 | 0.0 | 0.0 |
| pitch width W | B: +-10 cm, corners are unmarked | 5.77 cm | 0.233 mm/cm | -2.14 mm/cm | 1.3 | 12.3 | 3.9 | 14.6 |
| stump height H | B: +-1 cm set depth | 0.577 cm | 0.501 mm/cm | -2.87 mm/cm | 0.3 | 1.7 | 0.8 | 2.0 |
| wicket half-width w | B: +-2.5 mm stump spacing | 1.44 mm | 0.00457 mm/mm | -0.0804 mm/mm | 0.0 | 0.1 | 0.0 | 0.1 |
| bails tapped as top | B: 0-1.27 cm, Law 8.3.1, uncorrected | 0.733 cm | 0.497 mm/cm | -2.88 mm/cm | 0.4 | 2.1 | 1.0 | 2.5 |
| restitution e | B: model, U[0.40, 0.70] (James et al. 2004 pitch range) | 0.0866 | -0.0879 mm/0.01 | -0.650 mm/0.01 | 0.8 | 5.9 | 1.0 | 4.4 |
| drag Cd | B: model, U[0.35, 0.55] (Mehta 2005), not modelled | 0.454 | -0.0812 mm/0.01 | -0.430 mm/0.01 | 3.7 | 19.0 | 10.6 | 20.5 |
| swing Cs | B: model, U[-0.3, 0.3] (Mehta 2005), not modelled | 0.173 | 2.22 mm/0.01 | -0.0316 mm/0.01 | 38.2 | 46.5 | 31.5 | 25.0 |
| seam deviation | B: model, U[-2, 2] deg off the seam | 1.15 deg | -1.16 mm/deg | 0.659 mm/deg | 1.4 | 1.0 | 0.4 | 0.6 |
| friction at contact | B: model, U[0.05, 0.20] speed loss | 0.05 | 0.104 mm/0.01 | 0.542 mm/0.01 | 0.7 | 4.1 | 1.0 | 2.1 |

u(x) is the standard uncertainty of the input (for a rectangular PDF, half-width/√3). u_i is in
mm. The last two columns are medians over the 100-delivery distribution below.

| | Lateral y (mm) | Vertical z (mm) | Macro |
|---|---|---|---|
| u_c without the sampler row | 39.4 | 65.3 | BudRepUcNoSamplerY/Z |
| u_c with the sampler row | 42.8 | 108.3 | BudRepUcY/Z |
| pipeline's own 1σ for this delivery | 9.4 | 44.6 | BudRepPipeSigmaY/Z |
| RSS of the measurement rows only (no physics rows) | 8.5 | 41.1 | from exp4_budget_rep.csv |
| scatter of 20 noise-only runs | 7.37 | 36.77 | exp4_budget.json |
| ball-centre row | 7.3 | 35.2 | BudRepSecondY/ZMm |

Variance shares without the sampler row: lateral, swing 94.2 %, ball centre 3.4 %, taps 0.6 %,
drag 0.9 %, jitter 0.5 %. Vertical, swing 50.7 %, ball centre 29.0 %, drag 8.4 %, jitter 5.8 %,
pitch width 3.6 %.

What this says:
- **The pipeline's σ is a fair measurement-noise σ.** The measurement rows alone give 8.5 / 41.1
  mm against the pipeline's 9.4 / 44.6 mm. The ball-centre row (7.3 / 35.2 mm) matches the
  scatter of 20 repeated noise-only runs (7.37 / 36.77 mm), which checks the Jacobian method.
- **What the pipeline's σ leaves out is the flight model.** Unmodelled swing alone is 38.2 /
  46.5 mm. That is why the stated σ under-covers (section 3).
- **Calibration and geometry inputs are small.** Taps 3.0 / 4.8 mm, pitch width 1.3 / 12.3 mm,
  everything else under 5 mm here. Rolling shutter over 0 to 30 ms either way is 0.7 / 4.0 mm.
- **Biases at nominal inputs**, counted inside u_i: drag -3.59 / -18.45 mm, swing -6.42 /
  -37.05 mm, bails 0.32 / -1.83 mm. The estimator's own error at nominal inputs, averaged over
  the frame phase, is 1.52 / 8.71 mm.
- **Bounce split:** the split index moved in half of the 20 draws, but moving it by one frame
  changed the crossing by 0.0 mm at this delivery.

**Distribution over 100 deliveries** (speed 60 to 150 km/h, length 1 to 10 m, line ±0.6 m,
release 1.8 to 2.3 m; 2 phases and 3 quadrature nodes to keep the run time down):

| | Lateral y (mm) | Vertical z (mm) |
|---|---|---|
| median u_c, no sampler [BudDistUcMedY/Z] | 46.9 | 53.8 |
| 90th percentile u_c, no sampler [BudDistUcPNinetyY/Z] | 88.3 | 143.7 |
| median u_c with the sampler [BudDistUcMedWithSamplerY/Z] | 64.3 | 86.4 |

- Largest row per delivery (no sampler): lateral, swing 68, drag 21, ball centre 9,
  jitter 2. Vertical, swing 35, ball centre 31, drag 19, pitch width 10, restitution 3, jitter 2.
- Median variance share: lateral, swing 56.3 %, ball centre 13.7 %, drag 6.7 %. Vertical, ball
  centre 24.3 %, swing 17.7 %, drag 14.5 %, pitch width 6.4 %.

**The sampler row is a bug, not an uncertainty.** The submitted 17 ms request grid (section 8)
adds 16.7 / 86.4 mm on the representative delivery and a median 19.0 / 38.3 mm over the set.
It is reported as its own row and kept out of u_c. Fixing it removes it.

## 2. JCGM 101 Monte Carlo against the linear budget (exp5)

`exp5_mc.py --workers 4`, seed 505, 1268.2 s (representative 958.3 s). Raw:
`raw/exp5_mc_rep.csv` (30,000 trials), `raw/exp5_mc_subset.csv` (10 × 1000), `raw/exp5_mc.json`.
Table: `tables/mc.tex`. Macros `Mc*`.

Method. Every input of the exp4 budget is drawn from its PDF at once and each trial runs the
app's calibration solve and the bounce-anchored fit, so the propagation is through the full
nonlinear solver, not a linearisation. The output is estimate minus truth at the stump plane.
The submitted sampler is left out, as in u_c. Validation follows JCGM 101 section 8: the
linear 95 % interval is y ± 1.96 u_c, and both end-point differences d_low and d_high must be at
most δ, where δ = ½ × 10^l comes from u_c written to two significant figures. For u_c = 39.4 mm
that is δ = 0.5 mm. The representative delivery uses the adaptive procedure of 7.9 in batches
of 10^4, capped at 3 batches.

**Monte Carlo trials: M = 30,000** on the representative delivery (3 batches, 0 failed
trials) [McM, McBatches, McFailed]. The 7.9 stopping rule was **not** met [McStable = no]: after
3 batches twice the batch standard deviation of the interval end points was still up to 2.8 mm
(y) and 2.4 mm (z) [McTwoSMaxY, McTwoSMaxZ], against δ = 0.5 mm. Meeting δ would take about
(2.8 / 0.5)^2 = 31 times as many trials, around 8 hours at the measured rate. The comparison
below does not need that: the differences are 26 to 85 mm, at least 9 times the numerical noise.

| Measurand | Linear estimate (mm) | u_c (mm) | Linear 95 % interval (mm) | MC mean (mm) | MC u (mm) | MC 95 % interval (mm) | d_low / d_high (mm) | δ (mm) | Passes |
|---|---|---|---|---|---|---|---|---|---|
| lateral y | 1.5 | 39.4 | [-75.7, 78.7] | -7.4 | 55.0 | [-129.5, 104.8] | 53.8 / 26.1 | 0.5 | no |
| vertical z | 8.7 | 65.3 | [-119.4, 136.8] | -47.7 | 53.6 | [-158.8, 52.3] | 39.5 / 84.5 | 0.5 | no |

What it shows:

- **The linear budget does not pass JCGM 101 validation**, for either measurand, by a wide
  margin: d_low / d_high = 53.8 / 26.1 mm in y and 39.5 / 84.5 mm in z against δ = 0.5 mm
  [McDLow*, McDHigh*, McValid*].
- **The Monte Carlo distribution is shifted, not just wider.** The linear estimate is 1.5 / 8.7 mm
  but the Monte Carlo mean is -7.4 / -47.7 mm. The unmodelled flight effects push the height
  error one way whatever their sign. exp4 already showed it for swing: a slope of -0.0316 mm
  per 0.01 of Cs but a -37.05 mm bias, because swing either way leaves the fit low. The budget
  counts that as a symmetric RMS term; the Monte Carlo shows it is a bias.
- **u differs in both directions.** The Monte Carlo standard deviation is 1.40 times u_c in y and
  0.82 times in z [McRatioY, McRatioZ]. The 95 % interval in z is asymmetric, [-158.8, 52.3] mm,
  which a ± k u_c interval cannot represent.
- **The pipeline's own σ over the same trials** has a median of 27.2 mm in y and 53.7 mm in z
  [McPipeSigmaMed*], against a Monte Carlo spread of 55.0 and 53.6 mm. So in y the app's sigma is
  about half the real spread, and in z it is about right. That matches exp6, where the app's sigma
  under-covers y more than z (53.6 against 60.8 % at 1σ).

Subset: the first 10 deliveries of the exp4 sample, 1000 trials each, no adaptive stopping.
That is too few trials for a 0.5 mm tolerance, so the pass counts below are expected to be 0 on
numerical grounds alone; the ratios are the useful part.

| # | Speed (km/h) | Length (m) | u_c y / z (mm) | MC u y / z (mm) | MC / linear, y / z | MC mean y / z (mm) | δ y / z (mm) | Passes y / z |
|---|---|---|---|---|---|---|---|---|
| 0 | 87 | 5.1 | 57.4 / 85.9 | 65.5 / 74.1 | 1.14 / 0.86 | -15.5 / -64.9 | 0.5 / 0.5 | no / no |
| 1 | 63 | 5.3 | 35.0 / 60.4 | 47.6 / 72.1 | 1.36 / 1.19 | -22.2 / -60.9 | 0.5 / 0.5 | no / no |
| 2 | 136 | 6.2 | 51.3 / 45.9 | 56.2 / 47.8 | 1.10 / 1.04 | -22.7 / -17.5 | 0.5 / 0.5 | no / no |
| 3 | 95 | 4.8 | 72.6 / 101.1 | 82.1 / 77.5 | 1.13 / 0.77 | -16.5 / -75.6 | 0.5 / 5.0 | no / no |
| 4 | 90 | 9.9 | 36.6 / 45.8 | 32.3 / 40.0 | 0.88 / 0.87 | 30.5 / -36.6 | 0.5 / 0.5 | no / no |
| 5 | 132 | 2.9 | 41.3 / 42.4 | 74.4 / 61.7 | 1.80 / 1.46 | 8.1 / -4.4 | 0.5 / 0.5 | no / no |
| 6 | 94 | 7.7 | 20.8 / 49.7 | 35.3 / 42.6 | 1.70 / 0.86 | 3.7 / -40.0 | 0.5 / 0.5 | no / no |
| 7 | 71 | 4.2 | 95.5 / 145.5 | 101.3 / 110.3 | 1.06 / 0.76 | 20.6 / -117.5 | 0.5 / 5.0 | no / no |
| 8 | 130 | 1.2 | 177.7 / 225.8 | 59.8 / 50.3 | 0.34 / 0.22 | 50.3 / -28.5 | 5.0 / 5.0 | no / no |
| 9 | 74 | 1.6 | 149.4 / 98.9 | 102.2 / 95.1 | 0.68 / 0.96 | -4.8 / -71.6 | 5.0 / 0.5 | no / no |

- **0 of 10 pass in y and 0 of 10 in z** [McSubValidY, McSubValidZ].
- **MC u over u_c runs from 0.34 to 1.80 in y (median 1.11) and 0.22 to 1.46 in z (median
  0.87)** [McSubRatio*]. The two lowest ratios are the two fullest deliveries (1.2 m and
  1.6 m). At 1.2 m the linear u_c is 3.0 times the Monte Carlo spread in y and 4.5 times in z.
- **The z mean is negative for all 10** (-4.4 to -117.5 mm). The bias is not a feature of one
  delivery.

Consequence for the paper. Quote the Monte Carlo interval for the stated uncertainty, or
correct the mean bias before using a symmetric interval. The linear budget is still the right
tool for ranking the inputs, but not for the interval itself.

## 3. Why the 1-sigma under-covers, and coverage after the fix (exp6)

`exp6_coverage.py`, seed 606, 409.0 s on 4 workers (main run 304.1 s). Raw:
`raw/exp6_worldb.csv`, `raw/exp6_sweeps.csv`, `raw/exp6_model_error.json`. Tables:
`tables/coverage.tex`, `tables/coverage_sweeps.tex`.

**World B.** 600 deliveries, 599 fitted, all 599 saw the bounce. It is exp1's physics world
(drag with Cd U[0.35, 0.55], swing, friction, turn, restitution 0.4 to 0.7) plus every
electronic and geometric input from the budget: 1 px centres, 10 % radius noise, 5 % dropout,
2 px taps, 0.5 ms frame jitter, frame-rate metadata U[0.99673, 1], rolling shutter U[-30, 30]
ms, distortion ±1 %, pitch length ±5 cm, width ±10 cm, stump height ±1 cm, stump spacing
±2.5 mm, bails U[0, 1.27] cm, reference camera, frames labelled with their own timestamps.

**Three σ sets.**
- fit: the pipeline's own covariance, the app's own sigma.
- fit + cal: plus the tap noise pushed through the calibration solve (σ_cal).
- full: plus a model-error term σ_mod, fitted by maximum likelihood and chosen by 5-fold
  cross-validation. Each delivery gets σ_mod from the folds that did not contain it.

Model-error forms, chosen by held-out negative log-likelihood (lower is better):

| Measurand | Chosen form | Parameter | Held-out NLL: constant / proportional / both |
|---|---|---|---|
| pitching y | constant | 11.74 mm | -1656.02 / -1547.51 / -1656.02 |
| crease y | constant + proportional to bounce distance | 16.77 mm + 2.31 mm per m | -1178.83 / -1175.82 / -1180.70 |
| stump y | proportional to bounce distance | 1.95 mm per m | -1125.00 / -1125.61 / -1124.25 |
| stump z | proportional to bounce distance | 9.33 mm per m | -583.35 / -624.77 / -624.69 |

Medians over World B (mm):

| Measurand | Mean error | Median abs error | σ_fit | σ_cal | σ_mod |
|---|---|---|---|---|---|
| stump y [ModY*] | 5.6 | 20.2 | 23.5 | 3.7 | 11.2 |
| stump z [ModZ*] | -18.3 | 36.2 | 46.9 | 5.2 | 54.0 |
| crease y [ModCrease*] | 3.7 | 13.2 | 12.9 | 3.4 | 21.8 |
| pitching y [ModPitch*] | -1.7 | 9.5 | 4.7 | 6.3 | 11.7 |

**Coverage before and after** (share of deliveries with |error| ≤ kσ; nominal 68.3 % at k = 1
and 95 % at k = 1.96). The binomial standard error at n = 599 is 1.9 points at 68 % and 0.89
points at 95 %.

| Run and σ | y at 1σ | y at 1.96σ | z at 1σ | z at 1.96σ |
|---|---|---|---|---|
| exp1, the pipeline σ the paper quotes (at 1σ / 2σ) [CovY/ZOne, Two] | 51.6 | 80.8 (2σ) | 61.4 | 85.8 (2σ) |
| World B, fit (the app's sigma) [CovBFit*] | 53.6 | 84.1 | 60.8 | 85.3 |
| World B, fit + cal [CovBFitCal*] | 56.4 | 85.8 | 61.4 | 86.3 |
| World B, full [CovBFull*] | **63.9** | **90.7** | **85.5** | **97.7** |
| crease y: fit / fit + cal / full | 44.2 / 47.9 / 74.6 | 71.1 / 74.5 / 91.2 | | |
| pitching y: fit / fit + cal / full | 23.7 / 43.6 / 69.8 | 48.9 / 71.6 / 92.8 | | |

Empirical coverage factor: the k that actually covers 68.27 % and 95 % (percentiles of |e|/σ):

| σ | y: k68 / k95 | z: k68 / k95 | Macros |
|---|---|---|---|
| exp1 pipeline σ | 1.47 / 3.48 | 1.19 / 3.43 | KEmpExpOne* |
| World B fit | 1.32 / 2.99 | 1.25 / 3.10 | KEmpFit* |
| World B fit + cal | 1.28 / 2.84 | 1.23 / 2.91 | KEmpFitCal* |
| World B full | 1.09 / 2.47 | 0.66 / 1.53 | KEmpFull* |

**Sweeps** (199 fitted deliveries per cell out of 200; same world, one input fixed). Median
|error| in mm, then 1σ coverage fit → full. The binomial standard error at n = 199 is 3.3
points at 68 %.

| Cell | y median | y cover | z median | z cover |
|---|---|---|---|---|
| rolling shutter 0 ms | 17.4 | 55.3 → 64.3 | 35.1 | 58.8 → 85.4 |
| +30 ms, uncorrected | 20.2 | 56.8 → 67.8 | 31.2 | 63.3 → 85.4 |
| +30 ms, corrected | 18.6 | 57.8 → 69.3 | 32.7 | 63.8 → 86.4 |
| -30 ms, uncorrected | 20.8 | 54.8 → 65.8 | 38.0 | 61.8 → 84.9 |
| -30 ms, corrected | 19.1 | 58.3 → 68.8 | 35.2 | 65.8 → 87.4 |
| timestamps | 18.6 | 54.3 → 66.8 | 31.2 | 62.8 → 86.4 |
| timestamps, 59.80 Hz metadata | 18.9 | 52.8 → 67.3 | 32.7 | 62.3 → 84.9 |
| fixed sampler | 18.9 | 53.3 → 68.3 | 36.3 | 59.3 → 82.4 |
| fixed sampler, 59.80 Hz metadata | 19.7 | 52.8 → 67.3 | 34.1 | 61.8 → 83.9 |
| submitted 17 ms grid | 26.7 | 52.3 → 58.3 | 52.0 | 53.3 → 77.9 |
| submitted grid, 59.80 Hz metadata | 25.8 | 55.3 → 62.8 | 45.9 | 57.8 → 79.9 |

The ±5, ±10 and ±16 ms rolling-shutter cells are in the json and `tables/coverage_sweeps.tex`;
fit coverage stays between 51.8 % and 56.8 % in y across all of them.

**Diagnosis.**
- **Rolling shutter is not the cause.** Fit coverage in y is 55.3 % with no rolling shutter and
  56.8 % at +30 ms. The paper's worry (main.tex:386-387) does not show up in the data.
- **Calibration is a small part.** Adding σ_cal lifts 1σ coverage by 2.8 points in y and 0.6 in
  z at the stump. It matters more at the pitching point (23.7 % to 43.6 %).
- **Frame-rate metadata (59.80 against 60 Hz) does nothing measurable.**
- **The submitted 17 ms grid still hurts accuracy and coverage; the fixed sampler tracks
  timestamps closely.** Median error is 26.7 / 52.0 mm on the submitted grid against 18.6 / 31.2
  mm on timestamps, and fit coverage is 52.3 / 53.3 % against 54.3 / 62.8 %. The fixed sampler,
  the one now in place, lands close to timestamps: 18.9 / 36.3 mm median error and 53.3 / 59.3 %
  fit coverage.
- **The missing term is model error, and it narrows the gap without closing it for y.** The
  median σ_mod is 11.2 mm for y, about half of σ_fit (23.5 mm), and 54.0 mm for z, close to its
  σ_fit (46.9 mm). With it, y at 1σ rises to 63.9 % and z at 1σ rises to 85.5 %.

**What is still off, stated plainly.**
- **y under-covers at both levels.** At 1σ, 63.9 % against 68.3 %, about 2.3 standard errors
  short. At 1.96σ, 90.7 % against 95 %, about five standard errors short. The lateral errors
  have heavier tails than a Gaussian: the empirical k95/k68 is 2.47/1.09 = 2.3, not 1.96.
- **z over-covers:** 85.5 % and 97.7 %. The Gaussian likelihood fit puts σ_mod wide enough for
  the tail, which makes it too wide for the core (median |e|/σ is 0.43). A heavier-tailed
  model-error PDF would fix both. That is left for later; for now the paper should state the
  empirical k from the table, not assume 1.96.

## 4. JCGM 106 guard band (exp7)

`exp7_risk.py`, 0.5 s. Runs on the 599 World B deliveries of exp6 (truth: 39 out, 15 umpire's
call, 545 not out). Raw: `raw/exp7_risk_curve.csv` (183 rows: 3 σ sets × 61 values of k),
`raw/exp7_risk.json`. Figure: `figures/risk.pdf`.

**Decision rule.** The code's rule (`decision.py:_band`), not the paper's: a test passes ("in")
when the centre is at least kσ inside the edge, and fails ("out") when it is more than R + kσ
outside, R = 36 mm the ball radius. In between is umpire's call. Truth is the ICC rule on the
true path (k = 0, σ = 0). This is the JCGM 106 form: the acceptance limit moved in by a guard
band of kσ.

**Risk definitions** (JCGM 106 clauses 9.3 and 9.4). Flat prior, independent Gaussian errors
per test, m the signed margin of each test:
- specific false-out risk of an OUT call = 1 - Π Φ((m + R)/σ), with R = 0 on the pitching test:
  the chance that the true path is more than the umpire's-call width outside at least one limit,
  so the true verdict is not out (`uq.specific_risk`).
- specific missed-out risk of a NOT OUT call = Π Φ(m/σ): the chance that the true centre is inside
  every limit, so the true verdict is out.
- global risk is counted against the known truth: the joint false-out rate over all 599
  deliveries, with a Clopper-Pearson 95 % upper limit.

**How k is chosen.** For each σ set and each α in {1 %, 5 %}: the smallest k on a 0.05 grid
from 0 to 3 from which every OUT call has specific false-out risk ≤ α. Closed-form bounds for
comparison, from 1 - Φ(k) = α with one binding test and 1 - Φ(k)^4 = α with all four tests on
their boundaries at once:

| α | one test [RiskBoundSingle*] | four tests [RiskBoundFour*] |
|---|---|---|
| 1 % | 2.33 | 2.81 |
| 5 % | 1.64 | 2.23 |

**Chosen k and what it costs** [Risk{Fit,FitCal,Full}*{One,Five}]:

| σ set | α | k | Agree (%) | Umpire's call (%) | Out (%) | False outs | CP95 of false-out rate (%) | True outs sent to umpire's call (%) |
|---|---|---|---|---|---|---|---|---|
| fit | 1 % | 2.25 | 92.0 | 10.5 | 3.2 | 0 | 0.50 | 51.3 |
| fit | 5 % | 1.20 | 95.0 | 7.0 | 5.0 | 1 | 0.79 | 28.2 |
| fit + cal | 1 % | 1.80 | 93.0 | 9.5 | 3.7 | 0 | 0.50 | 43.6 |
| fit + cal | 5 % | 1.45 | 94.3 | 8.2 | 4.2 | 0 | 0.50 | 35.9 |
| **full** | **1 %** | **1.85** | 89.5 | 13.0 | 2.2 | 0 | 0.50 | 66.7 |
| **full** | **5 %** | **1.00** | 93.8 | 8.3 | 4.3 | 0 | 0.50 | 35.9 |
| fit (the app's rule) | | 1 | 95.8 | 6.2 | 5.7 | 1 | 0.79 | 17.9 |
| any (no guard band) | | 0 | 97.2 | 2.5 | 6.8 | 3 | 1.29 | 5.1 |

Missed outs are 0 in every row above.

**The app's rule's out calls are riskier than they look.** Scored with its own σ, the worst
OUT call at k = 1 has 6.0 % specific false-out risk [RiskFitKOneMaxSpec]. Scored with the full
σ, which section 3 shows is the honest one, the worst is 27.6 % [RiskShippedMaxSpecFull], the
mean over its out calls is 2.9 % [RiskShippedMeanSpecFull], and 4 of its out calls are above
5 % [RiskShippedOutsOverFive]. The count of false outs against truth (1 in 599) looks fine only
because most deliveries are nowhere near an edge.

**Global risk does not pick k.** The joint false-out rate is 0.50 % at k = 0 (3 in 599), already
under 1 %, so a point-estimate global rule would choose k = 0 for every σ set
[RiskFullKGlobalOne = 0.00]. The Clopper-Pearson 95 % upper limit gets under 1 % from k = 0.5 in
every set. With 39 true outs the sample is too small to pin a global rate near 1 %, which is why
the specific risk drives the choice.

**Recommendation.** Use the full σ and k = 1.00 for α = 5 %, or k = 1.85 for α = 1 %, and say
which one. Also state the sample-free worst-case bounds (2.23 and 2.81), since the chosen k
depends on where this sample's out calls happen to fall. The price is agreement (95.8 % under
the app's rule to 93.8 % at α = 5 %) and more umpire's calls (6.2 % to 8.3 %), because about a
third of the true outs (35.9 %) now come back as umpire's call. That is the honest cost of a
tool this uncertain, and the paper should say so rather than quote 95.8 %.

## 5. Unmodelled physics (exp8, part 1)

Script `exp8_physics.py --part physics`, raw `raw/exp8_physics.csv`, summary `raw/exp8_physics.json`,
table `tables/physics.tex`, macros `Phys*`.

Set-up. 200 deliveries drawn once (60 to 150 km/h, length 1 to 10 m, line within 0.6 m, release
1.8 to 2.3 m). The baseline is the estimator's own model: no drag, no swing, restitution 0.55,
friction 0.10, no turn. Each row turns on one effect on the same deliveries, taps, frame phase
and noise seeds, so rows differ only in the physics. Magnitudes: drag Cd 0.35 to 0.55 and swing
side-force coefficient up to 0.3 (Mehta 2005), restitution 0.40 to 0.70 (James et al. 2004),
seam 1 to 3 deg and turn 0 to 6 deg (assumed, no source gives a distribution), friction 0.20.
"Combined pace" draws all of them at once. Measurement effects are exp1's (1 px centres, 10 %
radius, 5 % dropout, 2 px taps, 60 fps) plus 0.5 ms frame jitter. The full sigma uses exp6's
cross-validated model term, so it was fitted on World B and not on these rows.

| Row | n | Median abs y / z (mm) | Mean y / z (mm) | 1σ cover, fit, y / z (%) | 1σ cover, full, y / z (%) | Agree: fit k=1 / full k=1.85 / full k=1.0 (%) | Umpire's call, same three (%) |
|---|---|---|---|---|---|---|---|
| baseline | 199 | 9.9 / 20.6 | -1.8 / 6.0 | 70.9 / 78.4 | 82.4 / 96.0 | 96.0 / 87.4 / 93.5 | 7.5 / 16.1 / 10.1 |
| drag Cd 0.35 | 200 | 10.3 / 22.9 | -0.4 / -1.3 | 70.5 / 76.0 | 86.5 / 94.0 | 96.0 / 87.5 / 93.0 | 8.0 / 16.5 / 11.0 |
| drag Cd 0.45 | 199 | 10.6 / 25.1 | -0.2 / -4.2 | 69.3 / 73.4 | 80.9 / 92.0 | 97.0 / 88.9 / 93.0 | 7.0 / 15.1 / 11.1 |
| drag Cd 0.55 | 200 | 12.0 / 27.9 | -1.0 / -10.2 | 66.5 / 71.5 | 79.5 / 90.0 | 98.0 / 89.5 / 95.0 | 6.5 / 15.0 / 9.5 |
| swing Cs 0.1 | 199 | 17.3 / 23.8 | 1.0 / -5.8 | 63.3 / 80.9 | 77.9 / 95.0 | 95.5 / 86.9 / 92.0 | 5.5 / 14.1 / 9.0 |
| swing Cs 0.2 | 200 | 29.1 / 28.6 | 1.4 / -29.2 | 62.5 / 79.0 | 72.5 / 94.5 | 94.5 / 90.5 / 94.5 | 9.0 / 14.0 / 10.0 |
| swing Cs 0.3 | 200 | 43.8 / 36.3 | -1.4 / -52.1 | 67.0 / 78.0 | 72.5 / 93.5 | 97.0 / 92.0 / 95.5 | 4.5 / 9.5 / 6.0 |
| seam 1 deg | 199 | 11.9 / 20.1 | -1.6 / 5.9 | 71.4 / 79.4 | 84.4 / 96.5 | 94.5 / 83.9 / 90.5 | 10.6 / 21.1 / 14.6 |
| seam 2 deg | 199 | 11.9 / 22.0 | -1.8 / 5.8 | 75.4 / 78.4 | 85.4 / 96.5 | 94.5 / 82.9 / 91.0 | 6.0 / 17.6 / 9.5 |
| seam 3 deg | 199 | 11.0 / 20.7 | -3.5 / 4.3 | 73.9 / 78.4 | 88.4 / 98.0 | 97.5 / 85.9 / 94.5 | 4.5 / 16.1 / 7.5 |
| spin 0 deg | 200 | 10.7 / 22.7 | -0.9 / 3.6 | 71.0 / 77.5 | 86.5 / 91.5 | 95.5 / 86.5 / 92.0 | 10.0 / 19.0 / 13.5 |
| spin 3 deg | 200 | 10.8 / 23.2 | -0.3 / 5.6 | 71.0 / 72.0 | 83.0 / 88.5 | 96.0 / 84.5 / 89.0 | 6.0 / 17.5 / 13.0 |
| spin 6 deg | 200 | 15.8 / 21.8 | 0.7 / 6.1 | 61.5 / 67.5 | 73.5 / 88.5 | 96.5 / 90.0 / 94.0 | 6.5 / 13.0 / 9.0 |
| restitution 0.40 | 200 | 12.1 / 39.3 | -0.7 / 34.2 | 57.0 / 57.0 | 75.0 / 77.5 | 97.5 / 90.0 / 95.0 | 7.0 / 14.5 / 9.5 |
| restitution 0.70 | 199 | 12.5 / 19.1 | -1.2 / -14.4 | 76.9 / 77.9 | 84.9 / 96.0 | 97.0 / 89.9 / 95.5 | 5.5 / 12.6 / 7.0 |
| restitution U[0.40,0.70] | 199 | 10.8 / 26.2 | -1.8 / 8.1 | 69.3 / 74.4 | 78.9 / 91.0 | 95.0 / 88.4 / 93.0 | 8.5 / 15.1 / 10.6 |
| friction 0.20 | 199 | 13.5 / 30.5 | -0.8 / 17.0 | 65.3 / 71.4 | 81.4 / 89.4 | 97.0 / 86.4 / 92.5 | 6.5 / 17.1 / 11.1 |
| combined pace | 200 | 26.0 / 39.2 | -7.9 / -33.8 | 51.5 / 64.0 | 65.0 / 85.5 | 95.0 / 88.0 / 93.0 | 5.5 / 14.5 / 9.0 |

Findings.

- **Swing is the largest single effect.** The median lateral error goes from 9.9 mm to 17.3,
  29.1 and 43.8 mm at Cs 0.1, 0.2 and 0.3. The mean lateral error stays near zero because the
  swing direction is drawn per delivery, but the height picks up a bias of -5.8, -29.2 and
  -52.1 mm. The same swing term is the biggest row of the exp4 budget.
- **Restitution and friction set the height bias.** A pitch at 0.40 instead of the assumed 0.55
  gives a +34.2 mm mean height error; 0.70 gives -14.4 mm; friction 0.20 gives +17.0 mm. Lateral
  error barely moves. Restitution 0.40 has the worst full-sigma height coverage of any single
  row, 77.5 %.
- **Drag and seam are small.** Drag moves the median height error from 20.6 mm to between 22.9 and
  27.9 mm and the lateral error by under 3 mm. Seam of 1 to 3 deg moves both by under 3 mm. Turn of 6 deg on
  a slow ball takes the lateral median from 10.7 to 15.8 mm.
- **Coverage does not collapse, for a reason.** The pipeline scales its covariance by the
  residual variance (`reconstruction.py:244`), so a worse fit reports a wider sigma. Fit coverage
  still falls from 70.9 / 78.4 % to 51.5 / 64.0 % under combined pace. The full sigma gives
  65.0 / 85.5 % there.
- **The baseline over-covers under the full sigma** (82.4 / 96.0 %). The model term was fitted on
  World B, which has these effects switched on, so it is too wide for a world without them. It
  is a model-error allowance, not a noise term, and it only fits the world it was estimated in.
- **Agreement hides most of this.** Under the app's rule agreement stays between 94.5 and
  98.0 % in every row, including combined pace at 95.0 %, because most deliveries are far from an
  edge. The honest sigma costs agreement instead: 82.9 to 92.0 % at k = 1.85 and 89.0 to 95.5 % at
  k = 1.0, with umpire's call between 9.5 and 21.1 % at k = 1.85.

## 6. Tap sensitivity (exp8, part 2)

Script `exp8_physics.py --part taps`, raw `raw/exp8_taps.csv`, summary in `raw/exp8_physics.json`,
table `tables/taps.tex`, macros `Tap*`.

Set-up. The first 300 deliveries of exp6's World B, rebuilt with the same taps and detections.
The unperturbed estimate matches exp6 on all 299 that solve (0 mismatches). Two kinds of error:
every one of the twelve taps moved d = 2, 5 or 10 px in its own random direction, or all twelve
moved the same +-d px in v (a user who taps consistently high or low). Verdicts are compared
with the unperturbed verdict of the same delivery under three rules: the app's rule (fit sigma,
k = 1), and the full sigma with the exp7 k at 5 % (1.0) and 1 % (1.85).

| Perturbation | n | Median / 90th abs Δy (mm) | Median / 90th abs Δz (mm) | Verdict changes: fit k=1 / full k=1.85 / full k=1.0 | Straight out ↔ not out |
|---|---|---|---|---|---|
| random 2 px | 299 | 1.9 / 5.9 | 2.2 / 6.4 | 2 (0.7 %) / 1 (0.3 %) / 2 (0.7 %) | 0 / 0 / 0 |
| random 5 px | 299 | 4.4 / 15.6 | 5.2 / 17.5 | 3 (1.0 %) / 1 (0.3 %) / 5 (1.7 %) | 0 / 0 / 0 |
| random 10 px | 299 | 9.1 / 31.8 | 10.7 / 34.2 | 6 (2.0 %) / 4 (1.3 %) / 2 (0.7 %) | 1 / 0 / 0 |
| v shift +2 px | 299 | 2.8 / 12.5 | 3.4 / 6.9 | 0 (0.0 %) / 0 (0.0 %) / 2 (0.7 %) | 0 / 0 / 0 |
| v shift -2 px | 299 | 2.9 / 12.7 | 3.5 / 7.1 | 1 (0.3 %) / 1 (0.3 %) / 0 (0.0 %) | 0 / 0 / 0 |
| v shift +5 px | 299 | 6.8 / 33.5 | 8.2 / 17.3 | 0 (0.0 %) / 1 (0.3 %) / 2 (0.7 %) | 0 / 0 / 0 |
| v shift -5 px | 299 | 7.2 / 32.7 | 8.8 / 17.8 | 4 (1.3 %) / 3 (1.0 %) / 2 (0.7 %) | 0 / 0 / 0 |
| v shift +10 px | 299 | 13.3 / 65.4 | 16.5 / 35.2 | 1 (0.3 %) / 2 (0.7 %) / 4 (1.3 %) | 0 / 0 / 0 |
| v shift -10 px | 299 | 15.2 / 68.9 | 17.7 / 37.0 | 8 (2.7 %) / 3 (1.0 %) / 4 (1.3 %) | 0 / 0 / 0 |

Findings.

- **The stump-plane point moves 0.9 to 1.1 mm per pixel of random tap error.** Medians are
  1.9 / 2.2 mm at 2 px, 4.4 / 5.2 mm at 5 px and 9.1 / 10.7 mm at 10 px. The tails are long:
  the 90th percentile at 10 px is 31.8 / 34.2 mm.
- **A consistent high or low tap is worse in the lateral tail.** At +-10 px in v the lateral
  90th percentile is 65.4 and 68.9 mm, against 31.8 mm for random 10 px, because the whole pose
  tilts one way instead of the errors partly cancelling.
- **Few verdicts change, and almost none change outright.** The most changes in any case is 8 of 299
  (2.7 %, v shift -10 px, the app's rule). At 2 px, the tap noise the other experiments assume, the
  app's rule changes 2 (0.7 %). In 26 of the 27 case and rule pairs no verdict goes straight from
  out to not out or back. The one exception is random 10 px under the app's rule: 1 of the 6
  changed verdicts there (0.3 % of 299) jumps straight across with no stop in the band. Every
  other change moves into or out of umpire's call, which is what the band is for.

## 7. Frame rate (exp9)

150 exp1-style deliveries with the full unmodelled physics, reference camera, 1 px centres, 2 px taps, 0.5 ms frame jitter, each replayed at 30, 60, 120 and 240 fps under four samplers (seed 909, 69.5 s on 4 workers). "timestamps" hands the estimator every frame at its own time. "fixed" and "submitted" are the app's sampler after and before commit 143d31b (section 8); "@60" is the 60 Hz request the app always sends, "@fps" a request at the clip's rate. Coverage is of the pipeline's own sigma; agreement and umpire's call use the app's rule (k = 1). Table: `tables/fps.tex`.

| fps | Sampler | n | Median frames | Median abs y / z (mm) | 1-sigma cover y / z (%) | Agree (%) | Umpire's call (%) |
|---|---|---|---|---|---|---|---|
| 30 | timestamps | 150 | 18.5 | 23.3 / 42.3 | 67 / 69 | 92.7 | 7.3 |
| 30 | fixed @60 | 150 | 18 | 27.4 / 43.9 | 65 / 69 | 93.3 | 8.0 |
| 30 | fixed @fps | 150 | 19 | 26.2 / 46.6 | 63 / 69 | 93.3 | 8.0 |
| 30 | submitted @60 | 145 | 37 | 94.4 / 156.8 | 75 / 74 | 88.3 | 14.5 |
| 60 | timestamps | 150 | 37 | 24.5 / 38.6 | 52 / 61 | 95.3 | 5.3 |
| 60 | fixed @60 | 150 | 37 | 26.1 / 37.1 | 51 / 60 | 96.0 | 6.0 |
| 60 | fixed @fps | 150 | 37 | 26.1 / 37.1 | 51 / 60 | 96.0 | 6.0 |
| 60 | submitted @60 | 149 | 36.5 | 35.5 / 64.8 | 54 / 56 | 91.9 | 9.4 |
| 120 | timestamps | 150 | 74 | 24.8 / 31.7 | 41 / 57 | 94.0 | 6.0 |
| 120 | fixed @60 | 150 | 37.5 | 21.9 / 38.0 | 53 / 62 | 94.7 | 5.3 |
| 120 | fixed @fps | 150 | 73.5 | 22.8 / 30.8 | 43 / 56 | 94.7 | 5.3 |
| 120 | submitted @60 | 150 | 36.5 | 32.2 / 51.9 | 44 / 55 | 95.3 | 7.3 |
| 240 | timestamps | 150 | 146.5 | 24.5 / 31.7 | 30 / 42 | 96.0 | 3.3 |
| 240 | fixed @60 | 150 | 37 | 16.8 / 30.7 | 57 / 65 | 94.0 | 6.0 |
| 240 | fixed @fps | 150 | 147.5 | 25.1 / 34.7 | 25 / 44 | 95.3 | 4.0 |
| 240 | submitted @60 | 150 | 37 | 23.7 / 41.0 | 53 / 61 | 96.0 | 5.3 |

What it shows:

- **With true timestamps, frame rate barely moves the error.** Median lateral error stays at 23.3 to 24.8 mm from 30 to 240 fps. Vertical error falls from 42.3 to 31.7 mm, and agreement rises from 92.7% to 96.0%.
- **Coverage gets worse as the rate goes up.** The pipeline's 1-sigma covers 67% / 69% at 30 fps and 30% / 42% at 240 fps. More frames shrink the fit sigma, but the model-error bias does not shrink with it. This is the same diagnosis as section 3, seen from another side, and it contradicts main.tex:426 ("almost no effect").
- **The submitted sampler was worst at low rates.** At 30 fps it fetched each frame about twice (37 frames against 18.5) under labels up to a frame apart: median error 94.4 / 156.8 mm and agreement 88.3%, against 27.4 / 43.9 mm and 93.3% for the fixed sampler. At 60 fps, the rate the app records at, it cost 35.5 / 64.8 mm against 26.1 / 37.1 mm fixed, and agreement 91.9% against 96.0%.
- **The fixed sampler is close to timestamps at 30 and 60 fps**: within 4.1 mm of median error and one percentage point of agreement. At 120 and 240 fps the app still asks for 60 Hz, so it uses every second or fourth frame (37 frames). Its median error there is 21.9 / 38.0 mm and 16.8 / 30.7 mm, and its coverage is better than with every frame (53 / 62 % and 57 / 65 %), because fewer frames shrink the sigma less while the model error stays the same.

## 8. Things the runs turned up in the code

- **The submitted frame sampler mislabelled frames. Fixed.** At submission `process_job.py` asked
  for a frame every `round(1000 / sample_fps)` ms and labelled each with the requested time, not
  the frame's own timestamp. The app always sends `sample_fps: 60` (`analyze_screen.dart:326`), so
  the step was 17 ms whatever the video's rate. `VideoReader.frame_at_ms` returns the nearest
  frame, so on a 60 Hz clip each label was off by a sawtooth of up to half a frame (8.3 ms) and
  one frame in 50 was skipped; on a 30 Hz clip every frame was fetched about twice under two
  labels up to 16.7 ms apart. Frames now carry their decoded timestamp (commit 143d31b); repeats
  and backwards stamps are dropped, and a missing stamp falls back to the requested time with a
  warning. `uq.frame_times(..., "submitted")` reproduces the old sampler and `"fixed"` the new
  one (commit 0893393), so exp9 reports both. Section 14 has what it changes.
- **The paper's guard band is not the code's.** main.tex:337 says each band is widened to
  max(R, kσ). `decision.py:_band` does something else: a call is "in" only when the centre is at
  least kσ inside the edge, and "out" only when it is more than R + kσ outside. So the code uses
  R + kσ on the outside and kσ on the inside, which is the JCGM 106 form (acceptance limit moved
  by the guard band). Reviewer 1 (M4) asks exactly why max and not R + kσ. The text should
  describe the code.
- **exp2 and exp3 sat on the old geometry. Rerun.** The 2026-09-02 CSVs carried verdicts and
  truth labels on the 26.4 cm wicket with the old bands, and the submitted code. Section 11.
- **The tapped pose was not refined on the pixels. Fixed.** Section 14.
- **The retrained detector fires on a large round object in test4. Filtered.** Section 14.

## 9. Threats to validity

- **The synthetic world is still partly circular.** exp4 to exp9 all use `synth.py`'s flight
  model. Its bounce (restitution plus friction at contact) is the estimator's own bounce model,
  and every "unmodelled" effect in exp8 is one the generator already knows how to make. Nothing
  here has metric truth from a real delivery. Review item 5 (a paper screen and bounce marks,
  40 to 60 deliveries) is the only thing that breaks this, and it needs filming.
- **σ_mod was fitted on the same generator it is tested on.** It is cross-validated on held-out
  World B deliveries, but those come from the same distribution. exp8 shows the limit: with the
  effects switched off the full σ over-covers (82.4 / 96.0 %), and with restitution at 0.40 it
  under-covers height (77.5 %). The model term covers the world it was estimated in and should
  be described that way.
- **Coverage after the fix is not nominal in both directions.** Lateral 95 % coverage is 90.7 %,
  about five standard errors short, and height over-covers at 85.5 / 97.7 %. A Gaussian with one
  additive term cannot fit both the core and the tail. A heavier-tailed PDF for the model term
  was not tried.
- **The chosen k depends on this sample.** k_specific is set by where 599 deliveries' out calls
  happen to fall, with only 39 true outs. At 5 % it went from 1.40 before the pose refine to 1.00
  after it, and at 1 % from 2.15 to 1.85. The closed-form bounds (2.23 and 2.81
  for four tests) do not depend on the sample, which is why they are quoted next to it.
- **The risk model is simple.** Flat prior, Gaussian errors, the four Law 36 tests treated as
  independent. The y and z errors at the stump plane are correlated and that is ignored.
- **exp2 and exp3 use a retrained detector.** The submitted weights were lost, so the rerun numbers
  come from a different detector than the submitted ones (section 11). main.tex says so.
- **Reference camera only.** exp4 to exp9 use the camera behind the striker at 2.8 m. The other
  five placements were not budgeted.
- **The Type B ranges are assumptions.** Rolling shutter ±30 ms, pitch width ±10 cm, stump
  height ±1 cm, distortion ±1 %, seam ±2 deg and turn up to 6 deg have no measured source. Drag,
  swing and restitution come from Mehta 2005 and James et al. 2004. The budget is only as good
  as these ranges.
- **The distribution budget uses coarser quadrature** than the representative delivery (3 nodes
  and 2 frame phases against 5 and 8) to keep runtime down. The representative delivery is the
  one with full resolution.
- **The Monte Carlo is not adaptively stable.** exp5 stopped at the 3-batch cap without meeting
  the JCGM 101 7.9 stability test at δ = 0.5 mm (section 2). The subset uses 1000 trials per
  delivery, which is too few for a 0.5 mm tolerance.
- **Rolling shutter is simulated but not corrected in the app.** The "corrected" cells in exp6
  tell the solver the true readout time and shift each detection's time by its image column
  (`uq.py:165`), so they show what a correction could buy, not what the app does. `reconstruction.py` and `process_job.py` still
  have no rolling-shutter input.
- **The runtimes come from one shared machine** (11 cores, other jobs running), so they vary from
  run to run.

## 10. Prose the new numbers break

Line numbers are `paper/main.tex` before the section 12 changes (`git show 94d6645:paper/main.tex`).
Rows marked "done" are changed in main.tex; the others need the author's call.

| main.tex | What it says now | What the new files show | Suggested change |
|---|---|---|---|
| 45-46, 589 | the propagated bound is "slightly optimistic", covering \CovYOne / \CovZOne % (now 51.6 / 61.4) | On World B the app's sigma covers 53.6 / 60.8 % at 1σ; the cross-validated model term brings it to 63.9 / 85.5 % [CovBFit*One, CovBFull*One]. Over the Monte Carlo trials the pipeline sigma has a median of 27.2 mm in y against a real spread of 55.0 mm [McPipeSigmaMedY, McUY]. "Slightly" undersells it. | done: "misses model error ... raises this to ..." |
| 100, 388 | the real clips give "a repeatability test" | What exp3 does is re-fit the same clip on its even and odd frames. That is within-clip resampling, not repeatability in the VIM sense (JCGM 200, 2.21: same procedure, operator and system, repeated measurements on the same object). | "half-rate consistency" or "a split-frame check". Left for the author, since it touches three places in the author's prose. |
| 186-187 | Robinson's equations of a spinning sphere "under drag and lift, which the synthetic generator integrates" | Only partly. `synth.fly` integrates quadratic drag and a lateral side force before contact, and applies spin as a sideways turn at contact. It has no lift (Magnus) term. | "whose drag and side-force terms the generator integrates". Left for the author. |
| 214-215 | $w_o = 0.132$ m, stumps $h_s = 0.711$ m | Law 8 gives ±0.1143 m; the decision zone now reaches the bails, 0.7239 m (commits d14d948, 91e0bf8) | done: 0.1143 and $h_b = 0.724$ m |
| 312-314 | the covariance "is a first-order approximation and Section measures how far it can be trusted" | The Monte Carlo fails the JCGM 101 check by up to 84.5 mm, and the height distribution is shifted, not just wider [McDHighZ, McMeanZ]. | Still true as written; the new budget subsection answers it. Optionally add "and a Monte Carlo check shows where it fails". |
| 336-342 | each band is widened to $\max(R, k\sigma)$ with $k = 1$ | `decision.py:_band` uses $k\sigma$ inside and $R + k\sigma$ outside (section 8). With the full sigma, $k = 1.00$ keeps every out call under 5 % specific risk and $k = 1.85$ under 1 % [RiskFullKFive, RiskFullKOne]; before the pose refine these were 1.40 and 2.15. | done: the text describes the code's rule |
| 350 | the generator uses drag $C_d = 0.5$ | true for exp1. exp4 to exp9 draw $C_d$ from 0.35 to 0.55 (Mehta 2005) | none for exp1; the supplement should say which experiments use which range |
| 362 | "the estimator never receives the true camera" | This was not true before commit 81f97e0: the synthetic runs handed the solver the true focal length. Now the focal length is solved from the taps, with a 1.65 % median error [AblAppFocalErr]. | done: added "the focal length is solved from the taps with $L$ fixed" |
| 385-386 | frame-interval jitter "is small beside" the pixel term | On the representative delivery, jitter is 2.9 / 15.8 mm against 7.3 / 35.2 mm for ball centre and bounce split; medians 6.9 / 9.5 against 15.6 / 25.1 mm (`tables/budget.tex`). Half the size is not small. | done: points to the budget table instead |
| 386-387 | rolling shutter is "the one electronic error source the stated uncertainty does not account for" | Uncorrected rolling shutter is 0.7 / 4.0 mm on the representative delivery and 3.1 / 6.7 mm median. Lateral 1σ coverage is 55.3 % with no skew and 56.8 % with 30 ms [SwRsZeroCovFitY, SwRsThirtyCovFitY]. The term the sigma misses is model error, σ_mod 11.2 / 54.0 mm [ModYSigMod, ModZSigMod]. | done: "changes neither accuracy nor coverage measurably" |
| 422 | "a target 26 cm wide" | Law 8 wicket is 22.86 cm | done: 23 cm |
| 426-428 | frame rate "has almost no effect from 30 to 240 Hz" | With true timestamps agreement goes from 92.7 % at 30 fps to 96.0 % at 240 fps, so that part holds. Coverage does not: the pipeline's 1σ covers 67 / 69 % at 30 fps and 30 / 42 % at 240 fps (exp9). At 30 fps the submitted sampler gave 88.3 % agreement and 94.4 / 156.8 mm median error. | done: added "the stated sigma, though, shrinks with the frame count while the model error does not". The sampler bug is in the changes paragraph. |
| 428-429 | tap error "has little effect until it is large" | exp8: 0.9 to 1.1 mm per pixel of tap error and at most 8 of 299 verdicts change (2.7 %). One goes straight from out to not out or back: random 10 px taps under the app's rule [TapRandomOneZeroPxHardFlipsFit]. | exp8 supports "little effect". But Table II gives 95.8, 96.0, 94.5 and 95.2 % at 0, 2, 8 and 12 px, so "until it is large" implies a fall the data don't show. Author's call: "has little effect across the range tested". The clause predates the rerun. A 10 px tap is five times the budget's 2 px. |
| 433-437 | unmodelled physics moves agreement from \PhysOffAgree to \PhysOnAgree % | Now \PhysOffAgree to \PhysOnAgree = 94.5 to 96.2 %, still true for exp1's mild physics. At literature magnitudes agreement stays at 94.5 to 98.0 %, but swing Cs 0.3 moves the median lateral error from 9.9 to 43.8 mm and biases height by -52.1 mm. Combined pace effects give 26.0 / 39.2 mm and fit coverage of 51.5 / 64.0 % (exp8). | done: the Limitations item carries the exp8 numbers |
| 442 | disagreements "lie within a few millimetres of a band edge" | No produced file measures this. | done: the clause is cut. The alternative is to measure the margin of each disagreement in exp1 and quote it. |
| 447-464 | camera placement table* and paragraph | agreement moved by at most 0.7 points. The low and reference cameras swapped order, so "\CamStrikerHighAgree\% to \CamStrikerLowAgree\%" at 458-459 now reads 94.8 % to 94.2 %. | done: three sentences, the table moves to the supplement, and the paragraph quotes \CamStrikerMinAgree to \CamStrikerMaxAgree |
| 466-485 | coverage subsection, "the 55 % bound" | replaced by the budget, Monte Carlo and coverage results | done: the uncertainty budget subsection |
| 487-497 | k curve on exp1, "we ship $k = 1$" | replaced by the JCGM 106 risk curve | done: the guard band subsection |
| 566-573 | Limitations: "first-order approximation", "ignores drag, swing..." | see sections 2, 3 and 5 | done: the first two Limitations items |

## 11. exp2 and exp3 on the retrained detector

**Rerun on 2026-09-26 (567f905).** Both run the app pipeline with the learned detector, which
loads `server/models/cricket_ball.pt` (`process_job.py:50`). The submitted weights were lost, so the
detector was retrained on photos and cricket video frames (`server/models/DETECTOR.md`, sha1
`c3cdaba4`). Both experiments ran on those weights with the Law 8 wicket, the new bands and the fixed
code, and exp2 solves the focal length from the taps (`pin_fov: false`). The submitted runs are kept as
`raw/exp2_*_submitted.*` and `raw/exp3_real_submitted.csv`. Rendered clips agree on \EteAgree{} of
\EteN{} with \EteFalseOut{} false outs, so the two "no false outs" claims (main.tex 44 and 599) still
hold. The Real footage paragraph and Table V are written on the rerun.

## 12. main.tex changes (stays at 8 pages)

Every change below is in `paper/main.tex` and `paper/refs.bib`; `git diff 94d6645 -- paper/main.tex
paper/refs.bib` shows them. Line numbers on the left are the old main.tex.

**Result with the committed `numbers.tex`: 8 pages**. No undefined references or
citations, no BibTeX warnings, no overfull boxes. The one underfull hbox (lines 288-290) and the two
`OT1/ptm/m/scit` font warnings are in the unedited paper too (lines 294-296 there). Two underfull vbox
warnings on page 6 are new: the left column there is stretched to fill the space between Tables III and
IV and the text below them. They are cosmetic and go away with any later reflow. The right column on
page 8 now ends a few lines short of the bottom; that is all the room there is, so anything longer than
that has to be paid for with a cut.

### What replaces what

| old main.tex | Replaced by | Size change |
|---|---|---|
| 466-485, "How far the stated uncertainty can be trusted": Fig. coverage and the "55 % bound" text | Table budget (groups, representative delivery and median), Table coverage (before and after the model term), two paragraphs | one column figure out, two column tables in |
| 487-497, "The decision band": k curve on exp1, "we ship k = 1" | Fig. risk (specific false-out risk and agreement against k) and the JCGM 106 paragraph | one column figure in |
| 336-342, the max(R, kσ) band | The rule `decision.py` actually applies, kσ inside and R + kσ outside | about the same |
| 447-464, "Camera placement" subsection and its table* | One paragraph, no heading | one full-width table out |
| 501-509, Experiment 2 table* | nothing; the text already quotes its numbers | one full-width table out |
| 566-573, the first two Limitations items | Model error is outside the sigma; exp8 physics numbers | about the same |
| 193-197, Related Work, "Camera pose from known points..." paragraph | nothing; the method cites the same works where it uses them | 5 source lines out |
| 345, start of Experimental Setup | what changed in the app after submission and why (section 14), with exp9's `FpsThirty*AtSixtyAgree` and `CalUnrefSdY` / `CalAppSdY` from `theory/out/calib_check.txt` | 6 source lines in |
| 261, 271, 272, Method | one clause each: the pixel refine of the pose, the size test, the flight test | 3 source lines in |

### Moves to the supplement

- the per-input budget table, `tables/budget.tex` (the paper keeps the grouped `tables/budget_short.tex`)
- the Monte Carlo tables, `tables/mc.tex`
- the coverage sweeps over rolling shutter and model-term size, `tables/coverage_sweeps.tex`
- the physics degradation table, `tables/physics.tex`, and the tap table, `tables/taps.tex`
- the frame-rate table, `tables/fps.tex`
- the camera placement table (`tab:cameras`) and the Experiment 2 per-length table (`tab:rendered`)
- the old coverage figure, `figures/coverage.pdf`
- the calibration ablation of section 0

### Small edits

- Abstract (37): "the estimate's own one-sigma bound" becomes "a guard band set from the risk of a false out".
- Contributions (45-46): "slightly optimistic, covering \CovYOne / \CovZOne" becomes "misses model error
  and covers \CovBFitYOne / \CovBFitZOne ... a cross-validated model term raises this to \CovBFullYOne /
  \CovBFullZOne".
- Geometry (214-215): $w_o$ = 0.132 becomes 0.1143, $h_b$ = 0.724 m is added, and the height test uses
  $z^\star \leq h_b$.
- Setup (362): adds "the focal length is solved from the taps with $L$ fixed".
- Setup (385-387): jitter points to Table budget instead of "small beside it"; rolling shutter becomes
  "changes neither accuracy nor coverage measurably".
- Results (422): "26 cm" becomes "23 cm".
- Results (426-428): adds "the stated sigma, though, shrinks with the frame count while the model error
  does not".
- Results (442): cuts "the decisive-for-marginal cases lie within a few millimetres of a band edge", which
  no produced file measures.
- Conclusion: "slightly optimistic" becomes the model-error and guard-band wording, and the last sentence
  is shortened.
- Setup and Method: the changes paragraph and the three Method clauses.

### Cuts made only to fit

The first full build came out at 9 pages. These brought it back to 8: dropping the Related Work pose
paragraph, moving the Experiment 2 table, cutting the 442 clause, folding camera placement into one
paragraph, removing a global-risk sentence from the guard band text and an "acceptance limit is moved" sentence
from the decision rule, and shortening the Conclusion's last sentence. Shrinking the risk figure changed
nothing, because IEEEtran stretches the page to fill it, so it stayed at column width. Only cuts late
in the flow (Limitations, Conclusion) moved the references.

The changes paragraph and the Method clauses put it back to 9 pages. These paid for them, again all late
in the flow except the first two:

- Detection: "This stage is not the contribution; it is the input the reconstruction is given." is cut.
- Physics related work: the drag clause "which at 40~m/s is a deceleration comparable to $g$" is cut.
- Limitations: the "No metric truth" item ends "A second phone at right angles would supply it."; the
  contact item is one sentence; the calibration item is one sentence; the first Limitations item opens
  with "Swing, drag and pitch variation ... are outside the covariance."
- Conclusion: the opening two sentences become one, the restatement of the linear problems is cut, and the
  "installs nothing" sentence is dropped.
- Acknowledgments: the code sentence is shortened to "Code, raw results and the scripts that regenerate
  every number are at ... (AGPL-3.0)."

Page 8 now ends with the biography at the foot of the right column, so there is no slack at all. The Real
footage paragraph and Table V are already on the rerun (section 11). Any later change must be no longer
than what it replaces, and the paper must be rebuilt to check it is still 8 pages.

The rows of section 10 left for the author are unchanged (100/388 "repeatability", 186-187
"which the synthetic generator integrates", 350 $C_d$ range).

## 13. Review items this covers

The items are from section C, "Ranked action list", of the mock review of TIM-26-10891. For each one:
what it asked for, what was done, and what is still open.

**1. Law 8 width, ICC bands, bails, rerun.** Done.
- Outer stump edge 0.1143 m (d14d948). Umpire's call is one-sided, there is no band on the pitching
  test, and the zone reaches the top of the bails at 0.7239 m, quoted from ICC Appendix D 3.4 (91e0bf8).
- True crossing and contact positions are now in the exp1 CSV (5e36eba), as the item asked.
- exp1 was rerun (ccce0b7), and again on the pose refine. Agreement went from 94.3 to 93.7 %, inside
  the review's "a point or two". Every macro that moved is in section 0 and Appendix A.
- main.tex 215, 336-337 and 422 are fixed (section 12).
- exp2 and exp3 were rerun on the retrained detector (section 11).

**3. Unpin the focal length and the pitch length.** Done for exp1 and exp2.
- `synth.py` and `exp2_rendered.py` no longer pass the true field of view. The grid now spans 20 to
  130 deg with a continuous polish, so 90.5 deg is inside it (81f97e0).
- The ablation in section 0 tests 70 and 90.5 deg cameras. Median focal error is 1.65 % with the app's
  setup; agreement is 96.0 % against 95.8 % pinned, and median stump-plane error is within 0.1 cm.
- The near-degeneracy claim (line 259) is now shown: freeing the pitch length as well gives an 8.38 %
  focal error and puts the contact point 42.7 cm off.
- **Open:** coverage was not tabulated per ablation cell. The main run's 1σ coverage moved from
  50.5 / 60.6 to 51.6 / 61.4 %, but that run also changed the geometry and the pose refine.

**4. GUM budget with a model-discrepancy Type B term.** Done (exp4 and exp6), with two gaps.
- Rows present: taps, ball centre, frame jitter, frame phase, rolling shutter, frame-rate metadata,
  distortion, pitch and wicket dimensions, bails, and five physics rows (section 1).
- The model term is fitted by maximum likelihood and chosen by 5-fold cross-validation, so each delivery
  is scored with a term fitted without it (section 3).
- Result: lateral 1σ coverage 63.9 %, about 2.3 standard errors short of 68.3 %. Lateral 95 % is
  90.7 %, about five standard errors short. Height over-covers, 85.5 and 97.7 %.
- On exp8's physics rows, with the term fitted on World B, full-sigma coverage is 65.0 / 85.5 % under
  combined pace and 82.4 / 96.0 % on the baseline (section 5). So it does not transfer cleanly.
- **Gaps:** no detector streak-bias row, since it needs exp2. The ball-centre row is a 1 px Type B
  assumption, not Type A from the residuals.

**6. Physics the solver does not assume.** Partly done (exp8); the second generator was not built.
- exp8 runs drag, swing, seam, turn, restitution and friction at literature magnitudes through the
  unchanged estimator (section 5). Agreement stays at 94.5 to 98.0 % against 96.0 % on the baseline,
  inside the review's 2 points.
- **Not done:** Magnus lift, restitution that depends on speed and angle, late swing that grows as the
  ball slows, pitch tilt, and spin-dependent skid. `synth.py` has none of these. Its side force grows
  with speed squared, the opposite shape to late swing.
- exp8 uses the same generator as World B, where the model term was fitted, so it does **not** break the
  shared-model circularity the item was aimed at.

**7. Rolling-shutter term, correction and resweep.** Done in simulation; the app is unchanged.
- `uq.py` gives each detection the time t_i = k/fps + ρ(u_i/W - 0.5). exp6 sweeps ρ over 0, 5, 10, 16
  and 30 ms, both signs, with and without correction. The budget has the row: 0.7 / 4.0 mm on the
  representative delivery, 3.1 / 6.7 mm median.
- At 16 ms uncorrected, the lateral mean error moves from 5.2 mm (ρ = 0) to 0.5 mm (+16) and 9.9 mm
  (-16). Corrected, it is 5.1 and 5.3 mm (`raw/exp6_model_error.json`). All of this is small beside the
  17.4 mm median error.
- **Open:** the correction lives only in the harness (`uq.py:165`) and is handed the true ρ.
  `reconstruction.py` and `process_job.py` were not changed, and ρ is neither passed in nor fitted.

**10. JCGM 101 Monte Carlo.** Done (exp5), with a different design from the one asked for.
- The run is 30,000 trials on the representative delivery with adaptive stopping, plus 10 deliveries
  at 1000 trials each, instead of 200 × 500 (section 2).
- The adaptive rule was not met. Twice the batch standard deviation was still 2.8 mm against a
  0.5 mm δ.
- It draws every budget input, physics included. So it does see the model bias the review expected it
  to miss: the height distribution is shifted, and the linear budget fails validation by up to 84.5 mm.
- **Open:** a measurement-only Monte Carlo was not run. That run would test the review's claim that the
  Monte Carlo matches the linear sigma when the model is right. The nearest check is exp4's 20
  noise-only runs, which scatter by 7.37 / 36.77 mm against a measurement-only RSS of 8.5 / 41.1 mm.

**11. Empirical coverage factor.** Done (exp6 and exp7), reported as a diagnostic only.
- On exp1 the factors are 1.47 / 1.19 for 68 % and 3.48 / 3.43 for 95 %, close to the review's own
  1.51 / 1.23 and 3.68 / 3.64. With the full sigma on World B they are 1.09 / 0.66 and 2.47 / 1.53.
- As the item advised, the decision band does not use them. exp7 sets k from a false-out risk limit
  instead: 1.00 for 5 % and 1.85 for 1 % (section 4). Before the pose refine these were 1.40
  and 2.15.

## 14. App changes since submission

Three faults in the submitted app were fixed during revision, and every experiment was rerun on the
fixed code (section 9 has the runtimes, section 11 the detector runs). The paper says so in a new
paragraph at the start of Experimental Setup (section 12).

### Frame timestamps (143d31b, modelled in 0893393)

What was wrong is in section 8. exp9 runs both samplers on the same deliveries
(`raw/exp9_fps.json`, 150 per rate, fits on the app's 60 Hz request unless it says "@fps"):

| Clip rate | Sampler | Fits | Median lateral / vertical error | Agreement |
|---|---|---|---|---|
| 30 Hz | submitted | 145 | 94.4 / 156.8 mm | 88.3 % |
| 30 Hz | fixed | 150 | 27.4 / 43.9 mm | 93.3 % |
| 60 Hz | submitted | 149 | 35.5 / 64.8 mm | 91.9 % |
| 60 Hz | fixed | 150 | 26.1 / 37.1 mm | 96.0 % |

At 30 Hz the submitted sampler fed every frame twice under two labels, which more than tripled
the error. At 60 Hz the half-frame sawtooth still added about 9 mm laterally. exp1 and exp4 to exp8
hand the estimator every frame at its own timestamp (`uq.Effects(sampler="exact")`), so the fault
never reached them; their numbers move because of the pose refine below. The submitted exp2 and
exp3 results went through the faulty sampler; the reruns do not (section 11).

### Pose refined on the pixels (2f99c7b)

SQPnP minimises an object-space error, not the pixel error the taps actually have. On 400 noisy
tap sets (`theory/calib_check.py`, `theory/out/calib_check.txt`) the unrefined pose lost
information in one direction: its covariance against the lower bound had a largest generalised
eigenvalue of 16.03, and the yaw spread was 3.98 times the bound. A 7-parameter Levenberg-Marquardt
refine on the pixel residuals now runs after SQPnP. It brings the largest eigenvalue to 1.15 and
every coordinate to within 2 % of the bound. At the stumps, for a 120 km/h ball pitched 8 m out,
calibration's own spread drops from 0.88 / 0.71 cm to 0.42 / 0.56 cm (bound 0.41 / 0.55 cm). If
the refine fails or raises the pixel error, the app keeps the SQPnP pose and warns.

What the refine moved in the reruns:
- The taps' share of the budget roughly halved laterally: median 6.6 → 3.4 mm in y and 5.8 → 4.8 mm
  in z, and 5.7 → 3.0 / 4.9 → 4.8 mm on the representative delivery [BudGrpTaps*] (section 1).
- The lateral model term fell from 14.2 to 11.2 mm [ModYSigMod], and the full-sigma k fell from 1.40
  to 1.00 at 5 % and from 2.15 to 1.85 at 1 % [RiskFullKFive, RiskFullKOne] (sections 3 and 4).
- Tap errors change fewer verdicts, at most 8 of 299 against 10. But one verdict now jumps straight
  from out to not out or back: random 10 px taps under the app's rule (section 6). No such jump
  appears at 2 or 5 px.

### False detections (0285b1c)

The retrained detector fired on a large round object near the top of the frame in test4. Nothing
in the submitted app could reject it, because the tracker takes the best-scoring arc and the arc
through a fixed object is flat and long. Two tests now run, both from physics and geometry only.

**Size and place test (`tracking.drop_impossible`, every frame).** A detection is kept only if its
pixel ray enters the volume a ball in play can occupy, and its radius fits a regulation ball
somewhere along that stretch of the ray, with motion blur. Each limit and where it came from:

| Limit | Value | Source |
|---|---|---|
| Ball radius | 3.26 to 3.65 cm | Laws 4.1 and 4.6: circumference 20.5 cm (under-13 ball) to 22.9 cm (men's) |
| Top speed, for blur | 45 m/s | above the fastest recorded delivery, 161.3 km/h |
| Volume length | stumps to stumps plus 1.22 m each end | Law 7.4: the return creases run 1.22 m behind the stumps |
| Volume half width | 3.0 m | return crease at 1.32 m plus an arm; the flight fit's own release bound |
| Volume ceiling | 4.0 m | above any release; the flight fit's own release bound |
| Size slack | 2x | a colour segmenter may see only the lit half of the ball (0.71 of the radius), and a box can be loose |
| Size pad | 2 px | the floor the learned detector's radius is clamped to |
| Exposure cap | 1/240 s | exposure is at most one frame; past 240 Hz a misreported rate is assumed |

**Flight test (`process_job._fits_flight`, each candidate arc).** The part of the arc before any
bat or pad contact is fitted with the full 3-D flight model. Points more than 36 px off the fitted
flight are dropped and the fit is repeated. If the pixel rms is still above 12 px, the arc is
rejected and the next best arc is tried, up to 3. The 12 px limit is the one the app already used
to refuse a verdict before submission; 36 px is three times it, a 3-sigma rule even at the largest
residual the app accepts. The limit of 3 arcs only bounds the work. The retry happens only when
the flight test rejects an arc, so a clean clip runs exactly as before.

**Walk past the arc.** After the arc, the tracker walks on to the most confident nearby detection,
which may not be the ball. If the full fit then fails, walk points more than 36 px off the arc's
own flight are dropped, the fit is repeated, and a warning says how many were dropped.

**Known limit.** A false point that sits within 12 px of a plausible flight stays in the track.
Neither test can tell it from the ball.

**No limit was set on the real clips.** Every value above comes from the Laws, a record, or a bound
the app already had. test3, test4 and test5 are the Exp 3 test set and were not used to set or
check anything. The filter was checked on rendered clips only (`false_dets.py`).

### Check on rendered clips (`false_dets.py`)

`$PY false_dets.py` (474.9 s) and `--root DIR --tag before` on the code at 0893393 (467.4 s),
same 8 rendered not-out deliveries from the exp2 grid, same learned-detector weights (sha1
43983dcc). One fake 90 px box at confidence 0.95 is added to the learned detector's output on
a run of frames. Results in `raw/false_dets_{before,filtered}.csv` and `.json`.

| Scenario | Fake boxes | Before: right verdict | Before: fake points in track | After: right verdict | After: fake points in track | Fakes dropped by the size test |
|---|---|---|---|---|---|---|
| clean | 0 | 8 of 8 | 0 | 8 of 8 | 0 | none to drop |
| static, near the bottom edge | 233 | 3 of 8 (5 no verdict) | 5 | 8 of 8 | 0 | 0 |
| drift, along the bottom edge | 279 | 2 of 8 (6 no verdict) | 151 | 8 of 8 | 0 | 0 |
| top, near the top edge | 233 | 4 of 8 (2 umpire's call, 1 out, 1 no verdict) | 7 | 8 of 8 | 0 | 233 |

- **Before the filter, a fake at the top of the frame gave a false out.** One of the 8 not-out
  deliveries was called out and two went to umpire's call. The worst clip was 43.6 cm off
  laterally and 49.4 cm vertically. In the static and drift runs the fake mostly made the app
  refuse a verdict (3-D fit discarded at 19 to 362 px residual), which is safe but useless.
- **After the filter, every clip gives the same answer as with no fake.** In all three fake
  runs each clip's verdict, track length and error equal the clean run's (worst 0.92 cm lateral,
  4.47 cm vertical). The clean run itself is identical before and after the filter.
- **Which test caught what.** The size and place test dropped all 233 top-edge fakes. It kept
  every bottom-edge fake, because a ball that large close to the camera is possible. Those were
  removed later. In the static run the walk check dropped the fake in the same 5 clips where it
  had reached the track before. In the drift run the old tracker had taken the fake's own arc,
  every point fake, in 4 clips (deliveries 13, 26, 39 and 91); the flight test rejected each of
  those arcs. The walk check then dropped fake points past the arc in 4 clips (13, 39, 52, 78).
- **No ball detection was dropped.** The size and place test saw 725 detections within the
  ball's own blur of the true centre in each run and dropped none. It dropped 428 of 438 other
  detections, which the tracker ignored anyway.
- **What this does not show.** Eight deliveries, one camera, one fake shape. A fake that moves
  along a plausible flight within 12 px is the known limit above, and this check does not
  test it.

## Appendix A. Every exp1 macro that moved

115 of 196 macros in the submitted numbers.tex (tag paper-v1, 4271cd6) changed; 81 did not; 0 no longer exist: none.

| Macro | Submitted | Now |
|---|---|---|
| GeoNotOut | 9110 | 9783 |
| GeoOut | 512 | 715 |
| GeoUmp | 1178 | 302 |
| GeoFalseOut | 6 | 12 |
| GeoMissedOut | 3 | 12 |
| GeoFalseOutPct | 0.07 | 0.12 |
| GeoAgreeAll | 94.3 | 93.7 |
| GeoNoVerdict | 30 | 33 |
| GeoNoVerdictParabola | 1618 | 1620 |
| GeoMedYAll | 2.7 | 2.6 |
| GeoMedZAll | 3.9 | 3.8 |
| GeoMedYAllParabola | 30.5 | 30.2 |
| GeoMedZAllParabola | 42.7 | 42.4 |
| GeoMedSpeedErr | 14.4 | 14.1 |
| GeoMedContactX | 4.7 | 8.0 |
| RefAgree | 95.2 | 94.0 |
| RefPNineZeroY | 9.2 | 9.5 |
| RefAgreeParabola | 30.2 | 27.2 |
| RefMedYParabola | 27.8 | 26.9 |
| RefMedZParabola | 43.5 | 43.0 |
| NoiseZeroAgree | 97.5 | 97.8 |
| NoiseZeroMedZ | 2.4 | 2.3 |
| NoiseZeroUmp | 38 | 15 |
| NoiseTwoAgree | 95.0 | 93.0 |
| NoiseTwoMedY | 2.9 | 2.7 |
| NoiseTwoMedZ | 4.5 | 4.4 |
| NoiseTwoUmp | 51 | 39 |
| NoiseThreeAgree | 93.0 | 89.0 |
| NoiseThreeMedY | 4.0 | 3.9 |
| NoiseThreeMedZ | 6.2 | 5.9 |
| NoiseThreeUmp | 52 | 46 |
| NoiseFiveAgree | 88.0 | 83.0 |
| NoiseFiveMedY | 5.3 | 5.5 |
| NoiseFiveMedZ | 8.0 | 8.3 |
| NoiseFiveUmp | 72 | 74 |
| FpsThirtyAgree | 94.2 | 94.8 |
| FpsThirtyMedY | 2.8 | 2.5 |
| FpsThirtyUmp | 37 | 19 |
| FpsTwoFortyAgree | 95.0 | 96.0 |
| FpsTwoFortyMedZ | 3.2 | 3.1 |
| FpsTwoFortyUmp | 38 | 19 |
| TapTwelveAgree | 91.0 | 95.2 |
| TapTwelveMedY | 3.2 | 3.1 |
| TapTwelveMedZ | 5.4 | 4.7 |
| TapTwelveUmp | 41 | 19 |
| TapEightAgree | 95.5 | 94.5 |
| TapEightMedY | 2.8 | 2.6 |
| TapEightMedZ | 4.4 | 3.8 |
| TapEightUmp | 42 | 23 |
| DropFortyAgree | 96.0 | 95.5 |
| DropFortyMedY | 2.4 | 2.2 |
| DropFortyMedZ | 3.7 | 3.5 |
| DropFortyUmp | 54 | 35 |
| PhysOffAgree | 97.0 | 94.5 |
| PhysOffMedY | 1.1 | 1.2 |
| PhysOffMedZ | 2.2 | 2.1 |
| PhysOffUmp | 48 | 36 |
| PhysOnAgree | 95.5 | 96.2 |
| PhysOnMedZ | 3.9 | 3.7 |
| PhysOnUmp | 38 | 23 |
| SweepAgreeMin | 88.0 | 83.0 |
| SweepAgreeMax | 97.5 | 97.8 |
| SweepAgreeMinParabola | 26.0 | 25.5 |
| SweepAgreeMaxParabola | 36.8 | 41.0 |
| SweepFalseOutMax | 1 | 4 |
| SweepFalseOutParabolaMax | 8 | 10 |
| CamStrikerLowAgree | 95.5 | 94.2 |
| CamStrikerLowMedZ | 2.3 | 2.1 |
| CamStrikerRefMedY | 2.5 | 2.3 |
| CamStrikerRefMedZ | 3.4 | 3.5 |
| CamStrikerHighAgree | 94.0 | 94.8 |
| CamStrikerHighMedY | 2.4 | 2.5 |
| CamStrikerHighMedZ | 5.3 | 5.4 |
| CamStrikerSideAgree | 90.5 | 90.2 |
| CamStrikerSideMedY | 4.4 | 4.2 |
| CamBowlerRefAgree | 88.0 | 87.5 |
| CamBowlerRefMedZ | 11.2 | 11.0 |
| CamBowlerRefNoVerdict | 7 | 8 |
| CamBowlerSideAgree | 86.0 | 83.8 |
| CamBowlerSideMedY | 7.3 | 7.4 |
| CamBowlerSideMedZ | 9.7 | 9.6 |
| CamBowlerSideNoVerdict | 1 | 3 |
| CovYOne | 50.5 | 51.6 |
| CovYTwo | 79.3 | 80.8 |
| CovYThree | 91.4 | 92.4 |
| CovYMedian | 0.99 | 0.96 |
| CovZOne | 60.6 | 61.4 |
| CovZTwo | 84.7 | 85.8 |
| CovZThree | 93.0 | 93.6 |
| CovZMedian | 0.76 | 0.74 |
| KZeroAgree | 94.5 | 96.2 |
| KZeroFalseOut | 13 | 40 |
| KZeroUmp | 10.4 | 2.9 |
| KZeroMissedOut | 12 | 56 |
| KZeroUmpInverse | 10 | 34 |
| KHalfAgree | 94.4 | 95.1 |
| KHalfFalseOut | 10 | 26 |
| KHalfUmp | 11.1 | 5.5 |
| KHalfMissedOut | 6 | 20 |
| KHalfUmpInverse | 9 | 18 |
| KOneAgree | 94.3 | 93.7 |
| KOneFalseOut | 6 | 12 |
| KOneUmp | 12.0 | 7.8 |
| KOneMissedOut | 3 | 12 |
| KOneUmpInverse | 8 | 13 |
| KOneHalfAgree | 93.9 | 92.1 |
| KOneHalfFalseOut | 5 | 9 |
| KOneHalfUmp | 13.0 | 9.9 |
| KOneHalfMissedOut | 3 | 8 |
| KOneHalfUmpInverse | 8 | 10 |
| KTwoAgree | 93.2 | 90.6 |
| KTwoFalseOut | 4 | 8 |
| KTwoUmp | 14.3 | 11.6 |
| KTwoMissedOut | 2 | 5 |
| KTwoUmpInverse | 7 | 9 |
