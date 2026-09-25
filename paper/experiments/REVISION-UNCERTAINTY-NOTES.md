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
1681.8 s on 8 workers). What moved, old value to new:

| Quantity | Macro | Submitted | Now |
|---|---|---|---|
| pooled agreement (%) | GeoAgreeAll | 94.3 | 93.7 |
| truly not out | GeoNotOut | 9110 | 9783 |
| truly out | GeoOut | 512 | 715 |
| false outs | GeoFalseOut | 6 | 14 |
| false-out rate (%) | GeoFalseOutPct | 0.07 | 0.14 |
| missed outs | GeoMissedOut | 3 | 13 |
| umpire's calls | GeoUmp | 1178 | 302 |
| contact point along pitch (cm) | GeoMedContactX | 4.7 | 8.3 |
| 1-sigma coverage, lateral (%) | CovYOne | 50.5 | 50.7 |
| 1-sigma coverage, vertical (%) | CovZOne | 60.6 | 61.3 |
| 2-sigma coverage, lateral (%) | CovYTwo | 79.3 | 79.8 |
| 2-sigma coverage, vertical (%) | CovZTwo | 84.7 | 85.3 |
| k = 0 false outs | KZeroFalseOut | 13 | 42 |
| k = 0 missed outs | KZeroMissedOut | 12 | 56 |
| k = 0 umpire's call (%) | KZeroUmp | 10.4 | 2.7 |
| k = 1 false outs | KOneFalseOut | 6 | 14 |
| k = 1 missed outs | KOneMissedOut | 3 | 13 |
| k = 1 umpire's call (%) | KOneUmp | 12.0 | 7.7 |
| k = 2 agreement (%) | KTwoAgree | 93.2 | 90.6 |
| k = 2 false outs | KTwoFalseOut | 4 | 9 |
| k = 2 missed outs | KTwoMissedOut | 2 | 6 |
| k = 2 umpire's call (%) | KTwoUmp | 14.3 | 11.6 |
| physics off, agreement (%) | PhysOffAgree | 97.0 | 95.5 |
| physics on, agreement (%) | PhysOnAgree | 95.5 | 96.0 |
| 5 px centre noise, agreement (%) | NoiseFiveAgree | 88.0 | 83.5 |
| 12 px taps, agreement (%) | TapTwelveAgree | 91.0 | 95.2 |
| worst sweep row, false outs | SweepFalseOutMax | 1 | 4 |
| bowler's-end camera, agreement (%) | CamBowlerRefAgree | 88.0 | 86.8 |

The full list of the 116 exp1 macros that moved is Appendix A at the end of this file.

Calibration ablation (`exp1_geometry.py --ablation`, 400 deliveries per cell, 1137.6 s):

| Setup | Focal error (%) | Contact x (cm) | Median y / z (cm) | Agree (%) | False outs |
|---|---|---|---|---|---|
| app setup: focal solved, L = 20.12 m (main run) | 1.68 | 7.8 | 2.3 / 3.6 | 95.0 | 0 |
| focal length handed to the solver (the submitted setup) | 0.00 | 3.9 | 2.3 / 3.6 | 94.5 | 0 |
| focal and pitch length both solved | 8.45 | 42.2 | 2.2 / 3.7 | 94.8 | 0 |
| 70 deg camera, app setup | 1.09 | 5.3 | 2.3 / 3.1 | 95.0 | 1 |
| 70 deg camera, focal handed over | 0.00 | 3.1 | 2.4 / 3.1 | 94.8 | 1 |

So pinning the focal length was hiding a 1.68 % focal error and doubling the pitching-point
accuracy, but it did not flatter agreement or the stump-plane error. Leaving pitch length free
as well is what breaks the contact point (42.2 cm). The app's setup is the honest one to report.

## 1. JCGM 100 budget (exp4)

`exp4_budget.py`, seed 404, 3399.4 s on 6 workers. Raw: `raw/exp4_budget_rep.csv`,
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
| calibration taps | B: 2 px per coordinate (real clips: 2.05-10.55 px reprojection) | 2 px | 2.84 mm/px | 2.47 mm/px | 5.7 | 4.9 | 6.6 | 5.8 |
| ball centre | B: 1 px per coordinate (assumed) | 1 px | 7.28 mm/px | 35.2 mm/px | 7.3 | 35.2 | 15.6 | 24.8 |
| frame-time jitter | B: 0.5 ms per frame (assumed; PTS jitter measures the muxer only) | 0.5 ms | 5.72 mm/ms | 31.6 mm/ms | 2.9 | 15.8 | 6.9 | 9.6 |
| frame phase | B: release instant U[0, T] against the frame clock | 4.81 ms | 0.0897 mm/ms | 0.517 mm/ms | 0.4 | 2.5 | 0.2 | 0.5 |
| shipped frame sampler | B: effect of the 17 ms request grid, RMS over phases | 17 ms grid |  |  | 16.7 | 86.4 | 18.3 | 37.4 |
| bounce split | A: split index from 20 noisy draws x effect of k+-1 | P = 0.5 |  |  | 0.0 | 0.0 | 0.0 | 0.0 |
| frame rate 59.80 vs 60 Hz | B: container rate over timestamp rate, U[0.99673, 1] (test5.mp4) | 0.189 % | 0.0791 mm/0.1 % | 0.524 mm/0.1 % | 0.1 | 1.0 | 0.4 | 1.3 |
| rolling shutter, uncorrected | B: readout 0-30 ms, either direction (assumed) | 17.3 ms | -0.02 mm/ms | -0.119 mm/ms | 0.7 | 4.0 | 3.1 | 6.7 |
| lens distortion | B: +-1 % radial at the corner (assumed) | 0.577 % | 0.109 mm/% | -1.27 mm/% | 0.1 | 0.7 | 0.2 | 0.9 |
| pitch length L | B: +-5 cm marking, rectangular | 2.89 cm | -0.000348 mm/cm | -0.0111 mm/cm | 0.0 | 0.0 | 0.0 | 0.0 |
| pitch width W | B: +-10 cm, corners are unmarked | 5.77 cm | 0.247 mm/cm | -2.17 mm/cm | 1.4 | 12.5 | 4.1 | 15.1 |
| stump height H | B: +-1 cm set depth | 0.577 cm | 0.444 mm/cm | -2.74 mm/cm | 0.3 | 1.6 | 0.7 | 1.8 |
| wicket half-width w | B: +-2.5 mm stump spacing | 1.44 mm | 0.00627 mm/mm | -0.0793 mm/mm | 0.0 | 0.1 | 0.0 | 0.1 |
| bails tapped as top | B: 0-1.27 cm, Law 8.3.1, uncorrected | 0.733 cm | 0.445 mm/cm | -2.76 mm/cm | 0.3 | 2.0 | 0.9 | 2.4 |
| restitution e | B: model, U[0.40, 0.70] (James et al. 2004 pitch range) | 0.0866 | -0.0878 mm/0.01 | -0.65 mm/0.01 | 0.8 | 5.9 | 1.0 | 4.4 |
| drag Cd | B: model, U[0.35, 0.55] (Mehta 2005), not modelled | 0.454 | -0.0812 mm/0.01 | -0.43 mm/0.01 | 3.7 | 19.0 | 10.6 | 20.6 |
| swing Cs | B: model, U[-0.3, 0.3] (Mehta 2005), not modelled | 0.173 | 2.22 mm/0.01 | -0.0316 mm/0.01 | 38.2 | 46.5 | 31.6 | 25.3 |
| seam deviation | B: model, U[-2, 2] deg off the seam | 1.15 deg | -1.16 mm/deg | 0.659 mm/deg | 1.4 | 1.0 | 0.4 | 0.6 |
| friction at contact | B: model, U[0.05, 0.20] speed loss | 0.05 | 0.104 mm/0.01 | 0.543 mm/0.01 | 0.7 | 4.1 | 1.0 | 2.1 |

u(x) is the standard uncertainty of the input (for a rectangular PDF, half-width/√3). u_i is in
mm. The last two columns are medians over the 100-delivery distribution below.

| | Lateral y (mm) | Vertical z (mm) | Macro |
|---|---|---|---|
| u_c without the sampler row | 39.7 | 65.4 | BudRepUcNoSamplerY/Z |
| u_c with the sampler row | 43.1 | 108.4 | BudRepUcY/Z |
| pipeline's own 1σ for this delivery | 9.4 | 44.6 | BudRepPipeSigmaY/Z |
| RSS of the measurement rows only (no physics rows) | 9.8 | 41.2 | from exp4_budget_rep.csv |
| scatter of 20 noise-only runs | 7.37 | 36.77 | exp4_budget.json |
| ball-centre row | 7.3 | 35.2 | BudRepSecondY/ZMm |

Variance shares without the sampler row: lateral, swing 92.8 %, ball centre 3.4 %, taps 2.0 %,
drag 0.9 %, jitter 0.5 %. Vertical, swing 50.7 %, ball centre 29.0 %, drag 8.4 %, jitter 5.8 %,
pitch width 3.7 %.

What this says:
- **The pipeline's σ is a fair measurement-noise σ.** The measurement rows alone give 9.8 / 41.2
  mm against the pipeline's 9.4 / 44.6 mm. The ball-centre row (7.3 / 35.2 mm) matches the
  scatter of 20 repeated noise-only runs (7.37 / 36.77 mm), which checks the Jacobian method.
