# Identifiability and the Cramér-Rao bound for the stump-plane crossing

Notes for manuscript TIM-26-10891 (Pocket DRS), rev1 worktree. They cover the rev1 solver in
`server/app/pipeline/reconstruction.py`: the 9-parameter anchored model. The newer 10-parameter solver is
not analysed. Every number below comes from a script in this folder, and the outputs are in `out/`.
Section 11 lists the commands that reproduce them.

## 0. Summary

- **Proposition 1 (general position).** The pixel Jacobian has rank $\min\{9,\ \min(2N^-,6)+\min(2N^+,6)\}$,
  where $N^-$ and $N^+$ are the frames before and after the contact. The crossing $(y^*, z^*)$ has a finite
  Cramér-Rao bound (CRB) if and only if $N^+ \ge 3$, or $N^+ = 2$ and $N^- \ge 3$. With $N^+ \le 1$ neither
  coordinate is identifiable, however many frames precede the contact.
  - The rank upper bound and the $N^+ \le 1$ result are proved analytically.
  - Attainment of the rank and the negative $N^+ = 2$ cells come from one numerical witness per geometry,
    extended to almost every configuration by a genericity lemma.
- **Proposition 2 (camera in the plane of a straight delivery).** Each frame then carries one equation, not
  two, for the in-plane motion.
  - $y^*$ needs $N^+ \ge 2$, or $N^+ = 1$ and $N^- \ge 2$. This rule is exact.
  - $z^*$ needs $N^+ \ge 4$, or $N^+ = 3$ and $N^- \ge 3$, or $N^+ = 2$ and $N^- \ge 4$. This rule is
    generic.
  - Off the plane the lost information returns linearly with the offset. At $N^\pm \ge 3$ the plane
    makes no difference.
- **Proposition 3 (the camera at contact height).** Without gravity, a camera at contact height cannot
  recover the crossing from any number of frames, because central scaling about the camera is then an exact
  symmetry of the model. Gravity breaks the symmetry, so the crossing becomes identifiable, but only weakly.
- **Best possible uncertainty.** At the reference camera (2.8 m back, 1.7 m high), 60 fps and 1 px noise,
  the median bound over the 100-delivery grid is **2.38 cm lateral and 5.89 cm vertical**.
  - With the solver's priors it is 1.88 and 4.60 cm.
  - Pose from 12 taps at 2 px adds under 1%.
  - The bound falls as $f^{-1/2}$: 3.91, 2.38, 1.57 and 1.09 cm lateral at 30, 60, 120 and 240 fps.
  - It is linear in pixel noise and grows as camera distance to the power 1.15 to 1.3.
- **Efficiency.** With at least 8 frames after the bounce, least squares without priors reaches the bound
  (efficiency 0.89 to 1.10, 95% intervals containing 1).
  - With $N^+ \le 5$ the linear bound is not attainable, and bounded or prior-driven estimators beat it
    through bias.
  - The app's calibration step is about twice as noisy as its own CRB. At 8 m length that lowers efficiency
    to 0.85 to 0.94 once the 7-parameter reprojection refine on the tapped pose is applied.
- **Stated uncertainty.** The reported sigma falls below the classical CRB in 27 to 48% of deliveries.
  - That happens only because the reported sigma includes the priors.
  - Against the prior-aware bound it falls below in 7 to 15% of deliveries, by at most 19%. The sampling
    noise of $s^2$ explains that.
  - At lengths of 2 to 2.5 m the reported sigma is the prior width, not a measurement.
- **Coverage.** The submitted paper reports 50.5% lateral and 60.6% vertical one-sigma coverage (51.6% and
  61.4% after the reruns). That comes from physics the model leaves out, not from linearisation.
  - With drag, swing and friction off, coverage is 74.2% and 74.4%. The robust loss predicts 73.6%.
  - With them on, the re-run gives 51.5% and 63.8%.
  - Using the exact bound in place of the reported sigma would give only 46.0% and 56.1%.

## 1. Model

### 1.1 Parameters and trajectory

World axes:
- $x$ runs along the pitch, with $x = 0$ at the striker's stumps (the stump plane).
- The ball travels toward $-x$.
- $z$ points up.
- The ball radius is $R = 0.036$ m and $g = 9.81$ m/s$^2$.

The rev1 solver's parameter vector is

$$\theta = (t_b,\ x_b,\ y_b,\ v^-_x,\ v^-_y,\ v^-_z,\ v^+_x,\ v^+_y,\ e) \in \mathbb{R}^9,\qquad v^+_z = -e\,v^-_z ,$$

and the trajectory is two ballistic arcs joined at the contact point $\mathbf b = (x_b, y_b, R)$:

$$\mathbf p(t;\theta) = \mathbf b + \mathbf v^\mp \tau - \tfrac12 g \tau^2 \hat{\mathbf z},\qquad \tau = t - t_b ,$$

with $\mathbf v^-$ for $\tau < 0$ and $\mathbf v^+$ for $\tau > 0$.

### 1.2 Measurements

Frames arrive at rate $f$. The bounds and Part A of the Monte Carlo use every frame, and Part B drops 5%. Frames
end when the ball reaches the popping crease ($x \le 1.22$ m), so the crossing is always an extrapolation of about 1.22 m. The pixel model is

$$\mathbf u_i = \pi\big(\phi,\ \mathbf p(t_i;\theta)\big) + \mathbf w_i,\qquad \mathbf w_i \sim \mathcal N(0, \sigma^2 I_2)\ \text{i.i.d.},$$

- $\pi$ is a pinhole camera.
- The pose is $\phi = (\boldsymbol\omega, \mathbf t)$: a rotation vector and a translation.
- The focal length is $f_c$, and the principal point is fixed.
- $N^-$ frames have $t_i < t_b$ and $N^+$ have $t_i > t_b$.
- The pose comes from 12 tapped image points of known pitch features, each with noise
  $\mathcal N(0, \sigma_{\rm tap}^2 I_2)$.

### 1.3 The solver as shipped

It minimises $\sum_i f_s^2\,\rho\big((r_i/f_s)^2\big) + \|\mathbf r_P\|^2$ with bounded trust-region
reflective steps.
- The loss is soft_l1, $\rho(s) = 2(\sqrt{1+s}-1)$, with $f_s = 2$ px.
- The prior rows $\mathbf r_P = C(\theta-\theta_0)$ are $\big((e-0.55)/0.15,\ (v^+_x-v^-_x)/4,\ (v^+_y-v^-_y)/2\big)$.
  They are added unweighted to the pixel residuals.
- The bounds put $e$ in $[0.25, 0.85]$ and keep the velocities in physical ranges.

The reported covariance is $s^2 (J_w^\top J_w)^+$.
- $J_w$ is the Jacobian of the loss-scaled residuals, prior rows included.
- $s^2 = \sum r_w^2/(2N-9)$.

Three consequences matter below:

1. The prior information relative to the pixels is $P/\sigma^2$, with $P = C^\top C$. The implied prior
   standard deviation is therefore $\sigma$ times the nominal one. At 1 px it is the nominal 0.15, 4 m/s and
   2 m/s. At 2 px it is twice as loose.