- **What the pipeline's σ leaves out is the flight model.** Unmodelled swing alone is 38.2 /
  46.5 mm. That is why the stated σ under-covers (section 3).
- **Calibration and geometry inputs are small.** Taps 5.7 / 4.9 mm, pitch width 1.4 / 12.5 mm,
  everything else under 5 mm here. Rolling shutter over 0 to 30 ms either way is 0.7 / 4.0 mm.
- **Biases at nominal inputs**, counted inside u_i: drag -3.59 / -18.45 mm, swing -6.42 /
  -37.05 mm, bails 0.28 / -1.75 mm. The estimator's own error at nominal inputs, averaged over
  the frame phase, is 1.52 / 8.72 mm.
- **Bounce split:** the split index moved in half of the 20 draws, but moving it by one frame
  changed the crossing by 0.0 mm at this delivery.

**Distribution over 100 deliveries** (speed 60 to 150 km/h, length 1 to 10 m, line ±0.6 m,
release 1.8 to 2.3 m; 2 phases and 3 quadrature nodes to keep the run time down):

| | Lateral y (mm) | Vertical z (mm) |
|---|---|---|
| median u_c, no sampler [BudDistUcMedY/Z] | 48.3 | 54.4 |
| 90th percentile u_c, no sampler [BudDistUcPNinetyY/Z] | 88.5 | 129.4 |
| median u_c with the sampler [BudDistUcMedWithSamplerY/Z] | 65.0 | 82.9 |

- Largest row per delivery (no sampler): lateral, swing 66, drag 20, ball centre 11, taps 2,
  jitter 1. Vertical, swing 35, ball centre 32, drag 19, pitch width 10, restitution 3, jitter 1.
- Median variance share: lateral, swing 54.3 %, ball centre 12.2 %, drag 6.6 %. Vertical, ball
  centre 23.9 %, swing 17.5 %, drag 14.4 %, pitch width 6.6 %.

**The sampler row is a bug, not an uncertainty.** The shipped 17 ms request grid (section 8)
adds 16.7 / 86.4 mm on the representative delivery and a median 18.3 / 37.4 mm over the set.
It is reported as its own row and kept out of u_c. Fixing it removes it.

## 2. JCGM 101 Monte Carlo against the linear budget (exp5)

`exp5_mc.py --workers 6`, seed 505, 1350.3 s (representative 1085.9 s). Raw:
`raw/exp5_mc_rep.csv` (30,000 trials), `raw/exp5_mc_subset.csv` (10 × 1000), `raw/exp5_mc.json`.
Table: `tables/mc.tex`. Macros `Mc*`.

Method. Every input of the exp4 budget is drawn from its PDF at once and each trial runs the
app's calibration solve and the bounce-anchored fit, so the propagation is through the full
nonlinear solver, not a linearisation. The output is estimate minus truth at the stump plane.
The shipped sampler is left out, as in u_c. Validation follows JCGM 101 section 8: the
linear 95 % interval is y ± 1.96 u_c, and both end-point differences d_low and d_high must be at
most δ, where δ = ½ × 10^l comes from u_c written to two significant figures. For u_c = 39.7 mm
that is δ = 0.5 mm. The representative delivery uses the adaptive procedure of 7.9 in batches
of 10^4, capped at 3 batches.

**Monte Carlo trials: M = 30,000** on the representative delivery (3 batches, 0 failed
trials) [McM, McBatches, McFailed]. The 7.9 stopping rule was **not** met [McStable = no]: after
3 batches twice the batch standard deviation of the interval end points was still up to 2.9 mm
(y) and 1.9 mm (z) [McTwoSMaxY, McTwoSMaxZ], against δ = 0.5 mm. Meeting δ would take about
(2.9 / 0.5)^2 = 34 times as many trials, around 10 hours at the measured rate. The comparison
below does not need that: the differences are 25 to 84 mm, at least 8 times the numerical noise.

| Measurand | Linear estimate (mm) | u_c (mm) | Linear 95 % interval (mm) | MC mean (mm) | MC u (mm) | MC 95 % interval (mm) | d_low / d_high (mm) | δ (mm) | Passes |
|---|---|---|---|---|---|---|---|---|---|
| lateral y | 1.5 | 39.7 | [-76.3, 79.3] | -7.3 | 54.8 | [-128.8, 104.5] | 52.5 / 25.2 | 0.5 | no |
| vertical z | 8.7 | 65.4 | [-119.4, 136.9] | -46.8 | 53.8 | [-158.6, 53.0] | 39.1 / 83.8 | 0.5 | no |

What it shows:

- **The linear budget does not pass JCGM 101 validation**, for either measurand, by a wide
  margin: d_low / d_high = 52.5 / 25.2 mm in y and 39.1 / 83.8 mm in z against δ = 0.5 mm
  [McDLow*, McDHigh*, McValid*].
- **The Monte Carlo distribution is shifted, not just wider.** The linear estimate is 1.5 / 8.7 mm
  but the Monte Carlo mean is -7.3 / -46.8 mm. The unmodelled flight effects push the height
  error one way whatever their sign. exp4 already showed it for swing: a slope of -0.0316 mm
  per 0.01 of Cs but a -37.05 mm bias, because swing either way leaves the fit low. The budget
  counts that as a symmetric RMS term; the Monte Carlo shows it is a bias.
- **u differs in both directions.** The Monte Carlo standard deviation is 1.38 times u_c in y and
  0.82 times in z [McRatioY, McRatioZ]. The 95 % interval in z is asymmetric, [-158.6, 53.0] mm,
  which a ± k u_c interval cannot represent.
- **The pipeline's own σ over the same trials** has a median of 27.1 mm in y and 53.7 mm in z
  [McPipeSigmaMed*], against a Monte Carlo spread of 54.8 and 53.8 mm. So in y the shipped σ is
  about half the real spread, and in z it is about right. That matches exp6, where the shipped σ
  under-covers y more than z (51.7 against 61.2 % at 1σ).

Subset: the first 10 deliveries of the exp4 sample, 1000 trials each, no adaptive stopping.
That is too few trials for a 0.5 mm tolerance, so the pass counts below are expected to be 0 on
numerical grounds alone; the ratios are the useful part.

| # | Speed (km/h) | Length (m) | u_c y / z (mm) | MC u y / z (mm) | MC / linear, y / z | MC mean y / z (mm) | δ y / z (mm) | Passes y / z |
|---|---|---|---|---|---|---|---|---|
| 0 | 87 | 5.1 | 57.5 / 86.0 | 65.3 / 74.4 | 1.14 / 0.87 | -15.4 / -64.1 | 0.5 / 0.5 | no / no |
| 1 | 63 | 5.3 | 35.1 / 60.7 | 47.8 / 73.3 | 1.36 / 1.21 | -21.6 / -60.3 | 0.5 / 0.5 | no / no |
| 2 | 136 | 6.2 | 51.4 / 46.3 | 55.9 / 48.1 | 1.09 / 1.04 | -22.0 / -16.6 | 0.5 / 0.5 | no / no |
| 3 | 95 | 4.8 | 72.7 / 101.1 | 81.8 / 77.2 | 1.13 / 0.76 | -16.0 / -74.7 | 0.5 / 5.0 | no / no |
| 4 | 90 | 9.9 | 37.9 / 47.3 | 32.7 / 41.6 | 0.86 / 0.88 | 28.8 / -34.6 | 0.5 / 0.5 | no / no |
| 5 | 132 | 2.9 | 41.4 / 42.4 | 74.4 / 61.5 | 1.80 / 1.45 | 7.7 / -3.6 | 0.5 / 0.5 | no / no |
| 6 | 94 | 7.7 | 22.1 / 49.8 | 36.5 / 43.5 | 1.65 / 0.87 | 4.0 / -39.9 | 0.5 / 0.5 | no / no |
| 7 | 71 | 4.2 | 95.5 / 145.6 | 101.1 / 110.5 | 1.06 / 0.76 | 20.5 / -117.3 | 0.5 / 5.0 | no / no |
| 8 | 130 | 1.2 | 177.8 / 225.8 | 58.6 / 49.9 | 0.33 / 0.22 | 49.5 / -28.1 | 5.0 / 5.0 | no / no |
| 9 | 74 | 1.6 | 146.0 / 100.3 | 101.9 / 95.4 | 0.70 / 0.95 | -4.9 / -70.4 | 5.0 / 5.0 | no / no |

- **0 of 10 pass in y and 0 of 10 in z** [McSubValidY, McSubValidZ].
- **MC u over u_c runs from 0.33 to 1.80 in y (median 1.11) and 0.22 to 1.45 in z (median
  0.88)** [McSubRatio*]. The two lowest ratios are the two fullest deliveries (1.2 m and
  1.6 m). At 1.2 m the linear u_c is 3.0 times the Monte Carlo spread in y and 4.5 times in z.
- **The z mean is negative for all 10** (-3.6 to -117.3 mm). The bias is not a feature of one
  delivery.

Consequence for the paper. Quote the Monte Carlo interval for the stated uncertainty, or
correct the mean bias before using a symmetric interval. The linear budget is still the right
tool for ranking the inputs, but not for the interval itself.

## 3. Why the 1-sigma under-covers, and coverage after the fix (exp6)

`exp6_coverage.py`, seed 606, 2811.0 s on 5 workers (main run 2364.1 s). Raw:
`raw/exp6_worldb.csv`, `raw/exp6_sweeps.csv`, `raw/exp6_model_error.json`. Tables:
`tables/coverage.tex`, `tables/coverage_sweeps.tex`.

**World B.** 600 deliveries, 598 fitted, all 598 saw the bounce. It is exp1's physics world
(drag with Cd U[0.35, 0.55], swing, friction, turn, restitution 0.4 to 0.7) plus every
electronic and geometric input from the budget: 1 px centres, 10 % radius noise, 5 % dropout,
2 px taps, 0.5 ms frame jitter, frame-rate metadata U[0.99673, 1], rolling shutter U[-30, 30]
ms, distortion ±1 %, pitch length ±5 cm, width ±10 cm, stump height ±1 cm, stump spacing
±2.5 mm, bails U[0, 1.27] cm, reference camera, frames labelled with their own timestamps.

**Three σ sets.**
- fit: the pipeline's own covariance, as shipped.
- fit + cal: plus the tap noise pushed through the calibration solve (σ_cal).
- full: plus a model-error term σ_mod, fitted by maximum likelihood and chosen by 5-fold
  cross-validation. Each delivery gets σ_mod from the folds that did not contain it.

Model-error forms, chosen by held-out negative log-likelihood (lower is better):

| Measurand | Chosen form | Parameter | Held-out NLL: constant / proportional / both |
|---|---|---|---|
| pitching y | constant (+ proportional term at 0) | 11.74 mm | -1651.3 / -1552.73 / -1651.3 |
| crease y | proportional to bounce distance | 3.41 mm per m | -1216.16 / -1220.49 / -1218.5 |
| stump y | constant | 13.82 mm | -1122.95 / -1121.53 / -1121.52 |
| stump z | proportional to bounce distance | 9.20 mm per m | -609.53 / -663.41 / -662.98 |

Medians over World B (mm):

| Measurand | Mean error | Median abs error | σ_fit | σ_cal | σ_mod |
|---|---|---|---|---|---|
| stump y [ModY*] | 4.0 | 21.4 | 23.2 | 6.4 | 14.2 |
| stump z [ModZ*] | -16.6 | 35.5 | 46.4 | 6.9 | 53.8 |
| crease y [ModCrease*] | 2.7 | 14.1 | 12.9 | 5.2 | 19.9 |
| pitching y [ModPitch*] | -0.9 | 9.5 | 4.7 | 6.6 | 11.7 |

**Coverage before and after** (share of deliveries with |error| ≤ kσ; nominal 68.3 % at k = 1
and 95 % at k = 1.96). The binomial standard error at n = 598 is 1.9 points at 68 % and 0.89
points at 95 %.

| Run and σ | y at 1σ | y at 1.96σ | z at 1σ | z at 1.96σ |
|---|---|---|---|---|
| submitted paper, exp1 (at 1σ / 2σ) [CovY/ZOne, Two] | 50.7 | 79.8 (2σ) | 61.3 | 85.3 (2σ) |
| World B, fit (as shipped) [CovBFit*] | 51.7 | 84.1 | 61.2 | 85.1 |
| World B, fit + cal [CovBFitCal*] | 56.7 | 87.6 | 63.2 | 87.3 |
| World B, full [CovBFull*] | **66.4** | **91.5** | **86.1** | **98.0** |
| crease y: fit / fit + cal / full | 42.6 / 49.8 / 72.7 | 69.4 / 77.6 / 91.1 | | |
| pitching y: fit / fit + cal / full | 22.6 / 42.8 / 69.2 | 48.3 / 74.2 / 92.5 | | |

Empirical coverage factor: the k that actually covers 68.27 % and 95 % (percentiles of |e|/σ):

| σ | y: k68 / k95 | z: k68 / k95 | Macros |
|---|---|---|---|
| exp1 pipeline σ | 1.50 / 3.70 | 1.20 / 3.61 | KEmpExpOne* |
| World B fit | 1.37 / 3.03 | 1.23 / 3.31 | KEmpFit* |
| World B fit + cal | 1.23 / 2.59 | 1.13 / 2.70 | KEmpFitCal* |
| World B full | 1.05 / 2.35 | 0.65 / 1.51 | KEmpFull* |

**Sweeps** (199 fitted deliveries per cell out of 200; same world, one input fixed). Median
|error| in mm, then 1σ coverage fit → full. The binomial standard error at n = 199 is 3.3
points at 68 %.

| Cell | y median | y cover | z median | z cover |
|---|---|---|---|---|
| rolling shutter 0 ms | 17.5 | 51.8 → 67.8 | 35.2 | 59.8 → 85.4 |
| +30 ms, uncorrected | 19.8 | 52.8 → 73.4 | 34.8 | 59.8 → 85.9 |
| +30 ms, corrected | 18.2 | 53.8 → 72.4 | 32.5 | 62.8 → 85.4 |
| -30 ms, uncorrected | 20.4 | 52.8 → 69.8 | 38.7 | 59.8 → 83.9 |
| -30 ms, corrected | 19.1 | 54.3 → 71.4 | 34.7 | 64.8 → 87.4 |
| timestamps | 20.3 | 50.8 → 70.9 | 31.3 | 61.8 → 86.9 |
| timestamps, 59.80 Hz metadata | 21.4 | 50.3 → 71.4 | 33.5 | 62.3 → 86.4 |
| shipped 17 ms grid | 27.1 | 45.2 → 60.8 | 55.0 | 52.8 → 74.9 |
| shipped grid, 59.80 Hz metadata | 25.4 | 52.3 → 64.8 | 46.2 | 56.8 → 78.4 |

The ±5, ±10 and ±16 ms rolling-shutter cells are in the json and `tables/coverage_sweeps.tex`;
fit coverage stays between 49.2 % and 54.8 % in y across all of them.

**Diagnosis.**
- **Rolling shutter is not the cause.** Fit coverage in y is 51.8 % with no rolling shutter and
  52.8 % at +30 ms. The paper's worry (main.tex:386-387) does not show up in the data.
- **Calibration is a small part.** Adding σ_cal lifts 1σ coverage by 5.0 points in y and 2.0 in
  z at the stump. It matters more at the pitching point (22.6 % to 42.8 %).
- **Frame-rate metadata (59.80 against 60 Hz) does nothing measurable.**
- **The shipped sampler hurts both accuracy and coverage:** median error 27.1 / 55.0 mm against
  20.3 / 31.3 mm with timestamps, and fit coverage 45.2 / 52.8 % against 50.8 / 61.8 %.
- **The missing term is model error.** The median σ_mod (14.2 / 53.8 mm) is of the same size as
  σ_fit. With it, y at 1σ is 66.4 %, within one standard error of 68.3 %.

**What is still off, stated plainly.**
- **y at 95 % is low:** 91.5 % against 95 %, about four standard errors short. The lateral
  errors have heavier tails than a Gaussian: the empirical k95/k68 is 2.35/1.05 = 2.2, not 1.96.
- **z over-covers:** 86.1 % and 98.0 %. The Gaussian likelihood fit puts σ_mod wide enough for
  the tail, which makes it too wide for the core (median |e|/σ is 0.43). A heavier-tailed
  model-error PDF would fix both. That is left for later; for now the paper should state the
  empirical k from the table, not assume 1.96.

## 4. JCGM 106 guard band (exp7)

`exp7_risk.py`, 3.6 s. Runs on the 598 World B deliveries of exp6 (truth: 39 out, 15 umpire's
call, 544 not out). Raw: `raw/exp7_risk_curve.csv` (183 rows: 3 σ sets × 61 values of k),
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
- global risk is counted against the known truth: the joint false-out rate over all 598
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
| fit | 1 % | 2.25 | 91.8 | 10.7 | 3.2 | 0 | 0.50 | 51.3 |
| fit | 5 % | 1.20 | 95.2 | 6.9 | 4.8 | 1 | 0.79 | 28.2 |
| fit + cal | 1 % | 2.15 | 91.3 | 11.2 | 3.3 | 0 | 0.50 | 48.7 |
| fit + cal | 5 % | 1.45 | 93.6 | 8.9 | 4.0 | 0 | 0.50 | 38.5 |
| **full** | **1 %** | **2.15** | 88.1 | 14.4 | 2.0 | 0 | 0.50 | 69.2 |
| **full** | **5 %** | **1.40** | 91.5 | 11.0 | 3.2 | 0 | 0.50 | 51.3 |
| fit (shipped rule) | | 1 | 95.8 | 5.9 | 5.7 | 1 | 0.79 | 17.9 |
| any (no guard band) | | 0 | 97.5 | 2.3 | 6.9 | 2 | 1.05 | 2.6 |

Missed outs are 0 in every row above.

**The shipped rule's out calls are riskier than they look.** Scored with its own σ, the worst
OUT call at k = 1 has 6.1 % specific false-out risk [RiskFitKOneMaxSpec]. Scored with the full
σ, which section 3 shows is the honest one, the worst is 30.7 % [RiskShippedMaxSpecFull], the
mean over its out calls is 3.0 % [RiskShippedMeanSpecFull], and 5 of its out calls are above
5 % [RiskShippedOutsOverFive]. The count of false outs against truth (1 in 598) looks fine only
because most deliveries are nowhere near an edge.

**Global risk does not pick k.** The joint false-out rate is 0.33 % at k = 0 (2 in 598), already
under 1 %, so a point-estimate global rule would choose k = 0 for every σ set
[RiskFullKGlobalOne = 0.00]. The Clopper-Pearson 95 % upper limit gets under 1 % from k = 0.5 in
every set. With 39 true outs the sample is too small to pin a global rate near 1 %, which is why
the specific risk drives the choice.