2. At 1 px the curvature weight of the robust data term is $E[\psi'] = 0.7846$. The priors therefore weigh
   about 1.27 times more against the pixels than unit weighting would give.
3. The app clamps $\tau^* < 0$ to 0 when the contact lies beyond the stump plane ($x_b < 0$). It then reports
   the crossing as $(y_b, R)$, with a vertical sigma of exactly 0.
   - That point is wrong: the ball crossed the plane on the pre-contact arc.
   - A zero sigma is below any bound.

### 1.4 Lemma 1 (the crossing and its first-order map)

Assume $x_b > 0$ and $v^+_x < 0$, and that the post-contact arc stays above the ground until the plane. Then
the crossing time is $\tau^* = -x_b / v^+_x > 0$ and

$$y^* = y_b + v^+_y \tau^*,\qquad z^* = R + v^+_z \tau^* - \tfrac12 g \tau^{*2}.$$

The crossing therefore depends on $\theta$ only through $(x_b, y_b, v^+_x, v^+_y, v^+_z)$. If the trajectory
is perturbed by $\delta\mathbf p(t)$, the crossing moves by

$$\delta\mathbf m = A\,\delta\mathbf p(t^*),\qquad A = \begin{pmatrix} -v_y/v_x & 1 & 0\\ -v_z/v_x & 0 & 1\end{pmatrix},$$

where $\mathbf v = \dot{\mathbf p}(t^*)$.

*Proof.* The new crossing time $t^*+\delta t$ solves $x(t^*+\delta t) + \delta x(t^*) = 0$, so
$\delta t = -\delta x/v_x$. Then $\delta y^* = \delta y + v_y\delta t$ and $\delta z^* = \delta z + v_z
\delta t$. $\square$

Note that $A\mathbf v = 0$: sliding along the path does not move the crossing. The analytic gradient
$G = \partial\mathbf m/\partial\theta$ ($2\times 9$) matches finite differences of the app's own
`_stump_plane_point` to a relative error of $7.7\times10^{-11}$. The model derivative checks to
$2.4\times10^{-9}$, the pose derivative to $1.5\times10^{-9}$ and the focal derivative to
$9.2\times10^{-6}$.

## 2. Identifiability

### 2.1 Definitions and test

Let $F = J^\top J/\sigma^2$, where $J = \partial\pi/\partial\theta$ is stacked over frames ($2N \times 9$).
- $\theta$ is locally identifiable at a regular point if and only if $F$ is nonsingular [Rothenberg 1971].
- A scalar function $m_k$ has a finite CRB for locally unbiased estimators if and only if $\nabla m_k \in
  \mathrm{row}(J)$, or equivalently $\nabla m_k \perp \mathrm{null}(J)$.
- The bound is then $\nabla m_k F^+ \nabla m_k^\top$, whichever generalised inverse is used [Stoica and
  Marzetta 2001].
- If $\nabla m_k$ has a component in $\mathrm{null}(J)$, some direction changes $m_k$ and leaves the
  likelihood unchanged to first order. No locally unbiased estimator then has finite variance.

The numerical test is `lin_bound` in `crlb.py`:
1. Scale the columns of $J$ to unit norm.
2. Take the SVD and find the rank at relative tolerance $10^{-10}$.
3. Call $m_k$ not estimable when the relative part of the scaled $\nabla m_k$ lying in the null space
   exceeds $10^{-6}$.

### 2.2 Lemma 2 (genericity)

Fix which frames are pre-contact and which are post-contact. Every entry of $J$ and $\nabla\mathbf m$ is then
a rational function of $\theta$, the frame times, the camera centre, the focal length and a rational
parametrisation of the rotation. So the ranks of $J$ and $[J;\nabla m_k]$ take their maximum value except on
a proper algebraic subset, which has measure zero. One witness point where a $k\times k$ minor is nonzero
proves that the generic rank is at least $k$.

*Proof.* A minor is rational in those variables. If it is nonzero at one point it is not identically zero,
so its zero set is proper. $\square$

### 2.3 Lemma 3 (block structure)

Replace $(v^-_z, e)$ by $(v^-_z, v^+_z)$. The Jacobian determinant of that change is $-v^-_z \ne 0$, because
the ball is descending at contact, so rank and estimability do not change. In the new coordinates:
- a pre-contact frame depends only on $(t_b, x_b, y_b, \mathbf v^-)$;
- a post-contact frame depends only on $(t_b, x_b, y_b, \mathbf v^+)$;
- each frame gives two rows.

Therefore

$$\mathrm{rank}\,J \le \min\{9,\ \min(2N^-,6) + \min(2N^+,6)\}.$$

With $N^+ = 0$ the columns of $v^+_x, v^+_y, e$ are zero, because $e$ enters only after contact.

### 2.4 Proposition 1 (general position)

Assume $g > 0$, with frame times, delivery and camera in general position, off the exceptional set of
Lemma 2, which contains the in-plane geometry of Proposition 2.

(a) $\mathrm{rank}\,J = \min\{9,\ \min(2N^-,6)+\min(2N^+,6)\}$.

(b) $y^*$ and $z^*$ both have a finite CRB if and only if $N^+ \ge 3$, or $N^+ = 2$ and $N^- \ge 3$. No cell
has only one estimable component.

(c) Suppose $N^+ = 1$ and $N^- \ge 3$.
- $\mathrm{null}(J)$ is spanned by $d_1$: the change $\delta\mathbf v^+ = \hat{\mathbf r}_1/\tau_1$ with all
  other parameters fixed.
  - $\hat{\mathbf r}_1$ is the unit ray from the camera centre to $\mathbf p(t_1)$.
  - $\tau_1 = t_1 - t_b$.
- Along $d_1$ the crossing moves by $(\tau^*/\tau_1)\,A\hat{\mathbf r}_1$.
- So $y^*$ is estimable only if the ray to the single post-contact ball is parallel to the path in plan
  view ($\hat r_{1y}/\hat r_{1x} = v_y/v_x$).
- $z^*$ is estimable only if the ray's elevation slope equals the path slope at the crossing
  ($\hat r_{1z}/\hat r_{1x} = v_z/v_x$).
- Both are coincidences of measure zero.

With $N^+ = 0$ neither coordinate is estimable, because $\partial y^*/\partial v^+_y = \tau^* \ne 0$ and
$\partial z^*/\partial e = -v^-_z\tau^* \ne 0$ fall on zero columns.

*Proof.*

(a) Lemma 3 gives the upper bound. The witness GEN attains it in every cell with $N^\pm \in \{0,\dots,5\}$
(`out/crlb_identifiability.json`, `out/checks_log.txt` section 1b).
- GEN is 120 km/h, length 6 m, line 0.3 m, release $y$ = -0.3 m and `turn_ms` = 0.8.
- It is viewed by the `striker_side` camera at 240 fps.
- Adding rows cannot lower the rank, so larger counts stay at 9.
- Lemma 2 extends the result to almost every configuration.

(b) First the "if" direction.
- When $\min(2N^-,6)+\min(2N^+,6) \ge 9$, $J$ has full column rank and every gradient lies in its row
  space.
- That leaves $N^+ \ge 3$ with $N^- \le 1$.
  - There the post-contact rows alone have rank 6 on the six post coordinates $(t_b, x_b, y_b,
    \mathbf v^+)$. The witness shows rank 6 at $(N^-, N^+) = (0, 3)$.
  - In those coordinates $\nabla\mathbf m$ is zero on $\mathbf v^-$, so it lies in the row space of the
    post rows.
  - This is the known fact that a ballistic arc with known $g$ can be recovered from one camera
    [Ribnick et al. 2009].

Then the "only if" direction.
- $N^+ \le 1$ is part (c).
- For $N^+ = 2$ with $N^- \le 2$, $\mathrm{rank}\,J \le 8$.
- At the witness, $\mathrm{rank}[J;\nabla y^*]$ and $\mathrm{rank}[J;\nabla z^*]$ both exceed
  $\mathrm{rank}\,J$ by one.
- By Lemma 2 this holds generically, because the union of two proper algebraic sets is proper.

(c) Move $\mathbf v^+$ by $\hat{\mathbf r}_1/\tau_1$ and hold $t_b, x_b, y_b, \mathbf v^-$ fixed.
- The post-contact point moves by $\tau_1\cdot\hat{\mathbf r}_1/\tau_1 = \hat{\mathbf r}_1$, which is along
  its own ray. Its pixel therefore does not change: exactly, not only to first order.
- The pre-contact rows do not involve $\mathbf v^+$.
- So $Jd_1 = 0$.
- At the crossing time $\delta\mathbf p(t^*) = (\tau^*/\tau_1)\hat{\mathbf r}_1$, and Lemma 1 gives the
  crossing shift.
- For $N^- \ge 3$ the rank is 8 by (a), so $\mathrm{null}(J) = \mathrm{span}\{d_1\}$. Then $m_k$ is
  estimable if and only if component $k$ of $A\hat{\mathbf r}_1$ vanishes. $\square$

Numerical check (`checks.py` section 4):
- At GEN with $(N^-, N^+) = (3,1)$ and $(5,1)$: $\|Jd_1\|/(\|J\|\|d_1\|) = 0$ and the rank is 8.
- Neither component is estimable.
- The crossing moves by $-5.6609/-11.1355$ m per unit $d_1$, which equals $(\tau^*/\tau_1)A\hat{\mathbf r}_1$
  to every printed digit.
- A central finite difference of the app's projection along $d_1$ changes no pixel. Along a unit change of
  $v^+_x$ the pixel moves 0.043 px per m/s.
- The full witness table (`out/crlb_identifiability.json`, `general_g`) has exactly the 21 estimable cells of
  (b). With $g = 0$ (`general_g0`) only 15 of them stay estimable, so gravity carries part of the information
  even in general position.

### 2.5 Proposition 2 (camera centre in the plane of a straight delivery)

Suppose $v^\pm_y = 0$ and the camera centre lies in the vertical plane $\Pi$ that holds the trajectory. The
camera orientation is free: it may be yawed or rolled.

(a) $y^*$ has a finite CRB if and only if $N^+ \ge 2$, or $N^+ = 1$ and $N^- \ge 2$. The only exception is
a post frame exactly at the crossing time.

(b) Generically, $z^*$ has a finite CRB if and only if $N^+ \ge 4$, or $N^+ = 3$ and $N^- \ge 3$, or
$N^+ = 2$ and $N^- \ge 4$.

(c) $\mathrm{rank}\,J = 9$ if and only if $N^-, N^+ \ge 2$ and $N^- + N^+ \ge 6$.

*Proof.*
1. $\Pi$ contains the camera centre, so it images to a single line $\ell$. Rotate pixel axes to $(a, b)$,
   along and across $\ell$. The Gaussian noise model does not change under that rotation.
2. A displacement inside $\Pi$ keeps the point on $\ell$, so it changes $a$ only.
3. A displacement $\delta y$ out of $\Pi$ changes $b$ by $\beta_i\delta y_i$ with $\beta_i \ne 0$, because
   the ray lies in $\Pi$ and cannot be parallel to $\hat{\mathbf y}$. It may also change $a$.
4. At the truth $\partial y/\partial t_b = -v_y = 0$, so $\delta y_i = \delta y_b + \delta v^\mp_y\tau_i$.
   This involves only the out-of-plane parameters $\theta_o = (y_b, v^-_y, v^+_y)$.
5. Take a null vector of $J$. The $b$ rows force $\delta y_i = 0$ at every frame. The $a$ rows then reduce to
   the in-plane rows. So
   $$\mathrm{null}(J) = \mathrm{null}(A_{\rm in}) \times \mathrm{null}(Y),$$
   - $A_{\rm in}$ has one row per frame in $(t_b, x_b, v^-_x, v^-_z, v^+_x, v^+_z)$.
   - $Y$ has rows $(1, \tau_i, 0)$ for pre-contact frames and $(1, 0, \tau_j)$ for post-contact frames.
6. Since $v_y = 0$, $\nabla y^* = (0_{\rm in};\ 1, 0, \tau^*)$ and $\nabla z^*$ is zero on $\theta_o$.

For (a), $(1,0,\tau^*)$ must lie in $\mathrm{row}(Y)$.
- Two post rows span every $(\cdot, 0, \cdot)$.
- Two pre rows and one post row span $\mathbb R^3$.
- With one pre and one post row, $\alpha(1,\tau_a,0)+\beta(1,0,\tau_1) = (1,0,\tau^*)$ forces $\alpha = 0$
  and $\tau_1 = \tau^*$.
- With no post row, the third component is unreachable.

For (b), Lemma 3 applied to $A_{\rm in}$ gives
$\mathrm{rank}\,A_{\rm in} \le \min\{6,\ \min(N^-,4)+\min(N^+,4)\}$.
- $z^*$ is estimable when $A_{\rm in}$ has full rank, which holds in the listed cells with $N^+ \le 3$.
- It is also estimable when the four post-contact in-plane coordinates are determined by themselves
  ($N^+ \ge 4$).
- The witness INPLANE (120 km/h, 6 m, line 0, `striker_ref`, 240 fps) attains the rank bound. There
  $[A_{\rm in}; \nabla z^*]$ gains rank in the other cells.

For (c), full rank needs full rank of $A_{\rm in}$ and of $Y$. $\square$

Numerical checks (`checks_log.txt` sections 1b and 4):
- The table matches (a) and (b) cell by cell with the symmetric `striker_ref` camera.
- It matches again with that camera yawed and rolled by 8° about its centre. So the rule does not depend on
  mirror symmetry, as step 5 of the proof says.

Conditioning near and off the plane (240 fps, relative smallest singular value, columns scaled):

| offset from $\Pi$ | (2,3) | (3,2) | (2,4) | (3,3) |
|---|---|---|---|---|
| 0 m | 1.7e-17 | 2.0e-17 | 1.6e-9 | 4.7e-4 |
| 0.01 m | 4.8e-6 | 7.7e-6 | 3.8e-6 | 4.7e-4 |
| 0.1 m | 4.7e-5 | 7.7e-5 | 3.7e-5 | 4.9e-4 |
| 1 m | 2.9e-4 | 6.2e-4 | 2.8e-4 | 1.1e-3 |

- The degeneracy only matters at minimal counts, and the information returns linearly with the offset.
- The reference camera sits in the plane of a straight ball down the middle. That costs nothing once
  $N^+ \ge 4$, which holds for 75% of the 60 fps reference grid. The other 25% have $N^+ \le 2$.
- In-plane (2,4) and (4,2) have full rank in exact arithmetic, but their smallest singular value scales as
  $h^{3.85}$ and $h^{4.25}$ in the frame spacing $h = 1/f$. At 240 fps they are only 16 and 6 times above the
  rank tolerance. In practice they are deficient.

### 2.6 Proposition 3 (camera at contact height, the role of gravity)

Suppose $g = 0$ and the camera centre $\mathbf c$ is at height $R$. Then for every frame count the direction

$$d_s = \big(0,\ x_b - c_x,\ y_b - c_y,\ \mathbf v^-,\ v^+_x,\ v^+_y,\ 0\big)$$

lies in $\mathrm{null}(J)$. The crossing moves along it by $A(\mathbf p^* - \mathbf c)$, which is nonzero
unless the camera lies on the tangent to the path at the crossing. So the crossing is not estimable.

*Proof.*
- With $g = 0$ the model is piecewise linear, $\mathbf p = \mathbf b + \mathbf v^\mp\tau$.
- The map $\mathbf p \mapsto \mathbf c + \lambda(\mathbf p - \mathbf c)$ keeps every point on its own ray.
- Applied to the trajectory, it gives contact point $\mathbf c + \lambda(\mathbf b - \mathbf c)$ and
  velocities $\lambda\mathbf v^\mp$. The contact height stays $R$ for every $\lambda$ exactly when
  $c_z = R$.
- $v^+_z = -e v^-_z$ survives with $e$ unchanged, and $t_b$ is unchanged.
- $d_s$ is $\partial/\partial\lambda$ at $\lambda = 1$.
- With $g > 0$ the term $-\tfrac12 g\tau^2\hat{\mathbf z}$ does not scale, which breaks the symmetry.
  $\square$

Numerical check (`checks_log.txt` section 2, GEN at 240 fps):
- With $g = 0$: $\|Jd_s\|/(\|J\|\|d_s\|) = 1.0\times10^{-18}$, rank 8 at both (3,3) and (5,5), and not
  estimable.
- With $g = 9.81$: $3.4\times10^{-6}$, rank 9, and estimable, with smallest singular value
  $9.5\times10^{-6}$.
- A camera at 0.2 m or 1.7 m has rank 9 even with $g = 0$.

So metric scale comes from two independent sources:
- $g$, which fixes the time scale;
- the known contact plane seen from a different height.

Over a full 60 fps track, the bound is:

| camera height | lateral | vertical |
|---|---|---|
| 0.036 m | 4.38 cm | 6.48 cm |
| 0.2 m | 2.59 cm | 2.62 cm |
| 1.7 m | 2.94 cm | 5.00 cm |

### 2.7 Remarks

- **Hidden bounce.** The fit has no contact-pixel term. The app's contact pixel from `find_bounce_split`
  only seeds the starting point. $t_b$ is continuous and fitted, and the kink is inferred from the two arcs.
  So for the information, only $N^-$ and $N^+$ matter.
  - An occluded or between-frames contact costs nothing.
  - An occluded post-contact arc costs exactly the frames it hides.
  - With $N^+ \le 1$ the anchored model cannot give the crossing at all.
  - Whether the app finds the split at all is up to its bounce detector, which is not analysed. When no
    anchored fit converges, the app falls back to the single-parabola path, which is also not analysed.
- **Kink.** $J$ is continuous in the parameters but jumps when $t_b$ passes a frame time, because
  $\partial\mathbf p/\partial t_b = -\mathbf v^\mp + g\tau\hat{\mathbf z}$ switches branch. All bounds are
  local, at a fixed branch pattern. That pattern holds with probability one.
- **The anchor alone adds nothing without pre-contact frames.** Variant B is a free six-parameter ballistic
  arc fitted to the post-contact frames only. With $N^- = 0$ the anchored model is locally the same model:
  mapping $(t_b, x_b, y_b, \mathbf v^+)$ to the position and velocity at a fixed reference time has Jacobian
  determinant $-v^+_z \ne 0$. The identifiability table agrees, with B estimable exactly when $N^+ \ge 3$. The
  anchor's value is the link between the two arcs:
  - (3,2) is estimable for A and not for B;
  - on the grid, B's bound is 5.3 times A's laterally and 7.6 times vertically (median per-delivery
    ratio);
  - B is infinite for 22% and 25% of deliveries.
- **Free contact height (variant C, 10 parameters).** C needs rank 10.
  - A is the constrained CRB of C under $z_b = R$ [Gorman and Hero 1990].
  - The per-delivery median ratio C/A is 1.25 lateral and 1.47 vertical.
  - With $g = 0$, C and B are never estimable in any cell, in either geometry, because they have no scale.
- **Depth.** Near the crossing the position error is a needle along the camera ray: median axis ratio 56,
  median angle to the ray 0.82°, p90 1.28°. A depth error $\rho$ along $\hat{\mathbf r}$ moves the crossing
  by
  $$\delta y^* = \rho\big(\hat r_y - \tfrac{v_y}{v_x}\hat r_x\big),\qquad \delta z^* = \rho\,\hat r_x\,(s_{\rm ray} - s_{\rm path}),$$
  - $s = dz/dx$ is a slope.
  - Vertical error is small when the rays run parallel to the path, so a camera about 0.8 m high is best
    vertically.
  - Lateral error is small when the camera is on the line of the ball.
  - The along-ray and across-ray parts are negatively correlated, so "along-ray only" can exceed the total.
    The rows below are illustrative, not additive.

| camera | range | depth sd | along-ray only y/z | across-ray only y/z | bound y/z | ray slope |
|---|---|---|---|---|---|---|
| striker_ref | 3.0 m | 23.1 cm | 3.02/6.56 | 1.24/2.30 | 1.97/4.41 | -0.385 |
| striker_low | 2.9 m | 36.1 cm | 4.75/5.64 | 1.85/1.76 | 2.85/3.85 | -0.207 |
| striker_high | 4.5 m | 24.2 cm | 2.40/9.18 | 0.90/2.41 | 1.84/6.95 | -0.495 |
| striker_side | 3.4 m | 12.8 cm | 4.96/3.47 | 1.61/1.07 | 3.50/2.48 | -0.385 |
| bowler_ref | 22.9 m | 303.5 cm | 0.92/32.30 | 1.64/3.89 | 1.96/35.78 | +0.047 |
| bowler_side | 24.2 m | 242.1 cm | 20.07/30.33 | 2.83/3.58 | 22.34/33.38 | +0.057 |

(These are medians over the 75 grid deliveries with $N^- \ge 2$ and $N^+ \ge 3$, at 60 fps and 1 px, in cm.
The path slope at the crossing is -0.071.)

- **Conditioning at fixed counts.** For minimal counts in general position, the relative smallest singular
  value falls about linearly with the frame spacing: slope 0.89 to 1.25 in $\log h$ from 120 to 1920 fps.
  At a fixed count, what informs the fit is the time span the frames cover after the bounce. A high frame
  rate helps only because it adds frames.

## 3. The bounds

Every bound below is a $2\times2$ matrix for $(y^*, z^*)$ at the truth. The tables quote square roots of the
diagonal.

1. **px, the classical CRB.** $C_{\rm px} = G F^+ G^\top$, and infinite when the crossing is not estimable.
2. **px_pri, with the solver's priors.** $C_{\rm pri} = G (F + P)^{-1} G^\top$, where $P = C^\top C$ at the
   nominal prior widths.
   - This is the Bayesian information (van Trees) form evaluated at the truth [Gill and Levit 1995; Van
     Trees and Bell 2007].
   - The van Trees inequality bounds the risk averaged over the prior, not the MSE at each $\theta$. Here it
     is a reference level, not a pointwise bound.
   - It equals the solver's effective prior at $\sigma = 1$ px.
3. **joint, calibration as a nuisance.** Stack $\theta$ and the pose $\phi$ (6 parameters). The pose gets
   information from the ball pixels through $J_\phi$ and from the taps through
   $F_{\rm tap} = J_{\rm tap}^\top J_{\rm tap}/\sigma_{\rm tap}^2$. The bound is
   $$C_{\rm joint} = G\,\big(F_{\theta\theta} - F_{\theta\phi}F_{\phi\phi}^{-1}F_{\phi\theta}\big)^+ G^\top,\quad
   F_{\theta\phi} = J^\top J_\phi/\sigma^2,\ F_{\phi\phi} = J_\phi^\top J_\phi/\sigma^2 + F_{\rm tap}.$$
   - **joint_f** also frees the focal length (7 nuisances).
   - **joint_pri** adds $P$ to $F_{\theta\theta}$.
4. **twostep, the app's structure.** Fit $\theta$ with the tap pose held fixed. To first order the crossing
   error is $M(\mathbf w - J_\phi\delta\phi)$, with $M = G(J^\top J)^{-1}J^\top$, so
   $$C_{\rm 2s} = G F^{-1} G^\top + M J_\phi F_{\rm tap}^{-1} J_\phi^\top M^\top.$$
   - This is the covariance of one estimator, not a bound, and it is never below joint.
   - On the grid it equals joint to 3 or 4 digits: 2.397 and 5.900 cm for both. The ball pixels add
     essentially no pose information.
5. **The prior-regularised estimator is biased.**
   - With $H = F + P$, the first-order MAP covariance is $G H^{-1} F H^{-1} G^\top$, and its bias is
     $-GH^{-1}P(\theta-\theta_0)$.
   - Since $H^{-1}FH^{-1} = H^{-1} - H^{-1}PH^{-1} \preceq H^{-1}$, its variance at a point sits below
     px_pri.
   - The biased CRB, $(G+\nabla b)F^+(G+\nabla b)^\top$ [Hero, Fessler and Usman 1996], is attained to first
     order by the MAP, whose mean gradient is $GH^{-1}F$.
   - So a MAP spread below px, or even below px_pri at one $\theta$, breaks no bound. The MSE adds the
     squared prior pull.
6. **soft_l1.** For residuals $\mathcal N(0,\sigma^2)$ and $\psi(r) = r/\sqrt{1+r^2/C^2}$, the M-estimator
   covariance is $(E\psi^2/(E\psi')^2)(J^\top J)^{-1}$ [Huber 1964; Huber 1973]. Its efficiency is
   $\sigma^2 (E\psi')^2/E\psi^2$. The reported $s^2(J_w^\top J_w)^{-1}$ differs from this sandwich:

| $\sigma$ (px) | $C/\sigma$ | efficiency | reported var / true var |
|---|---|---|---|
| 0.5 | 4 | 0.9967 | 1.080 |
| 1 | 2 | 0.9787 | 1.247 |
| 2 | 1 | 0.9268 | 1.641 |
| 3 | 0.667 | 0.8820 | 2.048 |
| 4 | 0.5 | 0.8479 | 2.457 |

   At 1 px, $E\psi' = 0.7846$ and $E\psi^2 = 0.6290$. The reported sd is therefore 1.117 times the true sd.
   For an unbiased Gaussian error that alone gives one-sigma coverage of 73.6%, not 68.3%.

## 4. Numbers

Reference setting: `striker_ref`, 60 fps, 1 px, $\sigma_{\rm tap}$ = 2 px, 100-delivery grid (`synth.grid`).
The median track has 33 frames, 8 of them after contact. Values are medians in cm, lateral / vertical.

| bound | lateral / vertical | share infinite |
|---|---|---|
| px | 2.382 / 5.890 | 8% / 10% |
| px_pri | 1.884 / 4.597 | 0 |
| joint | 2.397 / 5.900 | 8% / 10% |
| joint_pri | 1.906 / 4.599 | 0 |
| joint_f | 2.398 / 5.903 | 8% / 10% |
| twostep | 2.397 / 5.900 | 8% / 10% |

An efficient unbiased estimator has median absolute error $0.674\sigma$. That is 1.61 / 3.97 cm on the px
bound and 1.27 / 3.10 cm on px_pri.

**Frame rate, px, cm:**

| camera | 30 fps | 60 fps | 120 fps | 240 fps |
|---|---|---|---|---|
| striker_low | 5.55 / 9.78 | 3.05 / 5.47 | 2.04 / 4.07 | 1.39 / 2.70 |
| striker_ref | 3.91 / 11.30 | 2.38 / 5.89 | 1.57 / 4.21 | 1.09 / 2.98 |
| striker_high | 3.85 / 17.73 | 2.49 / 9.87 | 1.59 / 7.01 | 1.12 / 4.97 |
| striker_side | 8.08 / 6.03 | 4.34 / 3.25 | 3.17 / 2.44 | 2.23 / 1.66 |
| bowler_ref | 3.74 / 97.1 | 2.41 / 58.7 | 1.80 / 44.2 | 1.26 / 32.9 |
| bowler_side | 54.3 / 89.8 | 33.3 / 53.9 | 24.5 / 40.4 | 17.9 / 29.5 |

- At the reference camera the exponent from 60 to 240 fps is 0.56 lateral and 0.49 vertical, which is the
  $f^{-1/2}$ law.
- 20% of deliveries have an infinite bound at 30 fps, and none do from 120 fps up.
- At the bowler end calibration matters: joint lateral is 4.22, 3.09, 2.64 and 2.30 cm at 30 to 240 fps.
- Priors carry the bowler-end vertical: px_pri is 8.79 cm against px 58.7 cm for `bowler_ref`.
- On the grid, 8 m deliveries at 240 fps reach 0.79 / 1.36 cm.

**Placement, px, 60 fps, cm:**

| back | lat / vert | height | lat / vert | offset | lat / vert |
|---|---|---|---|---|---|
| 1.5 m | 1.37 / 3.46 | 0.3 m | 2.34 / 2.83 | 0 m | 2.38 / 5.89 |
| 2.8 m | 2.38 / 5.89 | 0.5 m | 2.70 / 2.26 | 0.5 m | 2.82 / 5.21 |
| 4 m | 3.63 / 8.49 | 0.8 m | 3.27 / 1.52 | 1.5 m | 4.34 / 3.25 |
| 6 m | 6.63 / 13.45 | 1.2 m | 3.05 / 5.47 | 3 m | 5.85 / 2.12 |
| 10 m | 15.87 / 30.42 | 1.7 m | 2.38 / 5.89 | | |
| | | 2.6 m | 1.64 / 6.78 | | |
| | | 3.5 m | 1.31 / 7.51 | | |

- The back-distance exponent is 1.29 lateral and 1.15 vertical.
- No single placement is best for both components. High cameras suit lateral, and a camera about 0.8 m high,
  whose rays run nearly along the path, suits vertical.

**Noise and taps.**
- The px bound is exactly linear in $\sigma$: 1.19 / 2.95 at 0.5 px, 4.76 / 11.78 at 2 px, 7.15 / 17.67 at
  3 px and 11.91 / 29.45 at 5 px.
- px_pri grows more slowly: 3.43 / 6.13 at 2 px and 6.04 / 9.50 at 5 px.
- Tap noise, on the joint bound: 2.386 / 5.893 at 1 px, 2.397 / 5.900 at 2 px, 2.441 / 5.928 at 4 px,
  2.682 / 6.026 at 8 px and 3.103 / 6.180 at 12 px.
- joint_f is 2.916 / 6.093 at 8 px and 3.397 / 6.381 at 12 px.

**Length, 120 km/h, line 0.2 m, px, cm:**

| length | 60 fps | 240 fps |
|---|---|---|
| 1.5 m | infinite (px_pri 10.1 / 6.6) | 364 / 1814 |
| 2 m | 39.0 / 186.5 | 6.57 / 30.8 |
| 2.5 m | 6.43 / 28.6 | |
| 3 m | 3.84 / 15.9 | |
| 4 m | 2.38 / 8.59 | |
| 6 m | 2.02 / 5.60 | |
| 8 m | 1.48 / 2.77 | 0.705 / 1.327 |
| 10 m | 1.51 / 1.51 | |

On the grid by length (px): L2 is 90.5 / 662, with 32% / 40% infinite; L4 is 3.24 / 8.59; L6 is
1.74 / 4.41; L8 is 1.67 / 2.74. At L2, px_pri is 2.32 / 5.16. **At 2 m length the reported uncertainty is the
prior, not the pixels.**

## 5. Efficiency

`efficiency.py`: 400 draws per configuration, SeedSequence 20260925, `striker_ref`, 60 fps, line 0.2 m,
friction 0.10 unless marked `f0`, 1 px unless marked `n`. The estimators are:
- **ML**: squared loss, no priors, bounded.
- **ml_free**: the same, unbounded.
- **solver**: as shipped (soft_l1, priors, bounds).

Definitions:
- "eff" is bound$^2$/variance, with 95% intervals from the $\chi^2_{399}$ law of the sample variance.
- Below 1 means information is lost. Above 1 is only possible for a biased estimator, whether bounded,
  prior-driven or nonlinear.
- "bound" is px for plain rows and joint for `_cal` rows. The `_cal` rows solve the pose from 12 taps at
  2 px in every draw.
- "pri bound" is px_pri.
- "solver eff_mse" is bound$^2$/MSE.
- "stated rms" is the RMS of the solver's reported sigma.
- Values are cm, lateral / vertical.

| config | N- / N+ | bound (cm) | pri bound | ML sd | ML eff y [95% CI] | ML eff z [95% CI] | solver sd | solver bias | stated rms | 1-sigma coverage | solver eff_mse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| s90_L2.5 | 40 / 3 | 12.6 / 52.7 | 1.89 / 6.20 | 3.65 / 14.42 | 11.99 [10.48, 13.84] | 13.36 [11.68, 15.43] | 1.07 / 1.10 | -0.47 / +1.94 | 1.88 / 5.97 | 0.85 / 1.00 | 118 / 558 |
| s90_L4 | 36 / 8 | 2.0 / 7.0 | 1.69 / 5.81 | 2.14 / 7.49 | 0.90 [0.78, 1.03] | 0.89 [0.78, 1.02] | 1.38 / 4.56 | -0.24 / +0.90 | 1.80 / 6.17 | 0.78 / 0.78 | 2.10 / 2.31 |
| s90_L6 | 32 / 12 | 1.6 / 4.8 | 1.54 / 4.56 | 1.63 / 4.80 | 0.97 [0.85, 1.12] | 0.98 [0.86, 1.13] | 1.52 / 4.45 | -0.14 / +0.45 | 1.67 / 4.92 | 0.71 / 0.70 | 1.11 / 1.13 |
| s90_L8 | 27 / 18 | 1.1 / 2.7 | 1.13 / 2.73 | 1.15 / 2.81 | 0.97 [0.85, 1.12] | 0.96 [0.84, 1.10] | 1.14 / 2.77 | +0.00 / -0.02 | 1.26 / 3.05 | 0.72 / 0.71 | 0.99 / 0.98 |
| s120_L2.5 | 30 / 3 | 6.4 / 28.6 | 1.47 / 5.13 | 2.71 / 11.10 | 5.64 [4.93, 6.51] | 6.63 [5.80, 7.66] | 0.95 / 1.04 | -0.44 / +2.06 | 1.49 / 5.09 | 0.85 / 0.99 | 37.82 / 154 |
| s120_L4 | 27 / 6 | 2.4 / 8.6 | 1.70 / 5.88 | 2.26 / 8.28 | 1.11 [0.97, 1.28] | 1.08 [0.94, 1.24] | 1.17 / 3.78 | -0.58 / +2.25 | 1.77 / 6.12 | 0.82 / 0.82 | 3.33 / 3.82 |
| s120_L6 | 24 / 9 | 2.0 / 5.6 | 1.84 / 5.05 | 2.03 / 5.82 | 0.99 [0.87, 1.15] | 0.93 [0.81, 1.07] | 1.59 / 4.45 | -0.23 / +0.62 | 2.01 / 5.51 | 0.77 / 0.74 | 1.59 / 1.56 |
| s120_L8 | 20 / 14 | 1.5 / 2.8 | 1.46 / 2.73 | 1.51 / 2.83 | 0.96 [0.84, 1.11] | 0.96 [0.84, 1.11] | 1.46 / 2.72 | -0.14 / +0.25 | 1.60 / 3.01 | 0.70 / 0.72 | 1.02 / 1.04 |
| s145_L2.5 | 25 / 2 | 46.7 / 217 | 1.78 / 4.63 | 2.90 / 11.06 | 259 [227, 299] | 386 [337, 446] | 1.50 / 1.21 | -0.47 / +2.24 | 1.80 / 4.63 | 0.75 / 0.96 | 887 / 7297 |
| s145_L4 | 23 / 4 | 4.5 / 17.2 | 1.87 / 6.46 | 3.37 / 13.25 | 1.79 [1.57, 2.07] | 1.68 [1.47, 1.94] | 0.94 / 2.42 | -1.02 / +3.59 | 1.87 / 6.38 | 0.79 / 0.84 | 10.62 / 15.80 |
| s145_L6 | 20 / 8 | 1.7 / 4.6 | 1.60 / 4.22 | 1.71 / 4.66 | 1.03 [0.90, 1.19] | 0.99 [0.86, 1.14] | 1.40 / 3.73 | -0.32 / +0.89 | 1.73 / 4.56 | 0.74 / 0.74 | 1.46 / 1.47 |
| s145_L8 | 17 / 11 | 2.0 / 3.3 | 1.90 / 3.17 | 1.92 / 3.23 | 1.05 [0.92, 1.21] | 1.04 [0.91, 1.21] | 1.76 / 2.93 | -0.32 / +0.57 | 2.09 / 3.48 | 0.73 / 0.74 | 1.21 / 1.22 |
| s90_L2.5_cal | 40 / 3 | 12.6 / 52.7 | 1.89 / 6.20 | 3.65 / 14.52 | 11.98 [10.48, 13.84] | 13.20 [11.54, 15.24] | 1.20 / 1.97 | -0.49 / +1.93 | 55.74 / 80.63 | 0.85 / 1.00 | 95.14 / 367 |
| s90_L4_cal | 36 / 8 | 2.0 / 7.1 | 1.69 / 5.81 | 1.96 / 6.76 | 1.08 [0.95, 1.25] | 1.09 [0.95, 1.26] | 1.30 / 4.17 | -0.26 / +1.20 | 1.79 / 6.09 | 0.82 / 0.81 | 2.38 / 2.65 |
| s90_L6_cal | 32 / 12 | 1.6 / 4.8 | 1.54 / 4.56 | 1.65 / 4.75 | 0.97 [0.85, 1.12] | 1.01 [0.88, 1.17] | 1.55 / 4.42 | -0.11 / +0.34 | 1.68 / 4.96 | 0.72 / 0.72 | 1.11 / 1.16 |
| s90_L8_cal | 27 / 18 | 1.2 / 2.8 | 1.13 / 2.73 | 1.22 / 2.98 | 0.94 [0.82, 1.08] | 0.87 [0.76, 1.01] | 1.22 / 2.96 | -0.01 / -0.06 | 1.26 / 3.04 | 0.69 / 0.67 | 0.95 / 0.89 |
| s120_L2.5_cal | 30 / 3 | 6.4 / 28.6 | 1.47 / 5.13 | 2.71 / 11.09 | 5.63 [4.93, 6.50] | 6.65 [5.82, 7.68] | 0.93 / 1.05 | -0.47 / +2.12 | 1.48 / 5.06 | 0.81 / 0.99 | 38.03 / 146 |
| s120_L4_cal | 27 / 6 | 2.4 / 8.6 | 1.70 / 5.88 | 2.43 / 9.18 | 0.97 [0.85, 1.12] | 0.88 [0.77, 1.01] | 1.15 / 3.89 | -0.58 / +2.08 | 1.79 / 6.18 | 0.80 / 0.79 | 3.48 / 3.80 |
| s120_L6_cal | 24 / 9 | 2.0 / 5.6 | 1.84 / 5.05 | 2.14 / 6.01 | 0.91 [0.79, 1.05] | 0.87 [0.76, 1.01] | 1.69 / 4.59 | -0.25 / +0.74 | 2.00 / 5.49 | 0.73 / 0.75 | 1.43 / 1.46 |
| s120_L8_cal | 20 / 14 | 1.5 / 2.8 | 1.46 / 2.73 | 1.56 / 2.91 | 0.94 [0.83, 1.09] | 0.93 [0.81, 1.07] | 1.51 / 2.79 | -0.05 / +0.19 | 1.63 / 3.06 | 0.72 / 0.72 | 1.02 / 1.01 |
| s145_L2.5_cal | 25 / 2 | 46.7 / 217 | 1.78 / 4.63 | 2.83 / 11.14 | 272 [238, 314] | 381 [333, 440] | 1.46 / 1.15 | -0.50 / +2.15 | 1.79 / 4.62 | 0.73 / 0.98 | 922 / 7957 |
| s145_L4_cal | 23 / 4 | 4.5 / 17.2 | 1.87 / 6.46 | 3.57 / 13.33 | 1.61 [1.41, 1.86] | 1.67 [1.46, 1.92] | 1.02 / 2.39 | -0.91 / +3.39 | 1.90 / 6.45 | 0.79 / 0.85 | 11.00 / 17.23 |
| s145_L6_cal | 20 / 8 | 1.8 / 4.6 | 1.60 / 4.22 | 1.65 / 4.45 | 1.15 [1.00, 1.32] | 1.09 [0.96, 1.26] | 1.35 / 3.53 | -0.37 / +1.03 | 1.72 / 4.54 | 0.75 / 0.76 | 1.60 / 1.60 |
| s145_L8_cal | 17 / 11 | 2.0 / 3.3 | 1.90 / 3.17 | 2.11 / 3.60 | 0.90 [0.79, 1.04] | 0.85 [0.75, 0.98] | 1.91 / 3.24 | -0.18 / +0.31 | 2.13 / 3.55 | 0.73 / 0.71 | 1.09 / 1.05 |
| s120_L2.5_f0 | 30 / 2 | 57.9 / 270 | 2.00 / 4.78 | 3.18 / 11.37 | 332 [290, 384] | 563 [492, 650] | 1.80 / 1.36 | +0.04 / +0.11 | 2.15 / 4.99 | 0.76 / 1.00 | 1036 / 39105 |
| s120_L4_f0 | 27 / 5 | 3.2 / 12.1 | 1.79 / 6.24 | 2.95 / 11.26 | 1.18 [1.03, 1.37] | 1.16 [1.01, 1.33] | 1.09 / 3.03 | -0.05 / -0.01 | 1.87 / 6.51 | 0.91 / 0.98 | 8.73 / 16.02 |
| s120_L6_f0 | 24 / 9 | 1.4 / 3.9 | 1.30 / 3.68 | 1.31 / 3.71 | 1.09 [0.95, 1.26] | 1.10 [0.96, 1.27] | 1.18 / 3.27 | +0.04 / -0.12 | 1.43 / 4.02 | 0.78 / 0.76 | 1.35 / 1.42 |
| s120_L6_n0.5 | 24 / 9 | 1.0 / 2.8 | 0.98 / 2.72 | 1.02 / 2.89 | 0.98 [0.86, 1.13] | 0.94 [0.82, 1.08] | 0.81 / 2.27 | -0.30 / +0.84 | 0.95 / 2.62 | 0.71 / 0.71 | 1.36 / 1.35 |
| s120_L6_n2 | 24 / 9 | 4.0 / 11.2 | 3.05 / 8.20 | 4.63 / 13.66 | 0.76 [0.67, 0.88] | 0.67 [0.59, 0.78] | 3.50 / 9.96 | -0.10 / +0.40 | 4.67 / 12.99 | 0.79 / 0.78 | 1.34 / 1.27 |
| s120_L6_n3 | 24 / 9 | 6.1 / 16.8 | 3.85 / 10.06 | 6.13 / 17.53 | 0.98 [0.85, 1.13] | 0.92 [0.80, 1.06] | 4.70 / 12.81 | -0.07 / +0.34 | 8.13 / 22.77 | 0.85 / 0.86 | 1.67 / 1.72 |

**Where information goes.**

1. **Frames after the bounce.**
   - With $N^+ \ge 8$ at up to 1 px, ML efficiency is 0.89 to 1.10 and every interval contains 1.
   - The exception is `s120_L6_n2` at 0.76 / 0.67. A few tail draws drive it: the median-based efficiency is
     0.89 / 0.90, and the 3 px row is back at 0.98 / 0.92.
   - At $N^+ \le 5$ the linear bound is not attainable. Bounded ML reaches "efficiency" 1.2 to 563 because the
     bounds bind in 13% to 97% of draws.
   - Even unbounded ML beats the bound there: 1.40 / 1.33 at `s145_L4`, with 374 of 400 converged and bias
     -0.38 / +0.99 cm.
   - The bound describes these cells only as "no information in the pixels". Whatever accuracy the solver
     shows there comes from bounds and priors.
2. **Calibration.** `calib_check.py` uses 400 tap draws at 2 px with focal length 951.7 px, and has 0
   failures.
   - The app's pose sd is 0.99, 1.50, 3.98, 1.30, 1.01, 1.01 and 1.01 times its CRB for
     $(\omega_1,\omega_2,\omega_3,t_x,t_y,t_z,f)$.
   - Its generalised eigenvalues against the CRB span 0.81 to 16.0.
   - It is biased: $t_z$ +2.12 cm and $f$ +6.57 px.
   - A 7-parameter Levenberg-Marquardt reprojection refine starting from the app's pose gives 0.99 to 1.02
     times the CRB, with eigenvalues 0.79 to 1.15.
   - Pushed through the crossing map, the app's pose puts 0.86 / 0.78 cm into the crossing at `s90_L8`. The
     CRB-optimal pose puts in 0.38 / 0.56, and the refine 0.39 / 0.56.
   - `s90_L8_cal` now uses the refined pose, not the app's raw pose, so the check should use the refine's
     0.39 cm, not the app's 0.86 cm: $\sqrt{1.15^2+0.39^2} = 1.21$ cm against 1.22 cm observed for ML in
     `s90_L8_cal`.
   - That loss is what brings the long-length `_cal` rows to 0.85 to 0.94.
3. **Robust loss.** It costs 2% of variance at 1 px, 7% at 2 px and 12% at 3 px (section 3). That is small
   next to 1 and 2.
4. **Priors.** They buy a lot where the pixels are weak: the solver's eff_mse is 2 to 39,000 at 2.5 and 4 m.
   They cost bias where the pixels are strong.
   - At `s120_L6` the solver sd is 1.59 / 4.45 cm with bias -0.23 / +0.62 cm.
   - The first-order prediction for soft_l1 with priors is sd 1.62 / 4.40 and bias -0.49 / +1.42.
   - With $N^+ \ge 8$ the sd prediction is within 5% at 1 px or less, and within 20% at 2 and 3 px.
   - The bias is overpredicted, by up to 2.3 times at 1 px and 4 to 10 times at 2 and 3 px. The ML's own
     second-order bias (+0.30 / -0.92 cm at `s120_L6`) cancels part of the prior pull. Adding it to the
     prediction gives -0.19 / +0.50 against -0.23 / +0.62 observed.
5. **Not lost.**
   - The ball pixels would add almost no pose information: twostep equals joint.
   - Freeing the focal length costs under 1% until taps reach 8 px.

## 6. The reported sigma against the bound (Part B)

Part B used 400 random deliveries, 60 fps, 1 px, 5% dropout and 2 px taps, run with the physics off and then
on. The bounds are plug-in values at the fitted $\theta$ and pose. "bound_2s" is twostep at the fit.

| | physics off (n = 399) | physics on (n = 398) |
|---|---|---|
| coverage at 1, 2, 3 sigma, lateral | 74.2 / 95.5 / 99.2% | 51.5 / 84.9 / 95.0% |
| coverage at 1, 2, 3 sigma, vertical | 74.4 / 97.0 / 99.5% | 63.8 / 88.7 / 96.7% |
| coverage using bound_2s as sigma | 76.4 / 77.1% | 46.0 / 56.1% |
| median error, cm | 1.22 / 2.26 | 2.26 / 3.51 |
| median reported sigma | 2.34 / 4.63 | 2.40 / 4.96 |
| median px / px_pri / bound_2s | 2.40 / 4.82, 2.06 / 4.17, 2.43 / 4.84 | 2.13 / 4.25, 1.91 / 3.99, 2.23 / 4.27 |
| reported / px, median | 1.028 / 1.020 | 1.137 / 1.120 |
| reported / px_pri, median | 1.106 / 1.100 | 1.245 / 1.238 |
| reported below px | 45.0 / 47.5% | 26.8 / 29.1% |
| reported below px_pri | 13.5 / 14.5% | 6.8 / 6.5% |
| median error / reported | 0.563 / 0.589 | 0.985 / 0.766 |
| error over 3 x bound_2s | 0.3 / 0.6% | 10.6 / 5.7% |
| mean error, cm | +0.10 / +0.47 | +0.53 / -1.76 |
| fits with an extra bounce | 0.7% | 1.5% |

The physics-on run lands close to the paper's 50.5 / 60.6% as submitted and 51.6 / 61.4% after the reruns.

1. **Does the linearised covariance fall below the bound?**
   - Against the classical CRB it does, in 27 to 48% of deliveries. That is expected: it is a posterior
     spread and includes the prior rows (section 3, item 5).
   - Against px_pri it does in 7 to 15% of deliveries, by at most 19% (worst ratio 0.81, p5 0.94 to 0.975).
   - $s^2$ has about 50 degrees of freedom, so $s/\sigma$ has sd about 0.1. Times the soft_l1 factor 1.117,
     that predicts about 15% of deliveries below 1, which is what the table shows.
   - It is not a systematic underestimate. The one hard exception is the $\tau^* < 0$ clamp, which reports a
     vertical sigma of 0.
2. **Why coverage is about 50 / 60%.**
   - Physics off, the reported sigma over-covers slightly (74.2 / 74.4% against 73.6% predicted), and the
     median error is at or below an efficient unbiased estimator's.
   - Physics on, errors grow by 1.8 / 1.6 times while the reported sigma barely moves. Model residuals
     inflate $s^2$ only a little.
   - Using the exact bound as sigma would not help (46.0 / 56.1%).
   - 50.5% coverage means a true sd of about 1.47 times the reported one, and 60.6% about 1.17 times. The
     median-ratio estimate is 1.46 and 1.14.
   - The gap is bias from drag, swing and the friction step, which the model omits.
   - The heavy tails are the same story: 10.6% of lateral errors exceed 3 times the bound with physics on,
     against 0.3% off.
3. **How the paper's sweeps compare with the bound.**
   - The paper's fps sweep is flat (2.8, then 2.4, then 2.1 cm lateral from 30 to 240 fps; exponent about
     0.14) while the bound drops by 3.6 times. The error is therefore set by a physics floor of about 2 cm
     lateral, not by frames.
   - The paper's physics-off and physics-on results (1.1 / 2.2 and 2.8 / 3.9 cm) bracket it.
   - At 30 fps the paper's vertical median of 4.1 cm is below an efficient unbiased median of 7.6 cm.
   - At the bowler end its vertical medians (11.2 and 9.7 cm) are below the unbiased medians (39.6 and
     36.3 cm) but near the prior-aware ones (5.9 and 6.2 cm).
   - These vertical results lean on the restitution prior matching the simulator. This is an inference from
     medians, not a per-delivery test.

## 7. Fundamental against fixable

**Fundamental:**
- Noise over the square root of the frame count: the bound is linear in $\sigma$ and goes as $f^{-1/2}$.
- $N^+ \le 1$, and $N^+ = 2$ with $N^- \le 2$, give no information about the crossing. This covers the
  hidden post-contact arc, yorkers and full tosses at low frame rates. At 60 fps a 2 m length gives
  39 cm / 1.9 m.
- Depth along the ray: at the bowler end the vertical bound is 54 to 59 cm at 60 fps.
- Distance: the exponent is 1.15 to 1.3.
- The 1.22 m extrapolation from the crease to the stumps is set by the scene.
- The in-plane degeneracy, but only at minimal counts.
- A camera at contact height has only gravity for scale.

**Fixable:**
1. **Physics bias.** Model drag and swing, or carry a model-error term in the uncertainty. This is the
   largest single gap; see the GUM work.
2. **Calibration.** Add a 7-parameter reprojection refine after the app's pose. That halves the calibration
   part of the crossing error.
3. **Uncertainty that leaves out calibration.** Add
   $M J_\phi C_\phi J_\phi^\top M^\top$. All the Jacobians already exist.
4. **Over-stated uncertainty from soft_l1.** Report the sandwich covariance instead of
   $s^2(J_w^\top J_w)^{-1}$, which over-states the sd by 12% at 1 px and 28% at 2 px.
5. **Prior strength that scales with pixel noise.** Divide the prior rows by $s$ rather than leaving them in
   pixel units.
6. **The $\tau^* < 0$ clamp.** Compute the crossing on the pre-contact arc.
7. **Prior-driven outputs.** Flag them when $N^+ \le 2$, or when px over px_pri is large, instead of
   reporting the prior width as a measured sigma.
8. **Placement advice.** At 0.8 m height the vertical bound is 1.52 cm; at 3.5 m the lateral is 1.31 cm.

## 8. Claims in main.tex that need changing

**L172-175 (related work).** "our pre- and post-contact solves are of that form with three unknowns instead of
six, because the anchor supplies the position" describes only the starting point. In `reconstruction.py`
the three-unknown linear solves (`_velocity_from_anchor`) run once per candidate anchor from
`find_bounce_split`, and their output seeds `_fit_bounce`. The reported crossing comes from that joint fit,
where the contact time and position are free: nine unknowns and a nonlinear problem. Replacement for that
clause:

```latex
our model shares its use of $g$ but joins two such arcs at an unknown contact on the known ground plane,
nine unknowns fitted jointly; linear solves of that form, three unknowns per arc once a contact pixel is
picked, serve only to start the fit.
```

**L235-245 ("What the contact supplies").** The text says that with the contact pixel found, each arc "has
three unknowns instead of six", is "a linear system ... over-determined from two frames", and that the anchor
and $g$ remove the depth degeneracy. That is the app's initialiser. The contact pixel from
`find_bounce_split` sets candidate anchors, and the linear solves give starting velocities. The fit that
produces the answer then frees $t_b$, $x_b$ and $y_b$, so the problem is nonlinear, and two frames per side is
not enough (Proposition 1). Replacement:

```latex
A pitched delivery touches the ground once. At the contact instant $t_b$ the centre of the ball is at
$(x_b, y_b, R)$, on a plane the calibration already supplies. The model is two ballistic arcs joined at
that point, $\mathbf{p}(t) = (x_b, y_b, R) + \mathbf{v}^\mp \tau - \tfrac{1}{2} g \tau^2 \hat{\mathbf{z}}$,
$\tau = t - t_b$, with $v^+_z = -e\,v^-_z$: nine unknowns fitted jointly to the ball pixels on both sides.
A contact pixel picked from the track only starts the fit; the kink itself is inferred from the two arcs,
so a contact hidden between frames costs nothing. One camera loses depth along
each ray, and two things restore it: $g$ fixes the time scale in metres, and the contact plane fixes where
along its ray the contact lies unless the camera sits at contact height. The crossing is identifiable once
three frames follow the bounce, or two follow and three precede it, and not at all with one frame or none
after the bounce (Proposition~\ref{prop:ident}). Section~\ref{sec:results} measures the difference from a
single parabola as a factor of ten in error.
```

**L312-314 (the covariance).** The code does not compute $\hat\sigma^2(J^\top J)^{-1}$. Replacement:

```latex
The reported covariance is $s^2 (J_w^\top J_w)^{+}$, where $J_w$ is the Jacobian of the loss-weighted
residuals, the three prior rows included, and $s^2$ is their sum of squares over $2N-9$ degrees of
freedom~\cite{seber1989nonlinear}. Because it includes the priors it is a posterior spread rather than the
sampling covariance of an unbiased estimate: it can sit below the Cram\'er-Rao bound of the pixels alone,
and when fewer than three frames follow the bounce it reports the prior width. It excludes calibration
error. Section~\ref{sec:coverage} measures how far it can be trusted.
```

**L426-429 (frame rate and taps).** The claim that frame rate "has almost no effect ... because the ... parabolas ... are
over-determined from a handful of frames" misreads a flat curve. The tap sentence is right, and the bound
gives it numbers. Replacement for the frame-rate sentence:

```latex
Frame rate has little effect on the error from 30 to 240~Hz (\FpsThirtyAgree\% at 30~Hz), although the
Cram\'er-Rao bound for the same geometry falls as $f^{-1/2}$, from 3.9 to 1.1~cm laterally and from 11.3
to 3.0~cm vertically. The flat curve means the error is set by physics the model omits (drag, swing, the
friction step), about 2~cm laterally, not by the number of frames.
```

Add after the tap sentence: "Pose uncertainty from twelve taps at 2~px raises the lateral bound by under
1\%, at 8~px by 13\% and at 12~px by 30\%." The unchanged 40% dropout result tells the same story: in a
measurement-limited regime it would cost a factor of $1/\sqrt{0.6} = 1.29$.

**L480-483 (coverage).** "as expected of a first-order approximation" gives the wrong cause. Replacement for
the sentences from "The stated uncertainty is therefore" (end of L480) to "replaced by it" (L483):

```latex
The stated uncertainty is optimistic, but not because it is a first-order approximation. Re-running the
coverage test on 400 random deliveries with drag, swing and friction switched off, the one-sigma band
covers 70.8\% of lateral and 74.8\% of vertical errors, close to the 73.6\% expected when the robust loss
inflates the reported spread by 12\%; with them on it covers 52.5\% and 62.1\%. Even the exact
Cram\'er-Rao bound in place of the reported sigma would cover only 50.6\% and 57.1\%. The shortfall is bias
from physics the model leaves out, and it is why the decision bands are widened by $k\sigma$ rather than
replaced by it.
```

## 9. Draft LaTeX

### 9.1 Main paper (compact)

IEEEtran provides `IEEEproof`, and the kernel `\newtheorem` is enough, so no new package is needed.

```latex
% preamble
\newtheorem{proposition}{Proposition}

% in "What the contact supplies", after the replacement paragraph
\begin{proposition}[Identifiability of the crossing]\label{prop:ident}
Let $N^-$ and $N^+$ frames precede and follow the contact, with $g>0$ and the frame times, delivery and
camera in general position. The pixel Jacobian of the anchored model has rank
$\min\{9,\ \min(2N^-,6)+\min(2N^+,6)\}$, and the stump-plane crossing $(y^*,z^*)$ has a finite
Cram\'er-Rao bound if and only if $N^+\ge 3$, or $N^+=2$ and $N^-\ge 3$. With $N^+\le 1$ neither coordinate
is identifiable, however many frames precede the contact. If the camera centre lies in the vertical plane
of a straight delivery, $y^*$ needs $N^+\ge2$ (or $N^+=1$ and $N^-\ge2$) and $z^*$ needs $N^+\ge4$, or
$N^+=3$ and $N^-\ge3$, or $N^+=2$ and $N^-\ge4$.
\end{proposition}
\begin{IEEEproof}[Proof sketch]
Replacing $(v^-_z,e)$ by $(v^-_z,v^+_z)$, whose Jacobian is $-v^-_z\neq0$, makes the pre-contact rows depend
on six parameters and the post-contact rows on six, which caps the rank as stated. A numerical witness
attains the cap, and since every entry is rational in the parameters, frame times and camera, the rank
holds off a set of measure zero. The crossing depends only on the post-contact arc, so it is identifiable
when the post-contact rows alone have rank six ($N^+\ge3$) or $J$ has full rank. With $N^+=1$ the change
$\delta\mathbf v^+=\hat{\mathbf r}_1/\tau_1$, where $\hat{\mathbf r}_1$ is the unit ray to the single
post-contact ball and $\tau_1$ its time after contact, slides that ball along its ray and leaves every pixel
unchanged, yet moves the crossing by $(\tau^*/\tau_1)A\hat{\mathbf r}_1\neq0$, with $A$ the first-order map
from a trajectory perturbation to the crossing. A plane through the camera centre images to a line, so in
the in-plane case each frame gives one equation for the in-plane motion. Details are in the supplement.
\end{IEEEproof}
```

Numbers paragraph for the results section:

```latex
\subsection{How close to the bound}
Under Gaussian pixel noise the Cram\'er-Rao bound on the crossing, at the reference camera, 60~Hz and
1~px, has a median over the delivery grid of 2.4~cm laterally and 5.9~cm vertically (1.9 and 4.6~cm with
the solver's priors); pose from twelve taps at 2~px raises it by under 1\%. It falls as $f^{-1/2}$, to
1.1 and 3.0~cm at 240~Hz, grows linearly with pixel noise and with distance to the power 1.15 to 1.3, and
a camera 0.8~m high reaches 1.5~cm vertically because its rays run nearly along the ball's path. With at
least eight frames after the bounce, least squares without priors attains the bound (efficiency 0.89 to
1.10); with the app's calibration it falls to 0.71 to 0.90 at 8~m length, which a reprojection refine of
the tapped pose recovers. With two or fewer frames after the bounce the pixels carry no information
about the crossing and any reported accuracy comes from the priors.
```

### 9.2 Supplement (full derivation)

```latex
\section{Identifiability and the Cram\'er-Rao bound}

\subsection{Model}
Let $\theta=(t_b,x_b,y_b,v^-_x,v^-_y,v^-_z,v^+_x,v^+_y,e)$, $v^+_z=-e\,v^-_z$, $\mathbf b=(x_b,y_b,R)$ and
$\mathbf p(t;\theta)=\mathbf b+\mathbf v^\mp\tau-\tfrac12 g\tau^2\hat{\mathbf z}$ with $\tau=t-t_b$. Frame
$i$ gives $\mathbf u_i=\pi(\phi,\mathbf p(t_i;\theta))+\mathbf w_i$, $\mathbf w_i\sim\mathcal N(0,\sigma^2I_2)$
independent, and $J=\partial\pi/\partial\theta\in\mathbb R^{2N\times9}$, $F=J^\top J/\sigma^2$. $N^-$
frames have $t_i<t_b$ and $N^+$ have $t_i>t_b$.

\subsection{The crossing}
\begin{lemma}\label{lem:cross}
If $x_b>0$, $v^+_x<0$ and the post-contact arc stays above the ground, the crossing of $x=0$ is at
$\tau^*=-x_b/v^+_x$, $y^*=y_b+v^+_y\tau^*$, $z^*=R+v^+_z\tau^*-\tfrac12g\tau^{*2}$. A perturbation
$\delta\mathbf p(t)$ moves it by $\delta\mathbf m=A\,\delta\mathbf p(t^*)$ with
$A=\begin{psmallmatrix}-v_y/v_x&1&0\\-v_z/v_x&0&1\end{psmallmatrix}$, $\mathbf v=\dot{\mathbf p}(t^*)$, and
$A\mathbf v=0$.
\end{lemma}
\begin{IEEEproof}
The perturbed crossing time solves $x(t^*+\delta t)+\delta x(t^*)=0$, so $\delta t=-\delta x/v_x$, and
$\delta y^*=\delta y+v_y\delta t$, $\delta z^*=\delta z+v_z\delta t$.
\end{IEEEproof}

\subsection{Estimability}
A scalar $m_k(\theta)$ has a finite Cram\'er-Rao bound for locally unbiased estimators if and only if
$\nabla m_k\in\mathrm{row}(J)$, and the bound is then $\nabla m_kF^+\nabla m_k^\top$
\cite{stoica2001singular}; $\theta$ itself is locally identifiable at a regular point if and only if $F$ is
nonsingular \cite{rothenberg1971identification}.

\begin{lemma}[Genericity]\label{lem:gen}
For a fixed assignment of frames to the two arcs, the entries of $J$ and $\nabla\mathbf m$ are rational in
$\theta$, the frame times and a rational parametrisation of the camera. Hence $\mathrm{rank}\,J$ and
$\mathrm{rank}[J;\nabla m_k]$ equal their maxima off a proper algebraic set, and a nonzero $k\times k$
minor at one point shows the generic rank is at least $k$.
\end{lemma}

\begin{lemma}[Block structure]\label{lem:block}
The map $(v^-_z,e)\mapsto(v^-_z,v^+_z)$ has Jacobian $-v^-_z\neq0$. In the new coordinates a pre-contact
frame depends on $(t_b,x_b,y_b,\mathbf v^-)$ and a post-contact frame on $(t_b,x_b,y_b,\mathbf v^+)$, so
$\mathrm{rank}\,J\le\min\{9,\min(2N^-,6)+\min(2N^+,6)\}$.
\end{lemma}

\begin{proposition}\label{prop:s1}
With $g>0$ and a configuration in general position: (a) the bound of Lemma~\ref{lem:block} is attained;
(b) $y^*$ and $z^*$ are estimable if and only if $N^+\ge3$, or $N^+=2$ and $N^-\ge3$; (c) for $N^+=1$,
$N^-\ge3$, $\mathrm{null}(J)$ is spanned by $d_1:\ \delta\mathbf v^+=\hat{\mathbf r}_1/\tau_1$, which moves
the crossing by $(\tau^*/\tau_1)A\hat{\mathbf r}_1$, so $y^*$ is estimable only if
$\hat r_{1y}/\hat r_{1x}=v_y/v_x$ and $z^*$ only if $\hat r_{1z}/\hat r_{1x}=v_z/v_x$.
\end{proposition}
\begin{IEEEproof}
(a) A witness attains the bound in every cell with $N^\pm\le5$; Lemma~\ref{lem:gen} extends it.
(b) If $J$ has full rank, every gradient lies in its row space. If $N^+\ge3$ the post-contact rows alone
have rank six on $(t_b,x_b,y_b,\mathbf v^+)$, a ballistic arc under known $g$ being recoverable from one
camera \cite{ribnick2009projectiles}, and by Lemma~\ref{lem:cross} $\nabla\mathbf m$ is supported there.
For $N^+=2$, $N^-\le2$ the rank is at most eight and at the witness both $[J;\nabla y^*]$ and
$[J;\nabla z^*]$ gain rank, which Lemma~\ref{lem:gen} makes generic. (c) Holding $t_b,x_b,y_b,\mathbf v^-$,
the change moves $\mathbf p(t_1)$ by $\hat{\mathbf r}_1$, along its own ray, so no pixel changes, and moves
$\mathbf p(t^*)$ by $(\tau^*/\tau_1)\hat{\mathbf r}_1$; Lemma~\ref{lem:cross} gives the crossing shift. By
(a) the rank is eight, so $d_1$ spans the null space. With $N^+=0$ the columns of $v^+_x,v^+_y,e$ vanish
while $\partial y^*/\partial v^+_y=\tau^*$ and $\partial z^*/\partial e=-v^-_z\tau^*$ do not.
\end{IEEEproof}

\begin{proposition}\label{prop:s2}
Let $v^\pm_y=0$ and let the camera centre lie in the vertical plane $\Pi$ of the trajectory. Then
$\mathrm{null}(J)=\mathrm{null}(A_{\rm in})\times\mathrm{null}(Y)$, where $A_{\rm in}$ has one row per
frame in $(t_b,x_b,v^-_x,v^-_z,v^+_x,v^+_z)$ and $Y$ has rows $(1,\tau_i,0)$ before and $(1,0,\tau_j)$
after contact. Consequently $y^*$ is estimable if and only if $N^+\ge2$ or ($N^+=1$, $N^-\ge2$), and,
generically, $z^*$ if and only if $N^+\ge4$, or $N^+=3$ and $N^-\ge3$, or $N^+=2$ and $N^-\ge4$.
\end{proposition}
\begin{IEEEproof}
$\Pi$ images to a line $\ell$. In pixel axes along and across $\ell$, in-plane motion changes only the
along-line coordinate, and a lateral displacement $\delta y_i=\delta y_b+\delta v^\mp_y\tau_i$ changes the
across-line coordinate with nonzero gain. A null vector therefore has $\delta y_i=0$ for all $i$, and its
in-plane part lies in $\mathrm{null}(A_{\rm in})$. Since $v_y=0$, $\nabla y^*=(0;1,0,\tau^*)$, which lies in
$\mathrm{row}(Y)$ exactly in the stated cases, and $\nabla z^*$ has no lateral part. Lemma~\ref{lem:block}
applied to $A_{\rm in}$ gives rank at most $\min\{6,\min(N^-,4)+\min(N^+,4)\}$; $z^*$ is estimable when
this is six or when $N^+\ge4$ fixes the post-contact arc alone, and a witness shows it is not in the other
cells.
\end{IEEEproof}

\begin{proposition}\label{prop:s3}
If $g=0$ and the camera centre $\mathbf c$ is at height $R$, the scaling
$\mathbf p\mapsto\mathbf c+\lambda(\mathbf p-\mathbf c)$ maps the model to itself with $t_b$ and $e$ fixed,
so $d_s=(0,x_b-c_x,y_b-c_y,\mathbf v^-,v^+_x,v^+_y,0)\in\mathrm{null}(J)$ for every frame count, and the
crossing moves by $A(\mathbf p^*-\mathbf c)\neq0$. Gravity breaks the symmetry.
\end{proposition}

\subsection{Bounds}
With the solver's prior rows $C(\theta-\theta_0)$ and $P=C^\top C$, the bounds are
$C_{\rm px}=GF^+G^\top$, the prior-aware $C_{\rm pri}=G(F+P)^{-1}G^\top$ (the Bayesian information form
evaluated at the truth \cite{gill1995vantrees,vantrees2007bayesian}), and, with the pose $\phi$ as a nuisance
informed by the ball pixels and by twelve taps of noise $\sigma_{\rm tap}$,
$C_{\rm joint}=G(F_{\theta\theta}-F_{\theta\phi}F_{\phi\phi}^{-1}F_{\phi\theta})^+G^\top$ with
$F_{\phi\phi}=J_\phi^\top J_\phi/\sigma^2+J_{\rm tap}^\top J_{\rm tap}/\sigma_{\rm tap}^2$. Fitting
$\theta$ with the tapped pose held fixed has first-order covariance
$GF^{-1}G^\top+MJ_\phi F_{\rm tap}^{-1}J_\phi^\top M^\top$, $M=G(J^\top J)^{-1}J^\top$, which is never
below $C_{\rm joint}$. The prior-regularised estimator has covariance $GH^{-1}FH^{-1}G^\top\preceq
GH^{-1}G^\top$, $H=F+P$, and bias $-GH^{-1}P(\theta-\theta_0)$; it attains the biased bound
\cite{hero1996uniform} to first order, so its spread may lie below $C_{\rm px}$ without contradiction.
For the soft\_l1 loss with $\psi(r)=r/\sqrt{1+r^2/c^2}$ the asymptotic covariance is
$(E\psi^2/(E\psi')^2)(J^\top J)^{-1}$ \cite{huber1964robust,huber1973robust}; at $c/\sigma=2$ the efficiency
is 0.979 and the solver's reported variance is 1.25 times the true one. Fixing $z_b=R$ gives the
constrained bound of the ten-parameter model \cite{gorman1990constraints}.
```

The supplement needs `\newtheorem{lemma}{Lemma}` next to `proposition`, and `psmallmatrix` needs
`mathtools`. Use `\left(\begin{smallmatrix}...\end{smallmatrix}\right)` to avoid the extra package.

## 10. References (Crossref-verified, `out/crossref.json`)

- E. Ribnick, S. Atev, N. P. Papanikolopoulos, "Estimating 3D Positions and Velocities of Projectiles from
  Monocular Views," IEEE Trans. Pattern Anal. Mach. Intell., 31(5):938-944, 2009. doi:10.1109/TPAMI.2008.247
  (already in refs.bib as `ribnick2009projectiles`).
- R. Hartley, A. Zisserman, *Multiple View Geometry in Computer Vision*, Cambridge University Press, 2004.
  doi:10.1017/CBO9780511811685 (already `hartley2004mvg`).
- P. Stoica, T. L. Marzetta, "Parameter estimation problems with singular information matrices," IEEE Trans.
  Signal Process., 49(1):87-90, 2001. doi:10.1109/78.890346
- T. J. Rothenberg, "Identification in Parametric Models," Econometrica, 39(3):577, 1971. doi:10.2307/1913267
- R. D. Gill, B. Y. Levit, "Applications of the van Trees Inequality: A Bayesian Cramér-Rao Bound," Bernoulli,
  1(1/2):59, 1995. doi:10.2307/3318681
- P. J. Huber, "Robust Estimation of a Location Parameter," Ann. Math. Statist., 35(1):73-101, 1964.
  doi:10.1214/aoms/1177703732
- P. J. Huber, "Robust Regression: Asymptotics, Conjectures and Monte Carlo," Ann. Statist., 1(5), 1973.
  doi:10.1214/aos/1176342503
- J. D. Gorman, A. O. Hero, "Lower bounds for parametric estimation with constraints," IEEE Trans. Inf.
  Theory, 36(6):1285-1301, 1990. doi:10.1109/18.59929
- A. O. Hero, J. A. Fessler, M. Usman, "Exploring estimator bias-variance tradeoffs using the uniform CR
  bound," IEEE Trans. Signal Process., 44(8):2026-2041, 1996. doi:10.1109/78.533723
- G. A. F. Seber, C. J. Wild, *Nonlinear Regression*, Wiley, 1989. doi:10.1002/0471725315 (already
  `seber1989nonlinear`).
- H. L. Van Trees, K. L. Bell (eds.), *Bayesian Bounds for Parameter Estimation and Nonlinear
  Filtering/Tracking*, IEEE/Wiley, 2007. doi:10.1109/9780470544198
- S. M. Kay, *Fundamentals of Statistical Signal Processing: Estimation Theory*, Prentice Hall, 1993. It has no
  Crossref DOI; the Crossref search returns only reviews of it. The notes do not depend on it, so cite it only
  as a textbook reference for the CRB, or drop it.

BibTeX for the new entries:

```bibtex
@article{stoica2001singular, author={Stoica, P. and Marzetta, T. L.}, title={Parameter estimation problems with singular information matrices}, journal={IEEE Transactions on Signal Processing}, volume={49}, number={1}, pages={87--90}, year={2001}, doi={10.1109/78.890346}}
@article{rothenberg1971identification, author={Rothenberg, Thomas J.}, title={Identification in Parametric Models}, journal={Econometrica}, volume={39}, number={3}, pages={577}, year={1971}, doi={10.2307/1913267}}
@article{gill1995vantrees, author={Gill, Richard D. and Levit, Boris Y.}, title={Applications of the van {T}rees Inequality: A {B}ayesian {C}ram\'er-{R}ao Bound}, journal={Bernoulli}, volume={1}, number={1/2}, pages={59}, year={1995}, doi={10.2307/3318681}}
@article{huber1964robust, author={Huber, Peter J.}, title={Robust Estimation of a Location Parameter}, journal={The Annals of Mathematical Statistics}, volume={35}, number={1}, pages={73--101}, year={1964}, doi={10.1214/aoms/1177703732}}
@article{huber1973robust, author={Huber, Peter J.}, title={Robust Regression: Asymptotics, Conjectures and {M}onte {C}arlo}, journal={The Annals of Statistics}, volume={1}, number={5}, year={1973}, doi={10.1214/aos/1176342503}}
@article{gorman1990constraints, author={Gorman, J. D. and Hero, A. O.}, title={Lower bounds for parametric estimation with constraints}, journal={IEEE Transactions on Information Theory}, volume={36}, number={6}, pages={1285--1301}, year={1990}, doi={10.1109/18.59929}}
@article{hero1996uniform, author={Hero, A. O. and Fessler, J. A. and Usman, M.}, title={Exploring estimator bias-variance tradeoffs using the uniform {CR} bound}, journal={IEEE Transactions on Signal Processing}, volume={44}, number={8}, pages={2026--2041}, year={1996}, doi={10.1109/78.533723}}
@book{vantrees2007bayesian, editor={Van Trees, Harry L. and Bell, Kristine L.}, title={Bayesian Bounds for Parameter Estimation and Nonlinear Filtering/Tracking}, publisher={IEEE/Wiley}, year={2007}, doi={10.1109/9780470544198}}
```

## 11. Reproduction

Run from the worktree root. `PY` is the server venv. Nothing was installed into it; the scripts need only
numpy, scipy and the app package.

```sh
PY=/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/server/.venv/bin/python
$PY paper/theory/crlb.py                       # bounds, identifiability tables -> out/crlb_*.{json,csv,txt}
$PY paper/theory/checks.py                     # conditioning, in-plane, gravity, depth, null direction -> out/checks_log.txt (seconds)
$PY paper/theory/calib_check.py                # calibration efficiency -> out/calib_check.txt (seed 20260926)
$PY paper/theory/efficiency.py --workers 4     # Parts A and B -> out/efficiency_*.{json,csv,txt} (240 s: 12000 part-A draws, 797 part-B deliveries)
python3 paper/theory/check_refs.py             # Crossref lookups -> out/crossref.json (network)
```

## 12. What is not verified

1. **Witness-based generic claims.** Attainment of the rank, the $N^+ = 2$, $N^- \le 2$ negatives and the
   in-plane $z^*$ negatives rest on floating-point ranks at one witness per geometry, extended by Lemma 2.
   - Margins are wide in general position. The smallest relative singular value in the conditioning sweep is
     $1.57\times10^{-4}$ at worst at 240 fps and never below $1.8\times10^{-5}$ up to 1920 fps, against a
     tolerance of $10^{-10}$.
   - They are thin for in-plane (4,2) at 240 fps (6 times the tolerance) and (2,4) (16 times).
   - A symbolic rank at a rational witness would close this, and it was not done.
2. **Exactness.** The analytic parts are the rank upper bound, Proposition 1(c) with $N^+ = 0$, Proposition
   2(a), Proposition 3, and the null-space product in Proposition 2. Each was also checked numerically.
3. **Prior-driven accuracy.** The readings that the 30 fps and bowler-end vertical results lean on the
   restitution prior come from comparing medians with bound medians. They are not per-delivery tests.
4. **Idealised noise model.** Gaussian i.i.d. pixel noise; tap noise Gaussian; principal point and lens
   distortion fixed; no rolling shutter or frame-time jitter. Real detector errors are correlated and heavy
   tailed, so the bound is optimistic for them.
5. **Bias prediction.** The first-order bias of the prior pull is overpredicted, by up to 2.3 times at 1 px
   and 4 to 10 times at 2 and 3 px. The ML's own second-order bias explains most of the gap at `s120_L6`, but
   no second-order bias formula was derived. The sd prediction holds within 5% at 1 px or less and within
   20% at 2 and 3 px.
6. **Short `_cal` rows.** In `s90_L2.5_cal` and `s145_L2.5_cal` the solver's stated RMS is 55 to 160 cm in
   places. A few draws with a huge reported sigma dominate it. This was not investigated.
7. **Out of scope.** The 10-parameter solver, the no-bounce path and the GUM budget (another agent's work) are
   not covered.