**Recommendation.** Use the full σ and k = 1.40 for α = 5 %, or k = 2.15 for α = 1 %, and say
which one. Also state the sample-free worst-case bounds (2.23 and 2.81), since the chosen k
depends on where this sample's out calls happen to fall. The price is agreement (95.8 % shipped
to 91.5 % at α = 5 %) and more umpire's calls (5.9 % to 11.0 %), because half of the true outs
(51.3 %) now come back as umpire's call. That is the honest cost of a tool this uncertain, and
the paper should say so rather than quote 95.8 %.

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

| Row | n | Median abs y / z (mm) | Mean y / z (mm) | 1σ cover, fit, y / z (%) | 1σ cover, full, y / z (%) | Agree: fit k=1 / full k=2.15 / full k=1.40 (%) | Umpire's call, same three (%) |
|---|---|---|---|---|---|---|---|
| baseline | 199 | 10.0 / 19.4 | -0.9 / 7.2 | 69.3 / 78.4 | 84.4 / 96.0 | 96.5 / 86.4 / 92.0 | 7.0 / 17.1 / 11.6 |
| drag Cd 0.35 | 200 | 11.6 / 25.5 | -0.2 / 0.1 | 67.0 / 76.0 | 85.5 / 94.0 | 96.0 / 88.0 / 91.5 | 7.0 / 16.0 / 12.5 |
| drag Cd 0.45 | 200 | 12.0 / 25.0 | 0.2 / -4.8 | 63.5 / 68.5 | 81.0 / 90.5 | 96.5 / 87.5 / 93.0 | 6.5 / 16.5 / 11.0 |
| drag Cd 0.55 | 200 | 12.9 / 27.7 | -1.0 / -9.3 | 61.5 / 69.5 | 80.0 / 90.0 | 97.5 / 87.5 / 93.5 | 6.0 / 17.0 / 11.0 |
| swing Cs 0.1 | 199 | 17.5 / 23.7 | 1.5 / -4.8 | 60.3 / 79.4 | 75.9 / 94.5 | 95.0 / 84.9 / 88.4 | 6.0 / 16.1 / 12.6 |
| swing Cs 0.2 | 200 | 28.3 / 28.3 | 0.1 / -28.0 | 62.0 / 79.0 | 74.5 / 94.5 | 95.5 / 88.5 / 92.5 | 8.0 / 16.0 / 12.0 |
| swing Cs 0.3 | 200 | 44.2 / 35.6 | 0.0 / -49.9 | 67.0 / 78.5 | 76.5 / 93.5 | 97.0 / 91.5 / 93.5 | 4.5 / 10.0 / 8.0 |
| seam 1 deg | 199 | 12.5 / 19.4 | -1.5 / 6.1 | 65.8 / 80.4 | 86.4 / 96.5 | 95.0 / 83.4 / 87.9 | 10.1 / 21.6 / 17.1 |
| seam 2 deg | 199 | 12.9 / 20.9 | -1.5 / 6.0 | 69.8 / 77.9 | 84.9 / 97.0 | 94.5 / 80.9 / 87.9 | 6.0 / 19.6 / 12.6 |
| seam 3 deg | 199 | 12.2 / 20.1 | -1.9 / 5.0 | 66.8 / 77.4 | 85.9 / 98.0 | 97.5 / 86.4 / 91.0 | 3.5 / 15.6 / 11.1 |
| spin 0 deg | 200 | 10.1 / 23.0 | -1.0 / 4.4 | 74.0 / 76.5 | 87.5 / 91.5 | 95.5 / 85.5 / 92.0 | 10.0 / 20.0 / 13.5 |
| spin 3 deg | 200 | 12.6 / 23.9 | -2.0 / 4.6 | 68.5 / 72.0 | 84.5 / 89.0 | 95.0 / 84.0 / 88.0 | 7.0 / 18.0 / 14.0 |
| spin 6 deg | 200 | 17.4 / 22.9 | -0.9 / 5.3 | 61.0 / 69.0 | 75.0 / 89.0 | 95.0 / 89.0 / 93.5 | 7.0 / 14.0 / 9.5 |
| restitution 0.40 | 199 | 13.0 / 39.9 | -0.5 / 35.8 | 58.8 / 58.3 | 76.9 / 77.4 | 98.0 / 88.9 / 94.5 | 6.5 / 15.6 / 10.1 |
| restitution 0.70 | 199 | 14.2 / 20.2 | -0.5 / -15.4 | 69.8 / 78.4 | 83.9 / 96.0 | 96.5 / 88.9 / 93.5 | 6.0 / 13.6 / 9.0 |
| restitution U[0.40,0.70] | 200 | 12.1 / 26.7 | -0.8 / 7.1 | 67.5 / 73.5 | 81.0 / 91.0 | 95.0 / 87.0 / 92.0 | 8.5 / 16.5 / 11.5 |
| friction 0.20 | 199 | 14.5 / 31.5 | 0.1 / 15.9 | 64.3 / 67.8 | 80.9 / 89.4 | 95.5 / 85.4 / 90.5 | 7.0 / 18.1 / 13.1 |
| combined pace | 200 | 26.7 / 40.0 | -8.1 / -32.9 | 47.5 / 66.5 | 63.0 / 85.0 | 95.0 / 87.0 / 92.5 | 5.5 / 15.5 / 10.0 |

Findings.

- **Swing is the largest single effect.** The median lateral error goes from 10.0 mm to 17.5,
  28.3 and 44.2 mm at Cs 0.1, 0.2 and 0.3. The mean lateral error stays near zero because the
  swing direction is drawn per delivery, but the height picks up a bias of -4.8, -28.0 and
  -49.9 mm. The same swing term is the biggest row of the exp4 budget.
- **Restitution and friction set the height bias.** A pitch at 0.40 instead of the assumed 0.55
  gives a +35.8 mm mean height error; 0.70 gives -15.4 mm; friction 0.20 gives +15.9 mm. Lateral
  error barely moves. Restitution 0.40 has the worst full-sigma height coverage of any single
  row, 77.4 %.
- **Drag and seam are small.** Drag moves the median height error from 19.4 mm to between 25.0 and
  27.7 mm and the lateral error by under 3 mm. Seam of 1 to 3 deg moves both by under 3 mm. Turn of 6 deg on
  a slow ball takes the lateral median from 10.1 to 17.4 mm.
- **Coverage does not collapse, for a reason.** The pipeline scales its covariance by the
  residual variance (`reconstruction.py:244`), so a worse fit reports a wider sigma. Fit coverage
  still falls from 69.3 / 78.4 % to 47.5 / 66.5 % under combined pace. The full sigma gives
  63.0 / 85.0 % there.
- **The baseline over-covers under the full sigma** (84.4 / 96.0 %). The model term was fitted on
  World B, which has these effects switched on, so it is too wide for a world without them. It
  is a model-error allowance, not a noise term, and it only fits the world it was estimated in.
- **Agreement hides most of this.** Under the shipped rule agreement stays between 94.5 and
  98.0 % in every row, including combined pace at 95.0 %, because most deliveries are far from an
  edge. The honest sigma costs agreement instead: 80.9 to 91.5 % at k = 2.15 and 87.9 to 94.5 % at
  k = 1.40, with umpire's call between 10.0 and 21.6 % at k = 2.15.

## 6. Tap sensitivity (exp8, part 2)

Script `exp8_physics.py --part taps`, raw `raw/exp8_taps.csv`, summary in `raw/exp8_physics.json`,
table `tables/taps.tex`, macros `Tap*`.

Set-up. The first 300 deliveries of exp6's World B, rebuilt with the same taps and detections.
The unperturbed estimate matches exp6 on all 299 that solve (0 mismatches). Two kinds of error:
every one of the twelve taps moved d = 2, 5 or 10 px in its own random direction, or all twelve
moved the same +-d px in v (a user who taps consistently high or low). Verdicts are compared
with the unperturbed verdict of the same delivery under three rules: the shipped one (fit sigma,
k = 1), and the full sigma with the exp7 k at 5 % (1.40) and 1 % (2.15).

| Perturbation | n | Median / 90th abs Δy (mm) | Median / 90th abs Δz (mm) | Verdict changes: fit k=1 / full k=2.15 / full k=1.40 | Straight out ↔ not out |
|---|---|---|---|---|---|
| random 2 px | 298 | 3.2 / 10.0 | 2.6 / 10.5 | 3 (1.0 %) / 0 (0.0 %) / 5 (1.7 %) | 0 / 0 / 0 |
| random 5 px | 299 | 7.2 / 28.0 | 7.2 / 25.8 | 6 (2.0 %) / 5 (1.7 %) / 9 (3.0 %) | 0 / 0 / 0 |
| random 10 px | 299 | 15.7 / 48.8 | 13.9 / 52.6 | 9 (3.0 %) / 9 (3.0 %) / 8 (2.7 %) | 0 / 0 / 0 |
| v shift +2 px | 299 | 2.8 / 12.4 | 3.4 / 6.9 | 0 (0.0 %) / 1 (0.3 %) / 3 (1.0 %) | 0 / 0 / 0 |
| v shift -2 px | 299 | 2.9 / 12.8 | 3.6 / 7.4 | 2 (0.7 %) / 1 (0.3 %) / 0 (0.0 %) | 0 / 0 / 0 |
| v shift +5 px | 299 | 6.8 / 31.5 | 8.1 / 17.3 | 1 (0.3 %) / 2 (0.7 %) / 3 (1.0 %) | 0 / 0 / 0 |
| v shift -5 px | 299 | 7.2 / 32.7 | 8.8 / 17.8 | 6 (2.0 %) / 3 (1.0 %) / 3 (1.0 %) | 0 / 0 / 0 |
| v shift +10 px | 299 | 12.7 / 64.9 | 16.4 / 34.8 | 3 (1.0 %) / 4 (1.3 %) / 5 (1.7 %) | 0 / 0 / 0 |
| v shift -10 px | 299 | 14.8 / 67.7 | 17.7 / 36.1 | 10 (3.3 %) / 4 (1.3 %) / 5 (1.7 %) | 0 / 0 / 0 |

Findings.

- **The stump-plane point moves 1.3 to 1.6 mm per pixel of random tap error.** Medians are
  3.2 / 2.6 mm at 2 px, 7.2 / 7.2 mm at 5 px and 15.7 / 13.9 mm at 10 px. The tails are long:
  the 90th percentile at 10 px is 48.8 / 52.6 mm.
- **A consistent high or low tap is worse in the lateral tail.** At +-10 px in v the lateral
  90th percentile is 64.9 and 67.7 mm, against 48.8 mm for random 10 px, because the whole pose
  tilts one way instead of the errors partly cancelling.
- **Few verdicts change, and none change outright.** The most changes in any case is 10 of 299
  (3.3 %, shifted -10 px, shipped rule). At 2 px, the tap noise the other experiments assume, the
  shipped rule changes 3 (1.0 %). In all 27 case and rule pairs no verdict goes straight from out
  to not out or back. Every change moves into or out of umpire's call, which is what the band
  is for.

## 7. Frame rate (exp9)

150 exp1-style deliveries with the full unmodelled physics, reference camera, 1 px centres, 2 px taps, 0.5 ms frame jitter, each replayed at 30, 60, 120 and 240 fps under three samplers (seed 909, 665.0 s on 3 workers). Coverage is of the pipeline's own sigma; agreement and umpire's call use the shipped rule (k = 1). Table: `tables/fps.tex`.

| fps | Sampler | n | Median frames | Median abs y / z (mm) | 1-sigma cover y / z (%) | Agree (%) | Umpire's call (%) |
|---|---|---|---|---|---|---|---|
| 30 | timestamps | 150 | 18 | 22.6 / 41.1 | 62 / 69 | 92.7 | 7.3 |
| 30 | shipped @60 | 145 | 37 | 91.3 / 166.7 | 76 / 75 | 86.9 | 15.9 |
| 30 | shipped @fps | 148 | 19 | 29.1 / 48.9 | 66 / 68 | 93.2 | 8.1 |
| 60 | timestamps | 150 | 37 | 25.2 / 40.3 | 49 / 62 | 95.3 | 5.3 |
| 60 | shipped @60 | 149 | 36 | 34.9 / 62.8 | 50 / 56 | 91.9 | 9.4 |
| 60 | shipped @fps | 149 | 36 | 34.9 / 62.8 | 50 / 56 | 91.9 | 9.4 |
| 120 | timestamps | 150 | 74 | 22.7 / 30.4 | 39 / 59 | 94.7 | 6.0 |
| 120 | shipped @60 | 150 | 36 | 30.6 / 52.7 | 46 / 55 | 95.3 | 6.7 |
| 120 | shipped @fps | 150 | 76 | 33.4 / 57.8 | 39 / 49 | 94.7 | 4.7 |
| 240 | timestamps | 150 | 146 | 23.9 / 30.2 | 29 / 43 | 96.0 | 3.3 |
| 240 | shipped @60 | 150 | 37 | 26.3 / 43.3 | 51 / 59 | 95.3 | 6.0 |
| 240 | shipped @fps | 150 | 152 | 29.4 / 43.7 | 25 / 36 | 95.3 | 4.0 |

What it shows:

- **With true timestamps, frame rate barely moves the error.** Median lateral error stays at 22.6 to 25.2 mm from 30 to 240 fps. Vertical error falls from 41.1 to 30.2 mm, and agreement rises from 92.7% to 96.0%.
- **Coverage gets worse as the rate goes up.** The pipeline's 1-sigma covers 62% / 69% at 30 fps and 29% / 43% at 240 fps. More frames shrink the fit sigma, but the model-error bias does not shrink with it. This is the same diagnosis as section 3, seen from another side, and it contradicts main.tex:426 ("almost no effect").
- **The shipped sampler is worst at low rates.** At 30 fps it fetches each frame about twice (37 frames against 18) under labels up to a frame apart: median error 91.3 / 166.7 mm and agreement 86.9%. At 60 fps, the rate the app records at, it costs 34.9 / 62.8 mm against 25.2 / 40.3 mm with timestamps, and agreement 91.9% against 95.3%.
- **Setting sample_fps to the video rate does not fix it**, because round(1000/fps) is 17, 8 and 4 ms at 60, 120 and 240 fps, none of which is the frame period. Only labelling each frame with its own timestamp does.

## 8. Things the runs turned up in the code

- **The shipped frame sampler mislabels frames.** `process_job.py:202` asks for a frame every
  `round(1000 / sample_fps)` ms and labels each with the requested time, not the frame's own
  timestamp. The app always sends `sample_fps: 60` (`analyze_screen.dart:326`), so the step is
  17 ms whatever the video's rate. `VideoReader.frame_at_ms` returns the nearest frame, so on a
  60 Hz clip each label is off by a sawtooth of up to half a frame (8.3 ms) and one frame in 50
  is skipped; on a 30 Hz clip every frame is fetched about twice under two different labels up
  to 16.7 ms apart. `uq.frame_times(..., "shipped")` reproduces this exactly. It is a bug,
  not an uncertainty, so it is kept out of u_c and reported as its own row. The fix is to label
  each frame with its decoded timestamp, which `VideoReader` already has.
- **The paper's guard band is not the code's.** main.tex:337 says each band is widened to
  max(R, kσ). `decision.py:_band` does something else: a call is "in" only when the centre is at
  least kσ inside the edge, and "out" only when it is more than R + kσ outside. So the code uses
  R + kσ on the outside and kσ on the inside, which is the JCGM 106 form (acceptance limit moved
  by the guard band). Reviewer 1 (M4) asks exactly why max and not R + kσ. The text should
  describe the code.
- **exp2 and exp3 still sit on the old geometry.** Their committed CSVs (2026-09-02) carry
  verdicts and truth labels on the 26.4 cm wicket with the old bands. They cannot be rerun
  because `server/models/cricket_ball.pt` is missing (see section 11).

## 9. Threats to validity

- **The synthetic world is still partly circular.** exp4 to exp9 all use `synth.py`'s flight
  model. Its bounce (restitution plus friction at contact) is the estimator's own bounce model,
  and every "unmodelled" effect in exp8 is one the generator already knows how to make. Nothing
  here has metric truth from a real delivery. Review item 5 (a paper screen and bounce marks,
  40 to 60 deliveries) is the only thing that breaks this, and it needs filming.
- **σ_mod was fitted on the same generator it is tested on.** It is cross-validated on held-out
  World B deliveries, but those come from the same distribution. exp8 shows the limit: with the
  effects switched off the full σ over-covers (84.4 / 96.0 %), and with restitution at 0.40 it
  under-covers height (77.4 %). The model term covers the world it was estimated in and should
  be described that way.
- **Coverage after the fix is not nominal in both directions.** Lateral 95 % coverage is 91.5 %,
  about four standard errors short, and height over-covers at 86.1 / 98.0 %. A Gaussian with one
  additive term cannot fit both the core and the tail. A heavier-tailed PDF for the model term
  was not tried.
- **The chosen k depends on this sample.** k_specific is set by where 598 deliveries' out calls
  happen to fall, with only 39 true outs. The closed-form bounds (2.23 and 2.81 for four tests)
  do not depend on the sample, which is why they are quoted next to it.
- **The risk model is simple.** Flat prior, Gaussian errors, the four Law 36 tests treated as
  independent. The y and z errors at the stump plane are correlated and that is ignored.
- **exp2 and exp3 were not rerun.** Their committed results are on the old 26.4 cm wicket and old
  bands, because the detector weights are missing (section 11). Any paper number from them is
  on the old geometry.
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
- **The runtimes were measured on a busy machine** (load average about 50 on 11 cores), so they
  are upper bounds.

## 10. Prose the new numbers break

Line numbers are the current `paper/main.tex`. The edit plan in section 12 handles every row marked
"plan"; the others need the author's call.

| main.tex | What it says now | What the new files show | Suggested change |
|---|---|---|---|
| 45-46, 589 | the propagated bound is "slightly optimistic", covering \CovYOne / \CovZOne % (50.7 / 61.3) | On World B the shipped sigma covers 51.7 / 61.2 % at 1σ; the cross-validated model term brings it to 66.4 / 86.1 % [CovBFit*One, CovBFull*One]. Over the Monte Carlo trials the pipeline sigma has a median of 27.1 mm in y against a real spread of 54.8 mm [McPipeSigmaMedY, McUY]. "Slightly" undersells it. | plan: "misses model error ... raises this to ..." |
| 100, 388 | the real clips give "a repeatability test" | What exp3 does is re-fit the same clip on its even and odd frames. That is within-clip resampling, not repeatability in the VIM sense (JCGM 200, 2.21: same procedure, operator and system, repeated measurements on the same object). exp3 was not rerun (section 11). | "half-rate consistency" or "a split-frame check". Not in the plan, since it touches three places in the author's prose. |
| 186-187 | Robinson's equations of a spinning sphere "under drag and lift, which the synthetic generator integrates" | Only partly. `synth.fly` integrates quadratic drag and a lateral side force before contact, and applies spin as a sideways turn at contact. It has no lift (Magnus) term. | "whose drag and side-force terms the generator integrates". Not in the plan. |
| 214-215 | $w_o = 0.132$ m, stumps $h_s = 0.711$ m | Law 8 gives ±0.1143 m; the decision zone now reaches the bails, 0.7239 m (commits d14d948, 91e0bf8) | plan: 0.1143 and $h_b = 0.724$ m |
| 312-314 | the covariance "is a first-order approximation and Section measures how far it can be trusted" | The Monte Carlo fails the JCGM 101 check by up to 83.8 mm, and the height distribution is shifted, not just wider [McDHighZ, McMeanZ]. | Still true as written; the new budget subsection answers it. Optionally add "and a Monte Carlo check shows where it fails". |
| 336-342 | each band is widened to $\max(R, k\sigma)$ with $k = 1$ | `decision.py:_band` uses $k\sigma$ inside and $R + k\sigma$ outside (section 8). With the full sigma, $k = 1.40$ keeps every out call under 5 % specific risk and $k = 2.15$ under 1 % [RiskFullKFive, RiskFullKOne]. | plan: `decision.tex` describes the code's rule |
| 350 | the generator uses drag $C_d = 0.5$ | true for exp1. exp4 to exp9 draw $C_d$ from 0.35 to 0.55 (Mehta 2005) | none for exp1; the supplement should say which experiments use which range |
| 362 | "the estimator never receives the true camera" | This was not true before commit 81f97e0: the synthetic runs handed the solver the true focal length. Now the focal length is solved from the taps, with a 1.68 % median error [AblAppFocalErr]. | plan: add "the focal length is solved from the taps with $L$ fixed" |
| 385-386 | frame-interval jitter "is small beside" the pixel term | On the representative delivery, jitter is 2.9 / 15.8 mm against 7.3 / 35.2 mm for ball centre and bounce split; medians 6.9 / 9.6 against 15.6 / 24.8 mm (`budget.tex`). Half the size is not small. | plan: point to the budget table instead |
| 386-387 | rolling shutter is "the one electronic error source the stated uncertainty does not account for" | Uncorrected rolling shutter is 0.7 / 4.0 mm on the representative delivery and 3.1 / 6.7 mm median. Lateral 1σ coverage is 51.8 % with no skew and 52.8 % with 30 ms [SwRsZeroCovFitY, SwRsThirtyCovFitY]. The term the sigma misses is model error, σ_mod 14.2 / 53.8 mm [ModYSigMod, ModZSigMod]. | plan: "changes neither accuracy nor coverage measurably" |
| 422 | "a target 26 cm wide" | Law 8 wicket is 22.86 cm | plan: 23 cm |
| 426-428 | frame rate "has almost no effect from 30 to 240 Hz" | With true timestamps agreement goes from 92.7 % at 30 fps to 96.0 % at 240 fps, so that part holds. Coverage does not: the pipeline's 1σ covers 62 / 69 % at 30 fps and 29 / 43 % at 240 fps (exp9). At 30 fps the shipped sampler gives 86.9 % agreement and 91.3 / 166.7 mm median error. | plan: add "the stated sigma, though, shrinks with the frame count while the model error does not". The sampler bug is a code fix, not a paper claim. |
| 428-429 | tap error "has little effect until it is large" | exp8: 1.3 to 1.6 mm per pixel of tap error, at most 10 of 299 verdicts change (3.3 %), and none goes straight from out to not out or back. | none; exp8 supports the text |
| 433-437 | unmodelled physics moves agreement from \PhysOffAgree to \PhysOnAgree % | Still true for exp1's mild physics. At literature magnitudes agreement stays at 94.5 to 98.0 %, but swing Cs 0.3 moves the median lateral error from 10.0 to 44.2 mm and biases height by -49.9 mm. Combined pace effects give 26.7 / 40.0 mm and drop fit coverage to 47.5 / 66.5 % (exp8). | plan: the Limitations item carries the exp8 numbers |
| 442 | disagreements "lie within a few millimetres of a band edge" | No produced file measures this. | plan: cut the clause. The alternative is to measure the margin of each disagreement in exp1 and quote it. |
| 447-464 | camera placement table* and paragraph | numbers unchanged | plan: three sentences, the table goes to the supplement |
| 466-485 | coverage subsection, "the 55 % bound" | replaced by the budget, Monte Carlo and coverage results | plan: `budget.tex` |
| 487-497 | k curve on exp1, "we ship $k = 1$" | replaced by the JCGM 106 risk curve | plan: `guard.tex` |
| 566-573 | Limitations: "first-order approximation", "ignores drag, swing..." | see sections 2, 3 and 5 | plan: `limits.tex` |

## 11. Blocked

**exp2 and exp3 reruns: BLOCKED ON WEIGHTS.** Both run the app pipeline with the learned
detector, which loads `server/models/cricket_ball.pt` (`process_job.py:50`). The file is not
in the repo. The committed raw files are the real 2026-09-02 runs and were not overwritten. The
colour detector would run, but it is not the detector the paper describes, so it was not
swapped in. Once the weights are back: `$PY exp2_rendered.py` then `$PY exp3_real.py`, then
`make_numbers.py`, and the rendered and real tables move to the Law 8 wicket.

## 12. main.tex edit plan (stays at 8 pages)

main.tex itself is not edited. The plan lives in `paper/experiments/editplan/`: `apply_edits.py` makes
every change below on a temporary copy of `paper/`, and `sh paper/experiments/editplan/build.sh` builds
that copy and prints the page count. Each replacement asserts that its old text occurs exactly once, so a
later edit to main.tex makes the script stop instead of patching the wrong place.

**Result with the committed `numbers.tex`: 8 pages**. No undefined references or
citations, no BibTeX warnings, no overfull boxes. The one underfull hbox (lines 288-290) and the two
`OT1/ptm/m/scit` font warnings are in the unedited paper too (lines 294-296 there). Page 8 is full to
the bottom of both columns, so there is no room left: anything added has to be paid for with a cut.

### What replaces what

| main.tex now | Replaced by | Size change |
|---|---|---|
| 466-485, "How far the stated uncertainty can be trusted": Fig. coverage and the "55 % bound" text | `budget.tex`: Table budget (groups, representative delivery and median), Table coverage (before and after the model term), two paragraphs | one column figure out, two column tables in |
| 487-497, "The decision band": k curve on exp1, "we ship k = 1" | `guard.tex`: Fig. risk (specific false-out risk and agreement against k) and the JCGM 106 paragraph | one column figure in |
| 336-342, the max(R, kσ) band | `decision.tex`: the rule `decision.py` actually applies, kσ inside and R + kσ outside | about the same |
| 447-464, "Camera placement" subsection and its table* | `cameras.tex`: one paragraph, no heading | one full-width table out |
| 501-509, Experiment 2 table* | nothing; the text already quotes its numbers | one full-width table out |
| 566-573, the first two Limitations items | `limits.tex`: model error is outside the sigma; exp8 physics numbers | about the same |
| 193-197, Related Work, "Camera pose from known points..." paragraph | nothing; the method cites the same works where it uses them | 5 source lines out |

### Moves to the supplement

- the per-input budget table, `tables/budget.tex` (the paper keeps the grouped `tables/budget_short.tex`)
- the Monte Carlo tables, `tables/mc.tex`
- the coverage sweeps over rolling shutter and model-term size, `tables/coverage_sweeps.tex`
- the physics degradation table, `tables/physics.tex`, and the tap table, `tables/taps.tex`
- the frame-rate table, `tables/fps.tex`
- the camera placement table (`tab:cameras`) and the Experiment 2 per-length table (`tab:rendered`)
- the old coverage figure, `figures/coverage.pdf`
- the calibration ablation of section 0

### Draft LaTeX: uncertainty budget and coverage (replaces 466-485)

```latex
\subsection{Uncertainty budget and coverage}
\label{sec:coverage}

\begin{table}[t]
\centering
\caption{Standard uncertainty (mm) at the stump plane by input group (JCGM 100), root sum of squares within
a group: a representative delivery (120~km/h, 6~m, 60~Hz) and the median over \BudDistN{} deliveries.}
\label{tab:budget}
\scriptsize
\setlength{\tabcolsep}{3pt}
\input{tables/budget_short}
\end{table}

\begin{table}[t]
\centering
\caption{Coverage (\%) of the stated uncertainty on \CovBFitted{} World~B deliveries, which add every input
of Table~\ref{tab:budget}. The model term is cross-validated over five held-out folds.}
\label{tab:coverage}
\scriptsize
\setlength{\tabcolsep}{2pt}
\input{tables/coverage}
\end{table}

Each input in Table~\ref{tab:budget} was propagated through the calibration solve and the anchored
fit~\cite{jcgm100}, by numerical Jacobians for vector inputs (taps, ball centres, frame times) and by the RMS
output change over its PDF for scalar ones, so a bias the pipeline does not correct counts in full. The
measurement groups alone give \BudRepMeasY{} and \BudRepMeasZ~mm on the representative delivery, against a
pipeline sigma of \BudRepPipeSigmaY{} and \BudRepPipeSigmaZ~mm: the covariance is a fair measurement-noise
sigma. What it leaves out is the flight model, almost all of it unmodelled swing. A Monte Carlo propagation
of the same inputs through the full solver~\cite{jcgm101} ($M = \McM$) gives a vertical 95\,\% interval of
$[\McLowZ, \McHighZ]$~mm, shifted from the linear $[\McGumLowZ, \McGumHighZ]$~mm because swing of either sign
leaves the fit low. The linear budget fails the JCGM~101 validation by up to \McDHighZ~mm, so it ranks the
inputs and the Monte Carlo interval is the one to quote.

Table~\ref{tab:coverage} tests the stated sigma. Rolling shutter is not the cause of the shortfall: with no
readout skew and with 30~ms of it, lateral coverage is \SwRsZeroCovFitY\% and \SwRsThirtyCovFitY\%. The
missing term is model error, \ModYParamOne~mm laterally and \ModZParamOne~mm per metre of bounce-to-stump
distance vertically. Lateral coverage at 95\,\% is still \CovBFullYNinetyfive\%, with an empirical factor of
\KEmpFullYNinetyfive{} rather than 1.96, so the decision band takes its $k$ from risk and not from a nominal
Gaussian.
```

### Draft LaTeX: guard band (replaces 487-497)

```latex
\subsection{Choosing the guard band from false-out risk}
\label{sec:kcurve}

\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{risk.pdf}
\caption{World~B. Left: largest specific false-out risk among OUT calls against $k$, with 1 and 5\,\%
limits. Right: agreement (dashed) and umpire's call (solid). Vertical lines: the chosen $k$.}
\label{fig:risk}
\end{figure}

Following JCGM~106~\cite{jcgm106}, the specific risk of an OUT call is the probability, given the estimate,
that the true verdict is not out, $1 - \prod_i \Phi((m_i + R_i)/\sigma_i)$ over the signed margins $m_i$
of the four limits (pitching line, impact line, stump edge, top of the bails), with $R_i = R$ except on the
pitching line and a flat prior. Fig.~\ref{fig:risk} traces it on the \RiskN{} World~B
deliveries, \RiskTruthOut{} of them truly out. The shipped rule, pipeline sigma and $k = 1$, makes out calls
whose risk under the full sigma reaches \RiskShippedMaxSpecFull\%, with \RiskShippedOutsOverFive{} above
5\,\%. With the full sigma every out call is below 5\,\% from $k = \RiskFullKFive$ and below 1\,\% from
$k = \RiskFullKOne$; the sample-free bounds with all four limits binding at once are \RiskBoundFourFive{} and
\RiskBoundFourOne. The price is agreement, \RiskFitKOneAgree\% as shipped against \RiskFullAgreeFive\%
and \RiskFullAgreeOne\%, and umpire's call on \RiskFullUmpFive\% and \RiskFullUmpOne\% of deliveries,
because \RiskFullOutToUmpFive\% of true outs come back as umpire's call at $k = \RiskFullKFive$. No setting
has a missed out. For coaching we use the full sigma with $k = \RiskFullKFive$; officiating would want
$k = \RiskFullKOne$.
```

### Draft LaTeX: decision rule (replaces 336-342)

```latex
The playing conditions~\cite{icc2023drs} return umpire's call when the centre is outside a stump edge by
less than one ball radius $R$. We add a guard band on top of that rule~\cite{jcgm106,carullo2024conformity}: a
test is passed only if the centre is at least $k\sigma$ inside its limit, and failed only if it is more than
$R + k\sigma$ outside, with $\sigma$ the standard uncertainty of that coordinate; anything in between is
umpire's call. Section~\ref{sec:kcurve} sets $k$ from the risk of a false out.
```

### Draft LaTeX: camera placement (replaces 447-464)

```latex
Placement matters less than which end the phone films from. Behind the striker's stumps, low, high or back,
agreement is \CamStrikerHighAgree\% to \CamStrikerLowAgree\%, and \CamStrikerSideAgree\% with a 1.5~m offset
to the side. From the bowler's end it is \CamBowlerRefAgree\% and \CamBowlerSideAgree\%, with median vertical
errors of \CamBowlerRefMedZ{} and \CamBowlerSideMedZ~cm, because the decisive post-contact arc is 15 to 20~m
away and foreshortened. The app asks the user to film from behind the batter; the placement table is in the
supplement.
```

### Draft LaTeX: Limitations, first two items (replaces 566-573)

```latex
\textbf{The stated uncertainty misses the flight model.} The covariance is a fair measurement-noise sigma,
but swing, drag and pitch variation, the largest inputs of the budget, are outside it. The model term was
fitted on the same generator it is tested on, and the Monte Carlo interval is shifted as well as wider. With
an ambiguous contact split the solution is also multimodal, which no Gaussian sigma represents.

\textbf{The estimator ignores drag, swing, friction and spin.} Swing with a side-force coefficient of 0.3
moves the median lateral error from \PhysBaselineMedY{} to \PhysSwingCsZeroThreeMedY~mm and biases the
height by \PhysSwingCsZeroThreeMeanZ~mm; a pitch with restitution 0.40 biases it by
\PhysRestitutionZeroFourZeroMeanZ~mm. The reported release speed is an average over the arc, not the speed
at the hand.
```

### New references (appended to refs.bib)

```bibtex
@techreport{jcgm100,
  author      = {{JCGM}},
  title       = {Evaluation of Measurement Data: Guide to the Expression of Uncertainty in Measurement},
  institution = {BIPM},
  number      = {JCGM 100:2008}, year = {2008}
}
@techreport{jcgm101,
  author      = {{JCGM}},
  title       = {Evaluation of Measurement Data: Supplement 1 to the ``Guide to the Expression of Uncertainty in Measurement'', Propagation of Distributions Using a {Monte Carlo} Method},
  institution = {BIPM},
  number      = {JCGM 101:2008}, year = {2008}
}
@techreport{jcgm106,
  author      = {{JCGM}},
  title       = {Evaluation of Measurement Data: The Role of Measurement Uncertainty in Conformity Assessment},
  institution = {BIPM},
  number      = {JCGM 106:2012}, year = {2012}
}
```

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

### Cuts made only to fit

The first full build came out at 9 pages. These brought it back to 8: dropping the Related Work pose
paragraph, moving the Experiment 2 table, cutting the 442 clause, folding camera placement into one
paragraph, removing a global-risk sentence from `guard.tex` and an "acceptance limit is moved" sentence
from `decision.tex`, and shortening the Conclusion's last sentence. Shrinking the risk figure changed
nothing, because IEEEtran stretches the page to fill it, so it stayed at column width. Only cuts late
in the flow (Limitations, Conclusion) moved the references.

The plan leaves the rows of section 10 marked "author's call" alone (100/388 "repeatability", 186-187
"which the synthetic generator integrates", 350 $C_d$ range).

## 13. Review items this covers

The items are from section C, "Ranked action list", of the mock review of TIM-26-10891. For each one:
what it asked for, what was done, and what is still open.

**1. Law 8 width, ICC bands, bails, rerun.** Done for exp1, blocked for exp2.
- Outer stump edge 0.1143 m (d14d948). Umpire's call is one-sided, there is no band on the pitching
  test, and the zone reaches the top of the bails at 0.7239 m, quoted from ICC Appendix D 3.4 (91e0bf8).
- True crossing and contact positions are now in the exp1 CSV (5e36eba), as the item asked.
- exp1 was rerun (ccce0b7). Agreement went from 94.3 to 93.7 %, inside the review's "a point or two".
  Every macro that moved is in section 0 and Appendix A.
- main.tex 215, 336-337 and 422 are fixed in the edit plan (section 12), not in main.tex itself.
- **Open:** re-rendering exp2 and rerunning exp2 and exp3 are BLOCKED ON WEIGHTS (section 11).

**3. Unpin the focal length and the pitch length.** Done for exp1; exp2 is unpinned in code but not rerun.
- `synth.py` and `exp2_rendered.py` no longer pass the true field of view. The grid now spans 20 to
  130 deg with a continuous polish, so 90.5 deg is inside it (81f97e0).
- The ablation in section 0 tests 70 and 90.5 deg cameras. Median focal error is 1.68 % with the app's
  setup; agreement is 95.0 % against 94.5 % pinned, and median stump-plane error is the same.
- The near-degeneracy claim (line 259) is now shown: freeing the pitch length as well gives an 8.45 %
  focal error and puts the contact point 42.2 cm off.
- **Open:** coverage was not tabulated per ablation cell. The main run's 1σ coverage moved from
  50.5 / 60.6 to 50.7 / 61.3 %, but that run also changed the geometry.

**4. GUM budget with a model-discrepancy Type B term.** Done (exp4 and exp6), with two gaps.
- Rows present: taps, ball centre, frame jitter, frame phase, rolling shutter, frame-rate metadata,
  distortion, pitch and wicket dimensions, bails, and five physics rows (section 1).
- The model term is fitted by maximum likelihood and chosen by 5-fold cross-validation, so each delivery
  is scored with a term fitted without it (section 3).
- Result: lateral 1σ coverage 66.4 %, within one standard error of 68.3 %. Lateral 95 % is 91.5 %,
  short. Height over-covers, 86.1 and 98.0 %.
- On exp8's physics rows, with the term fitted on World B, full-sigma coverage is 63.0 / 85.0 % under
  combined pace and 84.4 / 96.0 % on the baseline (section 5). So it does not transfer cleanly.
- **Gaps:** no detector streak-bias row, since it needs exp2. The ball-centre row is a 1 px Type B
  assumption, not Type A from the residuals.

**6. Physics the solver does not assume.** Partly done (exp8); the second generator was not built.
- exp8 runs drag, swing, seam, turn, restitution and friction at literature magnitudes through the
  unchanged estimator (section 5). Agreement stays at 94.5 to 98.0 % against 96.5 % on the baseline,
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
- At 16 ms uncorrected, the lateral mean error moves from 4.6 mm (ρ = 0) to -0.2 mm (+16) and 9.5 mm
  (-16). Corrected, it is 4.6 and 5.0 mm (`raw/exp6_model_error.json`). All of this is small beside the
  17.5 mm median error.
- **Open:** the correction lives only in the harness (`uq.py:165`) and is handed the true ρ.
  `reconstruction.py` and `process_job.py` were not changed, and ρ is neither passed in nor fitted.

**10. JCGM 101 Monte Carlo.** Done (exp5), with a different design from the one asked for.
- The run is 30,000 trials on the representative delivery with adaptive stopping, plus 10 deliveries
  at 1000 trials each, instead of 200 × 500 (section 2).
- The adaptive rule was not met. Twice the batch standard deviation was still 2.9 mm against a
  0.5 mm δ.
- It draws every budget input, physics included. So it does see the model bias the review expected it
  to miss: the height distribution is shifted, and the linear budget fails validation by up to 83.8 mm.
- **Open:** a measurement-only Monte Carlo was not run. That run would test the review's claim that the
  Monte Carlo matches the linear sigma when the model is right. The nearest check is exp4's 20
  noise-only runs, which scatter by 7.37 / 36.77 mm against a measurement-only RSS of 9.8 / 41.2 mm.

**11. Empirical coverage factor.** Done (exp6 and exp7), reported as a diagnostic only.
- On exp1 the factors are 1.50 / 1.20 for 68 % and 3.70 / 3.61 for 95 %, which matches the review's
  own 1.51 / 1.23 and 3.68 / 3.64. With the full sigma on World B they are 1.05 / 0.65 and 2.35 / 1.51.
- As the item advised, the decision band does not use them. exp7 sets k from a false-out risk limit
  instead: 1.40 for 5 % and 2.15 for 1 % (section 4).

## Appendix A. Every exp1 macro that moved

116 of 196 macros in the submitted numbers.tex (tag paper-v1, 4271cd6) changed; 80 did not; 0 no longer exist: none.

| Macro | Submitted | Now |
|---|---|---|
| GeoNotOut | 9110 | 9783 |
| GeoOut | 512 | 715 |
| GeoUmp | 1178 | 302 |
| GeoFalseOut | 6 | 14 |
| GeoMissedOut | 3 | 13 |
| GeoFalseOutPct | 0.07 | 0.14 |
| GeoAgreeAll | 94.3 | 93.7 |
| GeoAgreeAllParabola | 33.6 | 33.5 |
| GeoNoVerdict | 30 | 32 |
| GeoNoVerdictParabola | 1618 | 1641 |
| GeoMedZAll | 3.9 | 3.8 |
| GeoMedYAllParabola | 30.5 | 30.1 |
| GeoMedSpeedErr | 14.4 | 13.6 |
| GeoMedContactX | 4.7 | 8.3 |
| RefAgree | 95.2 | 94.2 |
| RefMedY | 2.4 | 2.3 |
| RefMedZ | 3.8 | 3.7 |
| RefPNineZeroY | 9.2 | 9.1 |
| RefPNineZeroZ | 11.0 | 10.9 |
| RefAgreeParabola | 30.2 | 28.2 |
| RefMedYParabola | 27.8 | 25.9 |
| RefMedZParabola | 43.5 | 42.9 |
| NoiseZeroAgree | 97.5 | 96.8 |
| NoiseZeroMedZ | 2.4 | 2.3 |
| NoiseZeroUmp | 38 | 15 |
| NoiseTwoAgree | 95.0 | 93.5 |
| NoiseTwoMedY | 2.9 | 2.8 |
| NoiseTwoMedZ | 4.5 | 4.4 |
| NoiseTwoUmp | 51 | 37 |
| NoiseThreeAgree | 93.0 | 89.0 |
| NoiseThreeMedY | 4.0 | 3.8 |
| NoiseThreeMedZ | 6.2 | 6.1 |
| NoiseThreeUmp | 52 | 44 |
| NoiseFiveAgree | 88.0 | 83.5 |
| NoiseFiveMedY | 5.3 | 5.4 |
| NoiseFiveMedZ | 8.0 | 8.2 |
| FpsThirtyAgree | 94.2 | 94.0 |
| FpsThirtyMedY | 2.8 | 2.7 |
| FpsThirtyMedZ | 4.1 | 4.0 |
| FpsThirtyUmp | 37 | 21 |
| FpsTwoFortyAgree | 95.0 | 96.8 |
| FpsTwoFortyMedZ | 3.2 | 3.1 |
| FpsTwoFortyUmp | 38 | 16 |
| TapTwelveAgree | 91.0 | 95.2 |
| TapTwelveMedY | 3.2 | 3.5 |
| TapTwelveMedZ | 5.4 | 4.9 |
| TapTwelveUmp | 41 | 24 |
| TapEightAgree | 95.5 | 94.2 |
| TapEightMedY | 2.8 | 2.9 |
| TapEightMedZ | 4.4 | 4.2 |
| TapEightUmp | 42 | 25 |
| DropFortyAgree | 96.0 | 94.8 |
| DropFortyMedY | 2.4 | 2.3 |
| DropFortyMedZ | 3.7 | 3.6 |
| DropFortyUmp | 54 | 36 |
| PhysOffAgree | 97.0 | 95.5 |
| PhysOffMedY | 1.1 | 1.2 |
| PhysOffUmp | 48 | 32 |
| PhysOnAgree | 95.5 | 96.0 |
| PhysOnUmp | 38 | 23 |
| SweepAgreeMin | 88.0 | 83.5 |
| SweepAgreeMax | 97.5 | 96.8 |
| SweepAgreeMinParabola | 26.0 | 25.8 |
| SweepAgreeMaxParabola | 36.8 | 40.0 |
| SweepFalseOutMax | 1 | 4 |
| SweepFalseOutParabolaMax | 8 | 11 |
| CamStrikerLowAgree | 95.5 | 94.8 |
| CamStrikerRefAgree | 94.5 | 94.8 |
| CamStrikerRefMedY | 2.5 | 2.4 |
| CamStrikerRefMedZ | 3.4 | 3.5 |
| CamStrikerRefNoVerdict | 1 | 0 |
| CamStrikerHighAgree | 94.0 | 94.5 |
| CamStrikerHighMedZ | 5.3 | 5.2 |
| CamStrikerSideAgree | 90.5 | 90.2 |
| CamStrikerSideMedY | 4.4 | 4.2 |
| CamStrikerSideMedZ | 2.8 | 2.9 |
| CamBowlerRefAgree | 88.0 | 86.8 |
| CamBowlerRefMedZ | 11.2 | 11.6 |
| CamBowlerRefNoVerdict | 7 | 8 |
| CamBowlerSideAgree | 86.0 | 84.0 |
| CamBowlerSideMedY | 7.3 | 7.4 |
| CamBowlerSideMedZ | 9.7 | 9.9 |
| CamBowlerSideNoVerdict | 1 | 2 |
| CovYOne | 50.5 | 50.7 |
| CovYTwo | 79.3 | 79.8 |
| CovYThree | 91.4 | 91.3 |
| CovYMedian | 0.99 | 0.98 |
| CovZOne | 60.6 | 61.3 |
| CovZTwo | 84.7 | 85.3 |
| CovZThree | 93.0 | 93.1 |
| CovZMedian | 0.76 | 0.75 |
| KZeroAgree | 94.5 | 96.2 |
| KZeroFalseOut | 13 | 42 |
| KZeroUmp | 10.4 | 2.7 |
| KZeroMissedOut | 12 | 56 |
| KZeroUmpInverse | 10 | 36 |
| KHalfAgree | 94.4 | 94.9 |
| KHalfFalseOut | 10 | 27 |
| KHalfUmp | 11.1 | 5.5 |
| KHalfMissedOut | 6 | 21 |
| KHalfUmpInverse | 9 | 18 |
| KOneAgree | 94.3 | 93.7 |
| KOneFalseOut | 6 | 14 |
| KOneUmp | 12.0 | 7.7 |
| KOneMissedOut | 3 | 13 |
| KOneUmpInverse | 8 | 13 |
| KOneHalfAgree | 93.9 | 92.1 |
| KOneHalfFalseOut | 5 | 9 |
| KOneHalfUmp | 13.0 | 9.9 |
| KOneHalfMissedOut | 3 | 9 |
| KOneHalfUmpInverse | 8 | 10 |
| KTwoAgree | 93.2 | 90.6 |
| KTwoFalseOut | 4 | 9 |
| KTwoUmp | 14.3 | 11.6 |
| KTwoMissedOut | 2 | 6 |
| KTwoUmpInverse | 7 | 9 |
